from datetime import datetime, timedelta

from app.dashboard.routes import compute_dong_temperature
from app.models import Dong, Photo, Report, User


def test_compute_dong_temperature_increases_with_valid_reports():
    assert compute_dong_temperature(0) == 36.5
    assert compute_dong_temperature(10) == 39.5
    assert compute_dong_temperature(1000) == 99.9  # capped


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


def test_dashboard_shows_dong_temperature_and_ranking(app, db, client):
    _signup_and_login(client, app, db, "alice")

    with app.app_context():
        dong = Dong.query.first()
        alice = User.query.filter_by(username="alice").first()
        bob = User(
            username="bob", nickname="bob-nick", name="Bob", birthdate="1990-01-01",
            phone="010-0000-0001", dong_id=dong.id,
        )
        bob.set_password("x")
        db.session.add(bob)
        db.session.commit()

        base_time = datetime.utcnow() - timedelta(hours=2)
        photo_a = Photo(
            uploader_id=alice.id, plate_number="12가3456", image_path="x", image_hash="h1",
            captured_at=base_time, gps_source="MANUAL",
            latitude=37.5006, longitude=127.0364, dong_id=dong.id, status="MATCHED",
        )
        photo_b = Photo(
            uploader_id=bob.id, plate_number="12가3456", image_path="x", image_hash="h2",
            captured_at=base_time + timedelta(minutes=5), gps_source="MANUAL",
            latitude=37.5007, longitude=127.0365, dong_id=dong.id, status="MATCHED",
        )
        db.session.add_all([photo_a, photo_b])
        db.session.commit()

        report = Report(
            plate_number="12가3456", dong_id=dong.id, photo_a_id=photo_a.id, photo_b_id=photo_b.id,
            time_gap_seconds=300, ai_score=100, ai_reason="test", status="VALID",
            matched_at=base_time + timedelta(minutes=5),
        )
        db.session.add(report)
        db.session.commit()

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "역삼1동".encode("utf-8") in response.data
    assert "alice-nick".encode("utf-8") in response.data
    assert "bob-nick".encode("utf-8") in response.data
