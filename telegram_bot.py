#!/usr/bin/env python3
"""Entry point for the Triad Conductor Telegram bot."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Load .env before anything reads environment variables
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from conductor.telegram.bot import create_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-30s  %(levelname)-7s  %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting Triad Conductor Telegram bot…")
    try:
        app = create_application()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
