import hashlib
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image

from app import create_app
from app.extensions import db
from app.models import Dong, Photo, Report, TrustScoreLog, User

DONG_NAMES = ["역삼1동", "역삼2동", "삼성2동", "논현1동", "대치4동"]


def _make_seed_image(app, filename, color):
    path = os.path.join(app.config["UPLOAD_FOLDER"], "seed", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (640, 480), color=color).save(path, "JPEG", quality=80)
    with open(path, "rb") as f:
        image_hash = hashlib.sha256(f.read()).hexdigest()
    relative_path = os.path.join("uploads", "seed", filename).replace("\\", "/")
    return relative_path, image_hash


def run(app=None):
    app = app or create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        dongs = {name: Dong(name=name) for name in DONG_NAMES}
        db.session.add_all(dongs.values())
        db.session.commit()

        demo_user = User(
            username="demo", nickname="데모유저", name="김데모", birthdate="1990-01-01",
            phone="010-0000-0000", dong_id=dongs["역삼1동"].id, is_demo=True,
        )
        demo_user.set_password("demo1234")
        db.session.add(demo_user)

        nicknames = ["범주인709", "은조용한고양이", "동네대장동민", "친절한기록자", "청소요정"]
        trust_scores = [100, 95, 60, 45, 100]
        dong_list = list(dongs.values())
        other_users = []
        for i, nickname in enumerate(nicknames):
            user = User(
                username=f"user{i + 1}", nickname=nickname, name=f"테스트유저{i + 1}",
                birthdate="1995-05-05", phone=f"010-1111-{1000 + i}",
                dong_id=dong_list[i % len(dong_list)].id, trust_score=trust_scores[i],
            )
            user.set_password("test1234")
            other_users.append(user)
        db.session.add_all(other_users)
        db.session.commit()

        now = datetime.utcnow()

        # A PENDING photo owned by another (non-demo) user, ready to be
        # matched the moment the demo account uploads a photo of the same
        # plate/location — this is the live "killer demo" moment. Plate/
        # coords come from app.config (DEMO_PLATE/DEMO_LAT/DEMO_LON) rather
        # than being duplicated here, so this seeded photo and the
        # self-healing fallback in app/reports/routes.py's ensure_demo_hint()
        # (which recreates an equivalent photo once this one is consumed)
        # always agree on the same plate/location.
        waiting_path, waiting_hash = _make_seed_image(app, "demo_waiting.jpg", (200, 60, 60))
        waiting_photo = Photo(
            uploader_id=other_users[0].id, plate_number=app.config["DEMO_PLATE"], image_path=waiting_path,
            image_hash=waiting_hash, captured_at=now - timedelta(minutes=10), gps_source="MANUAL",
            latitude=app.config["DEMO_LAT"], longitude=app.config["DEMO_LON"],
            dong_id=other_users[0].dong_id, status="PENDING",
        )
        db.session.add(waiting_photo)

        # Historical VALID report between two other users, so the dashboard
        # and ranking look populated immediately.
        img_a_path, img_a_hash = _make_seed_image(app, "history_valid_a.jpg", (60, 120, 200))
        img_b_path, img_b_hash = _make_seed_image(app, "history_valid_b.jpg", (60, 160, 90))
        photo_a = Photo(
            uploader_id=other_users[1].id, plate_number="34나5678", image_path=img_a_path,
            image_hash=img_a_hash, captured_at=now - timedelta(days=1, hours=2), gps_source="MANUAL",
            latitude=37.5013, longitude=127.0398, dong_id=other_users[1].dong_id, status="MATCHED",
        )
        photo_b = Photo(
            uploader_id=other_users[2].id, plate_number="34나5678", image_path=img_b_path,
            image_hash=img_b_hash, captured_at=now - timedelta(days=1), gps_source="MANUAL",
            latitude=37.5014, longitude=127.0399, dong_id=other_users[1].dong_id, status="MATCHED",
        )
        db.session.add_all([photo_a, photo_b])
        db.session.flush()

        valid_report = Report(
            plate_number="34나5678", dong_id=other_users[1].dong_id,
            photo_a_id=photo_b.id, photo_b_id=photo_a.id, time_gap_seconds=7200, ai_score=85,
            ai_reason="시간차 120분 (-0점); 상습 위반 이력 0건 (+0점); 반복 단시간 방문 이력 0건 (-0점)",
            status="VALID", matched_at=now - timedelta(days=1), resolved_at=now - timedelta(days=1),
        )
        db.session.add(valid_report)
        db.session.flush()
        db.session.add_all(
            [
                TrustScoreLog(user_id=other_users[1].id, report_id=valid_report.id, delta=5, reason="유효 신고 매칭 성공"),
                TrustScoreLog(user_id=other_users[2].id, report_id=valid_report.id, delta=5, reason="유효 신고 매칭 성공"),
            ]
        )
        other_users[1].trust_score += 5
        other_users[2].trust_score += 5

        # Historical REJECTED report (ambiguous repeat-visit pattern).
        img_c_path, img_c_hash = _make_seed_image(app, "history_rejected_a.jpg", (150, 150, 60))
        img_d_path, img_d_hash = _make_seed_image(app, "history_rejected_b.jpg", (150, 60, 150))
        photo_c = Photo(
            uploader_id=other_users[3].id, plate_number="56다1234", image_path=img_c_path,
            image_hash=img_c_hash, captured_at=now - timedelta(hours=50), gps_source="MANUAL",
            latitude=37.4980, longitude=127.0450, dong_id=other_users[3].dong_id, status="MATCHED",
        )
        photo_d = Photo(
            uploader_id=other_users[4].id, plate_number="56다1234", image_path=img_d_path,
            image_hash=img_d_hash, captured_at=now - timedelta(hours=2), gps_source="MANUAL",
            latitude=37.4981, longitude=127.0451, dong_id=other_users[3].dong_id, status="MATCHED",
        )
        db.session.add_all([photo_c, photo_d])
        db.session.flush()
        db.session.add(
            Report(
                plate_number="56다1234", dong_id=other_users[3].dong_id,
                photo_a_id=photo_c.id, photo_b_id=photo_d.id, time_gap_seconds=172800, ai_score=30,
                ai_reason="시간차 2880분 (-35점); 상습 위반 이력 0건 (+0점); 반복 단시간 방문 이력 4건 (-30점)",
                status="REJECTED", matched_at=now - timedelta(hours=2), resolved_at=now - timedelta(hours=2),
            )
        )

        # Historical FALSE photo (duplicate-image reuse fraud example).
        false_path, false_hash = _make_seed_image(app, "history_false.jpg", (30, 30, 30))
        db.session.add(
            Photo(
                uploader_id=other_users[3].id, plate_number="78라4321", image_path=false_path,
                image_hash=false_hash, captured_at=now - timedelta(hours=5), gps_source="MANUAL",
                latitude=37.5100, longitude=127.0500, dong_id=other_users[3].dong_id, status="FALSE",
            )
        )
        db.session.add(
            TrustScoreLog(user_id=other_users[3].id, report_id=None, delta=-30, reason="중복 이미지 재사용 시도로 허위 판정")
        )

        db.session.commit()
        print("시드 데이터 생성 완료. 데모 계정: demo / demo1234")

    return app


if __name__ == "__main__":
    run()
