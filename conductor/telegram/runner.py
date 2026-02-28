"""RunnerManager: spawn conductor subprocess, poll state.json, send phase-change updates."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Bot

from .formatting import (
    format_final_report,
    format_heartbeat,
    format_phase_change,
    format_publish_report,
    format_status,
    format_stuck_alert,
)
from .store import TelegramStateStore

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2
CONDUCTOR_ROOT = Path(__file__).resolve().parents[2]  # triad-conductor/


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict):
        return data
    return None


def _extract_markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _resolve_run_status(state: dict[str, Any], run_report: Optional[dict[str, Any]] = None) -> str:
    final_status = state.get("final_status")
    if isinstance(final_status, str) and final_status:
        return final_status
    if run_report and isinstance(run_report.get("status"), str):
        return run_report["status"]
    if state.get("breaker_reason"):
        return "BLOCKED"
    return "SUCCESS"


def _sanitize_repo_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "triad-project"


def _normalize_github_remote(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://github.com/{path}"
    if raw.startswith("https://github.com/") and raw.endswith(".git"):
        return raw[:-4]
    return raw


def _render_project_description(
    *,
    project_title: str,
    source_description: str,
    run_id: str,
    run_status: str,
    state: dict[str, Any],
    run_report: Optional[dict[str, Any]],
    artifacts: list[str],
    github_url: str,
) -> str:
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [
        f"# {project_title} — Project Description",
        "",
        "> Auto-maintained by Triad Conductor (Telegram automation).",
        "",
        "## Source Description",
        source_description.strip() or "(no project.md content found)",
        "",
        "## Latest Build Run",
        f"- Run ID: `{run_id}`",
        f"- Status: `{run_status}`",
        f"- Completed phase: `{state.get('phase', 'UNKNOWN')}`",
        f"- Cost (USD): `{state.get('approx_cost_usd', 0.0):.2f}`",
        f"- Tool calls: `{state.get('tool_calls_used', 0)}`",
    ]
    if state.get("breaker_reason"):
        lines.append(f"- Breaker reason: {state.get('breaker_reason')}")

    if github_url:
        lines.extend(
            [
                "",
                "## GitHub",
                f"- Remote: {github_url}",
            ]
        )

    if run_report:
        lines.extend(
            [
                "",
                "## Final Report Snapshot",
                "```json",
                json.dumps(run_report, indent=2, ensure_ascii=False),
                "```",
            ]
        )

    if artifacts:
        lines.extend(
            [
                "",
                "## Run Artifacts",
            ]
        )
        for rel in artifacts:
            lines.append(f"- `{rel}`")

    lines.extend(
        [
            "",
            f"_Last updated: {generated_at}_",
            "",
        ]
    )
    return "\n".join(lines)


@dataclass
class ActiveRun:
    run_id: str
    chat_id: int
    process: subprocess.Popen
    conductor_root: Path
    task_file: Path
    project_root: Optional[Path] = None
    poll_task: Optional[asyncio.Task] = None
    last_phase: str = "INTAKE"
    started_at: float = field(default_factory=time.time)
    last_phase_change_at: float = field(default_factory=time.time)
    last_stuck_alert_at: float = 0.0


class RunnerManager:
    """Manages one active conductor run per Telegram chat."""

    def __init__(self, bot: Bot, store: Optional[TelegramStateStore] = None) -> None:
        self._bot = bot
        self._runs: Dict[int, ActiveRun] = {}  # chat_id -> ActiveRun
        self._store = store

    def _auto_open_monitor_enabled(self) -> bool:
        raw = os.environ.get("TRIAD_TELEGRAM_AUTO_OPEN_MONITOR", "1").strip().lower()
        return raw not in {"0", "false", "no", "off", ""}

    def _monitor_python_bin(self, conductor_root: Path) -> str:
        venv_python = conductor_root / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        return sys.executable

    def local_monitor_command(self, run_id: str, project_root: Optional[Path] = None) -> str:
        cmd = [
            self._monitor_python_bin(CONDUCTOR_ROOT),
            "-m",
            "conductor.telegram.live_monitor",
            "--run-id",
            run_id,
            "--conductor-root",
            str(CONDUCTOR_ROOT),
        ]
        if project_root is not None:
            cmd.extend(["--project-root", str(project_root)])
        return " ".join(shlex.quote(part) for part in cmd)

    def _auto_open_local_monitor(self, run: ActiveRun) -> None:
        if not self._auto_open_monitor_enabled():
            return
        if sys.platform != "darwin":
            logger.info("Auto-open monitor is currently supported only on macOS.")
            return
        if not shutil.which("osascript"):
            logger.warning("osascript not found; cannot auto-open local monitor terminal.")
            return

        monitor_cmd = self.local_monitor_command(run.run_id, run.project_root)
        shell_cmd = f"cd {shlex.quote(str(run.conductor_root))} && {monitor_cmd}"
        script_line = json.dumps(shell_cmd)
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f"tell application \"Terminal\" to do script {script_line}",
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            logger.warning("Failed to auto-open local monitor: %s", result.stderr.strip())

    def _heartbeat_interval_seconds(self) -> float:
        raw = os.environ.get("TRIAD_TELEGRAM_HEARTBEAT_SECONDS", "60").strip()
        try:
            value = float(raw)
        except ValueError:
            return 60.0
        if value <= 0:
            return 60.0
        return value

    def _stuck_alert_seconds(self) -> float:
        raw = os.environ.get("TRIAD_TELEGRAM_STUCK_ALERT_SECONDS", "600").strip()
        try:
            value = float(raw)
        except ValueError:
            return 600.0
        if value <= 0:
            return 600.0
        return value

    def _stuck_alert_cooldown_seconds(self) -> float:
        raw = os.environ.get("TRIAD_TELEGRAM_STUCK_ALERT_COOLDOWN_SECONDS", "600").strip()
        try:
            value = float(raw)
        except ValueError:
            return 600.0
        if value <= 0:
            return 600.0
        return value

    def queue_depth(self, chat_id: int) -> int:
        if not self._store:
            return 0
        return self._store.queue_depth(chat_id=chat_id)

    def has_active_run(self, chat_id: int) -> bool:
        run = self._runs.get(chat_id)
        if run is None:
            if self._store:
                self._store.clear_active_run(chat_id=chat_id)
            return False
        # Clean up finished processes
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return False
        return True

    def active_run_id(self, chat_id: int) -> Optional[str]:
        run = self._runs.get(chat_id)
        if run is None:
            return None
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return None
        return run.run_id

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

    def get_health(self, chat_id: int) -> Optional[dict[str, Any]]:
        run = self._runs.get(chat_id)
        if run is None:
            return None
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return None

        state_path = run.conductor_root / "runs" / run.run_id / "state.json"
        state = _read_json(state_path) or {}
        phase = str(state.get("phase") or run.last_phase or "UNKNOWN")
        age_seconds = self._state_age_seconds(state_path)
        phase_seconds = max(0.0, time.time() - run.last_phase_change_at)
        stuck_threshold = self._stuck_alert_seconds()
        is_stuck = phase != "DONE" and phase_seconds >= stuck_threshold
        return {
            "run_id": run.run_id,
            "phase": phase,
            "phase_age_seconds": phase_seconds,
            "state_age_seconds": age_seconds,
            "last_activity": self._read_last_activity_line(run),
            "queue_depth": self.queue_depth(chat_id),
            "stuck_threshold_seconds": stuck_threshold,
            "is_stuck": is_stuck,
        }

    def get_recent_logs(self, chat_id: int, *, lines: int = 20) -> Optional[list[str]]:
        run = self._runs.get(chat_id)
        if run is None:
            return None
        if run.process.poll() is not None:
            self._cleanup(chat_id)
            return None

        log_path = run.conductor_root / "runs" / run.run_id / "artifacts" / "logs" / "conductor.log"
        if not log_path.exists():
            return []
        max_lines = min(max(int(lines), 1), 80)
        try:
            with log_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 32768), os.SEEK_SET)
                chunk = f.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        entries = [line.rstrip() for line in chunk.splitlines() if line.strip()]
        return entries[-max_lines:]

    async def start_run(
        self,
        chat_id: int,
        task_text: str,
        dry_run: bool = False,
        project_root: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ) -> str:
        """Write task to file, spawn conductor, start poll loop. Returns run_id."""
        if self.has_active_run(chat_id):
            raise RuntimeError("Run is already active for this chat.")

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
            project_root=target_project_root,
            last_phase="INTAKE",
        )
        self._runs[chat_id] = active
        if self._store:
            self._store.register_active_run(
                chat_id=chat_id,
                run_id=run_id,
                task_file=task_file,
                project_root=target_project_root,
                last_phase=active.last_phase,
            )

        self._auto_open_local_monitor(active)

        # Start async poll loop
        active.poll_task = asyncio.create_task(self._poll_state(active))
        return run_id

    def queue_run(
        self,
        *,
        chat_id: int,
        task_text: str,
        dry_run: bool,
        project_root: Optional[Path],
        config_path: Optional[Path] = None,
    ) -> int:
        if not self._store:
            raise RuntimeError("Queue is not configured.")
        return self._store.enqueue_run(
            chat_id=chat_id,
            task_text=task_text,
            dry_run=dry_run,
            project_root=project_root,
            config_path=config_path,
        )

    async def _start_next_queued_run(self, chat_id: int) -> None:
        if self.has_active_run(chat_id):
            return
        if not self._store:
            return
        queued = self._store.pop_next_run(chat_id=chat_id)
        if queued is None:
            return
        try:
            run_id = await self.start_run(
                chat_id=chat_id,
                task_text=queued.task_text,
                dry_run=queued.dry_run,
                project_root=queued.project_root,
                config_path=queued.config_path,
            )
        except Exception as exc:
            logger.exception("Failed to start queued run for chat %s", chat_id)
            await self._bot.send_message(
                chat_id=chat_id,
                text=f"Queued run failed to start: {exc}",
            )
            return

        monitor_cmd = self.local_monitor_command(run_id, queued.project_root)
        await self._bot.send_message(
            chat_id=chat_id,
            text=(
                f"\U0001f680 Started queued run <code>{run_id}</code>.\n"
                f"Local live monitor command:\n<code>{html.escape(monitor_cmd)}</code>"
            ),
            parse_mode="HTML",
        )

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

    def _git(self, project_root: Path, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )

    def _ensure_main_checkout(self, project_root: Path, publish_report: dict[str, Any]) -> bool:
        inside = self._git(project_root, ["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0:
            publish_report["errors"].append(
                f"Project root is not a git repository: {inside.stderr.strip() or project_root}"
            )
            return False

        has_main = self._git(project_root, ["show-ref", "--verify", "--quiet", "refs/heads/main"])
        if has_main.returncode != 0:
            current = self._git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"])
            current_branch = (current.stdout or "").strip()
            if current.returncode == 0 and current_branch and current_branch != "HEAD":
                self._git(project_root, ["branch", "main", current_branch])
            else:
                create_main = self._git(project_root, ["checkout", "-b", "main"])
                if create_main.returncode != 0:
                    publish_report["errors"].append(
                        f"Failed to create main branch: {create_main.stderr.strip()}"
                    )
                    return False

        checkout_main = self._git(project_root, ["checkout", "main"])
        if checkout_main.returncode != 0:
            publish_report["errors"].append(f"Failed to checkout main: {checkout_main.stderr.strip()}")
            return False
        return True

    def _ensure_git_identity(self, project_root: Path) -> None:
        has_email = self._git(project_root, ["config", "user.email"])
        if has_email.returncode != 0:
            self._git(project_root, ["config", "user.email", "triad@local"])
        has_name = self._git(project_root, ["config", "user.name"])
        if has_name.returncode != 0:
            self._git(project_root, ["config", "user.name", "Triad Conductor"])

    def _merge_integrate_branch(
        self,
        project_root: Path,
        run_id: str,
        context: dict[str, Any],
        run_status: str,
        publish_report: dict[str, Any],
    ) -> None:
        if run_status not in {"SUCCESS", "PARTIAL"}:
            return
        branches = context.get("branches") if isinstance(context, dict) else None
        integrate_branch = branches.get("integrate") if isinstance(branches, dict) else None
        if not integrate_branch:
            publish_report["errors"].append("Integrate branch not found in run context; skipped merge to main.")
            return

        branch_ref = f"refs/heads/{integrate_branch}"
        branch_exists = self._git(project_root, ["show-ref", "--verify", "--quiet", branch_ref])
        if branch_exists.returncode != 0:
            publish_report["errors"].append(
                f"Integrate branch not found locally ({integrate_branch}); skipped merge to main."
            )
            return

        merge = self._git(
            project_root,
            ["merge", "--no-ff", integrate_branch, "-m", f"Merge {integrate_branch} from run {run_id}"],
        )
        if merge.returncode != 0:
            self._git(project_root, ["merge", "--abort"])
            publish_report["errors"].append(
                f"Failed to merge {integrate_branch} into main: {merge.stderr.strip()}"
            )
            return
        publish_report["integrate_merged"] = True

    def _load_run_report(self, run_dir: Path) -> Optional[dict[str, Any]]:
        final_report = _read_json(run_dir / "artifacts" / "final_report.json")
        if final_report:
            return final_report
        return _read_json(run_dir / "artifacts" / "blocked_report.json")

    def _collect_artifacts(self, run_dir: Path) -> list[str]:
        artifacts_dir = run_dir / "artifacts"
        if not artifacts_dir.exists():
            return []
        rel_paths: list[str] = []
        for path in sorted(artifacts_dir.rglob("*")):
            if path.is_file():
                rel_paths.append(str(path.relative_to(run_dir)))
        return rel_paths

    def _write_project_description(
        self,
        project_root: Path,
        run: ActiveRun,
        state: dict[str, Any],
        run_status: str,
        run_report: Optional[dict[str, Any]],
        github_url: str,
        artifacts: list[str],
    ) -> Path:
        source_path = project_root / "project.md"
        source_text = ""
        if source_path.exists():
            source_text = source_path.read_text(encoding="utf-8")
        elif run.task_file.exists():
            source_text = run.task_file.read_text(encoding="utf-8")
        project_title = _extract_markdown_title(source_text) or project_root.name

        description_md = _render_project_description(
            project_title=project_title,
            source_description=source_text,
            run_id=run.run_id,
            run_status=run_status,
            state=state,
            run_report=run_report,
            artifacts=artifacts,
            github_url=github_url,
        )
        description_filename = f"{_sanitize_repo_name(project_title)}_PROJECT_DESCRIPTION.md"
        description_path = project_root / description_filename
        description_path.write_text(description_md, encoding="utf-8")
        return description_path

    def _commit_description_update(
        self,
        project_root: Path,
        description_path: Path,
        run_id: str,
        publish_report: dict[str, Any],
    ) -> None:
        self._ensure_git_identity(project_root)
        self._git(project_root, ["add", str(description_path.name)])
        staged = self._git(project_root, ["diff", "--cached", "--quiet"])
        if staged.returncode == 0:
            return
        commit = self._git(project_root, ["commit", "-m", f"docs: update project description for run {run_id}"])
        if commit.returncode != 0:
            publish_report["errors"].append(
                f"Failed to commit {description_path.name}: {commit.stderr.strip()}"
            )
            return
        publish_report["description_committed"] = True

    def _ensure_github_remote(self, project_root: Path, publish_report: dict[str, Any]) -> bool:
        auto_publish = os.environ.get("TRIAD_GITHUB_AUTO_PUBLISH", "1").strip().lower()
        if auto_publish in {"0", "false", "no", "off"}:
            publish_report["errors"].append("GitHub auto-publish disabled by TRIAD_GITHUB_AUTO_PUBLISH.")
            return False

        remote = self._git(project_root, ["remote", "get-url", "origin"])
        if remote.returncode == 0:
            publish_report["github_checked"] = True
            publish_report["github_url"] = _normalize_github_remote((remote.stdout or "").strip())
            return True

        if not shutil.which("gh"):
            publish_report["errors"].append("GitHub CLI (gh) not found; cannot create repository automatically.")
            return False

        owner = os.environ.get("TRIAD_GITHUB_OWNER", "").strip()
        visibility = os.environ.get("TRIAD_GITHUB_VISIBILITY", "private").strip().lower()
        if visibility not in {"private", "public", "internal"}:
            visibility = "private"
        repo_name = _sanitize_repo_name(project_root.name)
        repo_slug = f"{owner}/{repo_name}" if owner else repo_name

        create_cmd = [
            "gh",
            "repo",
            "create",
            repo_slug,
            f"--{visibility}",
            "--source",
            str(project_root),
            "--remote",
            "origin",
        ]
        created = subprocess.run(create_cmd, text=True, capture_output=True)
        if created.returncode != 0:
            publish_report["errors"].append(
                f"Failed to create GitHub repo ({repo_slug}): {created.stderr.strip()}"
            )
            return False

        publish_report["github_created"] = True
        publish_report["github_checked"] = True
        remote_after = self._git(project_root, ["remote", "get-url", "origin"])
        if remote_after.returncode == 0:
            publish_report["github_url"] = _normalize_github_remote((remote_after.stdout or "").strip())
        return True

    def _push_main(self, project_root: Path, publish_report: dict[str, Any]) -> None:
        push = self._git(project_root, ["push", "-u", "origin", "main"])
        if push.returncode != 0:
            publish_report["errors"].append(f"Failed to push main: {push.stderr.strip()}")
            return
        publish_report["github_pushed"] = True
        remote = self._git(project_root, ["remote", "get-url", "origin"])
        if remote.returncode == 0:
            publish_report["github_url"] = _normalize_github_remote((remote.stdout or "").strip())

    def _publish_project(self, run: ActiveRun, state: dict[str, Any]) -> dict[str, Any]:
        publish_report: dict[str, Any] = {
            "project_root": str(run.project_root) if run.project_root else "",
            "description_path": "",
            "description_updated": False,
            "description_committed": False,
            "github_checked": False,
            "github_created": False,
            "github_pushed": False,
            "github_url": "",
            "integrate_merged": False,
            "run_status": "UNKNOWN",
            "errors": [],
        }
        if run.project_root is None:
            publish_report["errors"].append("Project root is not set for this run; skipped post-run publishing.")
            return publish_report

        project_root = run.project_root.expanduser()
        run_dir = run.conductor_root / "runs" / run.run_id
        context = _read_json(run_dir / "context.json") or {}
        run_report = self._load_run_report(run_dir)
        artifacts = self._collect_artifacts(run_dir)
        run_status = _resolve_run_status(state, run_report)
        publish_report["run_status"] = run_status

        main_ready = self._ensure_main_checkout(project_root, publish_report)
        if main_ready:
            self._merge_integrate_branch(project_root, run.run_id, context, run_status, publish_report)

        remote_ready = False
        if main_ready:
            remote_ready = self._ensure_github_remote(project_root, publish_report)

        description_path = self._write_project_description(
            project_root=project_root,
            run=run,
            state=state,
            run_status=run_status,
            run_report=run_report,
            github_url=publish_report.get("github_url", ""),
            artifacts=artifacts,
        )
        publish_report["description_path"] = str(description_path)
        publish_report["description_updated"] = True

        if main_ready:
            self._commit_description_update(project_root, description_path, run.run_id, publish_report)
            if remote_ready:
                self._push_main(project_root, publish_report)

        return publish_report

    def _state_age_seconds(self, state_path: Path) -> Optional[float]:
        try:
            mtime = state_path.stat().st_mtime
        except OSError:
            return None
        return time.time() - mtime

    def _read_last_activity_line(self, run: ActiveRun) -> str:
        log_path = run.conductor_root / "runs" / run.run_id / "artifacts" / "logs" / "conductor.log"
        if not log_path.exists():
            return ""
        try:
            with log_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096), os.SEEK_SET)
                chunk = f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        for line in reversed(chunk.splitlines()):
            s = line.strip()
            if s:
                return s[:280]
        return ""

    def _build_heartbeat_text(self, run: ActiveRun, state: dict[str, Any], state_path: Path) -> str:
        return format_heartbeat(
            state,
            last_activity=self._read_last_activity_line(run),
            state_age_seconds=self._state_age_seconds(state_path),
        )

    def _should_send_stuck_alert(self, run: ActiveRun, phase: str, state_path: Path) -> bool:
        if phase == "DONE":
            return False
        threshold = self._stuck_alert_seconds()
        now = time.time()
        phase_age = now - run.last_phase_change_at
        state_age = self._state_age_seconds(state_path) or 0.0
        if phase_age < threshold and state_age < threshold:
            return False
        cooldown = self._stuck_alert_cooldown_seconds()
        if run.last_stuck_alert_at and (now - run.last_stuck_alert_at) < cooldown:
            return False
        run.last_stuck_alert_at = now
        return True

    # ── internal ──

    async def _poll_state(self, run: ActiveRun) -> None:
        """Poll state.json every POLL_INTERVAL_S and notify on phase changes."""
        state_path = run.conductor_root / "runs" / run.run_id / "state.json"
        heartbeat_interval = self._heartbeat_interval_seconds()
        last_heartbeat_at = time.time()

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
                    run.last_phase = str(current_phase)
                    run.last_phase_change_at = time.time()
                    run.last_stuck_alert_at = 0.0
                    if self._store:
                        self._store.update_active_phase(chat_id=run.chat_id, phase=str(current_phase))

                    if current_phase == "DONE":
                        await self._send_completion(run, state_path)
                        break
                    last_heartbeat_at = time.time()
                    continue

                now = time.time()
                if now - last_heartbeat_at >= heartbeat_interval:
                    heartbeat_text = self._build_heartbeat_text(run, state, state_path)
                    await self._bot.send_message(
                        chat_id=run.chat_id,
                        text=heartbeat_text,
                        parse_mode="HTML",
                    )
                    last_heartbeat_at = now

                if self._should_send_stuck_alert(run, str(current_phase), state_path):
                    await self._bot.send_message(
                        chat_id=run.chat_id,
                        text=format_stuck_alert(
                            state,
                            phase_age_seconds=max(0.0, time.time() - run.last_phase_change_at),
                            state_age_seconds=self._state_age_seconds(state_path),
                            last_activity=self._read_last_activity_line(run),
                        ),
                        parse_mode="HTML",
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Poll loop error for run %s", run.run_id)
        finally:
            self._cleanup(run.chat_id)
            await self._start_next_queued_run(run.chat_id)

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

        publish_report = self._publish_project(run, state)
        publish_text = format_publish_report(publish_report)
        await self._bot.send_message(
            chat_id=run.chat_id, text=publish_text, parse_mode="HTML"
        )

        if self._store:
            self._store.record_run_finished(
                run_id=run.run_id,
                chat_id=run.chat_id,
                status=str(publish_report.get("run_status") or "UNKNOWN"),
                phase=str(state.get("phase") or ""),
                started_at=run.started_at,
                finished_at=time.time(),
                project_root=run.project_root,
                state_path=state_path,
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
        if self._store:
            self._store.clear_active_run(chat_id=chat_id)
        if run is None:
            return
        current_task = None
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if run.poll_task and run.poll_task is not current_task and not run.poll_task.done():
            run.poll_task.cancel()
        # Ensure process is terminated
        if run.process.poll() is None:
            run.process.terminate()
