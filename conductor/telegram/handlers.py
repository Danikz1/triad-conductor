"""Telegram command and message handlers for triad-conductor bot."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from .runner import RunnerManager

logger = logging.getLogger(__name__)

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
        "<b>Commands:</b>\n"
        "/run [--dry-run] [--project-root /path] — start a run\n"
        "/status — show current run state\n"
        "/stop — cancel the active run\n"
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


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store a plain-text message as the pending task."""
    if not _is_authorized(update):
        await update.message.reply_text("Access denied.")
        return

    text = update.message.text.strip()
    if not text:
        return

    _set_pending_task(context, text)
    preview = text[:100] + ("..." if len(text) > 100 else "")
    await update.message.reply_text(
        f"\U0001f4dd Task stored. Preview:\n<pre>{preview}</pre>\n\n"
        f"Send /run to launch, or send another message to replace.",
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
        f"Send /run to launch, or upload another file to replace.",
        parse_mode="HTML",
    )
