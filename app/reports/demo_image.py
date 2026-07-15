"""Generate the "샘플 사진" demo image judges download from the upload page.

Ported from the local reference generator in demo-assets/make_demo_image.py
(untracked, not part of the app) into a real module so it can be served
on demand via app.reports.routes.demo_sample.

IMPORTANT: this must produce different bytes on every call. upload() computes
a sha256 of the uploaded file and flags any *re-used* hash as a fraud
("FALSE") report with a -30 trust penalty. If judges downloaded one static
sample image, the second judge -- or the same judge uploading it twice --
would trip that fraud detector and break the demo.

An earlier version relied on ~10 near-invisible noise pixels for uniqueness.
That does NOT survive re-encoding: JPEG quantization at quality 85 is lossy
enough to erase +/-3-unit pixel jitter almost entirely, so in practice only
_CAR_COLORS.length distinct sha256s existed across many calls (empirically:
8 distinct hashes across 200 calls). Two entropy sources are used instead,
both verified to survive quality-85 JPEG re-encoding because they don't rely
on surviving lossy quantization at all:

1. A random 8-hex-char code (`uuid.uuid4().hex[:8].upper()`) is rendered as
   *visible text* in the caption strip. Rendered glyphs at caption size are
   large, high-contrast blocks of pixels -- utterly unlike single jittered
   pixels -- so they survive quantization trivially. This is the primary
   guarantee, and is a visible feature (judges can see each download really
   is unique) rather than a hidden hack.
2. Belt-and-suspenders: the same code is also written into the JPEG's COM
   (comment) marker via Pillow's `comment=` kwarg on save(). This is a raw
   metadata block copied byte-for-byte into the file, untouched by pixel
   quantization, so it changes the output hash even if the visible-text
   render were somehow defeated. Verified empirically against the pinned
   Pillow 10.4.0: two saves of the *same* pixel image with different
   `comment=` values produce different bytes and different sha256s.

The random car color is kept too (nice visual variety across downloads) but
is no longer relied on for uniqueness.
"""

import io
import random
import uuid

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 800, 600
BACKGROUND = (220, 220, 215)  # light gray sidewalk/background color

# Tasteful, solid car-body colors. Which one gets picked doesn't matter --
# what matters is that it varies call to call (see module docstring).
_CAR_COLORS = [
    (70, 150, 140),  # teal
    (180, 70, 70),  # brick red
    (60, 90, 160),  # blue
    (200, 150, 40),  # mustard
    (90, 90, 90),  # graphite
    (120, 70, 150),  # purple
    (60, 140, 90),  # green
    (150, 150, 150),  # silver
]

# Font fallback chain: Windows dev box first (Malgun Gothic ships with
# Windows), then the common NanumGothic locations on Debian/Ubuntu-based
# PythonAnywhere images. If none of these load, _load_font returns None and
# the caller must switch to ASCII-only text -- Pillow's built-in bitmap font
# has no Hangul glyphs and would otherwise render empty "tofu" boxes.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


def _load_font(size):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def generate_sample_image() -> bytes:
    """Return fresh JPEG bytes for a flat-illustration "illegally parked car".

    800x600, quality 85. Every call yields different bytes (see module
    docstring) so the demo's duplicate-image fraud detector never fires on
    a legitimately re-downloaded sample.
    """
    unique_code = uuid.uuid4().hex[:8].upper()

    img = Image.new("RGB", (WIDTH, HEIGHT), color=BACKGROUND)
    draw = ImageDraw.Draw(img)

    # --- Road and curb ---
    draw.rectangle([0, 200, WIDTH, HEIGHT], fill=(140, 140, 140))  # asphalt
    draw.rectangle([0, 0, WIDTH, 200], fill=BACKGROUND)  # sidewalk

    # Red/yellow no-parking curb stripes along the road edge
    stripe_height = 30
    stripe_width = 40
    for x in range(0, WIDTH, stripe_width * 2):
        draw.rectangle([x, 200, x + stripe_width, 200 + stripe_height], fill=(220, 50, 30))
        draw.rectangle(
            [x + stripe_width, 200, x + stripe_width * 2, 200 + stripe_height], fill=(255, 200, 0)
        )

    # --- Car (side view), overlapping the no-parking zone ---
    car_x, car_y = 150, 280
    car_width, car_height = 220, 100
    car_color = random.choice(_CAR_COLORS)  # randomized per call -- see docstring

    draw.rectangle([car_x, car_y, car_x + car_width, car_y + car_height], fill=car_color)

    # Rounded corners (circles drawn over the rectangle's corners)
    corner_radius = 15
    for cx, cy in (
        (car_x, car_y),
        (car_x + car_width - corner_radius * 2, car_y),
        (car_x, car_y + car_height - corner_radius * 2),
        (car_x + car_width - corner_radius * 2, car_y + car_height - corner_radius * 2),
    ):
        draw.ellipse([cx, cy, cx + corner_radius * 2, cy + corner_radius * 2], fill=car_color)

    # Cabin/window area
    cabin_x, cabin_y = car_x + 50, car_y + 15
    cabin_width, cabin_height = 130, 50
    draw.rectangle(
        [cabin_x, cabin_y, cabin_x + cabin_width, cabin_y + cabin_height], fill=(150, 200, 195)
    )

    # Wheels
    wheel_radius = 18
    wheel_y = car_y + car_height - 5
    draw.ellipse(
        [car_x + 50 - wheel_radius, wheel_y - wheel_radius, car_x + 50 + wheel_radius, wheel_y + wheel_radius],
        fill=(40, 40, 40),
    )
    draw.ellipse(
        [
            car_x + car_width - 50 - wheel_radius,
            wheel_y - wheel_radius,
            car_x + car_width - 50 + wheel_radius,
            wheel_y + wheel_radius,
        ],
        fill=(40, 40, 40),
    )

    # Headlight
    draw.ellipse(
        [car_x + car_width - 25, car_y + 35, car_x + car_width - 10, car_y + 50], fill=(255, 255, 200)
    )

    # --- License plate ---
    plate_x, plate_y = car_x + 15, car_y + car_height + 10
    plate_width, plate_height = 100, 35
    draw.rectangle(
        [plate_x, plate_y, plate_x + plate_width, plate_y + plate_height],
        fill=(245, 245, 245),
        outline=(100, 100, 100),
        width=2,
    )

    font_plate = _load_font(24)
    font_caption = _load_font(18)

    if font_plate is not None and font_caption is not None:
        plate_text = "12가3456"
        caption_text = f"데모용 예시 이미지 · 실제 사진 아님 · #{unique_code}"
    else:
        # No Hangul-capable font found on this machine -- fall back to
        # Pillow's default bitmap font with ASCII-only strings so we never
        # render tofu boxes in place of Korean glyphs.
        font_plate = ImageFont.load_default()
        font_caption = font_plate
        plate_text = "12GA3456"
        caption_text = f"DEMO SAMPLE - NOT A REAL PHOTO - #{unique_code}"

    bbox = draw.textbbox((0, 0), plate_text, font=font_plate)
    text_width = bbox[2] - bbox[0]
    text_x = plate_x + (plate_width - text_width) / 2
    text_y = plate_y + (plate_height - (bbox[3] - bbox[1])) / 2 - 3
    draw.text((text_x, text_y), plate_text, fill=(30, 30, 30), font=font_plate)

    # --- Caption strip (bottom) ---
    caption_strip_height = 50
    caption_y = HEIGHT - caption_strip_height
    draw.rectangle([0, caption_y, WIDTH, HEIGHT], fill=(50, 50, 50))

    bbox = draw.textbbox((0, 0), caption_text, font=font_caption)
    text_width = bbox[2] - bbox[0]
    text_x = (WIDTH - text_width) / 2
    text_y = caption_y + (caption_strip_height - (bbox[3] - bbox[1])) / 2 - 3
    draw.text((text_x, text_y), caption_text, fill=(220, 220, 220), font=font_caption)

    buf = io.BytesIO()
    # `comment=` writes unique_code into the JPEG's COM marker -- untouched
    # by pixel quantization, so it changes the output bytes/sha256 even
    # independent of the visible caption text above. See module docstring.
    img.save(buf, "JPEG", quality=85, comment=unique_code.encode("ascii"))
    return buf.getvalue()
