from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Task:
    issue_number: int
    title: str
    labels: tuple[str, ...]
    url: str = ""
    created_at: str = ""

    @property
    def pin(self) -> str | None:
        for label in self.labels:
            if label.startswith("worker:"):
                value = label.split(":", 1)[1]
                return "local" if value == "local" else value
        return None


class TaskSource(Protocol):
    def list_queued(self) -> list[Task]: ...
    def set_labels(self, task: Task, add: tuple[str, ...], remove: tuple[str, ...]) -> None: ...


class GitHubTaskSource:
    def __init__(self, repo: str | None = None): self.repo = repo
    def _gh(self, *args: str) -> str:
        command = ["gh", *args]
        if self.repo: command.extend(("--repo", self.repo))
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout
    def list_queued(self) -> list[Task]:
        data = json.loads(self._gh("issue", "list", "--state", "open", "--label", "dot:queue", "--json", "number,title,labels,url,createdAt", "--limit", "500"))
        return [Task(int(item["number"]), item["title"], tuple(label["name"] for label in item["labels"]), item.get("url", ""), item.get("createdAt", "")) for item in data]
    def set_labels(self, task: Task, add: tuple[str, ...], remove: tuple[str, ...]) -> None:
        if add: self._gh("issue", "edit", str(task.issue_number), "--add-label", ",".join(add))
        if remove: self._gh("issue", "edit", str(task.issue_number), "--remove-label", ",".join(remove))
