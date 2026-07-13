# 클린파킹 (크라우드소싱 불법 주정차 자동 신고 플랫폼) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Flask + SQLite web app where citizens each upload one photo of an illegally parked car, and the server automatically stitches together two different citizens' photos of the same plate/location into a submitted report, backed by a rule-based "AI" review engine, trust scores, and a clean-index dashboard — deployable to PythonAnywhere's free tier.

**Architecture:** Flask app factory (`app/__init__.py`) with three blueprints (`auth`, `reports`, `dashboard`) sharing one SQLAlchemy models module. A dedicated `app/reports/stitching.py` owns the whole match → score → resolve lifecycle so the upload route stays thin. Pure-Python helpers (`app/geo.py` for Haversine, `app/reports/exif_utils.py` for EXIF parsing) have no Flask dependency and are unit-tested in isolation.

**Tech Stack:** Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF, Pillow, Jinja2, SQLite, pytest. No other third-party dependencies.

## Global Constraints

- No external API calls, no GPU — everything (GPS distance, EXIF parsing, "AI" scoring) is self-contained Python. (Spec §2)
- PythonAnywhere free plan has a 512MB disk quota; keep `requirements.txt` to exactly the libraries listed above, keep seed images small and few, and resize every uploaded image to a max of 1280px before saving. (Spec §2, §10)
- PythonAnywhere free plan web apps (accounts created after 2026-01-15) auto-expire ~1 month after the last Reload; `DEPLOY.md` must contain a renewal checklist for the judging period. (Spec §10)
- License plate recognition is manual-entry-only in the demo; the upload form/code must carry a comment noting production would use Vision AI ANPR. (Spec §2, §9)
- Data Stitching match requires: same plate number, different uploaders, GPS distance ≤ 50m (Haversine), time gap 60 seconds–72 hours. (Spec §5)
- AI review score bands: score ≥ 70 → immediate `VALID`; 40 ≤ score < 70 → `REVIEWING`, lazily auto-resolved to `REJECTED` after a short demo delay; score < 40 → immediate `REJECTED`. (Spec §6)
- The "expired repeat-visit" signal in AI scoring MUST be computed from `captured_at` timestamps directly (`captured_at < now - 72h`), never from the lazily-updated `status` column — this was an identified bug in the original design. (Spec §5, §6)
- Duplicate-image-hash reuse is detected at upload time, independent of AI scoring: sets `Photo.status = "FALSE"`, applies -30 trust score to the uploader only, and creates no `Report` row (`report_id = NULL` in the trust log). (Spec §7)
- Trust score: starts at 100; `VALID` gives +5 to both contributing uploaders; `FALSE` gives -30 to the uploader who reused the image; `REJECTED` changes nothing. (Spec §8)
- Daily upload limits by trust score: ≥ 80 unlimited, 50–79 → 3/day, < 50 → 1/day. (Spec §8)
- Seed data must guarantee the demo account can trigger a live match: the seeded PENDING photo must belong to a non-demo user, and its plate number/coordinates must be surfaced to the demo user via an on-page banner. (Spec §9, §10)
- All UI copy is in Korean; layout is mobile-first responsive CSS.

---

## File Structure

```
parking-report/
├── app/
│   ├── __init__.py            # Flask app factory
│   ├── config.py              # Config class: paths, thresholds
│   ├── extensions.py          # db, login_manager, csrf singletons
│   ├── models.py              # Dong, User, Photo, Report, TrustScoreLog
│   ├── geo.py                 # haversine_distance_meters()
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── forms.py           # SignupForm, LoginForm
│   │   └── routes.py          # "/", /signup, /login, /logout, /demo-login
│   ├── reports/
│   │   ├── __init__.py
│   │   ├── forms.py           # UploadForm
│   │   ├── routes.py          # /upload, /my-reports
│   │   ├── exif_utils.py      # extract_gps_and_time()
│   │   ├── image_utils.py     # save_resized_image()
│   │   └── stitching.py       # matching + AI scoring + trust score lifecycle
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── routes.py          # /dashboard
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── auth/signup.html
│   │   ├── auth/login.html
│   │   ├── reports/upload.html
│   │   ├── reports/my_reports.html
│   │   └── dashboard/index.html
│   └── static/
│       ├── css/style.css
│       └── uploads/           # gitignored; created at runtime
├── scripts/
│   ├── __init__.py
│   └── seed_data.py
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_geo.py
│   ├── test_exif_utils.py
│   ├── test_image_utils.py
│   ├── test_auth.py
│   ├── test_upload.py
│   ├── test_stitching.py
│   ├── test_dashboard.py
│   ├── test_seed_data.py
│   └── test_end_to_end.py
├── wsgi.py
├── requirements.txt
├── DEPLOY.md
├── README.md
└── .gitignore
```

---

### Task 1: Project scaffolding — app factory, config, extensions, test harness

**Files:**
- Create: `app/config.py`
- Create: `app/extensions.py`
- Create: `app/__init__.py`
- Create: `wsgi.py`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `tests/conftest.py`
- Test: `tests/conftest.py` (fixtures used by every later test file)

**Interfaces:**
- Produces: `create_app(config_class=Config)` factory in `app/__init__.py`, `db` and `login_manager` in `app/extensions.py`, `Config` class in `app/config.py` with all keys listed in Global Constraints (thresholds, `UPLOAD_FOLDER`, `MAX_IMAGE_DIMENSION`).
- Produces: pytest fixtures `app`, `client`, `db` in `tests/conftest.py`, usable by every later test file without modification.

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import os
import tempfile

import pytest


@pytest.fixture
def app():
    from app import create_app
    from app.config import Config
    from app.extensions import db as _db

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    upload_dir = tempfile.mkdtemp()

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path
        UPLOAD_FOLDER = upload_dir

    application = create_app(TestConfig)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from app.extensions import db as _db

    return _db
```

Create `tests/test_smoke.py`:

```python
def test_app_factory_creates_working_app(app):
    assert app.config["TESTING"] is True


def test_db_tables_exist(app, db):
    with app.app_context():
        # Will raise if create_app()/db.init_app() wiring is broken.
        db.session.execute(db.text("SELECT 1"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` (nothing exists yet).

- [ ] **Step 3: Write minimal implementation**

Create `app/config.py`:

```python
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "instance", "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8MB upload cap
    MAX_IMAGE_DIMENSION = 1280

    # Data Stitching matching thresholds
    MATCH_RADIUS_METERS = 50
    MATCH_MIN_GAP_SECONDS = 60
    MATCH_MAX_GAP_SECONDS = 60 * 60 * 72  # 72 hours

    # AI review thresholds
    AI_VALID_THRESHOLD = 70
    AI_REJECT_THRESHOLD = 40
    REVIEWING_AUTO_RESOLVE_SECONDS = 60  # demo-only short delay

    # Trust score
    TRUST_SCORE_VALID_DELTA = 5
    TRUST_SCORE_FALSE_DELTA = -30
    DAILY_LIMIT_HIGH_SCORE = 80    # >= this: unlimited uploads/day
    DAILY_LIMIT_MID_SCORE = 50     # >= this: 3/day, else 1/day
    DAILY_LIMIT_MID_COUNT = 3
    DAILY_LIMIT_LOW_COUNT = 1
```

Create `app/extensions.py`:

```python
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
csrf = CSRFProtect()
```

Create `app/__init__.py`:

```python
import os

from flask import Flask

from app.config import Config
from app.extensions import csrf, db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.reports.routes import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(dashboard_bp)

    return app
```

Since `app/models.py`, `app/auth/routes.py`, `app/reports/routes.py`, and `app/dashboard/routes.py` don't exist yet, add temporary empty-but-valid placeholders so the factory can import them (they will be filled in by Tasks 2, 5, 7/9, 11):

Create `app/models.py`:

```python
from app.extensions import db  # noqa: F401
```

Create `app/auth/__init__.py` (empty), `app/reports/__init__.py` (empty), `app/dashboard/__init__.py` (empty).

Create `app/auth/routes.py`:

```python
from flask import Blueprint

auth_bp = Blueprint("auth", __name__)
```

Create `app/reports/routes.py`:

```python
from flask import Blueprint

reports_bp = Blueprint("reports", __name__)
```

Create `app/dashboard/routes.py`:

```python
from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)
```

Create `wsgi.py`:

```python
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
```

Create `requirements.txt`:

```
Flask==3.0.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-WTF==1.2.1
Pillow==10.4.0
pytest==8.3.2
```

Create `.gitignore`:

```
__pycache__/
*.pyc
instance/
app/static/uploads/
.venv/
venv/
*.egg-info/
.pytest_cache/
*.db
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -r requirements.txt && pytest tests/test_smoke.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/extensions.py app/__init__.py app/models.py \
  app/auth/__init__.py app/auth/routes.py app/reports/__init__.py app/reports/routes.py \
  app/dashboard/__init__.py app/dashboard/routes.py wsgi.py requirements.txt .gitignore \
  tests/conftest.py tests/test_smoke.py
git commit -m "feat: scaffold Flask app factory, config, and test harness"
```

---

### Task 2: SQLAlchemy models

**Files:**
- Modify: `app/models.py` (replace placeholder)
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `db` from `app.extensions` (Task 1).
- Produces: `Dong(id, name)`, `User(id, username, password_hash, nickname, name, birthdate, phone, dong_id, trust_score, is_demo, created_at, set_password(password), check_password(password))`, `Photo(id, uploader_id, plate_number, image_path, image_hash, captured_at, gps_source, latitude, longitude, dong_id, status, created_at)` with `uploader` relationship (backref `photos`), `Report(id, plate_number, dong_id, photo_a_id, photo_b_id, time_gap_seconds, ai_score, ai_reason, status, matched_at, resolved_at)` with `photo_a`/`photo_b`/`dong` relationships, `TrustScoreLog(id, user_id, report_id, delta, reason, created_at)`. `Photo.status` values used elsewhere: `"PENDING"`, `"MATCHED"`, `"EXPIRED"`, `"FALSE"`. `Report.status` values used elsewhere: `"REVIEWING"`, `"VALID"`, `"REJECTED"`, `"FALSE"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `AttributeError` or `ImportError` (models don't exist yet).

- [ ] **Step 3: Write minimal implementation**

Replace `app/models.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py tests/test_smoke.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add SQLAlchemy models for Dong, User, Photo, Report, TrustScoreLog"
```

---

### Task 3: Haversine geo utility

**Files:**
- Create: `app/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `haversine_distance_meters(lat1, lon1, lat2, lon2) -> float`, used by Task 8's `stitching.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_geo.py`:

```python
import pytest

from app.geo import haversine_distance_meters


def test_same_point_is_zero_distance():
    assert haversine_distance_meters(37.5006, 127.0364, 37.5006, 127.0364) == pytest.approx(0.0, abs=0.01)


def test_known_short_distance_within_tolerance():
    # ~111m per 0.001 degree of latitude near Seoul.
    distance = haversine_distance_meters(37.5006, 127.0364, 37.5016, 127.0364)
    assert distance == pytest.approx(111.0, rel=0.05)


def test_distance_beyond_50m_radius():
    distance = haversine_distance_meters(37.5006, 127.0364, 37.5010, 127.0370)
    assert distance > 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_geo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.geo'`

- [ ] **Step 3: Write minimal implementation**

Create `app/geo.py`:

```python
from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_METERS = 6371000


def haversine_distance_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in meters."""
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return EARTH_RADIUS_METERS * c
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_geo.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/geo.py tests/test_geo.py
git commit -m "feat: add Haversine distance utility"
```

---

### Task 4: EXIF extraction utility

**Files:**
- Create: `app/reports/exif_utils.py`
- Test: `tests/test_exif_utils.py`

**Interfaces:**
- Produces: `extract_gps_and_time(image_file) -> {"captured_at": datetime|None, "latitude": float|None, "longitude": float|None}`, consumed by Task 7's upload route.

- [ ] **Step 1: Write the failing test**

Create `tests/test_exif_utils.py`:

```python
import io

import pytest
from PIL import ExifTags, Image

from app.reports.exif_utils import _dms_to_decimal, extract_gps_and_time

EXIF_OFFSET_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "ExifOffset")


def test_dms_to_decimal_north_east_is_positive():
    assert _dms_to_decimal((37, 30, 2.16), "N") == pytest.approx(37.500600, rel=1e-4)


def test_dms_to_decimal_south_west_is_negative():
    assert _dms_to_decimal((37, 30, 2.16), "S") < 0


def test_no_exif_returns_all_none():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color=(10, 20, 30)).save(buf, "JPEG")
    buf.seek(0)

    result = extract_gps_and_time(buf)

    assert result == {"captured_at": None, "latitude": None, "longitude": None}


def test_datetime_original_in_exif_sub_ifd_is_parsed():
    # Real cameras store DateTimeOriginal inside the Exif sub-IFD (pointer
    # tag 0x8769 / "ExifOffset"), not the flat top-level IFD0. Writing it at
    # the flat level (as a naive implementation might read from) does NOT
    # round-trip through the sub-IFD accessor — verified directly against
    # Pillow: flat-level writes are invisible to get_ifd() reads and vice
    # versa. This test mimics the real-camera layout.
    image = Image.new("RGB", (50, 50), color=(10, 20, 30))
    exif = image.getexif()
    sub_ifd = exif.get_ifd(EXIF_OFFSET_TAG)
    sub_ifd[36867] = "2026:07:10 09:30:00"  # DateTimeOriginal

    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif.tobytes())
    buf.seek(0)

    result = extract_gps_and_time(buf)

    assert result["captured_at"].isoformat() == "2026-07-10T09:30:00"
    assert result["latitude"] is None
    assert result["longitude"] is None


def test_datetime_fallback_from_ifd0_when_no_exif_sub_ifd():
    # Some encoders only set the plain top-level "DateTime" tag (306) with
    # no Exif sub-IFD at all — extract_gps_and_time must still find it.
    image = Image.new("RGB", (50, 50), color=(10, 20, 30))
    exif = image.getexif()
    exif[306] = "2026:07:10 09:30:00"  # DateTime (plain IFD0 tag)

    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif.tobytes())
    buf.seek(0)

    result = extract_gps_and_time(buf)

    assert result["captured_at"].isoformat() == "2026-07-10T09:30:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exif_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.exif_utils'`

- [ ] **Step 3: Write minimal implementation**

Create `app/reports/exif_utils.py`:

```python
from datetime import datetime

from PIL import ExifTags, Image

GPS_IFD_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "GPSInfo")
EXIF_IFD_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "ExifOffset")
DATETIME_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "DateTime")
DATETIME_ORIGINAL_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal")

# Standard EXIF GPS sub-IFD tag numbers (fixed by the EXIF spec, not looked up
# via ExifTags.TAGS which only covers the main IFD).
GPS_LATITUDE_REF = 1
GPS_LATITUDE = 2
GPS_LONGITUDE_REF = 3
GPS_LONGITUDE = 4


def _dms_to_decimal(dms, ref):
    degrees, minutes, seconds = dms
    decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_gps_and_time(image_file):
    """Extract capture time and GPS coordinates from an image's EXIF data.

    Returns a dict with keys "captured_at", "latitude", "longitude". Any
    value that can't be determined from EXIF is None — callers must fall
    back to manual user input in that case (the common case for photos that
    passed through phone camera apps or browser uploads, which often strip
    GPS EXIF).

    DateTimeOriginal (the tag real cameras actually populate) lives in the
    Exif sub-IFD (pointer tag "ExifOffset" / 0x8769), not the flat top-level
    IFD0 that Image.getexif() returns directly — it must be fetched via
    get_ifd(EXIF_IFD_TAG). The plain "DateTime" tag (306) is checked as a
    fallback for images that only set that flatter, less-specific tag.
    """
    result = {"captured_at": None, "latitude": None, "longitude": None}

    try:
        image = Image.open(image_file)
        exif = image.getexif()
    except Exception:
        return result

    if not exif:
        return result

    datetime_str = None
    if hasattr(exif, "get_ifd"):
        exif_sub_ifd = exif.get_ifd(EXIF_IFD_TAG)
        if exif_sub_ifd:
            datetime_str = exif_sub_ifd.get(DATETIME_ORIGINAL_TAG)
    if not datetime_str:
        datetime_str = exif.get(DATETIME_TAG)

    if datetime_str:
        try:
            result["captured_at"] = datetime.strptime(datetime_str, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass

    gps_info = exif.get_ifd(GPS_IFD_TAG) if hasattr(exif, "get_ifd") else None
    if gps_info:
        try:
            result["latitude"] = _dms_to_decimal(gps_info[GPS_LATITUDE], gps_info[GPS_LATITUDE_REF])
            result["longitude"] = _dms_to_decimal(gps_info[GPS_LONGITUDE], gps_info[GPS_LONGITUDE_REF])
        except (KeyError, TypeError, ZeroDivisionError):
            result["latitude"] = None
            result["longitude"] = None

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_exif_utils.py -v`
Expected: 5 passed

Note: full GPS-IFD round-trip isn't exercised here because Pillow's support for *writing* nested GPS sub-IFDs is inconsistent across versions. The realistic path — manual lat/lon entry — is exercised end-to-end in Task 9's integration test instead, consistent with the spec's note that EXIF GPS is usually stripped by phone/browser uploads anyway.

- [ ] **Step 5: Commit**

```bash
git add app/reports/exif_utils.py tests/test_exif_utils.py
git commit -m "feat: add EXIF GPS/time extraction utility with manual-entry fallback contract"
```

---

### Task 5: Landing page + Auth (signup with fake verification, login, logout, demo login)

**Files:**
- Create: `app/auth/forms.py`
- Modify: `app/auth/routes.py` (replace placeholder)
- Create: `app/templates/base.html`
- Create: `app/templates/index.html`
- Create: `app/templates/auth/signup.html`
- Create: `app/templates/auth/login.html`
- Create: `app/static/css/style.css`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `User`, `Dong` from `app.models` (Task 2).
- Produces: routes `GET /` (redirects to `/dashboard` if authenticated, else renders landing page), `GET/POST /signup`, `GET/POST /login`, `GET /logout`, `GET /demo-login` (logs in the seeded `is_demo=True` user or flashes an error if none exists yet).

- [ ] **Step 1: Write the failing test**

Create `tests/test_auth.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — no `/`, `/signup`, `/login`, `/demo-login` routes exist yet, and `/my-reports` doesn't exist (expected until Task 7; for now these tests fail with 404/AttributeError, confirming nothing is implemented).

- [ ] **Step 3: Write minimal implementation**

Create `app/auth/forms.py`:

```python
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
```

Replace `app/auth/routes.py`:

```python
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
```

Create `app/templates/base.html`:

```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}클린파킹{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
  <nav class="navbar">
    <a href="{{ url_for('auth.home') }}" class="brand">클린파킹</a>
    <div class="nav-links">
      {% if current_user.is_authenticated %}
        <a href="{{ url_for('reports.upload') }}">신고하기</a>
        <a href="{{ url_for('reports.my_reports') }}">내 신고 현황</a>
        <a href="{{ url_for('dashboard.index') }}">대시보드</a>
        <a href="{{ url_for('auth.logout') }}">로그아웃</a>
      {% else %}
        <a href="{{ url_for('auth.login') }}">로그인</a>
        <a href="{{ url_for('auth.signup') }}">회원가입</a>
      {% endif %}
    </div>
  </nav>
  <main class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <ul class="flashes">
          {% for category, message in messages %}
            <li class="flash flash-{{ category }}">{{ message }}</li>
          {% endfor %}
        </ul>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

Create `app/templates/index.html`:

```html
{% extends "base.html" %}
{% block title %}클린파킹 - 우리 동네 불법주정차 신고{% endblock %}
{% block content %}
<section class="hero">
  <h1>사진 한 장이면 충분해요</h1>
  <p>서로 다른 두 시민이 각자 한 장씩만 찍으면, 나머지는 서버가 자동으로 이어붙여(Data Stitching) 신고를 완성합니다. 현장에서 1분을 기다릴 필요가 없어요.</p>
  <div class="hero-actions">
    <a class="btn btn-primary" href="{{ url_for('auth.demo_login') }}">데모 계정으로 둘러보기</a>
    <a class="btn btn-secondary" href="{{ url_for('auth.signup') }}">회원가입</a>
  </div>
</section>
{% endblock %}
```

Create `app/templates/auth/signup.html`:

```html
{% extends "base.html" %}
{% block title %}회원가입 - 클린파킹{% endblock %}
{% block content %}
<h1>회원가입</h1>
<form method="post" novalidate>
  {{ form.hidden_tag() }}
  <label>{{ form.username.label }} {{ form.username() }}</label>
  <label>{{ form.password.label }} {{ form.password() }}</label>
  <label>{{ form.password_confirm.label }} {{ form.password_confirm() }}</label>
  <label>{{ form.nickname.label }} {{ form.nickname() }}</label>
  <label>{{ form.dong_id.label }} {{ form.dong_id() }}</label>

  <fieldset class="verify-box">
    <legend>본인인증 (데모용 시뮬레이션)</legend>
    <label>{{ form.name.label }} {{ form.name() }}</label>
    <label>{{ form.birthdate.label }} {{ form.birthdate(placeholder="YYYY-MM-DD") }}</label>
    <label>{{ form.phone.label }} {{ form.phone(placeholder="010-0000-0000") }}</label>
    <button type="button" id="verify-btn" onclick="simulateVerification()">인증요청</button>
    <span id="verify-status"></span>
  </fieldset>

  {{ form.submit(class_="btn btn-primary") }}
</form>
<script>
function simulateVerification() {
  var btn = document.getElementById("verify-btn");
  var status = document.getElementById("verify-status");
  btn.disabled = true;
  status.textContent = "인증 중...";
  setTimeout(function () {
    status.textContent = "✓ 인증 완료 (데모용 시뮬레이션)";
    status.classList.add("verified");
  }, 1500);
}
</script>
{% endblock %}
```

Create `app/templates/auth/login.html`:

```html
{% extends "base.html" %}
{% block title %}로그인 - 클린파킹{% endblock %}
{% block content %}
<h1>로그인</h1>
<form method="post" novalidate>
  {{ form.hidden_tag() }}
  <label>{{ form.username.label }} {{ form.username() }}</label>
  <label>{{ form.password.label }} {{ form.password() }}</label>
  {{ form.submit(class_="btn btn-primary") }}
</form>
<p><a href="{{ url_for('auth.demo_login') }}">데모 계정으로 둘러보기</a></p>
{% endblock %}
```

Create `app/static/css/style.css`:

```css
:root {
  color-scheme: light dark;
  --accent: #ff6b3d;
  --bg: #ffffff;
  --fg: #1a1a1a;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--fg);
}

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e5e5e5;
}

.nav-links a { margin-left: 0.75rem; text-decoration: none; color: inherit; }
.brand { font-weight: bold; text-decoration: none; color: var(--accent); }

.container { max-width: 640px; margin: 0 auto; padding: 1rem; }

.hero { text-align: center; padding: 2rem 1rem; }
.hero-actions { margin-top: 1.5rem; display: flex; gap: 0.75rem; justify-content: center; flex-wrap: wrap; }

.btn {
  display: inline-block;
  padding: 0.6rem 1.2rem;
  border-radius: 8px;
  text-decoration: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
}
.btn-primary { background: var(--accent); color: white; }
.btn-secondary { background: #eee; color: var(--fg); }

form label { display: block; margin-bottom: 0.75rem; }
form input, form select { display: block; width: 100%; padding: 0.5rem; margin-top: 0.25rem; }

.verify-box { border: 1px dashed #ccc; padding: 0.75rem; border-radius: 8px; margin: 1rem 0; }
#verify-status.verified { color: green; font-weight: bold; }

.flashes { list-style: none; padding: 0; }
.flash { padding: 0.5rem 0.75rem; border-radius: 6px; margin-bottom: 0.5rem; }
.flash-success { background: #e6f7e9; }
.flash-error { background: #fdeaea; }
```

Update `app/reports/routes.py` (still a placeholder, but add the two route paths referenced by templates so `url_for` doesn't break page rendering during this task's tests — full logic lands in Tasks 7/9/10):

```python
from flask import Blueprint

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/upload")
def upload():
    return "placeholder"


@reports_bp.route("/my-reports")
def my_reports():
    return "placeholder"
```

Update `app/dashboard/routes.py` similarly:

```python
from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def index():
    return "placeholder"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auth.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/auth/forms.py app/auth/routes.py app/reports/routes.py app/dashboard/routes.py \
  app/templates/base.html app/templates/index.html app/templates/auth/signup.html \
  app/templates/auth/login.html app/static/css/style.css tests/test_auth.py
git commit -m "feat: add landing page and auth flow with simulated identity verification"
```

---

### Task 6: Image storage helper (resize + save)

**Files:**
- Create: `app/reports/image_utils.py`
- Test: `tests/test_image_utils.py`

**Interfaces:**
- Produces: `save_resized_image(raw_bytes, upload_folder, max_dimension) -> str` (path relative to the static folder, e.g. `"uploads/2026/07/<uuid>.jpg"`), consumed by Task 7's upload route.

- [ ] **Step 1: Write the failing test**

Create `tests/test_image_utils.py`:

```python
import io
import os

from PIL import Image

from app.reports.image_utils import save_resized_image


def test_save_resized_image_shrinks_large_image(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), color=(200, 100, 50)).save(buf, "JPEG")
    raw_bytes = buf.getvalue()

    relative_path = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)

    assert relative_path.startswith("uploads/")
    assert relative_path.endswith(".jpg")

    absolute_path = os.path.join(str(tmp_path), relative_path)
    assert os.path.exists(absolute_path)

    with Image.open(absolute_path) as saved:
        assert max(saved.size) <= 1280


def test_save_resized_image_generates_unique_filenames(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(1, 2, 3)).save(buf, "JPEG")
    raw_bytes = buf.getvalue()

    path_one = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)
    path_two = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)

    assert path_one != path_two
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_image_utils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.image_utils'`

- [ ] **Step 3: Write minimal implementation**

Create `app/reports/image_utils.py`:

```python
import io
import os
import uuid
from datetime import datetime

from PIL import Image


def save_resized_image(raw_bytes, upload_folder, max_dimension):
    """Resize an image so its longest side is at most max_dimension, save it
    as JPEG under upload_folder/uploads/YYYY/MM/<uuid>.jpg, and return the
    path relative to upload_folder (suitable for url_for('static', filename=...)).
    """
    image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    image.thumbnail((max_dimension, max_dimension))

    today = datetime.utcnow()
    relative_dir = os.path.join("uploads", f"{today.year:04d}", f"{today.month:02d}")
    absolute_dir = os.path.join(upload_folder, f"{today.year:04d}", f"{today.month:02d}")
    os.makedirs(absolute_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.jpg"
    image.save(os.path.join(absolute_dir, filename), "JPEG", quality=85)

    return os.path.join(relative_dir, filename).replace("\\", "/")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_image_utils.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/reports/image_utils.py tests/test_image_utils.py
git commit -m "feat: add image resize/save helper to respect disk quota"
```

---

### Task 7: Upload route (form, EXIF/manual fallback, daily limit, duplicate-hash FALSE detection)

**Files:**
- Create: `app/reports/forms.py`
- Modify: `app/reports/routes.py` (replace placeholder `upload`/`my_reports`)
- Create: `app/templates/reports/upload.html`
- Test: `tests/test_upload.py`

**Interfaces:**
- Consumes: `extract_gps_and_time` (Task 4), `save_resized_image` (Task 6), `Photo`, `TrustScoreLog` (Task 2).
- Produces: `check_daily_upload_limit(user) -> (bool, str|None)` and `get_demo_hint() -> dict|None` in `app/reports/routes.py`, both consumed by Task 9's integration wiring and reused as-is. `POST /upload` creates a `Photo` row; on duplicate `image_hash` it sets `status="FALSE"` and logs -30 trust score with no `Report`. This task does **not** yet call the stitching engine — that wiring is Task 9. `my_reports` route stays a placeholder here (`return "placeholder"`) since it needs Task 8's helpers; Task 10 replaces it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_upload.py`:

```python
import io

from PIL import Image

from app.models import Dong, Photo, TrustScoreLog, User


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
        follow_redirects=True,
    )

    assert "허위 신고로 판정".encode("utf-8") in response.data
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload.py -v`
Expected: FAIL — placeholder `/upload` route returns `"placeholder"` for both GET and POST, so none of the assertions about DB state or flash messages hold.

- [ ] **Step 3: Write minimal implementation**

Create `app/reports/forms.py`:

```python
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
```

Replace `app/reports/routes.py`:

```python
import hashlib
import io
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Photo, TrustScoreLog
from app.reports.exif_utils import extract_gps_and_time
from app.reports.forms import UploadForm
from app.reports.image_utils import save_resized_image

reports_bp = Blueprint("reports", __name__)


def check_daily_upload_limit(user):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = Photo.query.filter(
        Photo.uploader_id == user.id,
        Photo.created_at >= today_start,
    ).count()

    if user.trust_score >= current_app.config["DAILY_LIMIT_HIGH_SCORE"]:
        return True, None
    if user.trust_score >= current_app.config["DAILY_LIMIT_MID_SCORE"]:
        limit = current_app.config["DAILY_LIMIT_MID_COUNT"]
    else:
        limit = current_app.config["DAILY_LIMIT_LOW_COUNT"]

    if today_count >= limit:
        return False, f"신뢰도 점수에 따라 오늘 업로드 가능 횟수({limit}건)를 모두 사용했습니다."
    return True, None


def get_demo_hint():
    candidate = (
        Photo.query.filter_by(status="PENDING")
        .filter(Photo.uploader_id != current_user.id)
        .order_by(Photo.created_at.desc())
        .first()
    )
    if candidate is None:
        return None
    return {
        "plate_number": candidate.plate_number,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
    }


@reports_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    demo_hint = get_demo_hint() if current_user.is_demo else None

    if form.validate_on_submit():
        allowed, limit_message = check_daily_upload_limit(current_user)
        if not allowed:
            flash(limit_message, "error")
            return render_template("reports/upload.html", form=form, demo_hint=demo_hint)

        raw_bytes = form.photo.data.read()
        image_hash = hashlib.sha256(raw_bytes).hexdigest()
        duplicate = Photo.query.filter_by(image_hash=image_hash).first()

        gps_data = extract_gps_and_time(io.BytesIO(raw_bytes))
        captured_at = gps_data["captured_at"]
        latitude = gps_data["latitude"]
        longitude = gps_data["longitude"]
        gps_source = "EXIF"

        if captured_at is None:
            if not form.manual_captured_at.data:
                flash("EXIF에서 촬영 시각을 찾을 수 없습니다. 촬영 시각을 직접 입력해주세요.", "error")
                return render_template("reports/upload.html", form=form, demo_hint=demo_hint)
            captured_at = datetime.strptime(form.manual_captured_at.data, "%Y-%m-%d %H:%M:%S")
            gps_source = "MANUAL"

        if latitude is None or longitude is None:
            if form.manual_latitude.data is None or form.manual_longitude.data is None:
                flash("EXIF에서 위치 정보를 찾을 수 없습니다. 위도/경도를 직접 입력해주세요.", "error")
                return render_template("reports/upload.html", form=form, demo_hint=demo_hint)
            latitude = form.manual_latitude.data
            longitude = form.manual_longitude.data
            gps_source = "MANUAL"

        image_path = save_resized_image(
            raw_bytes, current_app.config["UPLOAD_FOLDER"], current_app.config["MAX_IMAGE_DIMENSION"]
        )

        photo = Photo(
            uploader_id=current_user.id,
            plate_number=form.plate_number.data,
            image_path=image_path,
            image_hash=image_hash,
            captured_at=captured_at,
            gps_source=gps_source,
            latitude=latitude,
            longitude=longitude,
            dong_id=current_user.dong_id,
            status="FALSE" if duplicate is not None else "PENDING",
        )
        db.session.add(photo)

        if duplicate is not None:
            current_user.trust_score += current_app.config["TRUST_SCORE_FALSE_DELTA"]
            db.session.add(
                TrustScoreLog(
                    user_id=current_user.id,
                    report_id=None,
                    delta=current_app.config["TRUST_SCORE_FALSE_DELTA"],
                    reason="중복 이미지 재사용 시도로 허위 판정",
                )
            )
            db.session.commit()
            flash("이미 사용된 사진입니다. 허위 신고로 판정되어 신뢰도 점수가 -30점 되었습니다.", "error")
            return redirect(url_for("reports.my_reports"))

        db.session.commit()
        flash("사진이 업로드되었습니다. 같은 차량의 다른 사진이 올라오면 자동으로 매칭됩니다.", "success")
        return redirect(url_for("reports.my_reports"))

    return render_template("reports/upload.html", form=form, demo_hint=demo_hint)


@reports_bp.route("/my-reports")
@login_required
def my_reports():
    return "placeholder"
```

Create `app/templates/reports/upload.html`:

```html
{% extends "base.html" %}
{% block title %}사진 업로드 - 클린파킹{% endblock %}
{% block content %}
<h1>불법 주정차 사진 업로드</h1>

{% if demo_hint %}
<div class="verify-box">
  <strong>데모 시연 안내</strong>
  <p>번호판 <code>{{ demo_hint.plate_number }}</code>, 위도 <code>{{ demo_hint.latitude }}</code>,
  경도 <code>{{ demo_hint.longitude }}</code>를 입력해보세요 — 다른 시민이 방금 올린 사진과 바로 매칭됩니다.</p>
</div>
{% endif %}

<form method="post" enctype="multipart/form-data" novalidate>
  {{ form.hidden_tag() }}
  <label>{{ form.photo.label }} {{ form.photo() }}</label>
  <label>{{ form.plate_number.label }} {{ form.plate_number() }}</label>
  <p>위치 정보를 찾을 수 없어요 — EXIF 인식에 실패하면 아래에 직접 입력해주세요.</p>
  <label>{{ form.manual_latitude.label }} {{ form.manual_latitude() }}</label>
  <label>{{ form.manual_longitude.label }} {{ form.manual_longitude() }}</label>
  <label>{{ form.manual_captured_at.label }} {{ form.manual_captured_at(placeholder="2026-07-10 09:00:00") }}</label>
  {{ form.submit(class_="btn btn-primary") }}
</form>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/reports/forms.py app/reports/routes.py app/templates/reports/upload.html tests/test_upload.py
git commit -m "feat: add photo upload route with EXIF/manual fallback, daily limits, and duplicate-hash FALSE detection"
```

---

### Task 8: Data Stitching + AI review engine

**Files:**
- Create: `app/reports/stitching.py`
- Test: `tests/test_stitching.py`

**Interfaces:**
- Consumes: `haversine_distance_meters` (Task 3), `Photo`, `Report`, `TrustScoreLog` (Task 2), a `config` dict-like object (in practice `current_app.config`, but tests pass a plain dict with the same keys as `app/config.py`'s `Config` class).
- Produces: `find_match_candidate(new_photo, config) -> Photo|None`, `score_match(older_photo, newer_photo, config, now) -> (float, str)`, `resolve_status_for_score(score, config) -> str`, `apply_valid_outcome(report, config)`, `attempt_stitch(new_photo, config) -> Report|None`, `sweep_expired_photos(config)`, `resolve_stale_reviewing_reports(config)` — all consumed by Task 9 (upload route wiring) and Task 10 (`my_reports` route).

- [ ] **Step 1: Write the failing test**

Create `tests/test_stitching.py`:

```python
from datetime import datetime, timedelta

from app.models import Dong, Photo, Report, TrustScoreLog, User
from app.reports.stitching import (
    apply_valid_outcome,
    attempt_stitch,
    find_match_candidate,
    resolve_stale_reviewing_reports,
    resolve_status_for_score,
    score_match,
    sweep_expired_photos,
)

TEST_CONFIG = {
    "MATCH_RADIUS_METERS": 50,
    "MATCH_MIN_GAP_SECONDS": 60,
    "MATCH_MAX_GAP_SECONDS": 60 * 60 * 72,
    "AI_VALID_THRESHOLD": 70,
    "AI_REJECT_THRESHOLD": 40,
    "REVIEWING_AUTO_RESOLVE_SECONDS": 60,
    "TRUST_SCORE_VALID_DELTA": 5,
}


def _make_user(db, dong_id, username):
    user = User(
        username=username, nickname=f"{username}-nick", name=username, birthdate="1990-01-01",
        phone="010-0000-0000", dong_id=dong_id,
    )
    user.set_password("x")
    db.session.add(user)
    db.session.commit()
    return user


def _make_photo(db, uploader, dong_id, plate, captured_at, lat=37.5006, lon=127.0364, status="PENDING"):
    photo = Photo(
        uploader_id=uploader.id, plate_number=plate, image_path="uploads/x.jpg", image_hash=f"hash-{captured_at}",
        captured_at=captured_at, gps_source="MANUAL", latitude=lat, longitude=lon, dong_id=dong_id, status=status,
    )
    db.session.add(photo)
    db.session.commit()
    return photo


def test_find_match_candidate_requires_different_uploader(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        user = _make_user(db, dong.id, "alice")

        existing = _make_photo(db, user, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        new_photo = Photo(
            uploader_id=user.id, plate_number="12가3456", image_path="x", image_hash="new-hash",
            captured_at=datetime(2026, 7, 10, 9, 5, 0), gps_source="MANUAL",
            latitude=37.5006, longitude=127.0364, dong_id=dong.id, status="PENDING",
        )

        assert find_match_candidate(new_photo, TEST_CONFIG) is None


def test_find_match_candidate_within_radius_and_time_window(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        existing = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        new_photo = Photo(
            uploader_id=bob.id, plate_number="12가3456", image_path="x", image_hash="new-hash",
            captured_at=datetime(2026, 7, 10, 9, 5, 0), gps_source="MANUAL",
            latitude=37.5007, longitude=127.0365, dong_id=dong.id, status="PENDING",
        )

        candidate = find_match_candidate(new_photo, TEST_CONFIG)
        assert candidate is not None
        assert candidate.id == existing.id


def test_find_match_candidate_rejects_too_far(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0), lat=37.5006, lon=127.0364)
        new_photo = Photo(
            uploader_id=bob.id, plate_number="12가3456", image_path="x", image_hash="new-hash",
            captured_at=datetime(2026, 7, 10, 9, 5, 0), gps_source="MANUAL",
            latitude=37.6000, longitude=127.2000, dong_id=dong.id, status="PENDING",
        )

        assert find_match_candidate(new_photo, TEST_CONFIG) is None


def test_find_match_candidate_still_matches_display_expired_photo(app, db):
    # EXPIRED is a display-only label; matching depends on the relative gap
    # between the two photos, not either one's age relative to wall-clock now.
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        existing = _make_photo(
            db, alice, dong.id, "12가3456", datetime(2020, 1, 1, 9, 0, 0), status="EXPIRED"
        )
        new_photo = Photo(
            uploader_id=bob.id, plate_number="12가3456", image_path="x", image_hash="new-hash",
            captured_at=datetime(2020, 1, 1, 10, 0, 0), gps_source="MANUAL",
            latitude=37.5006, longitude=127.0364, dong_id=dong.id, status="PENDING",
        )

        candidate = find_match_candidate(new_photo, TEST_CONFIG)
        assert candidate is not None
        assert candidate.id == existing.id


def test_score_match_high_score_for_short_gap_no_history(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        older = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        newer = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 10, 9, 5, 0))

        score, reason = score_match(older, newer, TEST_CONFIG, now=datetime(2026, 7, 10, 9, 5, 0))

        assert score == 100
        assert "시간차" in reason


def test_score_match_penalizes_long_gap(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        older = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        newer = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 11, 9, 0, 0))  # 24h gap

        score, _ = score_match(older, newer, TEST_CONFIG, now=datetime(2026, 7, 11, 9, 0, 0))

        assert score < 100


def test_resolve_status_for_score_bands():
    assert resolve_status_for_score(70, TEST_CONFIG) == "VALID"
    assert resolve_status_for_score(100, TEST_CONFIG) == "VALID"
    assert resolve_status_for_score(69, TEST_CONFIG) == "REVIEWING"
    assert resolve_status_for_score(40, TEST_CONFIG) == "REVIEWING"
    assert resolve_status_for_score(39, TEST_CONFIG) == "REJECTED"
    assert resolve_status_for_score(0, TEST_CONFIG) == "REJECTED"


def test_attempt_stitch_creates_valid_report_and_awards_trust_score(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        existing = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        new_photo = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 10, 9, 5, 0), lat=37.5007, lon=127.0365)

        report = attempt_stitch(new_photo, TEST_CONFIG)

        assert report is not None
        assert report.status == "VALID"
        assert existing.status == "MATCHED"
        assert new_photo.status == "MATCHED"

        alice_after = User.query.filter_by(username="alice").first()
        bob_after = User.query.filter_by(username="bob").first()
        assert alice_after.trust_score == 105
        assert bob_after.trust_score == 105
        assert TrustScoreLog.query.count() == 2


def test_attempt_stitch_returns_none_when_no_candidate(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        bob = _make_user(db, dong.id, "bob")

        lonely_photo = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))

        assert attempt_stitch(lonely_photo, TEST_CONFIG) is None


def test_sweep_expired_photos_flags_stale_pending_rows(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")

        old_photo = _make_photo(db, alice, dong.id, "12가3456", datetime(2020, 1, 1, 9, 0, 0))
        recent_photo = _make_photo(db, alice, dong.id, "99나9999", datetime.utcnow())

        sweep_expired_photos(TEST_CONFIG)

        assert Photo.query.get(old_photo.id).status == "EXPIRED"
        assert Photo.query.get(recent_photo.id).status == "PENDING"


def test_resolve_stale_reviewing_reports_auto_rejects_after_delay(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")
        photo_a = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0), status="MATCHED")
        photo_b = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 11, 5, 0, 0), status="MATCHED")

        stale_report = Report(
            plate_number="12가3456", dong_id=dong.id, photo_a_id=photo_a.id, photo_b_id=photo_b.id,
            time_gap_seconds=72000, ai_score=55, ai_reason="test",
            status="REVIEWING", matched_at=datetime.utcnow() - timedelta(seconds=120),
        )
        db.session.add(stale_report)
        db.session.commit()

        resolve_stale_reviewing_reports(TEST_CONFIG)

        assert Report.query.get(stale_report.id).status == "REJECTED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stitching.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reports.stitching'`

- [ ] **Step 3: Write minimal implementation**

Create `app/reports/stitching.py`:

```python
from datetime import datetime, timedelta

from app.extensions import db
from app.geo import haversine_distance_meters
from app.models import Photo, Report, TrustScoreLog


def find_match_candidate(new_photo, config):
    """Find an existing photo that matches new_photo's plate/location/time window.

    Includes status "EXPIRED" alongside "PENDING": EXPIRED is a display-only
    label (see sweep_expired_photos) — matching depends on the relative time
    gap between the two photos, not either one's age relative to wall-clock
    "now", so an EXPIRED-for-display row must still be considered.
    """
    candidates = (
        Photo.query.filter(
            Photo.plate_number == new_photo.plate_number,
            Photo.status.in_(["PENDING", "EXPIRED"]),
            Photo.uploader_id != new_photo.uploader_id,
            Photo.id != new_photo.id,
        )
        .order_by(Photo.created_at.asc())
        .all()
    )

    for candidate in candidates:
        gap = abs((new_photo.captured_at - candidate.captured_at).total_seconds())
        if gap < config["MATCH_MIN_GAP_SECONDS"] or gap > config["MATCH_MAX_GAP_SECONDS"]:
            continue
        distance = haversine_distance_meters(
            new_photo.latitude, new_photo.longitude, candidate.latitude, candidate.longitude
        )
        if distance <= config["MATCH_RADIUS_METERS"]:
            return candidate
    return None


def score_match(older_photo, newer_photo, config, now):
    """Rule-based, explainable "AI" confidence score (0-100) for a matched pair.

    Penalizes long gaps (repeat-visit risk), rewards known repeat offenders,
    and penalizes plates with a history of short unmatched sightings at the
    same spot (a signal of frequent brief stops, e.g. dropping someone off,
    rather than one continuous illegally-parked session).
    """
    gap_seconds = (newer_photo.captured_at - older_photo.captured_at).total_seconds()
    score = 100
    reasons = []

    if gap_seconds <= 6 * 3600:
        time_penalty = 0
    elif gap_seconds <= 24 * 3600:
        time_penalty = 15
    else:
        time_penalty = 35
    score -= time_penalty
    reasons.append(f"시간차 {int(gap_seconds // 60)}분 (-{time_penalty}점)")

    valid_count = Report.query.filter(
        Report.plate_number == older_photo.plate_number, Report.status == "VALID"
    ).count()
    repeat_bonus = min(valid_count * 5, 20)
    score += repeat_bonus
    reasons.append(f"상습 위반 이력 {valid_count}건 (+{repeat_bonus}점)")

    # Bug fix: this must use captured_at directly, not a lazily-updated
    # status column — sweep_expired_photos() only runs when someone views a
    # page, so an unvisited stale PENDING row would otherwise be
    # undercounted here.
    cutoff = now - timedelta(seconds=config["MATCH_MAX_GAP_SECONDS"])
    lonely_visit_count = Photo.query.filter(
        Photo.plate_number == older_photo.plate_number,
        Photo.status.in_(["PENDING", "EXPIRED"]),
        Photo.captured_at < cutoff,
        Photo.id.notin_([older_photo.id, newer_photo.id]),
    ).count()
    repeat_visit_penalty = min(lonely_visit_count * 10, 30)
    score -= repeat_visit_penalty
    reasons.append(f"반복 단시간 방문 이력 {lonely_visit_count}건 (-{repeat_visit_penalty}점)")

    score = max(0, min(100, score))
    return score, "; ".join(reasons)


def resolve_status_for_score(score, config):
    if score >= config["AI_VALID_THRESHOLD"]:
        return "VALID"
    if score < config["AI_REJECT_THRESHOLD"]:
        return "REJECTED"
    return "REVIEWING"


def apply_valid_outcome(report, config):
    for photo in (report.photo_a, report.photo_b):
        user = photo.uploader
        user.trust_score += config["TRUST_SCORE_VALID_DELTA"]
        db.session.add(
            TrustScoreLog(
                user_id=user.id,
                report_id=report.id,
                delta=config["TRUST_SCORE_VALID_DELTA"],
                reason="유효 신고 매칭 성공",
            )
        )
    report.status = "VALID"
    report.resolved_at = datetime.utcnow()


def attempt_stitch(new_photo, config):
    """Try to find a match for new_photo. If found, create a Report, mark
    both photos MATCHED, score it, and resolve VALID/REJECTED immediately or
    leave it REVIEWING for later lazy resolution. Returns the Report, or
    None if no match was found.
    """
    candidate = find_match_candidate(new_photo, config)
    if candidate is None:
        return None

    older, newer = sorted([candidate, new_photo], key=lambda p: p.captured_at)
    gap_seconds = int((newer.captured_at - older.captured_at).total_seconds())

    now = datetime.utcnow()
    score, reason = score_match(older, newer, config, now)

    report = Report(
        plate_number=new_photo.plate_number,
        dong_id=older.dong_id,
        photo_a_id=older.id,
        photo_b_id=newer.id,
        time_gap_seconds=gap_seconds,
        ai_score=score,
        ai_reason=reason,
        status="REVIEWING",
        matched_at=now,
    )
    db.session.add(report)
    older.status = "MATCHED"
    newer.status = "MATCHED"
    db.session.flush()

    outcome = resolve_status_for_score(score, config)
    if outcome == "VALID":
        apply_valid_outcome(report, config)
    elif outcome == "REJECTED":
        report.status = "REJECTED"
        report.resolved_at = now

    db.session.commit()
    return report


def sweep_expired_photos(config):
    """Lazily flip stale PENDING photos to EXPIRED for display purposes only.
    Never relied upon by score_match() — see the note there.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=config["MATCH_MAX_GAP_SECONDS"])
    Photo.query.filter(Photo.status == "PENDING", Photo.captured_at < cutoff).update(
        {"status": "EXPIRED"}, synchronize_session=False
    )
    db.session.commit()


def resolve_stale_reviewing_reports(config):
    cutoff = datetime.utcnow() - timedelta(seconds=config["REVIEWING_AUTO_RESOLVE_SECONDS"])
    stale = Report.query.filter(Report.status == "REVIEWING", Report.matched_at < cutoff).all()
    for report in stale:
        report.status = "REJECTED"
        report.resolved_at = datetime.utcnow()
    if stale:
        db.session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stitching.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/reports/stitching.py tests/test_stitching.py
git commit -m "feat: add Data Stitching matching engine and rule-based AI review scoring"
```

---

### Task 9: Wire stitching into the upload route

**Files:**
- Modify: `app/reports/routes.py:upload` (call `attempt_stitch` after saving a non-duplicate `Photo`)
- Test: `tests/test_upload.py` (append)

**Interfaces:**
- Consumes: `attempt_stitch` from `app.reports.stitching` (Task 8).
- Produces: on successful match, the upload response flashes "매칭되어 신고가 접수되었습니다" instead of the generic "업로드되었습니다" message — this exact substring is relied on by Task 14's end-to-end test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_upload.py`:

```python
from app.models import Report


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload.py -v`
Expected: FAIL — the new test fails because the current route never calls `attempt_stitch`, so no `Report` row is created and the flash message is the generic upload-success one.

- [ ] **Step 3: Write minimal implementation**

Modify `app/reports/routes.py`: add the import and call `attempt_stitch` right after `db.session.commit()` for the non-duplicate branch.

```python
from app.reports.stitching import attempt_stitch
```

Replace the tail of the `upload()` view (the non-duplicate branch, after the existing `db.session.commit()`) with:

```python
        db.session.commit()

        report = attempt_stitch(photo, current_app.config)
        if report is not None:
            flash("다른 시민의 사진과 매칭되어 신고가 접수되었습니다!", "success")
        else:
            flash("사진이 업로드되었습니다. 같은 차량의 다른 사진이 올라오면 자동으로 매칭됩니다.", "success")
        return redirect(url_for("reports.my_reports"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/reports/routes.py tests/test_upload.py
git commit -m "feat: wire Data Stitching engine into the upload route"
```

---

### Task 10: My-reports route & template

**Files:**
- Modify: `app/reports/routes.py:my_reports` (replace placeholder)
- Create: `app/templates/reports/my_reports.html`
- Test: `tests/test_upload.py` (append) — covers `/my-reports` grouping since it's part of the `reports` blueprint's behavior.

**Interfaces:**
- Consumes: `sweep_expired_photos`, `resolve_stale_reviewing_reports` (Task 8).
- Produces: `GET /my-reports` rendering four groups: 매칭 대기중 (`Photo.status == "PENDING"`), AI 검토중 (`Report.status == "REVIEWING"`), 접수완료-유효 (`Report.status == "VALID"`), 반려·만료 (`Report.status in ("REJECTED",)` + `Photo.status in ("EXPIRED", "FALSE")`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_upload.py`:

```python
def test_my_reports_groups_pending_and_valid_correctly(app, db, client):
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

    response = client.get("/my-reports")
    assert response.status_code == 200
    assert "매칭 대기중".encode("utf-8") in response.data
    assert "12가3456".encode("utf-8") in response.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload.py -v`
Expected: FAIL — `/my-reports` still returns the literal string `"placeholder"`.

- [ ] **Step 3: Write minimal implementation**

Replace the `my_reports` view in `app/reports/routes.py`:

```python
from app.models import Report
from app.reports.stitching import resolve_stale_reviewing_reports, sweep_expired_photos


@reports_bp.route("/my-reports")
@login_required
def my_reports():
    sweep_expired_photos(current_app.config)
    resolve_stale_reviewing_reports(current_app.config)

    pending_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="PENDING")
        .order_by(Photo.created_at.desc())
        .all()
    )
    expired_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="EXPIRED")
        .order_by(Photo.created_at.desc())
        .all()
    )
    false_photos = (
        Photo.query.filter_by(uploader_id=current_user.id, status="FALSE")
        .order_by(Photo.created_at.desc())
        .all()
    )

    my_photo_ids = [p.id for p in current_user.photos]
    my_reports_all = (
        Report.query.filter(
            db.or_(Report.photo_a_id.in_(my_photo_ids), Report.photo_b_id.in_(my_photo_ids))
        )
        .order_by(Report.matched_at.desc())
        .all()
    )
    reviewing = [r for r in my_reports_all if r.status == "REVIEWING"]
    valid = [r for r in my_reports_all if r.status == "VALID"]
    rejected = [r for r in my_reports_all if r.status == "REJECTED"]

    return render_template(
        "reports/my_reports.html",
        pending_photos=pending_photos,
        reviewing=reviewing,
        valid=valid,
        rejected=rejected,
        expired_photos=expired_photos,
        false_photos=false_photos,
    )
```

Create `app/templates/reports/my_reports.html`:

```html
{% extends "base.html" %}
{% block title %}내 신고 현황 - 클린파킹{% endblock %}
{% block content %}
<h1>내 신고 현황</h1>

<section>
  <h2>매칭 대기중 ({{ pending_photos|length }})</h2>
  <ul>
    {% for photo in pending_photos %}
    <li>번호판 {{ photo.plate_number }} · 촬영 {{ photo.captured_at }}</li>
    {% else %}
    <li class="empty">매칭 대기 중인 사진이 없습니다.</li>
    {% endfor %}
  </ul>
</section>

<section>
  <h2>AI 검토중 ({{ reviewing|length }})</h2>
  <ul>
    {% for report in reviewing %}
    <li>번호판 {{ report.plate_number }} · AI 점수 {{ report.ai_score }}점 · {{ report.ai_reason }}</li>
    {% else %}
    <li class="empty">검토 중인 신고가 없습니다.</li>
    {% endfor %}
  </ul>
</section>

<section>
  <h2>접수완료 - 유효 ({{ valid|length }})</h2>
  <ul>
    {% for report in valid %}
    <li>번호판 {{ report.plate_number }} · {{ report.dong.name }} · AI 점수 {{ report.ai_score }}점</li>
    {% else %}
    <li class="empty">아직 유효 처리된 신고가 없습니다.</li>
    {% endfor %}
  </ul>
</section>

<section>
  <h2>반려 · 만료</h2>
  <ul>
    {% for report in rejected %}
    <li>번호판 {{ report.plate_number }} · 반려 (AI 점수 {{ report.ai_score }}점, 무감점)</li>
    {% endfor %}
    {% for photo in expired_photos %}
    <li>번호판 {{ photo.plate_number }} · 매칭 상대를 찾지 못해 만료됨</li>
    {% endfor %}
    {% for photo in false_photos %}
    <li>번호판 {{ photo.plate_number }} · 허위(중복 이미지 재사용, -30점)</li>
    {% endfor %}
    {% if not rejected and not expired_photos and not false_photos %}
    <li class="empty">반려되거나 만료된 신고가 없습니다.</li>
    {% endif %}
  </ul>
</section>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/reports/routes.py app/templates/reports/my_reports.html tests/test_upload.py
git commit -m "feat: add my-reports page grouped by pending/reviewing/valid/rejected"
```

---

### Task 11: Dashboard route & template (clean index, ranking, trust score)

**Files:**
- Modify: `app/dashboard/routes.py` (replace placeholder)
- Create: `app/templates/dashboard/index.html`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `Dong`, `Report`, `User` (Task 2).
- Produces: `compute_dong_temperature(valid_count) -> float` and `GET /dashboard` rendering per-dong temperature, anonymous ranking (nickname + dong, valid-report count, top 10), and the current user's trust score.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard.py`:

```python
from datetime import datetime

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

        photo_a = Photo(
            uploader_id=alice.id, plate_number="12가3456", image_path="x", image_hash="h1",
            captured_at=datetime(2026, 7, 10, 9, 0, 0), gps_source="MANUAL",
            latitude=37.5006, longitude=127.0364, dong_id=dong.id, status="MATCHED",
        )
        photo_b = Photo(
            uploader_id=bob.id, plate_number="12가3456", image_path="x", image_hash="h2",
            captured_at=datetime(2026, 7, 10, 9, 5, 0), gps_source="MANUAL",
            latitude=37.5007, longitude=127.0365, dong_id=dong.id, status="MATCHED",
        )
        db.session.add_all([photo_a, photo_b])
        db.session.commit()

        report = Report(
            plate_number="12가3456", dong_id=dong.id, photo_a_id=photo_a.id, photo_b_id=photo_b.id,
            time_gap_seconds=300, ai_score=100, ai_reason="test", status="VALID",
            matched_at=datetime(2026, 7, 10, 9, 5, 0),
        )
        db.session.add(report)
        db.session.commit()

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "역삼1동".encode("utf-8") in response.data
    assert "alice-nick".encode("utf-8") in response.data
    assert "bob-nick".encode("utf-8") in response.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — `compute_dong_temperature` doesn't exist and `/dashboard` returns the literal string `"placeholder"`.

- [ ] **Step 3: Write minimal implementation**

Replace `app/dashboard/routes.py`:

```python
from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Dong, Report, User

dashboard_bp = Blueprint("dashboard", __name__)


def compute_dong_temperature(valid_count):
    return round(min(36.5 + valid_count * 0.3, 99.9), 1)


@dashboard_bp.route("/dashboard")
@login_required
def index():
    dongs = Dong.query.order_by(Dong.name).all()
    dong_stats = []
    for dong in dongs:
        valid_count = Report.query.filter_by(dong_id=dong.id, status="VALID").count()
        dong_stats.append(
            {
                "name": dong.name,
                "valid_count": valid_count,
                "temperature": compute_dong_temperature(valid_count),
                "is_mine": dong.id == current_user.dong_id,
            }
        )

    ranking = []
    for user in User.query.order_by(User.trust_score.desc()).all():
        my_photo_ids = [p.id for p in user.photos]
        if not my_photo_ids:
            continue
        valid_count = Report.query.filter(
            Report.status == "VALID",
            db.or_(Report.photo_a_id.in_(my_photo_ids), Report.photo_b_id.in_(my_photo_ids)),
        ).count()
        if valid_count > 0:
            ranking.append({"nickname": user.nickname, "dong_name": user.dong.name, "valid_count": valid_count})
    ranking.sort(key=lambda r: r["valid_count"], reverse=True)
    ranking = ranking[:10]

    return render_template(
        "dashboard/index.html",
        dong_stats=dong_stats,
        ranking=ranking,
        trust_score=current_user.trust_score,
    )
```

Create `app/templates/dashboard/index.html`:

```html
{% extends "base.html" %}
{% block title %}대시보드 - 클린파킹{% endblock %}
{% block content %}
<h1>대시보드</h1>

<section>
  <h2>내 신뢰도 점수: {{ trust_score }}점</h2>
</section>

<section>
  <h2>동네 청정 지수</h2>
  <ul>
    {% for dong in dong_stats %}
    <li{% if dong.is_mine %} class="mine"{% endif %}>
      {{ dong.name }}{% if dong.is_mine %} (내 동네){% endif %} — {{ dong.temperature }}℃
      (유효 신고 {{ dong.valid_count }}건)
    </li>
    {% endfor %}
  </ul>
</section>

<section>
  <h2>익명 랭킹 (유효 신고 건수 기준)</h2>
  <ol>
    {% for entry in ranking %}
    <li>{{ entry.nickname }} ({{ entry.dong_name }}) — {{ entry.valid_count }}건</li>
    {% else %}
    <li class="empty">아직 랭킹에 오른 사용자가 없습니다.</li>
    {% endfor %}
  </ol>
</section>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/routes.py app/templates/dashboard/index.html tests/test_dashboard.py
git commit -m "feat: add dashboard with clean-index temperature and anonymous ranking"
```

---

### Task 12: Demo seed script

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/seed_data.py`
- Test: `tests/test_seed_data.py`

**Interfaces:**
- Consumes: `create_app`, all models (Task 2), `app.extensions.db`.
- Produces: `run(app=None)` — rebuilds the DB from scratch and populates it; importable and callable from tests with a pre-built test `app` fixture. Guarantees a `Photo` with `plate_number == DEMO_PLATE`, `status == "PENDING"`, owned by a non-demo user.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed_data.py`:

```python
from app.models import Dong, Photo, Report, User


def test_seed_creates_demo_account_and_matchable_pending_photo(app):
    from scripts.seed_data import DEMO_PLATE, run

    run(app)

    with app.app_context():
        demo = User.query.filter_by(is_demo=True).first()
        assert demo is not None
        assert demo.username == "demo"

        waiting_photo = Photo.query.filter_by(plate_number=DEMO_PLATE, status="PENDING").first()
        assert waiting_photo is not None
        assert waiting_photo.uploader_id != demo.id

        assert Dong.query.count() >= 5
        assert User.query.count() >= 5
        assert Report.query.filter_by(status="VALID").count() >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.seed_data'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/__init__.py` (empty file).

Create `scripts/seed_data.py`:

```python
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
DEMO_PLATE = "12가3456"
DEMO_LAT = 37.5006
DEMO_LON = 127.0364


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
        # plate/location — this is the live "killer demo" moment.
        waiting_path, waiting_hash = _make_seed_image(app, "demo_waiting.jpg", (200, 60, 60))
        waiting_photo = Photo(
            uploader_id=other_users[0].id, plate_number=DEMO_PLATE, image_path=waiting_path,
            image_hash=waiting_hash, captured_at=now - timedelta(minutes=10), gps_source="MANUAL",
            latitude=DEMO_LAT, longitude=DEMO_LON, dong_id=other_users[0].dong_id, status="PENDING",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed_data.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/seed_data.py tests/test_seed_data.py
git commit -m "feat: add demo seed script with matchable pending photo and historical reports"
```

---

### Task 13: Deployment files

**Files:**
- Create: `DEPLOY.md`
- Create: `README.md`
- Modify: `requirements.txt` (already correct from Task 1 — verify, no changes expected)

**Interfaces:**
- No code interfaces — this task produces operator-facing documentation. Verification is manual (Step 4 below), not `pytest`.

- [ ] **Step 1: Write the content**

Create `DEPLOY.md`:

```markdown
# PythonAnywhere 배포 가이드

## 1. 최초 설정

1. PythonAnywhere 대시보드 > Consoles > Bash 콘솔에서 저장소를 클론합니다.

   ```bash
   git clone <repo-url> parking-report
   cd parking-report
   ```

2. 가상환경을 만들고 의존성을 설치합니다.

   ```bash
   mkvirtualenv --python=/usr/bin/python3.10 parking-report-venv
   pip install -r requirements.txt
   ```

3. DB와 데모 데이터를 생성합니다.

   ```bash
   python scripts/seed_data.py
   ```

## 2. Web 앱 설정 (Web 탭)

1. "Add a new web app" > Manual configuration > Python 3.10 선택
2. Virtualenv 경로: `/home/<username>/.virtualenvs/parking-report-venv`
3. WSGI 설정 파일을 열어 아래 내용으로 교체합니다.

   ```python
   import sys
   path = "/home/<username>/parking-report"
   if path not in sys.path:
       sys.path.insert(0, path)

   from wsgi import app as application
   ```

4. Static files 매핑 추가: URL `/static/` → Directory `/home/<username>/parking-report/app/static/`
5. Reload 버튼을 눌러 앱을 시작합니다.

## 3. 디스크 쿼터 주의 (무료 플랜 512MB)

- `requirements.txt`에 새 패키지를 추가하기 전에 꼭 필요한지 재검토하세요. 가상환경만으로 300MB 이상을 차지할 수 있습니다.
- 시드 이미지는 스크립트가 매번 640x480 소형 JPEG로 새로 생성하므로 저장소에 커밋하지 않습니다.
- 실사용자 업로드 이미지는 저장 전 1280px로 리사이즈되도록 구현되어 있습니다(`app/reports/image_utils.py`). 이 로직을 임의로 비활성화하지 마세요.
- 디스크 사용량은 Consoles > Bash에서 `du -sh ~` 로 주기적으로 확인하세요.

## 4. 심사 기간 갱신 체크리스트 (매우 중요)

PythonAnywhere 무료 플랜은 2026-01-15 이후 생성된 계정 기준으로 **웹 앱이 마지막 Reload로부터 약 1개월 후 자동 만료**됩니다. 공모전 제출은 링크 하나로 승부하는 경우가 많으므로, 심사 도중 링크가 죽는 것이 가장 큰 리스크입니다.

- [ ] 제출 직전: Web 탭에서 앱을 한 번 Reload하여 만료 시점을 뒤로 미룹니다.
- [ ] 심사 기간 동안 최소 2주 간격으로 PythonAnywhere에 로그인해 Web 탭에서 Reload하거나 앱에 직접 접속합니다.
- [ ] 심사 결과 발표 후에도 추가 문의가 예상되면 만료 전 다시 Reload합니다.
```

Create `README.md`:

```markdown
# 클린파킹 (공모전 데모)

AI 기반 크라우드소싱 불법 주정차 자동 신고 플랫폼 데모. 서로 다른 두 시민이 각자 찍은 사진을 서버가 자동으로 병합(Data Stitching)해 신고를 완성합니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/seed_data.py
python wsgi.py
```

브라우저에서 http://127.0.0.1:5000 접속 후 "데모 계정으로 둘러보기"를 눌러보세요.

## 테스트

```bash
pytest
```

## 배포

PythonAnywhere 무료 플랜 배포 절차는 `DEPLOY.md`를 참고하세요.

설계 문서: `docs/superpowers/specs/2026-07-13-parking-report-design.md`
```

- [ ] **Step 2: Verify requirements.txt matches Task 1 exactly**

Run: `cat requirements.txt`
Expected:
```
Flask==3.0.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-WTF==1.2.1
Pillow==10.4.0
pytest==8.3.2
```
If it differs, revert to this exact list — no new dependencies were introduced by Tasks 2-12.

- [ ] **Step 3: Manual verification**

Run: `python scripts/seed_data.py && python wsgi.py`
Expected: server starts on `http://127.0.0.1:5000`; open it in a browser and confirm the landing page loads with the "데모 계정으로 둘러보기" button.

- [ ] **Step 4: Commit**

```bash
git add DEPLOY.md README.md
git commit -m "docs: add PythonAnywhere deployment guide with expiry renewal checklist"
```

---

### Task 14: End-to-end smoke test

**Files:**
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: every route and helper from Tasks 5-11. No new production code — this task only adds a test that exercises the full user-facing flow through the Flask test client, as a final regression guard.

- [ ] **Step 1: Write the test**

Create `tests/test_end_to_end.py`:

```python
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
    _signup(client, "bob", "밥", dong_id)
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_end_to_end.py -v`
Expected: 1 passed (all preceding tasks' code already makes this pass — this step is a regression guard, not new TDD red/green).

- [ ] **Step 3: Run the full suite**

Run: `pytest -v`
Expected: all tests across every file pass with no failures.

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: add end-to-end smoke test covering signup through dashboard ranking"
```

---

## Self-Review Notes

**Spec coverage:**
- §1 core idea (Data Stitching from two citizens' photos) → Tasks 8, 9.
- §2 tech stack/constraints (no external API/GPU, disk quota) → Tasks 1, 6, 13.
- §3 folder structure → File Structure section + Task 1.
- §4 DB schema → Task 2.
- §5 matching engine (incl. EXPIRED-as-display-only fix) → Task 8.
- §6 AI review engine (incl. captured_at-based scoring fix) → Task 8.
- §7 FALSE detection (incl. Photo.status=FALSE clarification) → Task 7.
- §8 trust score / daily limits → Task 7 (limits), Task 8 (score deltas).
- §9 pages (landing, signup w/ fake verification, upload w/ demo banner, my-reports 4 groups, dashboard) → Tasks 5, 7, 10, 11.
- §10 deployment/seed (incl. expiry checklist, matchable seed photo) → Tasks 12, 13.
- §11 (deferred decisions: 3rd-photo handling, trust score cap, daily-limit day boundary) → intentionally not implemented; current code has no upper cap on trust_score and uses UTC-midnight as the daily boundary (see `check_daily_upload_limit`), which is an acceptable default per the spec's own note that these can be decided pragmatically during implementation.
- §12 test scope (Haversine, matching, AI bands, duplicate-hash FALSE, trust score/limits) → Tasks 3, 7, 8.

**Placeholder scan:** No TBD/TODO markers. Task 1 intentionally creates literal `"placeholder"` route handlers for `/upload`, `/my-reports`, `/dashboard` as a deliberate bridge so the app factory (which imports all blueprints) works before those blueprints are fully implemented in later tasks — each is explicitly replaced by name in a later task's Step 3, not left as a loose end.

**Type consistency:** `config` parameter in `app/reports/stitching.py` functions is used identically as a dict-like (`config["KEY"]`) whether called with `current_app.config` (routes) or a plain `dict` (tests) — verified consistent across Tasks 7-9, 11. `Photo.status` values (`PENDING`/`MATCHED`/`EXPIRED`/`FALSE`) and `Report.status` values (`REVIEWING`/`VALID`/`REJECTED`/`FALSE`) are used with the same string literals across Tasks 2, 7, 8, 10, 11, 12.
