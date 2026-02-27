"""Tests for conductor.git_ops module."""

import subprocess
from pathlib import Path

import pytest

from conductor.git_ops import (
    init_run_branches, create_builder_worktree,
    merge_builder_to_integrate, get_diff, get_loc_changed,
    cleanup_worktree, commit_all,
)


@pytest.fixture
def git_repo(tmp_dir):
    """Create a minimal git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_dir), capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_dir), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_dir), capture_output=True)
    (tmp_dir / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_dir), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_dir), capture_output=True)
    return tmp_dir


def test_init_run_branches(git_repo):
    branches = init_run_branches(git_repo, "test-run", "main")
    assert "anchor" in branches
    assert "builder" in branches
    assert "integrate" in branches
    # anchor is the base branch ref (main), builder/integrate are new branches
    result = subprocess.run(["git", "branch"], cwd=str(git_repo), capture_output=True, text=True)
    assert branches["builder"] in result.stdout
    assert branches["integrate"] in result.stdout


def test_create_builder_worktree(git_repo):
    branches = init_run_branches(git_repo, "test-run", "main")
    wt_dir = git_repo / "worktrees"
    wt_path = create_builder_worktree(git_repo, wt_dir, "test-run", branches["builder"])
    assert wt_path.exists()
    assert (wt_path / "README.md").exists()
    # Cleanup
    cleanup_worktree(git_repo, wt_path)


def test_commit_all(git_repo):
    (git_repo / "new_file.txt").write_text("hello\n")
    result = commit_all(git_repo, "add new file")
    assert result is True


def test_get_diff_and_loc(git_repo):
    branches = init_run_branches(git_repo, "test-run", "main")
    wt_dir = git_repo / "worktrees"
    wt_path = create_builder_worktree(git_repo, wt_dir, "test-run", branches["builder"])
    # Make a change in builder worktree
    (wt_path / "feature.py").write_text("def hello():\n    return 'world'\n")
    commit_all(wt_path, "add feature")
    # Get diff
    diff = get_diff(git_repo, branches["integrate"], branches["builder"])
    assert "feature.py" in diff
    loc = get_loc_changed(git_repo, branches["integrate"], branches["builder"])
    assert loc > 0
    cleanup_worktree(git_repo, wt_path)


def test_merge_builder_to_integrate(git_repo):
    branches = init_run_branches(git_repo, "test-run", "main")
    wt_dir = git_repo / "worktrees"
    wt_path = create_builder_worktree(git_repo, wt_dir, "test-run", branches["builder"])
    (wt_path / "feature.py").write_text("print('hi')\n")
    commit_all(wt_path, "add feature")
    cleanup_worktree(git_repo, wt_path)
    result = merge_builder_to_integrate(git_repo, branches["builder"], branches["integrate"])
    assert result is True
