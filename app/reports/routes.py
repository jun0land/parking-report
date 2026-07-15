import hashlib
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Photo, Report, TrustScoreLog, User
from app.reports.demo_image import generate_sample_image
from app.reports.exif_utils import extract_gps_and_time
from app.reports.forms import UploadForm
from app.reports.image_utils import save_resized_image
from app.reports.stitching import attempt_stitch, resolve_stale_reviewing_reports, sweep_expired_photos

reports_bp = Blueprint("reports", __name__)


def check_daily_upload_limit(user):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Photo.query.filter(
        Photo.uploader_id == user.id,
        Photo.created_at >= today_start,
    ).count()

    if user.trust_score >= current_app.config["DAILY_LIMIT_HIGH_SCORE"]:
        return True, None
    if user.trust_score >= current_app.config["DAILY_LIMIT_MID_SCORE"]:
        limit = current_app.config["DAILY_LIMIT_MID_COUNT"]
    else:
        limit = current_app.config["DAILY_LIMIT_LOW_COUNT"]

    if today_count >= limit:
        return False, f"신뢰도 점수에 따라 오늘 업로드 가능 횟수({limit}건)를 모두 사용했습니다."
    return True, None


def get_demo_hint():
    candidate = (
        Photo.query.filter_by(status="PENDING")
        .filter(Photo.uploader_id != current_user.id)
        .order_by(Photo.created_at.desc())
        .first()
    )
    if candidate is None:
        return None
    return {
        "plate_number": candidate.plate_number,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        # Freshly computed "now" (not the waiting photo's own captured_at,
        # which is ~10 minutes in the past per scripts/seed_data.py) so the
        # gap between it and the waiting photo stays well inside the
        # 60s-72h match window and the 0-penalty score band, no matter how
        # long the demo session has been sitting open.
        "captured_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }


def ensure_demo_hint():
    """Like get_demo_hint(), but self-healing: if the seeded "waiting" photo
    has already been consumed (matched by an earlier judge's demo run, or
    swept to EXPIRED after 72h), recreate an equivalent fresh one instead of
    returning None.

    Without this, the demo dies after exactly one successful run: the seed
    script creates a single PENDING photo, get_demo_hint() finds it, the demo
    account uploads a match, the photo flips to MATCHED -- and every judge
    after the first sees no banner, no hint, and no sample-download button
    until someone re-runs scripts/seed_data.py. This makes the demo's
    freshness independent of reseeding (see DEPLOY.md).

    NOTE: this mutates the database on what is otherwise a GET request
    (upload()'s GET path renders the form and, for demo accounts, this hint).
    That's normally a smell, but it's deliberately scoped to is_demo accounts
    only and only ever inserts a harmless synthetic PENDING photo -- it does
    not touch any real user's data.
    """
    hint = get_demo_hint()
    if hint is not None:
        return hint

    # Demo-login itself requires a seeded DB (the "demo" user only exists via
    # scripts/seed_data.py), so an unseeded DB with no non-demo users at all
    # is a degenerate case that shouldn't happen in practice. Fail safe to
    # None (matches today's behavior) rather than fabricate an owner.
    owner = User.query.filter_by(is_demo=False).first()
    if owner is None:
        return None

    image_bytes = generate_sample_image()
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    image_path = save_resized_image(
        image_bytes, current_app.config["UPLOAD_FOLDER"], current_app.config["MAX_IMAGE_DIMENSION"]
    )

    photo = Photo(
        uploader_id=owner.id,
        plate_number=current_app.config["DEMO_PLATE"],
        image_path=image_path,
        image_hash=image_hash,
        # ~10 minutes in the past, same as scripts/seed_data.py's original
        # waiting photo: comfortably inside the 60s-72h match window against
        # a demo-account upload captured "now".
        captured_at=datetime.utcnow() - timedelta(minutes=10),
        gps_source="MANUAL",
        latitude=current_app.config["DEMO_LAT"],
        longitude=current_app.config["DEMO_LON"],
        dong_id=owner.dong_id,
        status="PENDING",
    )
    db.session.add(photo)
    db.session.commit()

    return get_demo_hint()


@reports_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    demo_hint = ensure_demo_hint() if current_user.is_demo else None

    if form.validate_on_submit():
        allowed, limit_message = check_daily_upload_limit(current_user)
        if not allowed:
            flash(limit_message, "error")
            return render_template("reports/upload.html", form=form, demo_hint=demo_hint)

        raw_bytes = form.photo.data.read()
        image_hash = hashlib.sha256(raw_bytes).hexdigest()
        duplicate = Photo.query.filter_by(image_hash=image_hash).first()

        gps_data = extract_gps_and_time(io.BytesIO(raw_bytes))
        captured_at = gps_data["captured_at"]
        latitude = gps_data["latitude"]
        longitude = gps_data["longitude"]
        gps_source = "EXIF"

        if captured_at is None:
            if not form.manual_captured_at.data:
                flash("EXIF에서 촬영 시각을 찾을 수 없습니다. 촬영 시각을 직접 입력해주세요.", "error")
                return render_template("reports/upload.html", form=form, demo_hint=demo_hint)
            captured_at = datetime.strptime(form.manual_captured_at.data, "%Y-%m-%d %H:%M:%S")
            gps_source = "MANUAL"

        if latitude is None or longitude is None:
            if form.manual_latitude.data is None or form.manual_longitude.data is None:
                flash("EXIF에서 위치 정보를 찾을 수 없습니다. 위도/경도를 직접 입력해주세요.", "error")
                return render_template("reports/upload.html", form=form, demo_hint=demo_hint)
            latitude = form.manual_latitude.data
            longitude = form.manual_longitude.data
            gps_source = "MANUAL"

        image_path = save_resized_image(
            raw_bytes, current_app.config["UPLOAD_FOLDER"], current_app.config["MAX_IMAGE_DIMENSION"]
        )

        photo = Photo(
            uploader_id=current_user.id,
            plate_number=form.plate_number.data,
            image_path=image_path,
            image_hash=image_hash,
            captured_at=captured_at,
            gps_source=gps_source,
            latitude=latitude,
            longitude=longitude,
            dong_id=current_user.dong_id,
            status="FALSE" if duplicate is not None else "PENDING",
        )
        db.session.add(photo)

        if duplicate is not None:
            current_user.trust_score += current_app.config["TRUST_SCORE_FALSE_DELTA"]
            db.session.add(
                TrustScoreLog(
                    user_id=current_user.id,
                    report_id=None,
                    delta=current_app.config["TRUST_SCORE_FALSE_DELTA"],
                    reason="중복 이미지 재사용 시도로 허위 판정",
                )
            )
            db.session.commit()
            flash("이미 사용된 사진입니다. 허위 신고로 판정되어 신뢰도 점수가 -30점 되었습니다.", "error")
            return redirect(url_for("reports.my_reports"))

        db.session.commit()

        report = attempt_stitch(photo, current_app.config)
        if report is not None:
            flash("다른 시민의 사진과 매칭되어 신고가 접수되었습니다!", "success")
        else:
            flash("사진이 업로드되었습니다. 같은 차량의 다른 사진이 올라오면 자동으로 매칭됩니다.", "success")
        return redirect(url_for("reports.my_reports"))

    return render_template("reports/upload.html", form=form, demo_hint=demo_hint)


@reports_bp.route("/demo-sample.jpg")
@login_required
def demo_sample():
    # Generated fresh on every request rather than served as a static file:
    # upload() flags any *re-used* image hash as a fraud ("FALSE") report
    # with a -30 trust penalty, so a single static sample would break the
    # demo for the second judge (or the same judge downloading it twice).
    # See app/reports/demo_image.py for how uniqueness is guaranteed.
    image_bytes = generate_sample_image()
    response = Response(image_bytes, mimetype="image/jpeg")
    response.headers["Content-Disposition"] = "attachment; filename=demo-sample.jpg"
    return response


@reports_bp.route("/my-reports")
@login_required
def my_reports():
    sweep_expired_photos(current_app.config)
    resolve_stale_reviewing_reports(current_app.config)

    pending_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="PENDING")
        .order_by(Photo.created_at.desc())
        .all()
    )
    expired_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="EXPIRED")
        .order_by(Photo.created_at.desc())
        .all()
    )
    false_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="FALSE")
        .order_by(Photo.created_at.desc())
        .all()
    )

    # Direct query (rather than iterating current_user.photos) so this
    # doesn't depend on the relationship-collection cache staying in sync
    # with rows inserted via a separate path after the User was loaded.
    my_photo_ids = [
        pid for (pid,) in db.session.query(Photo.id).filter_by(uploader_id=current_user.id).all()
    ]
    my_reports_all = (
        Report.query.filter(
            db.or_(Report.photo_a_id.in_(my_photo_ids), Report.photo_b_id.in_(my_photo_ids))
        )
        .order_by(Report.matched_at.desc())
        .all()
    )
    reviewing = [r for r in my_reports_all if r.status == "REVIEWING"]
    valid = [r for r in my_reports_all if r.status == "VALID"]
    rejected = [r for r in my_reports_all if r.status == "REJECTED"]

    return render_template(
        "reports/my_reports.html",
        pending_photos=pending_photos,
        reviewing=reviewing,
        valid=valid,
        rejected=rejected,
        expired_photos=expired_photos,
        false_photos=false_photos,
    )
