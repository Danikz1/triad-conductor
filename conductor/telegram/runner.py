"""RunnerManager: spawn conductor subprocess, poll state.json, send phase-change updates."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Bot

from .formatting import (
    format_final_report,
    format_heartbeat,
    format_phase_change,
    format_publish_report,
    format_status,
)

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


class RunnerManager:
    """Manages one active conductor run per Telegram chat."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._runs: Dict[int, ActiveRun] = {}  # chat_id -> ActiveRun

    def _heartbeat_interval_seconds(self) -> float:
        raw = os.environ.get("TRIAD_TELEGRAM_HEARTBEAT_SECONDS", "60").strip()
        try:
            value = float(raw)
        except ValueError:
            return 60.0
        if value <= 0:
            return 60.0
        return value

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
            project_root=target_project_root,
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
                    run.last_phase = current_phase

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

        publish_report = self._publish_project(run, state)
        publish_text = format_publish_report(publish_report)
        await self._bot.send_message(
            chat_id=run.chat_id, text=publish_text, parse_mode="HTML"
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
