from types import SimpleNamespace

from digest import db


def test_connect_disables_server_side_prepared_statements(monkeypatch):
    connection = object()
    options = {}

    monkeypatch.setattr(
        db, "get_settings", lambda: SimpleNamespace(database_url="postgresql://test")
    )
    monkeypatch.setattr(
        db.psycopg, "connect", lambda *args, **kwargs: options.update(kwargs) or connection
    )
    monkeypatch.setattr(db, "register_vector", lambda conn: None)

    assert db.connect() is connection
    assert options["prepare_threshold"] is None
