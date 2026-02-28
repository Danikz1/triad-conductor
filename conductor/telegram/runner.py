"""RunnerManager: spawn conductor subprocess, poll state.json, send phase-change updates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Bot

from .formatting import format_final_report, format_phase_change, format_status

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2
CONDUCTOR_ROOT = Path(__file__).resolve().parents[2]  # triad-conductor/


@dataclass
class ActiveRun:
    run_id: str
    chat_id: int
    process: subprocess.Popen
    conductor_root: Path
    task_file: Path
    poll_task: Optional[asyncio.Task] = None
    last_phase: str = "INTAKE"


class RunnerManager:
    """Manages one active conductor run per Telegram chat."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._runs: Dict[int, ActiveRun] = {}  # chat_id -> ActiveRun

    def has_active_run(self, chat_id: int) -> bool:
        run = self._runs.get(chat_id)
        if run is None:
            return False
        # Clean up finished processes
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return False
        return True

    def get_status(self, chat_id: int) -> Optional[str]:
        """Read current state.json and return formatted status, or None."""
        run = self._runs.get(chat_id)
        if run is None:
            return None
        state_path = run.conductor_root / "runs" / run.run_id / "state.json"
        if not state_path.exists():
            return None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return format_status(state)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read state.json: %s", exc)
            return None

    async def start_run(
        self,
        chat_id: int,
        task_text: str,
        dry_run: bool = False,
        project_root: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ) -> str:
        """Write task to file, spawn conductor, start poll loop. Returns run_id."""
        conductor_root = CONDUCTOR_ROOT
        target_project_root = project_root
        run_id = f"tg-{uuid.uuid4().hex[:8]}"

        # Write task to file
        task_dir = conductor_root / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_file = task_dir / f"{run_id}.md"
        task_file.write_text(task_text, encoding="utf-8")

        # Build command — matches conductor.py CLI
        conductor_script = conductor_root / "conductor.py"
        cmd = [
            sys.executable,
            str(conductor_script),
            "run",
            "--task", str(task_file),
            "--run-id", run_id,
            "--config", str(config_path or conductor_root / "config.yaml"),
        ]
        if target_project_root:
            cmd.extend(["--project-root", str(target_project_root)])
        if dry_run:
            cmd.append("--dry-run")

        logger.info("Starting conductor: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=str(conductor_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        active = ActiveRun(
            run_id=run_id,
            chat_id=chat_id,
            process=proc,
            conductor_root=conductor_root,
            task_file=task_file,
        )
        self._runs[chat_id] = active

        # Start async poll loop
        active.poll_task = asyncio.create_task(self._poll_state(active))
        return run_id

    async def stop_run(self, chat_id: int) -> bool:
        """Send SIGINT to the conductor subprocess. Returns True if a run was stopped."""
        run = self._runs.get(chat_id)
        if run is None:
            return False
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return False
        run.process.send_signal(signal.SIGINT)
        return True

    # ── internal ──

    async def _poll_state(self, run: ActiveRun) -> None:
        """Poll state.json every POLL_INTERVAL_S and notify on phase changes."""
        state_path = run.conductor_root / "runs" / run.run_id / "state.json"

        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_S)

                # Check if process exited
                if run.process.poll() is not None:
                    await self._send_completion(run, state_path)
                    break

                if not state_path.exists():
                    continue

                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue

                current_phase = state.get("phase", "UNKNOWN")
                if current_phase != run.last_phase:
                    msg = format_phase_change(run.last_phase, current_phase, state)
                    await self._bot.send_message(
                        chat_id=run.chat_id, text=msg, parse_mode="HTML"
                    )
                    run.last_phase = current_phase

                    if current_phase == "DONE":
                        await self._send_completion(run, state_path)
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Poll loop error for run %s", run.run_id)
        finally:
            self._cleanup(run.chat_id)

    async def _send_completion(self, run: ActiveRun, state_path: Path) -> None:
        """Send the final report and state.json as an attachment."""
        state: Dict[str, Any] = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        report_text = format_final_report(state)
        await self._bot.send_message(
            chat_id=run.chat_id, text=report_text, parse_mode="HTML"
        )

        # Send state.json as a file attachment
        if state_path.exists():
            await self._bot.send_document(
                chat_id=run.chat_id,
                document=state_path,
                filename=f"state_{run.run_id}.json",
                caption="Final state.json",
            )

    def _cleanup(self, chat_id: int) -> None:
        """Remove run from tracking and cancel poll task."""
        run = self._runs.pop(chat_id, None)
        if run is None:
            return
        if run.poll_task and not run.poll_task.done():
            run.poll_task.cancel()
        # Ensure process is terminated
        if run.process.poll() is None:
            run.process.terminate()
