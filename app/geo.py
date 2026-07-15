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
