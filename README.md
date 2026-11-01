# agents (DOT)

A lightweight, CLI-first, sandboxed local agent framework. DOT lets a developer with ordinary
subscriptions (Cursor, Codex CLI, Claude Code, cloud assistants) and a capable Mac connect them all,
plus a local model, into one control plane, and get the most finished work out of each plan's
usage limits: local models take the cheap work, paid plans get the hard parts, workers rotate on
limits, and one central store keeps rules, skills and hooks in sync across every tool.

Status: design phase. See [docs/DESIGN.md](docs/DESIGN.md) and [docs/adr/](docs/adr/).

Planned CLI: `dot init`, `dot auth <provider>`, `dot up`, `dot status`, `dot next`, `dot stop`,
`dot sync`, `dot dash`.

License: MIT.
