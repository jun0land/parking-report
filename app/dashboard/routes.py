from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import Dong, Photo, Report, User

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

    # Credit BOTH contributing uploaders of every VALID report. Built as a
    # direct aggregate query (rather than iterating User.photos) so it
    # reflects the current DB state exactly — going through the ORM
    # relationship collection on already-identity-mapped User objects can
    # return a stale cached collection within a long-lived session.
    credit_a = db.session.query(Photo.uploader_id.label("uploader_id")).join(
        Report, Report.photo_a_id == Photo.id
    ).filter(Report.status == "VALID")
    credit_b = db.session.query(Photo.uploader_id.label("uploader_id")).join(
        Report, Report.photo_b_id == Photo.id
    ).filter(Report.status == "VALID")
    credits = credit_a.union_all(credit_b).subquery()

    counts = (
        db.session.query(credits.c.uploader_id, func.count().label("valid_count"))
        .group_by(credits.c.uploader_id)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )

    ranking = []
    for uploader_id, valid_count in counts:
        user = db.session.get(User, uploader_id)
        ranking.append({"nickname": user.nickname, "dong_name": user.dong.name, "valid_count": valid_count})

    return render_template(
        "dashboard/index.html",
        dong_stats=dong_stats,
        ranking=ranking,
        trust_score=current_user.trust_score,
    )
