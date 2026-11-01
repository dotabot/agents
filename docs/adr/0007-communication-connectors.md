# ADR 0007: Pluggable communication connectors, Slack first, with a command allow-list

Status: proposed

## Context
Status posts, hand-offs and remote commands should reach the user wherever they chat: Slack first,
later Discord, Telegram, Microsoft Teams, WhatsApp and email.

## Decision
A `CommConnector` interface (connect, post_status, post_handoff, inbound). Slack ships in v0.4 as
a Socket Mode app (no public endpoint). Inbound commands are accepted only from user ids on a
per-connector allow-list; approval-type commands may need confirmation on the Mac; no chat command
can merge, deploy or push to a protected branch. Tokens live in the macOS Keychain.

## Consequences
- One code path for all chat apps; connectors are optional extras.
- Each platform's app setup is a manual, documented step done by the user.
