import io
from datetime import datetime, timedelta

from PIL import Image

from app.models import Dong, Report


def _image_bytes(color):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=color).save(buf, "JPEG")
    return buf.getvalue()


def _signup(client, username, nickname, dong_id):
    return client.post(
        "/signup",
        data={
            "username": username, "password": "test1234", "password_confirm": "test1234",
            "nickname": nickname, "name": "테스트", "birthdate": "1990-01-01",
            "phone": "010-0000-0000", "dong_id": dong_id,
        },
        follow_redirects=True,
    )


def test_full_flow_two_citizens_to_dashboard_ranking(app, db, client):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        dong_id = dong.id

    _signup(client, "alice", "앨리스", dong_id)
    client.get("/logout")
    _signup(client, "bob", "밥돌이", dong_id)
    client.get("/logout")

    now = datetime.utcnow()
    older_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    newer_time = now.strftime("%Y-%m-%d %H:%M:%S")

    client.post("/login", data={"username": "alice", "password": "test1234"}, follow_redirects=True)
    client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes((10, 20, 30))), "car1.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5006",
            "manual_longitude": "127.0364",
            "manual_captured_at": older_time,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    client.get("/logout")

    client.post("/login", data={"username": "bob", "password": "test1234"}, follow_redirects=True)
    response = client.post(
        "/upload",
        data={
            "photo": (io.BytesIO(_image_bytes((200, 100, 50))), "car2.jpg"),
            "plate_number": "12가3456",
            "manual_latitude": "37.5007",
            "manual_longitude": "127.0365",
            "manual_captured_at": newer_time,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert "매칭되어 신고가 접수되었습니다".encode("utf-8") in response.data

    with app.app_context():
        report = Report.query.filter_by(plate_number="12가3456").first()
        assert report is not None
        assert report.status == "VALID"

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "밥".encode("utf-8") in dashboard.data
    assert "역삼1동".encode("utf-8") in dashboard.data
