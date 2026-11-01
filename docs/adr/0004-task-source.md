# ADR 0004: GitHub Issues + Projects board as the task source of truth

Status: proposed

## Context
Workers, humans and cloud admin bots (e.g. Grok Bot) must all see the same queue. The prior setup
proved label routing on GitHub issues works well with `gh`.

## Decision
Tasks are GitHub issues; a Projects v2 board shows state. Labels: `dot:queue|wip|done|blocked|handoff`
and routing pins `worker:cursor|codex|claude|local|cloud`. Workers claim atomically, branch
`<worker>/issue-<n>`, push and open a PR with `Closes #n`; rework continues on the open PR's branch.
DOT never merges or deploys. `worker:cloud` is never auto-run. SQLite mirrors state locally for
speed and offline status.

## Consequences
- No new service to host; cloud assistants already read GitHub.
- Depends on `gh` auth and GitHub API rate limits; DOT caches and batches calls.
- Other trackers (Linear, Jira) can be added later behind a TaskSource interface.
