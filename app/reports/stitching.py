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
