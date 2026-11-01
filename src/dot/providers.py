from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    cwd: Path | None = None


@dataclass(frozen=True)
class Detection:
    binary: str | None
    installed: bool


@dataclass(frozen=True)
class UsageSnapshot:
    windows: tuple[dict[str, object], ...] = ()
    source: str = "estimated"


@dataclass(frozen=True)
class ProviderEvent:
    kind: str
    data: dict[str, object]


class Provider(Protocol):
    id: str
    kind: str
    def detect(self) -> Detection: ...
    def login(self) -> Command: ...
    def run(self, task: str, worktree: Path) -> Command: ...
    def resume(self, session_id: str, prompt: str, worktree: Path) -> Command: ...
    def parse_events(self, stream) -> Iterator[ProviderEvent]: ...
    def usage(self) -> UsageSnapshot: ...
    def limit_patterns(self) -> list[str]: ...
    def sync_targets(self) -> list[str]: ...


class BaseProvider:
    kind = "worker"
    executable = ""
    def detect(self) -> Detection:
        binary = shutil.which(self.executable) if self.executable else None
        return Detection(binary, binary is not None)
    def limit_patterns(self) -> list[str]:
        return [r"rate limit", r"usage limit", r"quota exceeded", r"try again after"]
    def detects_limit(self, output: str) -> bool:
        return any(re.search(pattern, output, re.IGNORECASE) for pattern in self.limit_patterns())
    def parse_events(self, stream) -> Iterator[ProviderEvent]:
        for line in stream:
            text = line.decode() if isinstance(line, bytes) else line
            try:
                import json
                value = json.loads(text)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                yield ProviderEvent(str(value.get("type", "message")), value)
    def usage(self) -> UsageSnapshot:
        return UsageSnapshot()
    def sync_targets(self) -> list[str]:
        return []


class CodexProvider(BaseProvider):
    id, executable = "codex", "codex"
    def login(self) -> Command: return Command(("codex", "login"))
    def run(self, task: str, worktree: Path) -> Command:
        return Command(("codex", "exec", "--json", "-C", str(worktree), "-s", "workspace-write", task), worktree)
    def resume(self, session_id: str, prompt: str, worktree: Path) -> Command:
        return Command(("codex", "exec", "resume", session_id, "-C", str(worktree), prompt), worktree)
    def run_oss(self, task: str, worktree: Path, model: str) -> Command:
        return Command(("codex", "exec", "--oss", "--local-provider", "ollama", "-m", model, "-C", str(worktree), task), worktree)


class CursorProvider(BaseProvider):
    id, executable = "cursor", "cursor-agent"
    def login(self) -> Command: return Command(("cursor-agent", "login"))
    def run(self, task: str, worktree: Path) -> Command:
        return Command(("cursor-agent", "-p", "--output-format", "stream-json", "--trust", "--sandbox", "enabled", "--workspace", str(worktree), task), worktree)
    def resume(self, session_id: str, prompt: str, worktree: Path) -> Command:
        return Command(("cursor-agent", "-p", "--resume", session_id, "--sandbox", "enabled", "--workspace", str(worktree), prompt), worktree)


class OllamaProvider(BaseProvider):
    id, executable = "local", ""
    kind = "worker"
    endpoint = "http://127.0.0.1:11434/api/chat"
    def login(self) -> Command: return Command(())
    def run(self, task: str, worktree: Path) -> Command:
        return Command(("POST", self.endpoint, task), worktree)
    def resume(self, session_id: str, prompt: str, worktree: Path) -> Command:
        return self.run(prompt, worktree)


PROVIDERS: dict[str, BaseProvider] = {"codex": CodexProvider(), "cursor": CursorProvider(), "local": OllamaProvider(), "ollama": OllamaProvider()}
