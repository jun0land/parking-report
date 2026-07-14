import hashlib
import io
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Photo, TrustScoreLog
from app.reports.exif_utils import extract_gps_and_time
from app.reports.forms import UploadForm
from app.reports.image_utils import save_resized_image
from app.reports.stitching import attempt_stitch

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
    }


@reports_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    demo_hint = get_demo_hint() if current_user.is_demo else None

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


@reports_bp.route("/my-reports")
@login_required
def my_reports():
    return render_template("reports/my_reports.html")
