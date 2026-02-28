"""Tests for persistent Telegram SQLite state store."""

from __future__ import annotations

from pathlib import Path

from conductor.telegram.store import TelegramStateStore


def test_pending_task_roundtrip(tmp_path):
    store = TelegramStateStore(tmp_path / "telegram_state.db")
    store.set_pending_task(chat_id=123, task_text="# Task", project_root=Path("/tmp/project"))

    task, root = store.get_pending_task(chat_id=123)

    assert task == "# Task"
    assert root == Path("/tmp/project")

    store.clear_pending_task(chat_id=123)
    task2, root2 = store.get_pending_task(chat_id=123)
    assert task2 is None
    assert root2 is None


def test_run_queue_fifo(tmp_path):
    store = TelegramStateStore(tmp_path / "telegram_state.db")
    first = store.enqueue_run(chat_id=1, task_text="first", dry_run=False, project_root=None, config_path=None)
    second = store.enqueue_run(chat_id=1, task_text="second", dry_run=True, project_root=Path("/tmp/p"), config_path=None)

    assert second > first
    assert store.queue_depth(chat_id=1) == 2

    item1 = store.pop_next_run(chat_id=1)
    item2 = store.pop_next_run(chat_id=1)
    item3 = store.pop_next_run(chat_id=1)

    assert item1 is not None and item1.task_text == "first"
    assert item2 is not None and item2.task_text == "second"
    assert item2.dry_run is True
    assert item3 is None


def test_active_and_history_tracking(tmp_path):
    store = TelegramStateStore(tmp_path / "telegram_state.db")
    store.register_active_run(
        chat_id=9,
        run_id="tg-abc123",
        task_file=tmp_path / "task.md",
        project_root=tmp_path / "project",
        last_phase="PROPOSE",
    )

    active = store.get_active_run(chat_id=9)
    assert active is not None
    assert active["run_id"] == "tg-abc123"
    assert active["last_phase"] == "PROPOSE"

    store.record_run_finished(
        run_id="tg-abc123",
        chat_id=9,
        status="SUCCESS",
        phase="DONE",
        started_at=10.0,
        finished_at=20.0,
        project_root=tmp_path / "project",
        state_path=tmp_path / "state.json",
    )
    history = store.recent_runs(chat_id=9, limit=3)
    assert history
    assert history[0]["run_id"] == "tg-abc123"
    assert history[0]["status"] == "SUCCESS"

