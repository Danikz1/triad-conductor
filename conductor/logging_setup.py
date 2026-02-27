"""Logging configuration with file + console handlers."""

from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(run_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure root logger with console and file handlers.
    Returns the root logger."""
    log_dir = run_dir / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "conductor.log"

    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

    # File handler
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return root
