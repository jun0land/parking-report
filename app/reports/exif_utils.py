from datetime import datetime

from PIL import ExifTags, Image

GPS_IFD_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "GPSInfo")
EXIF_IFD_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "ExifOffset")
DATETIME_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "DateTime")
DATETIME_ORIGINAL_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal")

# Standard EXIF GPS sub-IFD tag numbers (fixed by the EXIF spec, not looked up
# via ExifTags.TAGS which only covers the main IFD).
GPS_LATITUDE_REF = 1
GPS_LATITUDE = 2
GPS_LONGITUDE_REF = 3
GPS_LONGITUDE = 4


def _dms_to_decimal(dms, ref):
    degrees, minutes, seconds = dms
    decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_gps_and_time(image_file):
    """Extract capture time and GPS coordinates from an image's EXIF data.

    Returns a dict with keys "captured_at", "latitude", "longitude". Any
    value that can't be determined from EXIF is None — callers must fall
    back to manual user input in that case (the common case for photos that
    passed through phone camera apps or browser uploads, which often strip
    GPS EXIF).

    DateTimeOriginal (the tag real cameras actually populate) lives in the
    Exif sub-IFD (pointer tag "ExifOffset" / 0x8769), not the flat top-level
    IFD0 that Image.getexif() returns directly — it must be fetched via
    get_ifd(EXIF_IFD_TAG). The plain "DateTime" tag (306) is checked as a
    fallback for images that only set that flatter, less-specific tag.
    """
    result = {"captured_at": None, "latitude": None, "longitude": None}

    try:
        image = Image.open(image_file)
        exif = image.getexif()
    except Exception:
        return result

    if not exif:
        return result

    datetime_str = None
    if hasattr(exif, "get_ifd"):
        exif_sub_ifd = exif.get_ifd(EXIF_IFD_TAG)
        if exif_sub_ifd:
            datetime_str = exif_sub_ifd.get(DATETIME_ORIGINAL_TAG)
    if not datetime_str:
        datetime_str = exif.get(DATETIME_TAG)

    if datetime_str:
        try:
            result["captured_at"] = datetime.strptime(datetime_str, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass

    gps_info = exif.get_ifd(GPS_IFD_TAG) if hasattr(exif, "get_ifd") else None
    if gps_info:
        try:
            result["latitude"] = _dms_to_decimal(gps_info[GPS_LATITUDE], gps_info[GPS_LATITUDE_REF])
            result["longitude"] = _dms_to_decimal(gps_info[GPS_LONGITUDE], gps_info[GPS_LONGITUDE_REF])
        except (KeyError, TypeError, ZeroDivisionError):
            result["latitude"] = None
            result["longitude"] = None

    return result
