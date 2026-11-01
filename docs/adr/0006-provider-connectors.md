# ADR 0006: Pluggable provider adapters with official logins only

Status: proposed

## Context
Users mix subscriptions: Codex CLI, Cursor CLI, Claude Code, local Ollama models, cloud assistants
such as Grok Bot, and later Gemini CLI, Aider, OpenCode. Each logs in, runs headless, resumes,
sandboxes and reports usage differently.

## Decision
A `Provider` interface (detect, login, run, resume, parse_events, usage, limit_patterns,
sync_targets) with first-class adapters for Codex, Cursor, Claude Code, Ollama and Grok Bot
(hand-off only). `dot auth <provider>` runs only the vendor's official login; DOT never reads or
stores provider credentials. Every usage figure is tagged measured, reported or estimated.
Adapters are entry points, so new providers ship as separate packages.

## Consequences
- Adding a provider is one class plus a sync-target table.
- Quality of usage data varies by vendor; the router works from estimates where needed and
  recalibrates on each observed limit.
