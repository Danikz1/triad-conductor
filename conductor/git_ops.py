"""Git operations: branches, worktrees, merges, diffs."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _git(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    cmd = ["git"] + args
    log.debug("git %s (cwd=%s)", " ".join(args), cwd)
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if result.returncode != 0:
        log.warning("git %s failed: %s", " ".join(args), result.stderr.strip())
    return result


def init_run_branches(
    repo_dir: Path,
    run_id: str,
    base_branch: str,
    branch_prefix: str = "run",
) -> dict[str, str]:
    """Create run anchor, builder, and integrate branches from base_branch.
    Returns dict with branch names."""
    builder = f"{branch_prefix}/{run_id}/builder"
    integrate = f"{branch_prefix}/{run_id}/integrate"

    _git(["checkout", base_branch], cwd=repo_dir)
    # Create builder and integrate branches directly from base
    # (no anchor branch needed — avoids git ref namespace conflict)
    _git(["branch", builder], cwd=repo_dir)
    _git(["branch", integrate], cwd=repo_dir)

    # Use the base branch commit as the anchor ref for diffs
    anchor_ref = base_branch

    return {"anchor": anchor_ref, "builder": builder, "integrate": integrate}


def create_builder_worktree(
    repo_dir: Path,
    worktrees_dir: Path,
    run_id: str,
    builder_branch: str,
) -> Path:
    """Create a git worktree for the builder branch. Returns the worktree path."""
    wt_path = worktrees_dir / run_id / "builder"
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", str(wt_path), builder_branch], cwd=repo_dir)
    return wt_path


def create_tournament_worktrees(
    repo_dir: Path,
    worktrees_dir: Path,
    run_id: str,
    integrate_branch: str,
    branch_prefix: str = "run",
) -> tuple[Path, Path, str, str]:
    """Create two tournament worktrees branching from integrate.
    Returns (pathA, pathB, branchA, branchB)."""
    branch_a = f"{branch_prefix}/{run_id}/builderA"
    branch_b = f"{branch_prefix}/{run_id}/builderB"
    _git(["branch", branch_a, integrate_branch], cwd=repo_dir)
    _git(["branch", branch_b, integrate_branch], cwd=repo_dir)

    path_a = worktrees_dir / run_id / "builderA"
    path_b = worktrees_dir / run_id / "builderB"
    path_a.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", str(path_a), branch_a], cwd=repo_dir)
    _git(["worktree", "add", str(path_b), branch_b], cwd=repo_dir)

    return path_a, path_b, branch_a, branch_b


def merge_builder_to_integrate(
    repo_dir: Path,
    builder_branch: str,
    integrate_branch: str,
) -> bool:
    """Merge builder branch into integrate. Returns True on success."""
    _git(["checkout", integrate_branch], cwd=repo_dir)
    result = _git(["merge", "--no-ff", builder_branch, "-m", f"Merge {builder_branch}"], cwd=repo_dir)
    return result.returncode == 0


def get_diff(repo_dir: Path, base: str, head: str) -> str:
    """Get unified diff between two branches/commits."""
    result = _git(["diff", f"{base}...{head}"], cwd=repo_dir)
    return result.stdout


def get_loc_changed(repo_dir: Path, base: str, head: str) -> int:
    """Count lines changed (added + deleted) between two refs."""
    result = _git(["diff", "--stat", f"{base}...{head}"], cwd=repo_dir)
    # Last line is like " 3 files changed, 10 insertions(+), 5 deletions(-)"
    lines = result.stdout.strip().splitlines()
    if not lines:
        return 0
    last = lines[-1]
    total = 0
    import re
    for m in re.finditer(r"(\d+)\s+(?:insertions?|deletions?)", last):
        total += int(m.group(1))
    return total


def cleanup_worktree(repo_dir: Path, wt_path: Path) -> None:
    """Remove a git worktree."""
    _git(["worktree", "remove", str(wt_path), "--force"], cwd=repo_dir)


def commit_all(cwd: Path, message: str) -> bool:
    """Stage all changes and commit in the given working directory."""
    _git(["add", "-A"], cwd=cwd)
    result = _git(["commit", "-m", message, "--allow-empty"], cwd=cwd)
    return result.returncode == 0
