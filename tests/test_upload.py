import io
from datetime import datetime, timedelta

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
