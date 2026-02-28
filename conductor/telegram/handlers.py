"""Telegram command and message handlers for triad-conductor bot."""

from __future__ import annotations

import datetime as dt
import html
import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .runner import RunnerManager

logger = logging.getLogger(__name__)

CONDUCTOR_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECTS_HOME = Path("/Users/daniyarserikson/Projects")

# ── Access control ──

def _allowed_user_ids() -> Optional[set[int]]:
    """Parse TELEGRAM_ALLOWED_USERS env var into a set of user IDs, or None (allow all)."""
    raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
    if not raw:
        return None
    try:
        return {int(uid.strip()) for uid in raw.split(",") if uid.strip()}
    except ValueError:
        logger.error("Invalid TELEGRAM_ALLOWED_USERS value: %r", raw)
        return set()  # empty set = deny all


def _is_authorized(update: Update) -> bool:
    allowed = _allowed_user_ids()
    if allowed is None:
        return True  # no restriction configured
    user = update.effective_user
    if user is None:
        return False
    return user.id in allowed


# ── Pending task storage (per-chat in bot_data) ──

def _get_pending_task(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.chat_data.get("pending_task")


def _set_pending_task(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    context.chat_data["pending_task"] = text


def _clear_pending_task(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.pop("pending_task", None)
    _clear_pending_project_root(context)


def _get_pending_project_root(context: ContextTypes.DEFAULT_TYPE) -> Optional[Path]:
    raw = context.chat_data.get("pending_project_root")
    if not raw:
        return None
    return Path(raw)


def _set_pending_project_root(context: ContextTypes.DEFAULT_TYPE, path: Path) -> None:
    context.chat_data["pending_project_root"] = str(path)


def _clear_pending_project_root(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.pop("pending_project_root", None)


def _help_message() -> str:
    return (
        "<b>Triad Conductor Bot</b>\n\n"
        "<b>Step 1: Send your project description</b>\n"
        "Send plain text or upload a <code>.md</code> file.\n\n"
        "<b>Step 2: Choose path</b>\n"
        "/consilium (alias: /refine) — evaluate/refine the description first\n"
        "/run (alias: /develop) — start development immediately\n\n"
        "<b>Development controls</b>\n"
        "/run [--dry-run] [--project-root /path]\n"
        "/status\n"
        "/stop\n\n"
        "<b>Consilium review controls</b>\n"
        "/approve\n"
        "/reject\n"
        "/history\n\n"
        "/help — show this message"
    )


def _next_step_prompt(preview: str, source_name: Optional[str] = None) -> str:
    header = (
        f"\U0001f4ce Task stored from <code>{source_name}</code>."
        if source_name
        else "\U0001f4dd Task stored."
    )
    return (
        f"{header}\nPreview:\n<pre>{preview}</pre>\n\n"
        "Choose next step:\n"
        "1) <b>Consilium evaluate/refine</b>: /consilium (or /refine)\n"
        "2) <b>Develop now</b>: /run (or /develop)\n\n"
        "Send a new message/file anytime to replace the pending task."
    )


def _sanitize_project_dir_name(name: str) -> str:
    cleaned = re.sub(r"[/\\\\]+", "-", (name or "").strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip("-")
    if cleaned:
        return cleaned
    ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
    return f"project_{ts}"


def _extract_project_name_from_markdown(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Untitled Project"


def _prepare_project_root(project_name: str, task_text: str) -> Path:
    projects_home = Path(os.environ.get("TRIAD_PROJECTS_HOME", str(DEFAULT_PROJECTS_HOME))).expanduser()
    projects_home.mkdir(parents=True, exist_ok=True)
    project_dir_name = _sanitize_project_dir_name(project_name)
    project_root = projects_home / project_dir_name
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "project.md").write_text(task_text, encoding="utf-8")
    return project_root


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _ensure_git_repo(project_root: Path) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    inside_repo = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )
    if inside_repo.returncode != 0:
        _run_git(["init", "-b", "main"], cwd=project_root, check=True)

    has_main = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )
    if has_main.returncode != 0:
        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        branch_name = (current_branch.stdout or "").strip()
        if branch_name and branch_name != "HEAD":
            subprocess.run(
                ["git", "branch", "main", branch_name],
                cwd=str(project_root),
                text=True,
                capture_output=True,
            )

    has_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root),
        text=True,
        capture_output=True,
    )
    if has_head.returncode != 0:
        has_user_email = subprocess.run(
            ["git", "config", "user.email"],
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        if has_user_email.returncode != 0:
            _run_git(["config", "user.email", "triad@local"], cwd=project_root, check=True)

        has_user_name = subprocess.run(
            ["git", "config", "user.name"],
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        if has_user_name.returncode != 0:
            _run_git(["config", "user.name", "Triad Conductor"], cwd=project_root, check=True)

        _run_git(["add", "-A"], cwd=project_root, check=True)
        _run_git(
            ["commit", "--allow-empty", "-m", "Initial commit for Triad Conductor run"],
            cwd=project_root,
            check=True,
        )


# ── Handlers ──

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(_help_message(), parse_mode="HTML")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help command — same as /start."""
    await start_cmd(update, context)


async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/run [--dry-run] [--project-root /path] — launch conductor."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    runner: RunnerManager = context.bot_data["runner"]
    chat_id = update.effective_chat.id

    if runner.has_active_run(chat_id):
        await update.message.reply_text("A run is already active. Use /stop first.")
        return

    task_text = _get_pending_task(context)
    if not task_text:
        await update.message.reply_text(
            "No task set. Send text or upload a <code>.md</code> file first.",
            parse_mode="HTML",
        )
        return

    # Parse flags from command args
    args = context.args or []
    dry_run = "--dry-run" in args
    project_root = None
    if "--project-root" in args:
        idx = args.index("--project-root")
        if idx + 1 < len(args):
            project_root = Path(args[idx + 1])
    else:
        project_root = _get_pending_project_root(context)

    if project_root is not None:
        try:
            project_root = project_root.expanduser()
            project_root.mkdir(parents=True, exist_ok=True)
            _ensure_git_repo(project_root)
        except Exception as exc:
            logger.exception("Failed to prepare project root %s", project_root)
            await update.message.reply_text(f"Failed to prepare project root: {exc}")
            return

    try:
        run_id = await runner.start_run(
            chat_id=chat_id,
            task_text=task_text,
            dry_run=dry_run,
            project_root=project_root,
        )
    except Exception as exc:
        logger.exception("Failed to start run")
        await update.message.reply_text(f"Failed to start run: {exc}")
        return

    _clear_pending_task(context)
    mode = " (dry-run)" if dry_run else ""
    project_line = f"\nProject root: <code>{project_root}</code>" if project_root else ""
    monitor_cmd = runner.local_monitor_command(run_id, project_root)
    await update.message.reply_text(
        f"\U0001f680 Run <code>{run_id}</code> started{mode}.\n"
        f"I'll send phase transition updates as the conductor progresses.{project_line}\n"
        f"Local live monitor command:\n<code>{html.escape(monitor_cmd)}</code>",
        parse_mode="HTML",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — show current run state."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    runner: RunnerManager = context.bot_data["runner"]
    chat_id = update.effective_chat.id

    if not runner.has_active_run(chat_id):
        await update.message.reply_text("No active run.")
        return

    status = runner.get_status(chat_id)
    if status:
        await update.message.reply_text(status, parse_mode="HTML")
    else:
        await update.message.reply_text("Run is active but state.json is not available yet.")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stop — send SIGINT to the conductor process."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    runner: RunnerManager = context.bot_data["runner"]
    chat_id = update.effective_chat.id

    stopped = await runner.stop_run(chat_id)
    if stopped:
        await update.message.reply_text(
            "\u23f9\ufe0f Stop signal sent. The conductor will shut down cleanly."
        )
    else:
        await update.message.reply_text("No active run to stop.")


# ── Refiner engine helpers ──

def _get_refiner(context: ContextTypes.DEFAULT_TYPE):
    """Get the active RefinerEngine from chat_data, or None."""
    return context.chat_data.get("refiner_engine")


def _set_refiner(context: ContextTypes.DEFAULT_TYPE, engine) -> None:
    context.chat_data["refiner_engine"] = engine


def _clear_refiner(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data.pop("refiner_engine", None)


# ── Triad Architect handlers ──

async def refine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/refine — start the Triad Architect refinement loop on the pending task."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    if _get_refiner(context) is not None:
        await update.message.reply_text(
            "A refinement session is already active.\n"
            "Use /approve to accept, /reject to discard, or send feedback."
        )
        return

    task_text = _get_pending_task(context)
    if not task_text:
        await update.message.reply_text(
            "No idea set. Send text or upload a .md file first, then /consilium (or /refine).",
        )
        return

    # Parse optional flags
    args = context.args or []
    dry_run = "--dry-run" in args
    constraints = []
    if "--constraint" in args:
        idx = args.index("--constraint")
        if idx + 1 < len(args):
            constraints = [args[idx + 1]]

    # Create refiner engine
    from conductor.config import load_config
    from conductor.refiner.engine import RefinerEngine

    config_path = CONDUCTOR_ROOT / "config.yaml"
    if config_path.exists():
        config = load_config(config_path)
    else:
        from conductor.config import Config
        config = Config()

    run_id = f"refine-{uuid.uuid4().hex[:8]}"
    run_dir = CONDUCTOR_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    engine = RefinerEngine(
        run_id=run_id,
        run_dir=run_dir,
        config=config,
        idea_text=task_text,
        constraints=constraints,
        dry_run=dry_run,
    )
    _set_refiner(context, engine)

    await update.message.reply_text(
        f"<b>Triad Architect</b> started (run: <code>{run_id}</code>)\n"
        f"Running INTAKE + EXPAND + SCORE + SYNTHESIZE...\n"
        f"This may take a moment.",
        parse_mode="HTML",
    )

    # Run the full pipeline: intake → expand+score → synthesize
    try:
        engine.run_intake()

        expand_result = engine.run_expand_and_score()
        if expand_result.get("blocked"):
            await update.message.reply_text(
                f"Expansion blocked: {expand_result.get('reason', 'unknown')}\n"
                f"Session cleared. Fix the issue and /refine again."
            )
            _clear_refiner(context)
            return

        synth_result = engine.run_synthesize()
        if synth_result.get("blocked"):
            await update.message.reply_text(
                f"Synthesis blocked: {synth_result.get('reason', 'unknown')}\n"
                f"Session cleared. Fix the issue and /refine again."
            )
            _clear_refiner(context)
            return

        # Send the refined spec for review
        from conductor.refiner.formatting import format_refined_spec
        spec_msg = format_refined_spec(synth_result["refined_spec"])
        await update.message.reply_text(spec_msg, parse_mode="HTML")

        cost_warning = engine.check_cost_cap()
        if cost_warning:
            await update.message.reply_text(f"Warning: {cost_warning}")

    except Exception as exc:
        logger.exception("Refine pipeline failed")
        await update.message.reply_text(f"Refinement failed: {exc}")
        _clear_refiner(context)


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/approve — approve the current refined spec and trigger handoff."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    engine = _get_refiner(context)
    if engine is None:
        await update.message.reply_text("No active refinement session. Use /refine first.")
        return

    if engine.refined_spec is None:
        await update.message.reply_text("No spec to approve yet. Wait for synthesis to complete.")
        return

    try:
        user_id = update.effective_user.id if update.effective_user else 0
        config_path = CONDUCTOR_ROOT / "config.yaml"

        handoff_result = engine.run_handoff(
            user_id=user_id,
            base_config_path=config_path,
        )

        from conductor.refiner.formatting import format_approval_confirmation
        msg = format_approval_confirmation(engine.refined_spec)
        await update.message.reply_text(msg, parse_mode="HTML")

        # Send the approved spec as a file
        task_path = handoff_result.get("task_path")
        if task_path and Path(task_path).exists():
            await update.message.reply_document(
                document=Path(task_path),
                filename="approved_spec.md",
                caption="Approved spec ready for /run",
            )

        # Store the approved task as pending so /run can pick it up
        approved_task = Path(task_path).read_text(encoding="utf-8") if task_path else ""
        if approved_task:
            project_name = (
                (engine.refined_spec or {}).get("project_name")
                or _extract_project_name_from_markdown(approved_task)
            )
            project_root = _prepare_project_root(project_name, approved_task)
            _ensure_git_repo(project_root)
            _set_pending_task(context, approved_task)
            _set_pending_project_root(context, project_root)
            await update.message.reply_text(
                f"Project folder prepared: <code>{project_root}</code>\n"
                f"Run /run to start development there.",
                parse_mode="HTML",
            )

        _clear_refiner(context)

    except Exception as exc:
        logger.exception("Handoff failed")
        await update.message.reply_text(f"Handoff failed: {exc}")


async def reject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reject — reject the current spec and end refinement."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    engine = _get_refiner(context)
    if engine is None:
        await update.message.reply_text("No active refinement session.")
        return

    engine.handle_review("reject")
    _clear_refiner(context)
    await update.message.reply_text("Refinement session rejected and cleared.")


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/history — show feedback history for the current refinement."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    engine = _get_refiner(context)
    if engine is None:
        await update.message.reply_text("No active refinement session.")
        return

    if not engine.feedback_history:
        await update.message.reply_text("No feedback recorded yet.")
        return

    lines = [f"<b>Feedback History (v{engine.version})</b>", ""]
    for i, fb in enumerate(engine.feedback_history, 1):
        lines.append(f"{i}. {fb}")

    from conductor.refiner.formatting import format_refiner_status
    status_line = format_refiner_status(
        {"approx_cost_usd": engine.state.approx_cost_usd, "tool_calls_used": engine.state.tool_calls_used},
        engine.state.phase,
        engine.version,
    )
    lines.append("")
    lines.append(status_line)

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Text / file message handlers ──

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages: route to refiner if active, otherwise store as pending task."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    text = update.message.text.strip()
    if not text:
        return

    # If a refiner session is active, treat text as review feedback
    engine = _get_refiner(context)
    if engine is not None and engine.refined_spec is not None:
        try:
            result = engine.handle_review(text)
            action = result.get("action")

            if action == "approved":
                # User typed "approve" — delegate to approve flow
                await approve_cmd(update, context)
                return

            if action == "rejected":
                _clear_refiner(context)
                await update.message.reply_text("Refinement session rejected and cleared.")
                return

            if action == "max_iterations":
                await update.message.reply_text(result["message"])
                return

            if action == "revise":
                needs_re_expand = result.get("needs_re_expand", False)
                phase_label = "EXPAND + SCORE + SYNTHESIZE" if needs_re_expand else "SYNTHESIZE"
                await update.message.reply_text(
                    f"Feedback received. Re-running {phase_label}..."
                )

                if needs_re_expand:
                    expand_result = engine.run_expand_and_score()
                    if expand_result.get("blocked"):
                        await update.message.reply_text(
                            f"Re-expansion blocked: {expand_result.get('reason', 'unknown')}"
                        )
                        return

                synth_result = engine.run_synthesize()
                if synth_result.get("blocked"):
                    await update.message.reply_text(
                        f"Re-synthesis blocked: {synth_result.get('reason', 'unknown')}"
                    )
                    return

                from conductor.refiner.formatting import format_refined_spec
                spec_msg = format_refined_spec(synth_result["refined_spec"])
                await update.message.reply_text(spec_msg, parse_mode="HTML")

                cost_warning = engine.check_cost_cap()
                if cost_warning:
                    await update.message.reply_text(f"Warning: {cost_warning}")
                return

        except Exception as exc:
            logger.exception("Review handling failed")
            await update.message.reply_text(f"Error processing feedback: {exc}")
            return

    # No active refiner — store as pending task
    _set_pending_task(context, text)
    _clear_pending_project_root(context)
    preview = text[:100] + ("..." if len(text) > 100 else "")
    await update.message.reply_text(_next_step_prompt(preview), parse_mode="HTML")


async def file_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded .md files as task input."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    doc = update.message.document
    if doc is None:
        return

    name = doc.file_name or ""
    if not name.endswith(".md"):
        await update.message.reply_text("Only <code>.md</code> files are accepted.", parse_mode="HTML")
        return

    tg_file = await doc.get_file()
    content_bytes = await tg_file.download_as_bytearray()
    text = content_bytes.decode("utf-8", errors="replace").strip()

    if not text:
        await update.message.reply_text("The uploaded file is empty.")
        return

    _set_pending_task(context, text)
    _clear_pending_project_root(context)
    preview = text[:100] + ("..." if len(text) > 100 else "")
    await update.message.reply_text(_next_step_prompt(preview, source_name=name), parse_mode="HTML")
