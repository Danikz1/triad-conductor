"""Phase 0: INTAKE - Setup directories, git branches, worktrees."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from conductor.config import Config
from conductor.git_ops import init_run_branches, create_builder_worktree
from conductor.state import RunState, persist_state

log = logging.getLogger(__name__)


def run_intake(
    state: RunState,
    config: Config,
    task_path: Path,
    project_root: Path,
    run_dir: Path,
) -> dict:
    """Execute the INTAKE phase.

    - Copies task file into run directory
    - Creates git branches (anchor, builder, integrate)
    - Creates builder worktree
    - Returns context dict with paths and branch names
    """
    log.info("=== PHASE 0: INTAKE ===")

    # Create run directories
    input_dir = run_dir / "input"
    artifacts_dir = run_dir / "artifacts"
    for d in [input_dir, artifacts_dir, artifacts_dir / "logs",
              artifacts_dir / "tests", artifacts_dir / "screenshots"]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy task file
    dest_task = input_dir / "task.md"
    shutil.copy2(str(task_path), str(dest_task))
    task_text = dest_task.read_text(encoding="utf-8")
    log.info("Task copied to %s (%d chars)", dest_task, len(task_text))

    # Create git branches
    branches = init_run_branches(
        repo_dir=project_root,
        run_id=state.run_id,
        base_branch=config.base_branch,
        branch_prefix=config.branch_prefix,
    )
    log.info("Git branches created: %s", branches)

    # Create builder worktree
    worktrees_dir = project_root / config.worktrees_dir
    builder_wt = create_builder_worktree(
        repo_dir=project_root,
        worktrees_dir=worktrees_dir,
        run_id=state.run_id,
        builder_branch=branches["builder"],
    )
    log.info("Builder worktree at %s", builder_wt)

    # Transition to PROPOSE
    state.phase = "PROPOSE"
    state_path = run_dir / "state.json"
    persist_state(state, state_path)

    return {
        "task_text": task_text,
        "branches": branches,
        "builder_worktree": builder_wt,
        "run_dir": run_dir,
        "artifacts_dir": artifacts_dir,
    }
