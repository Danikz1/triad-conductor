"""Run state management, persistence, and circuit breakers."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


def now_ts() -> float:
    return time.time()


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
    max_stuck_replans: int = 1


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
    fail_signatures: list[str] = field(default_factory=list)
    failing_counts: list[int] = field(default_factory=list)
    loc_changed: list[int] = field(default_factory=list)
    stuck_replans_used: int = 0
    tournament_used: bool = False
    final_status: Optional[str] = None  # SUCCESS | PARTIAL | BLOCKED
    breaker_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def check_breakers(state: RunState, limits: Limits) -> Optional[str]:
    """Return a reason string if any circuit breaker is tripped, else None."""
    wall = (now_ts() - state.started_at) / 60.0
    if wall > limits.max_wall_time_minutes:
        return f"Wall-time exceeded: {wall:.1f}min > {limits.max_wall_time_minutes}min"
    if state.tool_calls_used > limits.max_total_tool_calls:
        return f"Tool calls exceeded: {state.tool_calls_used} > {limits.max_total_tool_calls}"
    if state.approx_cost_usd > limits.max_total_cost_usd:
        return f"Cost exceeded: ${state.approx_cost_usd:.2f} > ${limits.max_total_cost_usd:.2f}"
    return None


def persist_state(state: RunState, path: Path) -> None:
    """Atomically write state to disk (write tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.rename(str(tmp), str(path))


def load_state(path: Path) -> RunState:
    """Load RunState from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunState.from_dict(data)


def save_json(path: Path, obj: Any) -> None:
    """Write any JSON-serializable object atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.rename(str(tmp), str(path))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
