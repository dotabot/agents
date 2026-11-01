from __future__ import annotations

import re
import subprocess

PROTECTED_BRANCHES = {"main", "dev"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
]

def validate_git_operation(operation: str, branch: str, force: bool = False) -> None:
    if operation == "commit" and branch in PROTECTED_BRANCHES:
        raise ValueError(f"refusing to commit on protected branch {branch}")
    if operation == "push" and branch in PROTECTED_BRANCHES:
        raise ValueError(f"refusing to push protected branch {branch}")
    if operation == "push" and force:
        raise ValueError("force-push is forbidden")
    if operation == "merge":
        raise ValueError("DOT never merges")

def scan_secrets(diff: str) -> list[str]:
    findings = []
    for number, line in enumerate(diff.splitlines(), 1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            findings.append(f"added line {number} matches a secret pattern")
    return findings

def scan_diff(base: str = "HEAD") -> list[str]:
    result = subprocess.run(["git", "diff", "--cached", base], check=True, capture_output=True, text=True)
    return scan_secrets(result.stdout)
