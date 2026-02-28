"""Local terminal monitor for Telegram-triggered runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

CONTEXT_SENTINEL = "__triad_path__"


def _deserialize_context_value(value):
    if isinstance(value, dict):
        if set(value.keys()) == {CONTEXT_SENTINEL}:
            return Path(value[CONTEXT_SENTINEL])
        return {k: _deserialize_context_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deserialize_context_value(v) for v in value]
    return value


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        return data
    return None


def _resolve_builder_worktree(
    *,
    context_data: Optional[dict[str, Any]],
    project_root: Optional[Path],
    run_id: str,
) -> Optional[Path]:
    if context_data:
        context = _deserialize_context_value(context_data)
        wt = context.get("builder_worktree")
        if isinstance(wt, Path):
            return wt
        if isinstance(wt, str):
            return Path(wt)
    if project_root:
        return project_root / "worktrees" / run_id / "builder"
    return None


def _tail_text(path: Path, max_lines: int = 12) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192), os.SEEK_SET)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return lines[-max_lines:]


def _run_capture(cmd: list[str], cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=8,
        )
    except Exception as exc:
        return f"[error] {exc}"
    output = (result.stdout + "\n" + result.stderr).strip()
    return output[:4000] if output else "(no output)"


def _clear_screen() -> None:
    # ANSI clear + cursor home
    print("\033[2J\033[H", end="")


def _render_once(
    *,
    run_id: str,
    run_dir: Path,
    state: Optional[dict[str, Any]],
    context_data: Optional[dict[str, Any]],
    project_root: Optional[Path],
) -> str:
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    lines = [
        f"Triad Telegram Live Monitor   {now}",
        f"Run ID: {run_id}",
        f"Run dir: {run_dir}",
        "",
    ]

    if state:
        lines.extend(
            [
                "[STATE]",
                f"phase={state.get('phase')}  milestone={state.get('milestone_index')}  build_iter={state.get('build_iteration')}",
                f"cost=${float(state.get('approx_cost_usd', 0.0)):.2f}  tool_calls={state.get('tool_calls_used', 0)}",
                "",
            ]
        )
    else:
        lines.extend(["[STATE]", "state.json not available yet", ""])

    log_lines = _tail_text(run_dir / "artifacts" / "logs" / "conductor.log", max_lines=10)
    lines.append("[LATEST LOG LINES]")
    if log_lines:
        lines.extend(log_lines)
    else:
        lines.append("conductor.log not available yet")
    lines.append("")

    wt = _resolve_builder_worktree(context_data=context_data, project_root=project_root, run_id=run_id)
    if wt:
        lines.extend(
            [
                f"[BUILDER WORKTREE] {wt}",
                "$ git status --short",
                _run_capture(["git", "status", "--short"], cwd=wt),
                "",
                "$ git diff --stat",
                _run_capture(["git", "diff", "--stat"], cwd=wt),
                "",
            ]
        )
    else:
        lines.extend(["[BUILDER WORKTREE]", "not resolved yet", ""])

    lines.append("Press Ctrl+C to exit.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Live monitor for Triad Telegram runs")
    ap.add_argument("--run-id", required=True, help="Telegram run id (tg-xxxx)")
    ap.add_argument(
        "--conductor-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Path to triad-conductor root",
    )
    ap.add_argument("--project-root", default=None, help="Project root path (optional)")
    ap.add_argument("--interval", type=float, default=2.0, help="Refresh interval seconds")
    args = ap.parse_args()

    run_id = args.run_id
    conductor_root = Path(args.conductor_root).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else None
    interval = args.interval if args.interval > 0 else 2.0

    run_dir = conductor_root / "runs" / run_id
    state_path = run_dir / "state.json"
    context_path = run_dir / "context.json"

    try:
        while True:
            state = _read_json(state_path)
            context_data = _read_json(context_path)
            text = _render_once(
                run_id=run_id,
                run_dir=run_dir,
                state=state,
                context_data=context_data,
                project_root=project_root,
            )
            _clear_screen()
            print(text)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


if __name__ == "__main__":
    main()
