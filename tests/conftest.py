import os
import tempfile

import pytest


@pytest.fixture
def app():
    from app import create_app
    from app.config import Config
    from app.extensions import db as _db

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    upload_dir = tempfile.mkdtemp()

    class TestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path
        UPLOAD_FOLDER = upload_dir

    application = create_app(TestConfig)

    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass  # Handle Windows file locking issues


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from app.extensions import db as _db

    return _db
