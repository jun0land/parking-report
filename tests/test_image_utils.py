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

    # NOTE: this test passes a bare tmp_path (no "uploads" suffix) as
    # upload_folder, so the physical file lives at upload_folder/YYYY/MM/...
    # (no "uploads" segment), while relative_path (meant to be resolved
    # against upload_folder's *parent*, i.e. the static folder) still starts
    # with "uploads/". Strip that leading segment to locate the physical
    # file under this bare-tmp_path setup. See
    # test_save_resized_image_matches_real_upload_folder_shape below for a
    # setup that mirrors the real app.config["UPLOAD_FOLDER"] shape.
    absolute_path = os.path.join(str(tmp_path), relative_path.split("/", 1)[1])
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


def test_save_resized_image_matches_real_upload_folder_shape(tmp_path):
    # app.config["UPLOAD_FOLDER"] is actually ".../app/static/uploads" -
    # i.e. upload_folder itself already ends in "uploads". Mimic that shape
    # here so the test would catch a spurious extra "uploads" segment being
    # added inside save_resized_image (which previously caused the physical
    # save location to diverge from the path returned for
    # url_for('static', filename=...)).
    upload_folder = str(tmp_path / "uploads")

    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color=(10, 20, 30)).save(buf, "JPEG")
    raw_bytes = buf.getvalue()

    relative_path = save_resized_image(raw_bytes, upload_folder, max_dimension=1280)

    assert relative_path.startswith("uploads/")

    # Simulate how url_for('static', filename=relative_path) resolves in the
    # real app: static folder is the parent of UPLOAD_FOLDER (tmp_path here),
    # joined with the returned relative path.
    static_folder = str(tmp_path)
    resolved_path = os.path.join(static_folder, relative_path.replace("/", os.sep))
    assert os.path.exists(resolved_path)

    # Also verify directly via upload_folder + the remainder of the relative
    # path (dropping the leading "uploads/" segment), per the task's spec.
    direct_path = os.path.join(upload_folder, relative_path.split("/", 1)[1])
    assert os.path.exists(direct_path)
