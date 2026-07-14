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
    exif.update({EXIF_OFFSET_TAG: sub_ifd})

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
