from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, event
from .providers import PROVIDERS, OllamaProvider
from .router import claim_next, cool_down, refresh_cooldowns
from .tasks import GitHubTaskSource, Task, TaskSource

def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

def ensure_worktree(repo: Path, home: Path, worker_id: str, issue_number: int, base_branch: str) -> tuple[Path, str]:
    branch = f"{worker_id}/issue-{issue_number}"
    worktree = home / "worktrees" / worker_id
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if not worktree.exists():
        branches = _git("branch", "--list", branch, cwd=repo)
        if branches:
            _git("worktree", "add", str(worktree), branch, cwd=repo)
        else:
            _git("worktree", "add", "-b", branch, str(worktree), base_branch, cwd=repo)
    else:
        current_branch = _git("branch", "--show-current", cwd=worktree)
        if current_branch != branch:
            branches = _git("branch", "--list", branch, cwd=repo)
            if branches:
                _git("switch", branch, cwd=worktree)
            else:
                _git("switch", "-c", branch, base_branch, cwd=worktree)
    return worktree, branch

def _run_local(provider: OllamaProvider, task: str, worktree: Path, model: str = "qwen3-coder:30b") -> tuple[int, str]:
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": f"Work on this task in {worktree}: {task}"}], "stream": False}).encode()
    request = urllib.request.Request(provider.endpoint, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read())
        return 0, body.get("message", {}).get("content", "")
    except Exception as exc:
        return 1, str(exc)

def execute_task(db, home: Path, repo: Path, task: Task, worker_id: str, worktree: Path, branch: str, source: TaskSource, cooldown_hours: float = 3) -> int:
    provider = PROVIDERS[worker_id]
    issue_id = db.execute("SELECT id FROM tasks WHERE repo=? AND issue_number=?", (str(repo), task.issue_number)).fetchone()[0]
    db.execute("UPDATE tasks SET state='running' WHERE id=?", (issue_id,))
    prompt = f"GitHub issue #{task.issue_number}: {task.title}\nContinue from the current git status."
    if isinstance(provider, OllamaProvider):
        status, output = _run_local(provider, prompt, worktree)
    else:
        command = provider.run(prompt, worktree)
        result = subprocess.run(command.argv, cwd=command.cwd, capture_output=True, text=True)
        status, output = result.returncode, result.stdout + "\n" + result.stderr
    if provider.detects_limit(output):
        cool_down(db, worker_id, issue_id, hours=cooldown_hours)
        task_size = db.execute("SELECT size FROM tasks WHERE id=?", (issue_id,)).fetchone()[0]
        next_worker = next((name for name in ("codex", "cursor") if name != worker_id and db.execute("SELECT status FROM workers WHERE id=?", (name,)).fetchone() and db.execute("SELECT status FROM workers WHERE id=?", (name,)).fetchone()[0] == "idle"), None)
        if next_worker is None and task_size in {"S", "M"}:
            local = db.execute("SELECT status FROM workers WHERE id='local'").fetchone()
            if local and local[0] == "idle": next_worker = "local"
        if next_worker:
            db.execute("UPDATE workers SET current_task_id=NULL WHERE id=?", (worker_id,))
            db.execute("UPDATE workers SET status='running',current_task_id=?,worktree=?,started_at=? WHERE id=?", (issue_id, str(worktree), datetime.now(timezone.utc).isoformat(), next_worker))
            db.execute("UPDATE tasks SET worker_id=? WHERE id=?", (next_worker, issue_id))
            handover_prompt = f"Continue GitHub issue #{task.issue_number} from the current git status. Another worker reached its usage limit."
            next_provider = PROVIDERS[next_worker]
            if isinstance(next_provider, OllamaProvider):
                status, output = _run_local(next_provider, handover_prompt, worktree)
            else:
                command = next_provider.run(handover_prompt, worktree)
                result = subprocess.run(command.argv, cwd=worktree, capture_output=True, text=True)
                status, output = result.returncode, result.stdout + "\n" + result.stderr
            db.execute("INSERT INTO usage_events(provider_id,task_id,wall_s,limit_hit,ts,source) VALUES(?,?,?,0,?,'estimated')", (next_worker, issue_id, 0, datetime.now(timezone.utc).isoformat()))
            db.execute("UPDATE workers SET status='idle',current_task_id=NULL,last_activity_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), next_worker))
            worker_id = next_worker
    db.execute("INSERT INTO usage_events(provider_id,task_id,wall_s,limit_hit,ts,source) VALUES(?,?,?,0,?,'estimated')", (worker_id, issue_id, 0, datetime.now(timezone.utc).isoformat()))
    db.execute("UPDATE workers SET status='idle',current_task_id=NULL,last_activity_at=? WHERE id=? AND status!='cooling'", (datetime.now(timezone.utc).isoformat(), worker_id))
    event(db, "task_finished" if status == 0 else "task_failed", worker_id=worker_id, task_id=issue_id, payload={"exit": status, "branch": branch})
    return status

def run_once(home: Path, source: TaskSource, *, default_worker: str, repo: Path, base_branch: str, cooldown_hours: float = 3, worker_ids: tuple[str, ...] = ("codex", "cursor", "local")) -> Task | None:
    db = connect(home)
    for worker_id in worker_ids:
        row = db.execute("SELECT status,current_task_id FROM workers WHERE id=?", (worker_id,)).fetchone()
        if row is None or row["status"] != "idle" or row["current_task_id"] is not None: continue
        task = claim_next(db, source.list_queued(), source, worker_id, home / "worktrees" / worker_id, default_worker, str(repo), base_branch)
        if task:
            worktree, branch = ensure_worktree(repo, home, worker_id, task.issue_number, base_branch)
            db.execute("UPDATE workers SET worktree=? WHERE id=?", (str(worktree), worker_id))
            execute_task(db, home, repo, task, worker_id, worktree, branch, source, cooldown_hours)
            return task
    return None

def resume_paused_task(home: Path, config: dict, db, source: TaskSource) -> bool:
    row = db.execute("SELECT t.*,w.id AS worker_id,w.worktree,w.session_id FROM tasks t JOIN workers w ON w.id=t.worker_id WHERE t.state='claimed' AND w.status='paused' ORDER BY t.claimed_at LIMIT 1").fetchone()
    if row is None:
        return False
    repo = Path(config.get("repo", os.getcwd())).expanduser()
    worktree = Path(row["worktree"]) if row["worktree"] else home / "worktrees" / row["worker_id"]
    task = Task(row["issue_number"], row["title"], tuple(filter(None, row["labels"].split(","))))
    branch = row["branch"] or f"{row['worker_id']}/issue-{row['issue_number']}"
    db.execute("UPDATE workers SET status='running',current_task_id=?,started_at=? WHERE id=?", (row["id"], datetime.now(timezone.utc).isoformat(), row["worker_id"]))
    provider = PROVIDERS[row["worker_id"]]
    if row["session_id"] and not isinstance(provider, OllamaProvider):
        command = provider.resume(row["session_id"], "You were interrupted; check git status and continue.", worktree)
        result = subprocess.run(command.argv, cwd=worktree, capture_output=True, text=True)
        code = result.returncode
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (row["id"],))
        db.execute("UPDATE workers SET status='idle',current_task_id=NULL,last_activity_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), row["worker_id"]))
        return code == 0
    return execute_task(db, home, repo, task, row["worker_id"], worktree, branch, source) == 0

def daemon(home: Path) -> None:
    import tomllib
    with (home / "config.toml").open("rb") as stream: config = tomllib.load(stream)
    repo = Path(config.get("repo", os.getcwd())).expanduser()
    source = GitHubTaskSource(config.get("github", {}).get("repo"))
    while True:
        run_once(home, source, default_worker=config.get("default_worker", "codex"), repo=repo, base_branch=config.get("base_branch", "main"), cooldown_hours=float(config.get("cooldown_hours", 3)), worker_ids=tuple(config.get("workers", ["codex", "cursor", "local"])))
        time.sleep(15)

def stop_pid(pid: int) -> None:
    os.killpg(pid, signal.SIGTERM)
