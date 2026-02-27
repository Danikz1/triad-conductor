"""
Triad Conductor (skeleton)

This is a minimal, dependency-light skeleton to implement the state machine in `conductor/state_machine.md`.

Notes:
- This file is intentionally incomplete; wire it to your chosen model CLIs and MCP tools.
- Validate model outputs against JSON Schemas in `schemas/` before using them.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

def now_ts() -> float:
    return time.time()

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def sh(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)

@dataclass
class Limits:
    max_wall_time_minutes: int = 90
    max_total_tool_calls: int = 200
    max_total_cost_usd: float = 25.0

@dataclass
class PhaseLimits:
    max_build_iterations: int = 5
    max_review_loops: int = 3
    max_optimize_passes: int = 2

@dataclass
class RunState:
    run_id: str
    started_at: float
    phase: str
    milestone_index: int = 0
    build_iteration: int = 0
    review_loops_used: int = 0
    optimize_passes_used: int = 0
    tool_calls_used: int = 0
    approx_cost_usd: float = 0.0
    fail_signatures: List[str] = None
    failing_counts: List[int] = None
    loc_changed: List[int] = None
    stuck_replans_used: int = 0

    def __post_init__(self):
        self.fail_signatures = self.fail_signatures or []
        self.failing_counts = self.failing_counts or []
        self.loc_changed = self.loc_changed or []

def check_breakers(state: RunState, limits: Limits) -> Optional[str]:
    wall = (now_ts() - state.started_at) / 60.0
    if wall > limits.max_wall_time_minutes:
        return f"Wall-time exceeded: {wall:.1f}min > {limits.max_wall_time_minutes}min"
    if state.tool_calls_used > limits.max_total_tool_calls:
        return f"Tool calls exceeded: {state.tool_calls_used} > {limits.max_total_tool_calls}"
    if state.approx_cost_usd > limits.max_total_cost_usd:
        return f"Cost exceeded: ${state.approx_cost_usd:.2f} > ${limits.max_total_cost_usd:.2f}"
    return None

def compute_failure_signature(test_output: str) -> str:
    # TODO: implement: pick first failing test + first stack line, or first compiler error line.
    lines = [ln.strip() for ln in test_output.splitlines() if ln.strip()]
    return lines[0][:200] if lines else "NO_OUTPUT"

def stuck_detector(state: RunState) -> bool:
    # Deterministic triggers (see state_machine.md)
    if len(state.fail_signatures) >= 3 and len(set(state.fail_signatures[-3:])) == 1:
        return True
    if len(state.failing_counts) >= 3 and state.failing_counts[-1] >= state.failing_counts[-2] >= state.failing_counts[-3]:
        return True
    if len(state.loc_changed) >= 2 and state.loc_changed[-1] < 10 and state.loc_changed[-2] < 10:
        # Small diffs twice in a row while still failing
        return True
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--task", required=True, help="Path to task.md")
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args()

    runs_dir = ROOT / "runs" / args.run_id
    state_path = runs_dir / "state.json"
    artifacts = runs_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    # Initialize state
    state = RunState(run_id=args.run_id, started_at=now_ts(), phase="INTAKE")
    save_json(state_path, asdict(state))

    # TODO: Implement phase transitions:
    # INTAKE -> PROPOSE -> SYNTHESIZE -> BUILD -> CROSS_CHECK -> OPTIMIZE -> REPORT
    # Use prompts/ and schemas/ to call models and validate responses.

    print(f"Initialized run {args.run_id} at {state_path}")

if __name__ == "__main__":
    main()
