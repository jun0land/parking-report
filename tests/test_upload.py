import io

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

    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": "2026-07-10 09:00:00",
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

    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car.jpg"),
            "plate_number": "12가3456",
            "manual_captured_at": "2026-07-10 09:00:00",
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

    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(image_bytes), "car.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": "2026-07-10 09:00:00",
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
            "manual_captured_at": "2026-07-11 09:00:00",
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

    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car1.jpg"),
            "plate_number": "11가1111",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": "2026-07-10 09:00:00",
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
            "manual_captured_at": "2026-07-10 10:00:00",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "오늘 업로드 가능 횟수".encode("utf-8") in response.data
    with app.app_context():
        assert Photo.query.filter_by(plate_number="22나2222").count() == 0


def test_second_upload_from_different_user_triggers_valid_match(app, db, client):
    _signup_and_login(client, app, db, "alice")
    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes()), "car1.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": "2026-07-10 09:00:00",
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
            "manual_captured_at": "2026-07-10 09:05:00",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "매칭되어 신고가 접수되었습니다".encode("utf-8") in response.data
    with app.app_context():
        report = Report.query.filter_by(plate_number="12가3456").first()
        assert report is not None
        assert report.status == "VALID"
