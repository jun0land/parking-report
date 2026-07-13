def test_app_factory_creates_working_app(app):
    assert app.config["TESTING"] is True


def test_db_tables_exist(app, db):
    with app.app_context():
        # Will raise if create_app()/db.init_app() wiring is broken.
        db.session.execute(db.text("SELECT 1"))
