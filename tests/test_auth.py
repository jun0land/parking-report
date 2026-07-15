from app.models import Dong, User


def _create_dong(app, db, name="역삼1동"):
    with app.app_context():
        dong = Dong(name=name)
        db.session.add(dong)
        db.session.commit()
        return dong.id


def test_landing_page_shows_demo_button(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "데모 계정으로 둘러보기".encode("utf-8") in response.data


def test_signup_creates_user_and_logs_in(app, db, client):
    dong_id = _create_dong(app, db)

    response = client.post(
        "/signup",
        data={
            "username": "alice",
            "password": "hunter22",
            "password_confirm": "hunter22",
            "nickname": "앨리스",
            "name": "김앨리스",
            "birthdate": "1990-01-01",
            "phone": "010-1234-5678",
            "dong_id": dong_id,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert User.query.filter_by(username="alice").count() == 1

    my_reports_response = client.get("/my-reports")
    assert my_reports_response.status_code == 200  # logged in automatically after signup


def test_signup_page_shows_fake_verification_widget(client):
    response = client.get("/signup")
    assert "본인인증".encode("utf-8") in response.data
    assert b"simulateVerification" in response.data


def test_login_with_wrong_password_fails(app, db, client):
    dong_id = _create_dong(app, db)
    with app.app_context():
        user = User(
            username="bob", nickname="밥", name="김밥", birthdate="1990-01-01",
            phone="010-0000-0000", dong_id=dong_id,
        )
        user.set_password("correct-password")
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/login", data={"username": "bob", "password": "wrong"}, follow_redirects=True
    )
    assert "아이디 또는 비밀번호가 올바르지 않습니다".encode("utf-8") in response.data


def test_demo_login_without_seed_data_flashes_error(client):
    response = client.get("/demo-login", follow_redirects=True)
    assert "데모 계정이 아직 준비되지 않았습니다".encode("utf-8") in response.data


def test_demo_login_logs_in_demo_user(app, db, client):
    dong_id = _create_dong(app, db)
    with app.app_context():
        demo_user = User(
            username="demo", nickname="데모유저", name="김데모", birthdate="1990-01-01",
            phone="010-0000-0000", dong_id=dong_id, is_demo=True,
        )
        demo_user.set_password("demo1234")
        db.session.add(demo_user)
        db.session.commit()

    response = client.get("/demo-login", follow_redirects=True)
    assert response.status_code == 200
    my_reports_response = client.get("/my-reports")
    assert my_reports_response.status_code == 200
