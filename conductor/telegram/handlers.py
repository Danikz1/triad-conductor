"""Telegram command and message handlers for triad-conductor bot."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .runner import RunnerManager

logger = logging.getLogger(__name__)

CONDUCTOR_ROOT = Path(__file__).resolve().parents[2]

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


# ── Handlers ──

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start command."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "<b>Triad Conductor Bot</b>\n\n"
        "Send me a task description (text or <code>.md</code> file), then use /run to launch.\n\n"
        "<b>Development:</b>\n"
        "/run [--dry-run] [--project-root /path] — start a conductor run\n"
        "/status — show current run state\n"
        "/stop — cancel the active run\n\n"
        "<b>Triad Architect (idea refinement):</b>\n"
        "/refine — start refining the pending task idea\n"
        "/approve — approve the current refined spec\n"
        "/reject — reject and stop refinement\n"
        "/history — show refinement feedback history\n"
        "(or just reply with feedback / D1: answer / A1: correction)\n\n"
        "/help — show this message",
        parse_mode="HTML",
    )


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
            "No task set. Send me a text message or upload a <code>.md</code> file first.",
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
    await update.message.reply_text(
        f"\U0001f680 Run <code>{run_id}</code> started{mode}.\n"
        f"I'll send phase transition updates as the conductor progresses.",
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
            "No idea set. Send me a text message first, then /refine.",
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
            _set_pending_task(context, approved_task)

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
    preview = text[:100] + ("..." if len(text) > 100 else "")
    await update.message.reply_text(
        f"\U0001f4dd Task stored. Preview:\n<pre>{preview}</pre>\n\n"
        f"Send /run to launch, /refine to refine with Triad Architect, or send another message to replace.",
        parse_mode="HTML",
    )


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
    preview = text[:100] + ("..." if len(text) > 100 else "")
    await update.message.reply_text(
        f"\U0001f4ce Task stored from <code>{name}</code>. Preview:\n<pre>{preview}</pre>\n\n"
        f"Send /run to launch, /refine to refine with Triad Architect, or upload another file to replace.",
        parse_mode="HTML",
    )
