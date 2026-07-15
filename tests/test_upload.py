import hashlib
import io
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from PIL import Image

from app.models import Dong, Photo, Report, TrustScoreLog, User


def _image_bytes(color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=color).save(buf, "JPEG")
    return buf.getvalue()


def _signup_and_login(client, app, db, username):
    with app.app_context():
        dong = Dong.query.first()
        if dong is None:
            dong = Dong(name="역삼1동")
            db.session.add(dong)
            db.session.commit()
        dong_id = dong.id

    client.post(
        "/signup",
        data={
            "username": username, "password": "test1234", "password_confirm": "test1234",
            "nickname": f"{username}-nick", "name": "테스트", "birthdate": "1990-01-01",
            "phone": "010-0000-0000", "dong_id": dong_id,
        },
        follow_redirects=True,
    )


def test_upload_with_manual_gps_creates_pending_photo(app, db, client):
    _signup_and_login(client, app, db, "alice")

    # Uses a captured_at relative to "now" (rather than a hardcoded past
    # date) because this request follows a redirect into /my-reports, whose
    # view calls sweep_expired_photos() — a hardcoded date drifts past the
    # 72-hour match window over time and would flip the assertion below from
    # PENDING to EXPIRED.
    recent_capture = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": recent_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        photo = Photo.query.filter_by(plate_number="12가3456").first()
        assert photo is not None
        assert photo.status == "PENDING"
        assert photo.gps_source == "MANUAL"
        assert photo.latitude == 37.5006


def test_upload_without_gps_or_manual_fallback_is_rejected(app, db, client):
    _signup_and_login(client, app, db, "alice")

    recent_capture = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car.jpg"),
            "plate_number": "12가3456",
            "manual_captured_at": recent_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "위치 정보를 찾을 수 없습니다".encode("utf-8") in response.data
    with app.app_context():
        assert Photo.query.filter_by(plate_number="12가3456").count() == 0


def test_duplicate_image_hash_marks_false_and_penalizes_trust_score(app, db, client):
    _signup_and_login(client, app, db, "alice")
    image_bytes = _image_bytes()

    now = datetime.utcnow()
    first_capture = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    second_capture = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(image_bytes), "car.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": first_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(image_bytes), "car-reused.jpg"),
            "plate_number": "99나9999",
            "manual_latitude": "37.6000",
            "manual_longitude": "127.1000",
            "manual_captured_at": second_capture,
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/my-reports")
    with app.app_context():
        false_photo = Photo.query.filter_by(plate_number="99나9999").first()
        assert false_photo.status == "FALSE"

        user = User.query.filter_by(username="alice").first()
        assert user.trust_score == 70  # 100 - 30

        log = TrustScoreLog.query.filter_by(user_id=user.id).first()
        assert log.delta == -30
        assert log.report_id is None


def test_daily_upload_limit_blocks_low_trust_users(app, db, client):
    _signup_and_login(client, app, db, "alice")
    with app.app_context():
        user = User.query.filter_by(username="alice").first()
        user.trust_score = 40  # below DAILY_LIMIT_MID_SCORE -> 1/day limit
        db.session.commit()

    now = datetime.utcnow()
    first_capture = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    second_capture = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car1.jpg"),
            "plate_number": "11가1111",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": first_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes(color=(1, 1, 1))), "car2.jpg"),
            "plate_number": "22나2222",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": second_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "오늘 업로드 가능 횟수".encode("utf-8") in response.data
    with app.app_context():
        assert Photo.query.filter_by(plate_number="22나2222").count() == 0


def test_second_upload_from_different_user_triggers_valid_match(app, db, client):
    _signup_and_login(client, app, db, "alice")

    # Anchor both captures to a shared "now" so the 5-minute gap between them
    # (the intended relative timing this test exercises) is preserved
    # regardless of when the suite runs, instead of a hardcoded calendar date
    # that drifts further into the past with every day that passes.
    now = datetime.utcnow()
    first_capture = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    second_capture = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car1.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": first_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    client.get("/logout")

    _signup_and_login(client, app, db, "bob")
    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes(color=(9, 9, 9))), "car2.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5007",
            "manual_longitude": "127.0365",
            "manual_captured_at": second_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "매칭되어 신고가 접수되었습니다".encode("utf-8") in response.data
    with app.app_context():
        report = Report.query.filter_by(plate_number="12가3456").first()
        assert report is not None
        assert report.status == "VALID"


def test_my_reports_groups_pending_and_valid_correctly(app, db, client):
    _signup_and_login(client, app, db, "alice")

    # Uses a captured_at relative to "now" rather than a hardcoded past date:
    # /my-reports calls sweep_expired_photos(), which would flip a stale
    # PENDING photo to EXPIRED once its captured_at drifts more than 72 hours
    # (MATCH_MAX_GAP_SECONDS) into the past, moving it into the wrong section
    # below and breaking the grouping this test verifies.
    recent_capture = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car1.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": recent_capture,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    response = client.get("/my-reports")
    assert response.status_code == 200
    # These checks are deliberately more specific than "does the plate number
    # appear somewhere on the page": the pending section renders each row as
    # "번호판 {plate} · 촬영 ...", while the expired section instead renders
    # "번호판 {plate} · 매칭 상대를 찾지 못해 만료됨". Asserting the pending
    # count and the pending-row text (and that the expired-row text is
    # absent) actually verifies this photo is grouped under "매칭 대기중" and
    # not silently miscategorized into "반려 · 만료".
    assert "매칭 대기중 (1)".encode("utf-8") in response.data
    assert "번호판 12가3456 · 촬영".encode("utf-8") in response.data
    assert "매칭 상대를 찾지 못해 만료됨".encode("utf-8") not in response.data


def test_my_reports_shows_valid_report_inserted_directly_after_signup(app, db, client):
    # Regression test for a stale `current_user.photos` relationship-collection
    # cache. Signing up loads and caches the User object in the session's
    # identity map. If that object's `.photos` collection gets touched (and
    # thereby cached) before a Photo/Report pair for this user is inserted
    # through a path that never goes through `current_user.photos` (e.g. a
    # direct db.session.add(), the same way the matching/stitching pipeline
    # does it), a naive `[p.id for p in current_user.photos]` read can return
    # a stale, empty list even though the rows are genuinely committed.
    #
    # This is primed and read within a single shared session/request context
    # (rather than two separate HTTP requests) because Flask-SQLAlchemy scopes
    # `db.session` per app context and tears it down after every request/app
    # context exits -- so two separate `client.get()`/`with app.app_context()`
    # calls each get a fresh, empty identity map and can never observe this
    # staleness. The hazard only shows up when a single session's cached
    # `.photos` survives across an insert that happens on that same session
    # without an intervening `db.session.commit()` (a commit would expire the
    # cache via SQLAlchemy's `expire_on_commit=True` default and incidentally
    # "fix" the read -- which is exactly why today's code only works by
    # accident: `sweep_expired_photos()`, called at the top of `my_reports()`,
    # happens to commit unconditionally on every view of the page). To keep
    # this test honest about *why* it passes, `sweep_expired_photos` is
    # patched to a no-op for the direct `my_reports_view()` call below, so the
    # masking commit can't hide a regression in the `my_photo_ids` query
    # itself -- reverting just that line in routes.py must fail this test.
    _signup_and_login(client, app, db, "alice")

    from flask_login import login_user

    from app.reports.routes import my_reports as my_reports_view

    with app.test_request_context("/my-reports"):
        user = User.query.filter_by(username="alice").first()
        login_user(user)
        dong = Dong.query.first()

        # Prime the relationship-collection cache as empty -- mirrors any
        # code path that touches `current_user.photos` before this user has
        # uploaded anything.
        assert list(user.photos) == []

        now = datetime.utcnow()
        photo_a = Photo(
            uploader_id=user.id,
            plate_number="12가3456",
            image_path="a.jpg",
            image_hash="hash-a",
            captured_at=now - timedelta(hours=2),
            gps_source="MANUAL",
            latitude=37.5006,
            longitude=127.0364,
            dong_id=dong.id,
            status="MATCHED",
        )
        photo_b = Photo(
            uploader_id=user.id,
            plate_number="12가3456",
            image_path="b.jpg",
            image_hash="hash-b",
            captured_at=now - timedelta(hours=1, minutes=55),
            gps_source="MANUAL",
            latitude=37.5007,
            longitude=127.0365,
            dong_id=dong.id,
            status="MATCHED",
        )
        db.session.add_all([photo_a, photo_b])
        # flush (not commit): visible within this session without expiring
        # the already-cached `.photos` collection above -- see the note at
        # the top of this test for why that distinction matters here.
        db.session.flush()

        report = Report(
            plate_number="12가3456",
            dong_id=dong.id,
            photo_a_id=photo_a.id,
            photo_b_id=photo_b.id,
            time_gap_seconds=300,
            ai_score=0.95,
            ai_reason="테스트 매칭",
            status="VALID",
            matched_at=now - timedelta(hours=1, minutes=50),
        )
        db.session.add(report)
        db.session.flush()

        # The relationship collection accessed above is still cached empty...
        assert list(user.photos) == []

        # ...but my_reports() must not be fooled by it: its own direct
        # Photo.id query must surface the valid report regardless. Patch
        # sweep_expired_photos to a no-op for this call only, so its
        # unconditional commit (and the resulting identity-map expiry) can't
        # incidentally paper over a regression in the my_photo_ids query.
        with patch("app.reports.routes.sweep_expired_photos", lambda config: None):
            rendered = my_reports_view()
        assert "접수완료 - 유효 (1)" in rendered
        assert "12가3456" in rendered

        db.session.commit()

    # Sanity check against the ordinary request path too.
    response = client.get("/my-reports")
    assert response.status_code == 200
    assert "접수완료 - 유효 (1)".encode("utf-8") in response.data
    assert "12가3456".encode("utf-8") in response.data


def test_demo_hint_includes_a_fresh_captured_at(app, db, client):
    # Deliberately NOT wrapped in its own `with app.app_context():`: the
    # `app` fixture already keeps one app context open for the whole test
    # (see conftest.py), and `client.get()/post()` below reuse that same
    # context (and therefore the same db.session) rather than pushing a new
    # one. Loading `demo` here in a *separate* nested app context, mutating
    # it, and committing would write the change to the DB just fine -- but
    # the outer session's identity map (already holding a `demo` object from
    # the signup POST below) would never be told to refresh, so a later
    # query through that outer session (e.g. inside get_demo_hint() during
    # client.get("/upload")) would silently return the stale, pre-mutation
    # copy instead of hitting the DB again. Keeping every read/write here on
    # the one shared session sidesteps that entirely.
    _signup_and_login(client, app, db, "demo")

    demo = User.query.filter_by(username="demo").first()
    demo.is_demo = True

    other = User(
        username="other", nickname="other-nick", name="테스트", birthdate="1990-01-01",
        phone="010-0000-0001", dong_id=demo.dong_id,
    )
    other.set_password("test1234")
    db.session.add(other)
    db.session.commit()

    # Waiting PENDING photo owned by someone else -- mirrors the seeded
    # "demo_waiting.jpg" photo scripts/seed_data.py creates ~10 minutes
    # in the past, which is what get_demo_hint() surfaces to the demo
    # account.
    db.session.add(
        Photo(
            uploader_id=other.id, plate_number="12가3456", image_path="waiting.jpg",
            image_hash="waiting-hash", captured_at=datetime.utcnow() - timedelta(minutes=10),
            gps_source="MANUAL", latitude=37.5006, longitude=127.0364,
            dong_id=other.dong_id, status="PENDING",
        )
    )
    db.session.commit()

    response = client.get("/upload")
    assert response.status_code == 200
    assert "촬영 시각".encode("utf-8") in response.data

    pattern = "촬영 시각 <code>([^<]+)</code>".encode("utf-8")
    match = re.search(pattern, response.data)
    assert match is not None, response.data
    captured_at_str = match.group(1).decode("utf-8")

    # Must be a real, parseable timestamp in the format the upload form
    # expects (manual_captured_at), and must be "now" -- not the waiting
    # photo's own ~10-minute-old captured_at -- so the gap between the two
    # stays comfortably inside the match window regardless of how long the
    # demo session has been open.
    parsed = datetime.strptime(captured_at_str, "%Y-%m-%d %H:%M:%S")
    assert abs((datetime.utcnow() - parsed).total_seconds()) < 30


def test_demo_hint_self_heals_when_no_pending_candidate_exists(app, db, client):
    # Regression test for the demo dying after its first successful run:
    # scripts/seed_data.py creates exactly one PENDING "waiting" photo, and
    # get_demo_hint() returns None once it's consumed (matched, or swept to
    # EXPIRED after 72h) -- which used to make the whole banner (including
    # the sample-download button, since the template gates both behind
    # `{% if demo_hint %}`) vanish for every judge after the first, until
    # someone manually re-ran the seed script. ensure_demo_hint() (called
    # from upload()) must notice there's no PENDING candidate and create a
    # fresh one automatically.
    #
    # See test_demo_hint_includes_a_fresh_captured_at's docstring for why
    # this stays on the single shared session/app-context the `app` fixture
    # already provides, rather than nesting its own.
    _signup_and_login(client, app, db, "demo")

    demo = User.query.filter_by(username="demo").first()
    demo.is_demo = True

    other = User(
        username="other2", nickname="other2-nick", name="테스트", birthdate="1990-01-01",
        phone="010-0000-0002", dong_id=demo.dong_id,
    )
    other.set_password("test1234")
    db.session.add(other)
    db.session.commit()

    # No PENDING photo exists anywhere -- mirrors a DB where the seeded
    # waiting photo has already been consumed (matched or expired), or a
    # freshly-seeded-with-users-but-no-photos DB.
    assert Photo.query.filter_by(status="PENDING").count() == 0

    response = client.get("/upload")
    assert response.status_code == 200

    # Banner (and, since it's in the same gated block, the sample-download
    # button) must render even though there was no pre-existing candidate.
    assert "데모 시연 안내".encode("utf-8") in response.data
    assert "샘플 사진 다운로드".encode("utf-8") in response.data

    # A fresh PENDING photo must now exist, owned by a non-demo user (never
    # by the demo account itself -- get_demo_hint() explicitly excludes the
    # current user, so a self-owned candidate could never be surfaced back).
    fresh_photo = Photo.query.filter_by(status="PENDING").first()
    assert fresh_photo is not None
    assert fresh_photo.uploader_id != demo.id
    owner = User.query.get(fresh_photo.uploader_id)
    assert owner.is_demo is False

    plate_match = re.search("번호판 <code>([^<]+)</code>".encode("utf-8"), response.data)
    lat_match = re.search("위도 <code>([^<]+)</code>".encode("utf-8"), response.data)
    lon_match = re.search("경도 <code>([^<]+)</code>".encode("utf-8"), response.data)
    captured_match = re.search("촬영 시각 <code>([^<]+)</code>".encode("utf-8"), response.data)
    assert plate_match and lat_match and lon_match and captured_match

    # A follow-up upload using exactly the hinted values must really match
    # (via the live stitching engine) against the freshly self-healed
    # waiting photo -- not just render, but actually work end to end.
    upload_response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes(color=(5, 5, 5))), "demo-followup.jpg"),
            "plate_number": plate_match.group(1).decode("utf-8"),
            "manual_latitude": lat_match.group(1).decode("utf-8"),
            "manual_longitude": lon_match.group(1).decode("utf-8"),
            "manual_captured_at": captured_match.group(1).decode("utf-8"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "매칭되어 신고가 접수되었습니다".encode("utf-8") in upload_response.data


def test_demo_sample_download_is_unique_jpeg_every_time(app, db, client):
    _signup_and_login(client, app, db, "alice")

    response1 = client.get("/demo-sample.jpg")
    assert response1.status_code == 200
    assert response1.content_type == "image/jpeg"
    disposition = response1.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "demo-sample.jpg" in disposition

    # Valid, openable JPEG bytes.
    img = Image.open(io.BytesIO(response1.data))
    assert img.format == "JPEG"

    # N=20 downloads, all sha256s must be unique. A 2-download comparison
    # can pass by luck (e.g. if uniqueness relied on picking a different
    # car color out of a handful of choices); a prior version of this sample
    # generator relied on near-invisible noise pixels that JPEG's quality-85
    # quantization silently erased, so only ~8 distinct hashes existed across
    # 200 real downloads. 20 downloads makes that class of regression fail
    # here instead of surfacing empirically in front of judges.
    hashes = set()
    for _ in range(20):
        response = client.get("/demo-sample.jpg")
        assert response.status_code == 200
        hashes.add(hashlib.sha256(response.data).hexdigest())

    assert len(hashes) == 20
