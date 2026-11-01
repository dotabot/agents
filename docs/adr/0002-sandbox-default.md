# ADR 0002: macOS Seatbelt by default, Docker/Lima optional

Status: proposed

## Context
Workers run AI agents that execute shell commands. Codex and Cursor already sandbox their commands
with Apple Seatbelt (`sandbox-exec`) on macOS. Containers isolate more but cost RAM and setup, and
vendor logins live on the host.

## Decision
Default `sandbox = "seatbelt"`: vendor sandbox on (`codex -s workspace-write`/`--approve-for-me`,
`cursor-agent --sandbox enabled`, Claude allow-lists) plus a DOT Seatbelt profile around each
worker: writes only to its worktree and temp, reads denied for credentials and `.env*`, network
limited to provider endpoints and loopback Ollama. Optional `docker` or `lima` mode for untrusted
repos, full-auto modes and local-model workers.

## Consequences
- Zero extra install, near-native speed, and consistent with what the vendor CLIs expect.
- `sandbox-exec` is deprecated-but-working on macOS; container mode is the escape hatch.
- Git policy (no protected-branch pushes, no force-push, no merge, signed commits, secrets scan) is
  enforced by DOT and hooks regardless of sandbox mode.
