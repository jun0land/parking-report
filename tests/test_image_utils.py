import io
import os

from PIL import Image

from app.reports.image_utils import save_resized_image


def test_save_resized_image_shrinks_large_image(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), color=(200, 100, 50)).save(buf, "JPEG")
    raw_bytes = buf.getvalue()

    relative_path = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)

    assert relative_path.startswith("uploads/")
    assert relative_path.endswith(".jpg")

    absolute_path = os.path.join(str(tmp_path), relative_path)
    assert os.path.exists(absolute_path)

    with Image.open(absolute_path) as saved:
        assert max(saved.size) <= 1280


def test_save_resized_image_generates_unique_filenames(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(1, 2, 3)).save(buf, "JPEG")
    raw_bytes = buf.getvalue()

    path_one = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)
    path_two = save_resized_image(raw_bytes, str(tmp_path), max_dimension=1280)

    assert path_one != path_two
