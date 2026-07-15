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

    # Demo plate/coords shared by scripts/seed_data.py (the seeded "waiting"
    # photo) and app/reports/routes.py's ensure_demo_hint() (the self-healing
    # fallback that recreates that same waiting photo once it's been
    # consumed). Single source of truth so the two never drift apart.
    DEMO_PLATE = "12가3456"
    DEMO_LAT = 37.5006
    DEMO_LON = 127.0364
