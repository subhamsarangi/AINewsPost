import pytest
from unittest.mock import Mock

from digest import pipeline


def test_pipeline_check_raises_for_stopping_task(monkeypatch):
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(pipeline.db, "connect", lambda: conn)
    monkeypatch.setattr(
        pipeline.db, "get_bg_task", lambda conn, task_key: {"status": "stopping"}
    )

    with pytest.raises(pipeline.PipelineCancelled):
        pipeline._check_cancelled("digest_gen_2026-11-17")


def test_pipeline_check_is_noop_without_a_task_key():
    pipeline._check_cancelled(None)
