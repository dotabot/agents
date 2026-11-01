from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .config import dot_home, init_home, load_config
from .db import connect, event
from .providers import PROVIDERS
from .router import refresh_cooldowns
from .tasks import GitHubTaskSource, TaskSource

def _setup_workers(home: Path, config: dict) -> None:
    db = connect(home)
    for key, provider in (("codex", "codex"), ("cursor", "cursor"), ("local", "local")):
        adapter = PROVIDERS[provider]
        detected = adapter.detect()
        enabled = bool(config.get("providers", {}).get(key, {}).get("enabled", key == "local" or detected.installed))
        db.execute("INSERT INTO providers(id,kind,binary,enabled) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET binary=excluded.binary,enabled=excluded.enabled", (provider, adapter.kind, detected.binary, int(enabled)))
        db.execute("INSERT INTO workers(id,provider_id,status) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=CASE WHEN workers.status IN ('running','cooling','paused') THEN workers.status ELSE excluded.status END", ("local" if provider == "local" else provider, provider, "idle" if enabled else "disabled"))

def _source(source: TaskSource | None, config: dict) -> TaskSource:
    return source or GitHubTaskSource(config.get("github", {}).get("repo"))

def command_init(args: argparse.Namespace, home: Path) -> int:
    root = init_home(home)
    config = load_config(root)
    _setup_workers(root, config)
    print(f"Initialized DOT state in {root}")
    for name, provider in (("codex", PROVIDERS["codex"]), ("cursor", PROVIDERS["cursor"])):
        print(f"{name}: {'found' if provider.detect().installed else 'not found'}")
    return 0

def command_auth(args: argparse.Namespace) -> int:
    provider = PROVIDERS.get(args.provider)
    if provider is None: print(f"Unknown provider: {args.provider}", file=sys.stderr); return 2
    login = provider.login()
    detection = provider.detect()
    login_text = " ".join(login.argv) or "No login required for local Ollama"
    print(f"Official login command: {login_text}")
    print(f"Binary: {detection.binary or 'not found'}")
    return 0 if detection.installed or args.provider in {"ollama", "local"} else 1

def _worker_summary(db) -> list[dict]:
    refresh_cooldowns(db)
    return [dict(row) for row in db.execute("SELECT w.id,w.provider_id,w.worktree,w.status,w.current_task_id,w.session_id,w.pid,w.cooling_until,t.issue_number,t.title FROM workers w LEFT JOIN tasks t ON t.id=w.current_task_id ORDER BY w.id")]

def command_status(args: argparse.Namespace, home: Path) -> int:
    db = connect(home); result = {"workers": _worker_summary(db), "queued": db.execute("SELECT COUNT(*) FROM tasks WHERE state='queued'").fetchone()[0]}
    if args.json: print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for worker in result["workers"]: print(f"{worker['id']}: {worker['status']}" + (f" — #{worker['issue_number']} {worker['title']}" if worker["issue_number"] else ""))
        print(f"Queued local tasks: {result['queued']}")
    return 0

def command_next(args: argparse.Namespace, home: Path, source: TaskSource | None = None) -> int:
    config = load_config(home); tasks = _source(source, config).list_queued(); db = connect(home)
    default_worker = config.get("default_worker", "codex")
    options = []
    for task in sorted(tasks, key=lambda item: (item.created_at or f"~{item.issue_number:020d}", item.issue_number)):
        if task.pin == "cloud": continue
        target = task.pin or default_worker
        row = db.execute("SELECT status,current_task_id FROM workers WHERE id=?", (target,)).fetchone()
        if row and row["status"] == "idle" and row["current_task_id"] is None:
            options.append((task, target)); break
    if not options: print("No eligible queued task") ; return 0
    task, worker = options[0]
    if args.dry_run:
        print(f"Would assign #{task.issue_number} {task.title} to {worker}")
        return 0
    from .worker import ensure_worktree, execute_task
    repo = Path(config.get("repo", os.getcwd())).expanduser()
    from .router import claim_next
    path = home / "worktrees" / worker
    claimed = claim_next(db, tasks, _source(source, config), worker, path, default_worker, str(repo), config.get("base_branch", "main"))
    if claimed is None: print("No eligible queued task") ; return 1
    worktree, branch = ensure_worktree(repo, home, worker, task.issue_number, config.get("base_branch", "main"))
    db.execute("UPDATE workers SET worktree=? WHERE id=?", (str(worktree), worker))
    return execute_task(db, home, repo, task, worker, worktree, branch, _source(source, config), float(config.get("cooldown_hours", 3)))

def command_up(home: Path) -> int:
    config = load_config(home); _setup_workers(home, config); db = connect(home)
    pid_file = home / "dotd.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text()); os.kill(pid, 0); print(f"DOT is already running (pid {pid})"); return 0
        except (ValueError, ProcessLookupError): pid_file.unlink(missing_ok=True)
    from .worker import resume_paused_task
    if resume_paused_task(home, config, db, _source(None, config)):
        print("Resumed the paused task before starting the worker pool")
    process = subprocess.Popen([sys.executable, "-m", "dot", "_daemon"], cwd=Path.cwd(), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "DOT_HOME": str(home)})
    pid_file.write_text(str(process.pid))
    print(f"DOT worker pool started (pid {process.pid})")
    return 0

def command_stop(home: Path) -> int:
    pid_file = home / "dotd.pid"
    if pid_file.exists():
        from .worker import stop_pid
        try: stop_pid(int(pid_file.read_text()))
        except ProcessLookupError: pass
        pid_file.unlink(missing_ok=True)
    db = connect(home)
    db.execute("UPDATE workers SET status='paused',pid=NULL WHERE status='running'")
    db.execute("UPDATE tasks SET state='claimed' WHERE state='running'")
    event(db, "workers_stopped")
    print("DOT workers stopped; task claims remain in place")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dot"); subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init")
    auth = subs.add_parser("auth"); auth.add_argument("provider", choices=sorted(PROVIDERS))
    subs.add_parser("up")
    status = subs.add_parser("status"); status.add_argument("--json", action="store_true")
    nxt = subs.add_parser("next"); nxt.add_argument("--dry-run", action="store_true")
    subs.add_parser("stop")
    subs.add_parser("_daemon", help=argparse.SUPPRESS)
    return parser

def main(argv: list[str] | None = None, *, home: Path | None = None, task_source: TaskSource | None = None) -> int:
    args = build_parser().parse_args(argv); root = home or dot_home()
    if args.command == "init": return command_init(args, root)
    if args.command == "auth": return command_auth(args)
    if args.command == "_daemon":
        from .worker import daemon
        daemon(root); return 0
    if not root.exists():
        print("DOT is not initialized. Run `dot init` first.", file=sys.stderr); return 2
    if args.command == "up": return command_up(root)
    if args.command == "status": return command_status(args, root)
    if args.command == "next": return command_next(args, root, task_source)
    if args.command == "stop": return command_stop(root)
    return 2

if __name__ == "__main__": raise SystemExit(main())
