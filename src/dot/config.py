from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any


def dot_home() -> Path:
    return Path(os.environ.get("DOT_HOME", Path.home() / ".dot")).expanduser()


def load_config(home: Path | None = None) -> dict[str, Any]:
    path = (home or dot_home()) / "config.toml"
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def init_home(home: Path | None = None) -> Path:
    root = home or dot_home()
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    repo = Path.cwd()
    has_dev = subprocess.run(["git", "branch", "--list", "dev"], cwd=repo, capture_output=True, text=True).returncode == 0 and bool(subprocess.run(["git", "branch", "--list", "dev"], cwd=repo, capture_output=True, text=True).stdout.strip())
    defaults = {
        "repo": str(repo),
        "base_branch": "dev" if has_dev else "main",
        "default_worker": "codex",
        "cooldown_hours": 3,
        "workers": ["codex", "cursor", "local"],
        "providers": {"codex": {"enabled": True}, "cursor": {"enabled": True}, "ollama": {"enabled": True}},
    }
    config_path = root / "config.toml"
    if not config_path.exists():
        lines = [f'repo = "{defaults["repo"].replace(chr(34), chr(92)+chr(34))}"', f'base_branch = "{defaults["base_branch"]}"', 'default_worker = "codex"', "cooldown_hours = 3", 'workers = ["codex", "cursor", "local"]', "", "[providers.codex]", f'enabled = {str(bool(shutil.which("codex"))).lower()}', "", "[providers.cursor]", f'enabled = {str(bool(shutil.which("cursor-agent"))).lower()}', "", "[providers.ollama]", "enabled = true", ""]
        config_path.write_text("\n".join(lines), encoding="utf-8")
    return root
