# ADR 0001: Python 3.12 single package, managed with uv

Status: proposed

## Context
DOT orchestrates subprocesses (vendor CLIs, `gh`, `git`, Ollama over HTTP), parses JSON streams,
keeps a small SQLite state and serves a tiny localhost dashboard. It must be easy for anyone to
install on a Mac and easy to extend with provider and chat adapters. Candidates: Python, Go, Node.

## Decision
One Python 3.12 package (`dot`), installed with `uv tool install` (or run with `uvx`). Standard
library first (`argparse`, `sqlite3`, `subprocess`, `asyncio`, `http.server`, `tomllib`); a small
dependency set only where it pays (e.g. `httpx`, `slack_bolt` as an optional extra). Adapters are
registered via entry points, so third-party packages can add providers and connectors.

## Consequences
- Fast to write and read; contributors can add an adapter in one file. uv makes install a
  one-liner and pins the interpreter.
- Not a single static binary (Go would be); acceptable because uv bootstraps Python itself.
- Hook bridge and sync can share code with the daemon (the proven prior bridge was Python).
