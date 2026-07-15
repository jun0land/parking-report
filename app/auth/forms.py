from flask_wtf import FlaskForm
from wtforms import PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class SignupForm(FlaskForm):
    username = StringField("아이디", validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField("비밀번호", validators=[DataRequired(), Length(min=6)])
    password_confirm = PasswordField(
        "비밀번호 확인",
        validators=[DataRequired(), EqualTo("password", message="비밀번호가 일치하지 않습니다")],
    )
    nickname = StringField("닉네임", validators=[DataRequired(), Length(min=2, max=50)])
    name = StringField("이름", validators=[DataRequired(), Length(max=50)])
    birthdate = StringField("생년월일", validators=[DataRequired(), Length(max=10)])
    phone = StringField("휴대폰번호", validators=[DataRequired(), Length(max=20)])
    dong_id = SelectField("행정동", coerce=int, validators=[DataRequired()])
    submit = SubmitField("가입 완료")


class LoginForm(FlaskForm):
    username = StringField("아이디", validators=[DataRequired()])
    password = PasswordField("비밀번호", validators=[DataRequired()])
    submit = SubmitField("로그인")
