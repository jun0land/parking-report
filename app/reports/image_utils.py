import io
import os
import uuid
from datetime import datetime

from PIL import Image


def save_resized_image(raw_bytes, upload_folder, max_dimension):
    """Resize an image so its longest side is at most max_dimension, save it
    as JPEG under upload_folder/YYYY/MM/<uuid>.jpg, and return the path
    "uploads/YYYY/MM/<uuid>.jpg" relative to upload_folder's parent directory
    (i.e. the Flask static folder), suitable for
    url_for('static', filename=...). upload_folder is expected to already BE
    the uploads directory (e.g. app.config["UPLOAD_FOLDER"], which points at
    .../app/static/uploads).
    """
    image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    image.thumbnail((max_dimension, max_dimension))

    today = datetime.utcnow()
    relative_dir = os.path.join("uploads", f"{today.year:04d}", f"{today.month:02d}")
    absolute_dir = os.path.join(upload_folder, f"{today.year:04d}", f"{today.month:02d}")
    os.makedirs(absolute_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.jpg"
    image.save(os.path.join(absolute_dir, filename), "JPEG", quality=85)

    return os.path.join(relative_dir, filename).replace("\\", "/")
