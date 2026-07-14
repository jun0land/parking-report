from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth.forms import LoginForm, SignupForm
from app.extensions import db
from app.models import Dong, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("index.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    form = SignupForm()
    form.dong_id.choices = [(d.id, d.name) for d in Dong.query.order_by(Dong.name).all()]

    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("이미 사용 중인 아이디입니다.", "error")
            return render_template("auth/signup.html", form=form)
        if User.query.filter_by(nickname=form.nickname.data).first():
            flash("이미 사용 중인 닉네임입니다.", "error")
            return render_template("auth/signup.html", form=form)

        user = User(
            username=form.username.data,
            nickname=form.nickname.data,
            name=form.name.data,
            birthdate=form.birthdate.data,
            phone=form.phone.data,
            dong_id=form.dong_id.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("본인인증이 완료되었습니다 (데모용 시뮬레이션). 가입을 환영합니다!", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/signup.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("auth/login.html", form=form)
        login_user(user)
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/demo-login")
def demo_login():
    demo_user = User.query.filter_by(is_demo=True).first()
    if demo_user is None:
        flash("데모 계정이 아직 준비되지 않았습니다. scripts/seed_data.py를 먼저 실행해주세요.", "error")
        return redirect(url_for("auth.login"))
    login_user(demo_user)
    return redirect(url_for("dashboard.index"))
