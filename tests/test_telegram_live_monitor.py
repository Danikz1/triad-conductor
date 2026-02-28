"""Tests for local Telegram live monitor helpers."""

from __future__ import annotations

from pathlib import Path

from conductor.telegram import live_monitor


def test_deserialize_context_value_path_sentinel():
    raw = {
        "builder_worktree": {"__triad_path__": "/tmp/worktrees/tg-abc/builder"},
        "nested": [{"k": {"__triad_path__": "/tmp/x"}}],
    }
    out = live_monitor._deserialize_context_value(raw)
    assert out["builder_worktree"] == Path("/tmp/worktrees/tg-abc/builder")
    assert out["nested"][0]["k"] == Path("/tmp/x")


def test_resolve_builder_worktree_from_context_or_fallback(tmp_path):
    context_data = {"builder_worktree": {"__triad_path__": str(tmp_path / "ctx-builder")}}
    from_ctx = live_monitor._resolve_builder_worktree(
        context_data=context_data,
        project_root=tmp_path / "project",
        run_id="tg-1",
    )
    assert from_ctx == tmp_path / "ctx-builder"

    fallback = live_monitor._resolve_builder_worktree(
        context_data=None,
        project_root=tmp_path / "project",
        run_id="tg-2",
    )
    assert fallback == tmp_path / "project" / "worktrees" / "tg-2" / "builder"
