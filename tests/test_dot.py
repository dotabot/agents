from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from dot.cli import main
from dot.db import connect
from dot.git_policy import scan_secrets, validate_git_operation
from dot.providers import CodexProvider, CursorProvider
from dot.router import claim_next, cool_down, eligible, refresh_cooldowns
from dot.tasks import Task


class FakeSource:
    def __init__(self, tasks):
        self.tasks = tasks
        self.labels = []

    def list_queued(self):
        return list(self.tasks)

    def set_labels(self, task, add, remove):
        self.labels.append((task.issue_number, add, remove))


@pytest.fixture
def home(tmp_path):
    (tmp_path / "config.toml").write_text('repo = "."\ndefault_worker = "codex"\nbase_branch = "main"\n')
    db = connect(tmp_path)
    for worker in ("codex", "cursor", "local"):
        db.execute("INSERT INTO providers(id,kind,enabled) VALUES(?, 'worker', 1)", (worker,))
        db.execute("INSERT INTO workers(id,provider_id,status) VALUES(?,?,'idle')", (worker, worker))
    return tmp_path


def test_routing_obeys_pin_default_and_cloud():
    assert eligible(Task(1, "x", ("dot:queue", "worker:cursor")), "cursor", "codex")
    assert not eligible(Task(1, "x", ("dot:queue", "worker:cursor")), "codex", "codex")
    assert eligible(Task(2, "x", ("dot:queue",)), "codex", "codex")
    assert not eligible(Task(3, "x", ("dot:queue", "worker:cloud")), "codex", "codex")


def test_claim_next_claims_oldest_eligible_and_swaps_labels(home):
    db = connect(home)
    source = FakeSource([Task(8, "newer", ("dot:queue",)), Task(2, "older", ("dot:queue",))])
    result = claim_next(db, source.tasks, source, "codex", home / "wt", "codex", "repo", "main")
    assert result.issue_number == 2
    assert source.labels == [(2, ("dot:wip",), ("dot:queue",))]
    assert db.execute("SELECT branch,state FROM tasks WHERE issue_number=2").fetchone()[:] == ("codex/issue-2", "claimed")


def test_claim_rolls_back_when_github_label_swap_fails(home):
    class BrokenSource(FakeSource):
        def set_labels(self, task, add, remove):
            raise RuntimeError("gh failed")

    db = connect(home)
    task = Task(3, "claim", ("dot:queue",))
    with pytest.raises(RuntimeError):
        claim_next(db, [task], BrokenSource([task]), "codex", home / "wt", "codex", "repo", "main")
    assert db.execute("SELECT state,worker_id FROM tasks WHERE issue_number=3").fetchone()[:] == ("queued", None)
    assert db.execute("SELECT status,current_task_id FROM workers WHERE id='codex'").fetchone()[:] == ("idle", None)


def test_claim_is_atomic_across_workers(home):
    db1 = connect(home); db2 = connect(home)
    task = Task(1, "once", ("dot:queue",))
    source = FakeSource([task]); barrier = threading.Barrier(2)
    def attempt(db, worker):
        barrier.wait()
        return claim_next(db, [task], source, worker, home / worker, "codex", "repo", "main")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda args: attempt(*args), [(db1, "codex"), (db2, "cursor")]))
    assert sum(item is not None for item in outcomes) == 1


def test_cooldown_expires(home):
    db = connect(home)
    until = cool_down(db, "codex", None)
    assert db.execute("SELECT status FROM workers WHERE id='codex'").fetchone()[0] == "cooling"
    refresh_cooldowns(db, until)
    assert db.execute("SELECT status FROM workers WHERE id='codex'").fetchone()[0] == "idle"
    assert db.execute("SELECT source FROM usage_events").fetchone()[0] == "estimated"


def test_limit_hands_task_to_next_paid_worker_on_same_branch(home, monkeypatch):
    from dot import worker

    db = connect(home)
    task_id = db.execute("INSERT INTO tasks(repo,issue_number,title,labels,state,worker_id,branch) VALUES('repo',4,'limited','dot:wip','running','codex','codex/issue-4') RETURNING id").fetchone()[0]
    db.execute("UPDATE workers SET status='running',current_task_id=? WHERE id='codex'", (task_id,))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("cwd")))
        output = "usage limit reached" if argv[0] == "codex" else "continued"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    worker.execute_task(db, home, Path("repo"), Task(4, "limited", ("dot:wip",)), "codex", Path("/tmp/worktree"), "codex/issue-4", FakeSource([]))
    assert calls[0][1] == Path("/tmp/worktree")
    assert calls[1][1] == Path("/tmp/worktree")
    assert db.execute("SELECT status FROM workers WHERE id='codex'").fetchone()[0] == "cooling"
    assert db.execute("SELECT worker_id,branch FROM tasks WHERE id=?", (task_id,)).fetchone()[:] == ("cursor", "codex/issue-4")
    assert db.execute("SELECT status FROM workers WHERE id='cursor'").fetchone()[0] == "idle"


def test_worker_reuses_one_worktree_across_issue_branches(tmp_path, monkeypatch):
    from dot import worker

    repo = tmp_path / "repo"
    repo.mkdir()
    branches = set()
    current = {"branch": ""}

    def fake_git(*args, cwd=None):
        if args[:2] == ("branch", "--list"):
            return args[2] if args[2] in branches else ""
        if args[:2] == ("branch", "--show-current"):
            return current["branch"]
        if args[:2] == ("worktree", "add"):
            if "-b" in args:
                branch = args[args.index("-b") + 1]
                path = Path(args[args.index("-b") + 2])
            else:
                branch = args[3]
                path = Path(args[2])
            path.mkdir(parents=True)
            branches.add(branch)
            current["branch"] = branch
            return ""
        if args[0] == "switch":
            branch = args[2] if args[1] == "-c" else args[1]
            branches.add(branch)
            current["branch"] = branch
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(worker, "_git", fake_git)
    first, first_branch = worker.ensure_worktree(repo, tmp_path, "codex", 1, "main")
    second, second_branch = worker.ensure_worktree(repo, tmp_path, "codex", 2, "main")
    assert first == second == tmp_path / "worktrees" / "codex"
    assert first_branch == "codex/issue-1"
    assert second_branch == current["branch"] == "codex/issue-2"


def test_limit_detection_and_provider_commands():
    assert CodexProvider().detects_limit("Your usage limit was reached")
    assert not CodexProvider().detects_limit("completed successfully")
    codex = CodexProvider().run("fix it", Path("/tmp/wt"))
    assert codex.argv[:5] == ("codex", "exec", "--json", "-C", "/tmp/wt")
    assert "--oss" in CodexProvider().run_oss("fix", Path("/tmp/wt"), "model").argv
    cursor = CursorProvider().resume("chat-1", "continue", Path("/tmp/wt"))
    assert cursor.argv[:4] == ("cursor-agent", "-p", "--resume", "chat-1")
    assert "enabled" in cursor.argv


def test_git_policy_refuses_protected_force_and_merge():
    for operation, branch, force in (("commit", "main", False), ("push", "dev", False), ("push", "feature", True), ("merge", "feature", False)):
        with pytest.raises(ValueError): validate_git_operation(operation, branch, force)
    validate_git_operation("commit", "codex/issue-4")


def test_secrets_scan_only_flags_added_lines():
    assert scan_secrets("+API_KEY=abcdefghijklmnop123456\n")
    assert scan_secrets("-API_KEY=abcdefghijklmnop123456\n") == []


def test_cli_smoke_init_status_next_and_auth(home, capsys):
    assert main(["status", "--json"], home=home) == 0
    assert '"workers"' in capsys.readouterr().out
    source = FakeSource([Task(7, "queued", ("dot:queue",))])
    assert main(["next", "--dry-run"], home=home, task_source=source) == 0
    assert "Would assign #7" in capsys.readouterr().out
    assert main(["auth", "ollama"], home=home) == 0
    assert "127.0.0.1" not in capsys.readouterr().out


def test_init_creates_config_and_state(tmp_path, monkeypatch, capsys):
    home = tmp_path / "new-dot"
    assert main(["init"], home=home) == 0
    assert (home / "config.toml").exists()
    assert (home / "state.db").exists()

