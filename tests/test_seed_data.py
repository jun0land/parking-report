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
