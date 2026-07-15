from datetime import datetime

from app.extensions import db
from app.models import Dong, Photo, Report, User
from app.reports.stitching import attempt_stitch, find_match_candidate


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


def test_seed_waiting_photo_actually_matches_a_fresh_demo_upload(app):
    """Guards the "killer demo" moment: a demo-account upload of DEMO_PLATE at
    DEMO_LAT/DEMO_LON, taken right now, must really pass the live matching
    engine (app/reports/stitching.py) against the seeded waiting photo -- not
    just satisfy the precursor checks above. A future change to DEMO_LAT/LON,
    the waiting photo's captured_at offset, or the MATCH_* thresholds in
    app/config.py would silently break the live demo without this test
    catching it.
    """
    from scripts.seed_data import DEMO_LAT, DEMO_LON, DEMO_PLATE, run

    run(app)

    with app.app_context():
        demo = User.query.filter_by(is_demo=True).first()
        waiting_photo = Photo.query.filter_by(plate_number=DEMO_PLATE, status="PENDING").first()
        assert waiting_photo is not None

        # Simulate exactly what a fresh demo-account upload would look like
        # right now: same plate/coordinates, captured "now".
        new_photo = Photo(
            uploader_id=demo.id, plate_number=DEMO_PLATE, image_path="uploads/demo_fresh.jpg",
            image_hash="fresh-demo-upload-hash", captured_at=datetime.utcnow(), gps_source="MANUAL",
            latitude=DEMO_LAT, longitude=DEMO_LON, dong_id=demo.dong_id, status="PENDING",
        )

        candidate = find_match_candidate(new_photo, app.config)
        assert candidate is not None
        assert candidate.id == waiting_photo.id

        # Commit the synthetic photo so it has a real id, then run the full
        # end-to-end stitch exactly as app/reports/routes.py does on upload.
        db.session.add(new_photo)
        db.session.flush()

        report = attempt_stitch(new_photo, app.config)

        assert report is not None
        assert {report.photo_a_id, report.photo_b_id} == {waiting_photo.id, new_photo.id}
        assert Photo.query.get(waiting_photo.id).status == "MATCHED"
        assert Photo.query.get(new_photo.id).status == "MATCHED"
