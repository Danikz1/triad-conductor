"""Build and configure the Telegram bot application."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from .handlers import (
    approve_cmd,
    file_message,
    health_cmd,
    help_cmd,
    history_cmd,
    logs_cmd,
    refine_cmd,
    reject_cmd,
    run_cmd,
    start_cmd,
    status_cmd,
    stop_cmd,
    text_message,
)
from .runner import RunnerManager
from .store import TelegramStateStore

logger = logging.getLogger(__name__)


async def _post_init_set_commands(app) -> None:
    """Populate Telegram command menu with the full bot command set."""
    commands = [
        BotCommand("start", "Show getting-started guide"),
        BotCommand("help", "Show all commands"),
        BotCommand("consilium", "Evaluate/refine pending project description"),
        BotCommand("refine", "Alias of /consilium"),
        BotCommand("run", "Start development run"),
        BotCommand("develop", "Alias of /run"),
        BotCommand("status", "Show active run status"),
        BotCommand("health", "Show run liveness details"),
        BotCommand("logs", "Show recent run logs"),
        BotCommand("stop", "Stop active run"),
        BotCommand("approve", "Approve refined spec"),
        BotCommand("reject", "Reject refined spec"),
        BotCommand("history", "Show refinement feedback history"),
    ]
    await app.bot.set_my_commands(commands)


def create_application():
    """Build a telegram.ext.Application with all handlers registered."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to your .env file or export it as an environment variable."
        )

    app = ApplicationBuilder().token(token).post_init(_post_init_set_commands).build()

    conductor_root = Path(__file__).resolve().parents[2]
    state_db = Path(
        os.environ.get(
            "TRIAD_TELEGRAM_STATE_DB",
            str(conductor_root / "runs" / "telegram_state.db"),
        )
    ).expanduser()
    store = TelegramStateStore(state_db)

    # Inject RunnerManager into bot_data so handlers can access it
    app.bot_data["store"] = store
    app.bot_data["runner"] = RunnerManager(bot=app.bot, store=store)

    # Command handlers — development
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("develop", run_cmd))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    # Command handlers — Triad Architect (idea refinement)
    app.add_handler(CommandHandler("consilium", refine_cmd))
    app.add_handler(CommandHandler("refine", refine_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("reject", reject_cmd))
    app.add_handler(CommandHandler("history", history_cmd))

    # Message handlers (order matters: documents before text)
    app.add_handler(MessageHandler(filters.Document.ALL, file_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    return app
