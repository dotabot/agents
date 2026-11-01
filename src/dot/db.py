from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY, kind TEXT NOT NULL, binary TEXT, version TEXT, logged_in INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, max_size TEXT NOT NULL DEFAULT 'L');
CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, provider_id TEXT NOT NULL REFERENCES providers(id), worktree TEXT, status TEXT NOT NULL DEFAULT 'idle', current_task_id INTEGER, session_id TEXT, pid INTEGER, started_at TEXT, last_activity_at TEXT, cooling_until TEXT);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, repo TEXT NOT NULL, issue_number INTEGER NOT NULL, title TEXT NOT NULL, labels TEXT NOT NULL, size TEXT NOT NULL DEFAULT 'M', pin TEXT, state TEXT NOT NULL DEFAULT 'queued', worker_id TEXT, branch TEXT, pr_number INTEGER, rework_pr INTEGER, head_sha_at_claim TEXT, brief_path TEXT, claimed_at TEXT, done_at TEXT, UNIQUE(repo, issue_number));
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, worker_id TEXT NOT NULL REFERENCES workers(id), task_id INTEGER REFERENCES tasks(id), provider_session_id TEXT, kind TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, exit INTEGER);
CREATE TABLE IF NOT EXISTS usage_windows(provider_id TEXT NOT NULL REFERENCES providers(id), window TEXT NOT NULL, used_fraction REAL NOT NULL, resets_at TEXT, source TEXT NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY(provider_id, window));
CREATE TABLE IF NOT EXISTS usage_events(id INTEGER PRIMARY KEY, provider_id TEXT NOT NULL REFERENCES providers(id), task_id INTEGER REFERENCES tasks(id), tokens_in INTEGER, tokens_out INTEGER, wall_s REAL, limit_hit INTEGER NOT NULL DEFAULT 0, ts TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'estimated');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, task_id INTEGER, worker_id TEXT, payload_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS tasks_queue_order ON tasks(state, issue_number);
CREATE INDEX IF NOT EXISTS workers_claim ON workers(status, cooling_until);
"""

def connect(home: Path) -> sqlite3.Connection:
    home.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home / "state.db", timeout=30, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db

@contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()

def event(db: sqlite3.Connection, kind: str, *, actor: str = "dot", task_id: int | None = None, worker_id: str | None = None, payload: dict | None = None) -> None:
    db.execute("INSERT INTO events(ts,actor,kind,task_id,worker_id,payload_json) VALUES(?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), actor, kind, task_id, worker_id, json.dumps(payload or {})))
