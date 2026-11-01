# ADR 0003: Central store as Markdown + YAML frontmatter and TOML, rendered into native formats

Status: proposed

## Context
Cursor (`.cursor/rules/*.mdc`, skills, `hooks.json`, `mcp.json`), Codex (`AGENTS.md`,
`~/.agents/skills`, `hooks.json`, `config.toml`) and Claude Code (`CLAUDE.md`, `.claude/skills`,
`settings.json`, `.mcp.json`) each want their own files. Hand-maintaining them drifts.

## Decision
`~/.dot/store` (plus an optional per-project `.dot/store`) is the single source of truth:
Markdown + YAML frontmatter for rules, skills, memory, workflows and agents (the same SKILL.md shape
all three tools accept), TOML for hooks, guardrails and integrations, UTCP manuals as JSON.
`dot sync` renders native files with a generated-marker and hash; one `dot hook <event>` bridge
backs every native hook. `dot sync --check` detects drift; `--adopt` pulls hand edits back.

## Consequences
- Human-readable, diffable, git-versioned; skills are symlinked rather than copied.
- Some features have no equivalent everywhere (e.g. Codex has no read-file hook); the sync table
  documents partial mappings and the sandbox covers the gap.
- Secrets are referenced by name only and never rendered.
