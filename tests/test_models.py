from datetime import datetime

from app.models import Dong, Photo, Report, TrustScoreLog, User


def test_user_password_hashing(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()

        user = User(
            username="alice",
            nickname="앨리스",
            name="김앨리스",
            birthdate="1990-01-01",
            phone="010-1234-5678",
            dong_id=dong.id,
        )
        user.set_password("hunter2")
        db.session.add(user)
        db.session.commit()

        fetched = User.query.filter_by(username="alice").first()
        assert fetched.trust_score == 100
        assert fetched.is_demo is False
        assert fetched.check_password("hunter2") is True
        assert fetched.check_password("wrong") is False


def test_photo_and_report_relationships(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()

        uploader_a = User(
            username="a", nickname="a-nick", name="A", birthdate="1990-01-01",
            phone="010-0000-0001", dong_id=dong.id,
        )
        uploader_a.set_password("x")
        uploader_b = User(
            username="b", nickname="b-nick", name="B", birthdate="1990-01-01",
            phone="010-0000-0002", dong_id=dong.id,
        )
        uploader_b.set_password("x")
        db.session.add_all([uploader_a, uploader_b])
        db.session.commit()

        photo_a = Photo(
            uploader_id=uploader_a.id, plate_number="12가3456", image_path="uploads/a.jpg",
            image_hash="hash-a", captured_at=datetime(2026, 1, 1, 10, 0, 0),
            gps_source="MANUAL", latitude=37.5, longitude=127.0, dong_id=dong.id, status="MATCHED",
        )
        photo_b = Photo(
            uploader_id=uploader_b.id, plate_number="12가3456", image_path="uploads/b.jpg",
            image_hash="hash-b", captured_at=datetime(2026, 1, 1, 10, 5, 0),
            gps_source="MANUAL", latitude=37.5001, longitude=127.0001, dong_id=dong.id, status="MATCHED",
        )
        db.session.add_all([photo_a, photo_b])
        db.session.commit()

        assert photo_a.uploader.username == "a"
        assert uploader_a.photos == [photo_a]

        report = Report(
            plate_number="12가3456", dong_id=dong.id, photo_a_id=photo_a.id, photo_b_id=photo_b.id,
            time_gap_seconds=300, ai_score=90.0, ai_reason="test", status="VALID",
            matched_at=datetime(2026, 1, 1, 10, 5, 0),
        )
        db.session.add(report)
        db.session.commit()

        assert report.photo_a.plate_number == "12가3456"
        assert report.photo_b.uploader_id == uploader_b.id
        assert report.dong.name == "역삼1동"

        log = TrustScoreLog(user_id=uploader_a.id, report_id=report.id, delta=5, reason="유효 신고 매칭 성공")
        db.session.add(log)
        db.session.commit()
        assert TrustScoreLog.query.count() == 1
