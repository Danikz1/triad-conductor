"""Build and configure the Telegram bot application."""

from __future__ import annotations

import logging
import os

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from .handlers import (
    file_message,
    help_cmd,
    run_cmd,
    start_cmd,
    status_cmd,
    stop_cmd,
    text_message,
)
from .runner import RunnerManager

logger = logging.getLogger(__name__)


def create_application():
    """Build a telegram.ext.Application with all handlers registered."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to your .env file or export it as an environment variable."
        )

    app = ApplicationBuilder().token(token).build()

    # Inject RunnerManager into bot_data so handlers can access it
    app.bot_data["runner"] = RunnerManager(bot=app.bot)

    # Command handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    # Message handlers (order matters: documents before text)
    app.add_handler(MessageHandler(filters.Document.ALL, file_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    return app
