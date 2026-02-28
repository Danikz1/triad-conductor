"""Tests for CLI context persistence helpers used by resume mode."""

from pathlib import Path

from conductor.cli import load_context, persist_context


def test_context_roundtrip_preserves_paths(tmp_dir):
    context = {
        "project_root": tmp_dir,
        "builder_worktree": tmp_dir / "worktrees" / "builder",
        "task_text": "Implement feature",
        "branches": {"builder": "run/x/builder", "integrate": "run/x/integrate"},
        "nested": {
            "mcp_config_path": tmp_dir / "mcp" / "config.json",
            "paths": [tmp_dir / "a", tmp_dir / "b"],
        },
    }
    path = tmp_dir / "context.json"
    persist_context(context, path)
    loaded = load_context(path)

    assert loaded["project_root"] == tmp_dir
    assert loaded["builder_worktree"] == tmp_dir / "worktrees" / "builder"
    assert loaded["nested"]["mcp_config_path"] == tmp_dir / "mcp" / "config.json"
    assert loaded["nested"]["paths"] == [tmp_dir / "a", tmp_dir / "b"]
    assert loaded["task_text"] == "Implement feature"
