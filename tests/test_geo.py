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
