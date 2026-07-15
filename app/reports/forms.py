from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import FloatField, StringField, SubmitField
from wtforms.validators import DataRequired, Optional


class UploadForm(FlaskForm):
    photo = FileField(
        "사진",
        validators=[
            FileRequired(message="사진을 선택해주세요."),
            FileAllowed(["jpg", "jpeg", "png"], "이미지 파일만 업로드할 수 있어요."),
        ],
    )
    plate_number = StringField(
        "번호판 (데모: 수동 입력 — 실서비스에서는 Vision AI 자동 인식으로 대체됩니다)",
        validators=[DataRequired()],
    )
    manual_latitude = FloatField("위도 (EXIF 인식 실패 시 입력)", validators=[Optional()])
    manual_longitude = FloatField("경도 (EXIF 인식 실패 시 입력)", validators=[Optional()])
    manual_captured_at = StringField(
        "촬영 시각 YYYY-MM-DD HH:MM:SS (EXIF 인식 실패 시 입력)", validators=[Optional()]
    )
    submit = SubmitField("업로드")
