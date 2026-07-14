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


def test_score_match_penalizes_repeat_lonely_visits(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        older = _make_photo(db, alice, dong.id, "12가3456", datetime(2026, 7, 10, 9, 0, 0))
        newer = _make_photo(db, bob, dong.id, "12가3456", datetime(2026, 7, 10, 9, 5, 0))

        # Two prior "lonely" sightings of the same plate: never matched, long
        # since expired relative to the cutoff, and excluded from the pair
        # above by id. These should trigger the repeat-visit penalty.
        _make_photo(db, alice, dong.id, "12가3456", datetime(2020, 1, 1, 9, 0, 0), status="PENDING")
        _make_photo(db, alice, dong.id, "12가3456", datetime(2020, 1, 1, 10, 0, 0), status="EXPIRED")

        score, reason = score_match(older, newer, TEST_CONFIG, now=datetime(2026, 7, 10, 9, 5, 0))

        # time_penalty = 0 (5min gap <= 6h); repeat_bonus = 0 (no VALID reports);
        # repeat_visit_penalty = min(2 * 10, 30) = 20 -> score = 100 - 20 = 80
        assert score == 80
        assert "반복 단시간 방문 이력 2건" in reason


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


def test_attempt_stitch_rejects_low_score_match(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        # 30h gap between the matched pair -> time_penalty = 35 (> 24h)
        existing = _make_photo(db, alice, dong.id, "34나5678", datetime(2026, 7, 10, 9, 0, 0))
        new_photo = _make_photo(
            db, bob, dong.id, "34나5678", datetime(2026, 7, 11, 15, 0, 0), lat=37.5007, lon=127.0365
        )

        # 3 old lonely sightings of the same plate -> repeat_visit_penalty = min(3 * 10, 30) = 30.
        # Far enough in the past (2020) that they can never satisfy find_match_candidate's
        # gap window against the 2026 pair above, so they can't be picked as the match itself.
        _make_photo(db, alice, dong.id, "34나5678", datetime(2020, 1, 1, 9, 0, 0), status="PENDING")
        _make_photo(db, alice, dong.id, "34나5678", datetime(2020, 1, 1, 10, 0, 0), status="PENDING")
        _make_photo(db, alice, dong.id, "34나5678", datetime(2020, 1, 1, 11, 0, 0), status="EXPIRED")

        # Expected score = 100 - 35 (time) + 0 (no VALID history) - 30 (repeat visits) = 35 < 40 -> REJECTED
        report = attempt_stitch(new_photo, TEST_CONFIG)

        assert report is not None
        assert report.ai_score == 35
        assert report.status == "REJECTED"
        assert report.resolved_at is not None

        alice_after = User.query.filter_by(username="alice").first()
        bob_after = User.query.filter_by(username="bob").first()
        assert alice_after.trust_score == 100
        assert bob_after.trust_score == 100
        assert TrustScoreLog.query.count() == 0


def test_attempt_stitch_leaves_mid_score_match_reviewing(app, db):
    with app.app_context():
        dong = Dong(name="역삼1동")
        db.session.add(dong)
        db.session.commit()
        alice = _make_user(db, dong.id, "alice")
        bob = _make_user(db, dong.id, "bob")

        # 10h gap between the matched pair -> time_penalty = 15 (> 6h, <= 24h)
        existing = _make_photo(db, alice, dong.id, "56다7890", datetime(2026, 7, 10, 9, 0, 0))
        new_photo = _make_photo(
            db, bob, dong.id, "56다7890", datetime(2026, 7, 10, 19, 0, 0), lat=37.5007, lon=127.0365
        )

        # 2 old lonely sightings of the same plate -> repeat_visit_penalty = min(2 * 10, 30) = 20
        _make_photo(db, alice, dong.id, "56다7890", datetime(2020, 1, 1, 9, 0, 0), status="PENDING")
        _make_photo(db, alice, dong.id, "56다7890", datetime(2020, 1, 1, 10, 0, 0), status="EXPIRED")

        # Expected score = 100 - 15 (time) + 0 (no VALID history) - 20 (repeat visits) = 65
        # -> REVIEWING (40 <= 65 < 70)
        report = attempt_stitch(new_photo, TEST_CONFIG)

        assert report is not None
        assert report.ai_score == 65
        assert report.status == "REVIEWING"
        assert report.resolved_at is None

        alice_after = User.query.filter_by(username="alice").first()
        bob_after = User.query.filter_by(username="bob").first()
        assert alice_after.trust_score == 100
        assert bob_after.trust_score == 100
        assert TrustScoreLog.query.count() == 0


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
