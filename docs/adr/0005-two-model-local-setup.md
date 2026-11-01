# ADR 0005: Two local models: a 30B coder aide and a small fast tracker

Status: proposed

## Context
On an M2 Max (96 GB) `qwen3-coder:30b` processes prompts at about 100 tok/s at long context: a
36k-token agent prompt took about 13 minutes for a tiny fix. Live tracking needs answers in seconds.
Published M2 Max numbers put 3-4B models (qwen3:4b, llama3.2:3b, gemma3:4b) at roughly 65-115 tok/s
generation and ~1k tok/s prompt processing.

## Decision
Run two Ollama models side by side (`OLLAMA_MAX_LOADED_MODELS=2`, long `keep_alive`):
- **Aide/coder**: an existing 30B coder (e.g. `qwen3-coder:30b`) for micro tasks, pre-reading,
  summaries and `worker:local`, with a default 8k-token prompt budget; DOT trims context instead of
  feeding it a full agent harness prompt.
- **Tracker**: a small fast model (`qwen3:4b` recommended, `llama3.2:3b` alternative) with a 4k
  budget for status lines, triage and event summaries.
The aide serves Cursor, Codex, Claude Code and DOT itself, so paid plans only get the hard parts.

## Consequences
- ~21 GB RAM for both; fits comfortably in 96 GB alongside the IDEs.
- Local code changes still need a paid-plan or human review before merge.
- Model names are config, not code; users with smaller Macs can drop to one small model.
