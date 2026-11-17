from types import SimpleNamespace
from unittest.mock import Mock

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


def test_start_bg_task_clears_logs_only_after_claiming_task():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"task_key": "digest_gen_2026-11-17"}

    assert db.start_bg_task(conn, "digest_gen_2026-11-17")
    assert conn.execute.call_count == 2
    assert "WHERE bg_tasks.status NOT IN ('generating', 'stopping')" in (
        conn.execute.call_args_list[0].args[0]
    )


def test_start_bg_task_does_not_clear_logs_when_already_running():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = None

    assert not db.start_bg_task(conn, "digest_gen_2026-11-17")
    assert conn.execute.call_count == 1


def test_request_bg_task_stop_marks_running_task_as_stopping():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"status": "stopping"}

    assert db.request_bg_task_stop(conn, "digest_gen_2026-11-17") == "stopping"


def test_finish_bg_task_does_not_overwrite_a_stop_request():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = None

    assert not db.finish_bg_task(conn, "digest_gen_2026-11-17", "done")
