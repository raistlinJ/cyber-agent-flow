# shell_extended tool guide

Tool name: `shell_extended`

## Purpose

- Run read-oriented network commands with stronger guardrails than dangerous shell.

## Allowed commands

- `curl`, `dig`, `host`, `nslookup`, `openssl s_client`, `tracepath`, `traceroute`, `ping`

## curl rules

- HTTP(S) only.
- Disallowed write/upload style flags (for example `-o`, `-O`, `-T`, `-d`, `-F`, `-X`, `-K`).
- Default safety timeouts are injected if absent:
  - `--connect-timeout 5`
  - `--max-time 30`
- Explicit `--max-time` must be between 1 and 90.

## Other command rules

- `openssl` only supports `s_client` with restricted flags.
- `ping` enforces bounded count and disallows flood mode.
- `tracepath` and `traceroute` default max-hops added when absent.

## Behavior

- Validation failure can escalate to `shell_dangerous` only if dangerous tool is enabled.
