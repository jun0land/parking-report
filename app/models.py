from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class Dong(db.Model):
    __tablename__ = "dongs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nickname = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    birthdate = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    dong_id = db.Column(db.Integer, db.ForeignKey("dongs.id"), nullable=False)
    trust_score = db.Column(db.Integer, nullable=False, default=100)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    dong = db.relationship("Dong")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Photo(db.Model):
    __tablename__ = "photos"

    id = db.Column(db.Integer, primary_key=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plate_number = db.Column(db.String(20), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)
    image_hash = db.Column(db.String(64), nullable=False, index=True)
    captured_at = db.Column(db.DateTime, nullable=False)
    gps_source = db.Column(db.String(10), nullable=False)  # "EXIF" or "MANUAL"
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    dong_id = db.Column(db.Integer, db.ForeignKey("dongs.id"), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="PENDING")  # PENDING/MATCHED/EXPIRED/FALSE
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    uploader = db.relationship("User", backref="photos")
    dong = db.relationship("Dong")


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), nullable=False)
    dong_id = db.Column(db.Integer, db.ForeignKey("dongs.id"), nullable=False)
    photo_a_id = db.Column(db.Integer, db.ForeignKey("photos.id"), nullable=False)
    photo_b_id = db.Column(db.Integer, db.ForeignKey("photos.id"), nullable=False)
    time_gap_seconds = db.Column(db.Integer, nullable=False)
    ai_score = db.Column(db.Float, nullable=False)
    ai_reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="REVIEWING")  # REVIEWING/VALID/REJECTED/FALSE
    matched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    dong = db.relationship("Dong")
    photo_a = db.relationship("Photo", foreign_keys=[photo_a_id])
    photo_b = db.relationship("Photo", foreign_keys=[photo_b_id])


class TrustScoreLog(db.Model):
    __tablename__ = "trust_score_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id"), nullable=True)
    delta = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
