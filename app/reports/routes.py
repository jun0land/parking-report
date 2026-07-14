from flask import Blueprint

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/upload")
def upload():
    return "placeholder"


@reports_bp.route("/my-reports")
def my_reports():
    return "placeholder"
