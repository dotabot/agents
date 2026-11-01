from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import event, transaction
from .tasks import Task, TaskSource

def eligible(task: Task, worker_id: str, default_worker: str, paid_workers: tuple[str, ...] = ("codex", "cursor")) -> bool:
    if task.pin == "cloud": return False
    target = task.pin or default_worker
    return target == worker_id

def cool_down(db: sqlite3.Connection, worker_id: str, task_id: int | None, resets_at: datetime | None = None, hours: float = 3) -> datetime:
    until = resets_at or (datetime.now(timezone.utc) + timedelta(hours=hours))
    db.execute("UPDATE workers SET status='cooling', cooling_until=? WHERE id=?", (until.isoformat(), worker_id))
    db.execute("INSERT INTO usage_events(provider_id,task_id,limit_hit,ts,source) VALUES(?,?,1,?,'estimated')", (worker_id, task_id, datetime.now(timezone.utc).isoformat()))
    event(db, "limit_hit", worker_id=worker_id, task_id=task_id, payload={"cooling_until": until.isoformat()})
    return until

def refresh_cooldowns(db: sqlite3.Connection, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    db.execute("UPDATE workers SET status='idle', cooling_until=NULL WHERE status='cooling' AND cooling_until <= ?", (now.isoformat(),))

def claim_next(db: sqlite3.Connection, tasks: list[Task], source: TaskSource, worker_id: str, worktree: Path, default_worker: str = "codex", repo: str = "", base_branch: str = "main") -> Task | None:
    refresh_cooldowns(db)
    with transaction(db):
        row = db.execute("SELECT status,current_task_id FROM workers WHERE id=?", (worker_id,)).fetchone()
        if row is None or row["status"] != "idle" or row["current_task_id"] is not None: return None
        busy = {r[0] for r in db.execute("SELECT issue_number FROM tasks WHERE state IN ('claimed','running')")}
        task = next((t for t in sorted(tasks, key=lambda t: (t.created_at or f"~{t.issue_number:020d}", t.issue_number)) if t.issue_number not in busy and "dot:queue" in t.labels and eligible(t, worker_id, default_worker)), None)
        if task is None: return None
        branch = f"{worker_id}/issue-{task.issue_number}"
        cursor = db.execute("INSERT INTO tasks(repo,issue_number,title,labels,pin,state,worker_id,branch,claimed_at) VALUES(?,?,?,?,?,'claimed',?,?,?) ON CONFLICT(repo,issue_number) DO UPDATE SET state='claimed',worker_id=excluded.worker_id,branch=excluded.branch,claimed_at=excluded.claimed_at WHERE tasks.state IN ('queued','blocked') RETURNING id", (repo, task.issue_number, task.title, ",".join(task.labels), task.pin, worker_id, branch, datetime.now(timezone.utc).isoformat()))
        claimed = cursor.fetchone()
        if claimed is None: return None
        task_id = claimed[0]
        db.execute("UPDATE workers SET status='running',current_task_id=?,worktree=?,started_at=? WHERE id=?", (task_id, str(worktree), datetime.now(timezone.utc).isoformat(), worker_id))
        event(db, "task_claimed", worker_id=worker_id, task_id=task_id, payload={"issue": task.issue_number, "branch": branch})
    try:
        source.set_labels(task, ("dot:wip",), ("dot:queue",))
    except Exception:
        with transaction(db):
            db.execute("UPDATE tasks SET state='queued',worker_id=NULL,branch=NULL,claimed_at=NULL WHERE repo=? AND issue_number=? AND state='claimed'", (repo, task.issue_number))
            db.execute("UPDATE workers SET status='idle',current_task_id=NULL WHERE id=? AND current_task_id=?", (worker_id, task_id))
            event(db, "claim_rolled_back", worker_id=worker_id, task_id=task_id)
        raise
    return task
