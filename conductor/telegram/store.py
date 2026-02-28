"""Persistent SQLite store for Telegram bot state (pending tasks, queue, run metadata)."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class QueuedRun:
    queue_id: int
    chat_id: int
    task_text: str
    dry_run: bool
    project_root: Optional[Path]
    config_path: Optional[Path]
    enqueued_at: float


class TelegramStateStore:
    """Simple SQLite-backed state used by the Telegram bot."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_tasks (
                    chat_id INTEGER PRIMARY KEY,
                    task_text TEXT NOT NULL,
                    project_root TEXT,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    task_text TEXT NOT NULL,
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    project_root TEXT,
                    config_path TEXT,
                    enqueued_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS active_runs (
                    chat_id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_file TEXT NOT NULL,
                    project_root TEXT,
                    started_at REAL NOT NULL,
                    last_phase TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_history (
                    run_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT,
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL,
                    project_root TEXT,
                    state_path TEXT
                );
                """
            )

    def set_pending_task(
        self,
        *,
        chat_id: int,
        task_text: str,
        project_root: Optional[Path] = None,
    ) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO pending_tasks(chat_id, task_text, project_root, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    task_text=excluded.task_text,
                    project_root=excluded.project_root,
                    updated_at=excluded.updated_at
                """,
                (chat_id, task_text, str(project_root) if project_root else None, now),
            )

    def get_pending_task(self, *, chat_id: int) -> tuple[Optional[str], Optional[Path]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT task_text, project_root FROM pending_tasks WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return None, None
        root = Path(row["project_root"]) if row["project_root"] else None
        return str(row["task_text"]), root

    def clear_pending_task(self, *, chat_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM pending_tasks WHERE chat_id = ?", (chat_id,))

    def enqueue_run(
        self,
        *,
        chat_id: int,
        task_text: str,
        dry_run: bool,
        project_root: Optional[Path],
        config_path: Optional[Path],
    ) -> int:
        now = time.time()
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO run_queue(chat_id, task_text, dry_run, project_root, config_path, enqueued_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    task_text,
                    1 if dry_run else 0,
                    str(project_root) if project_root else None,
                    str(config_path) if config_path else None,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def queue_depth(self, *, chat_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM run_queue WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def pop_next_run(self, *, chat_id: int) -> Optional[QueuedRun]:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT id, chat_id, task_text, dry_run, project_root, config_path, enqueued_at
                FROM run_queue
                WHERE chat_id = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM run_queue WHERE id = ?", (row["id"],))

        return QueuedRun(
            queue_id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            task_text=str(row["task_text"]),
            dry_run=bool(row["dry_run"]),
            project_root=Path(row["project_root"]) if row["project_root"] else None,
            config_path=Path(row["config_path"]) if row["config_path"] else None,
            enqueued_at=float(row["enqueued_at"]),
        )

    def register_active_run(
        self,
        *,
        chat_id: int,
        run_id: str,
        task_file: Path,
        project_root: Optional[Path],
        last_phase: str,
    ) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO active_runs(chat_id, run_id, task_file, project_root, started_at, last_phase)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    task_file=excluded.task_file,
                    project_root=excluded.project_root,
                    started_at=excluded.started_at,
                    last_phase=excluded.last_phase
                """,
                (
                    chat_id,
                    run_id,
                    str(task_file),
                    str(project_root) if project_root else None,
                    now,
                    last_phase,
                ),
            )

    def update_active_phase(self, *, chat_id: int, phase: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE active_runs SET last_phase = ? WHERE chat_id = ?",
                (phase, chat_id),
            )

    def clear_active_run(self, *, chat_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM active_runs WHERE chat_id = ?", (chat_id,))

    def get_active_run(self, *, chat_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT run_id, task_file, project_root, started_at, last_phase
                FROM active_runs
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "task_file": str(row["task_file"]),
            "project_root": str(row["project_root"]) if row["project_root"] else None,
            "started_at": float(row["started_at"]),
            "last_phase": str(row["last_phase"]),
        }

    def record_run_finished(
        self,
        *,
        run_id: str,
        chat_id: int,
        status: str,
        phase: str,
        started_at: float,
        finished_at: float,
        project_root: Optional[Path],
        state_path: Path,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO run_history(
                    run_id, chat_id, status, phase, started_at, finished_at, project_root, state_path
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    chat_id,
                    status,
                    phase,
                    started_at,
                    finished_at,
                    str(project_root) if project_root else None,
                    str(state_path),
                ),
            )

    def recent_runs(self, *, chat_id: int, limit: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT run_id, status, phase, started_at, finished_at, project_root, state_path
                FROM run_history
                WHERE chat_id = ?
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()

        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "run_id": str(row["run_id"]),
                    "status": str(row["status"]),
                    "phase": str(row["phase"]) if row["phase"] else "",
                    "started_at": float(row["started_at"]),
                    "finished_at": float(row["finished_at"]),
                    "project_root": str(row["project_root"]) if row["project_root"] else "",
                    "state_path": str(row["state_path"]) if row["state_path"] else "",
                }
            )
        return out

