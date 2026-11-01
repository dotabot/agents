# agents (DOT)

A lightweight, CLI-first, sandboxed local agent framework. DOT lets a developer with ordinary
subscriptions (Cursor, Codex CLI, Claude Code, cloud assistants) and a capable Mac connect them all,
plus a local model, into one control plane, and get the most finished work out of each plan's
usage limits: local models take the cheap work, paid plans get the hard parts, workers rotate on
limits, and one central store keeps rules, skills and hooks in sync across every tool.

Status: v0.1 CLI and local worker pool. The implementation follows [docs/DESIGN.md](docs/DESIGN.md)
and the decisions in [docs/adr/](docs/adr/).

Install the development environment with `uv sync`, then run `uv run dot init`. Use `uv run dot
auth codex` or `uv run dot auth cursor` to see each vendor's official login command. Configure
`repo`, `default_worker`, and `base_branch` in `~/.dot/config.toml`, then use `uv run dot up` to
start the worker pool. `DOT_HOME` can point DOT at an alternate state directory.

The v0.1 CLI includes `init`, `auth`, `up`, `status [--json]`, `next [--dry-run]`, and `stop`.
Workers use GitHub issues labelled `dot:queue`; `worker:cloud` is never auto-run.

License: MIT.
