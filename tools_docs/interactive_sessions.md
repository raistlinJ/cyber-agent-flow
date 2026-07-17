# Interactive session tools guide

Tools:

- `interactive_session_list`
- `interactive_session_read`
- `interactive_session_write`
- `interactive_session_close`

## Purpose

- Continue interacting with preserved sessions (for example `isess-001`) safely.

## Critical rule

- Always use the preserved `isess-XXX` id.
- Do not use Metasploit numeric session ids as `session_id`.

## Typical flow

1. `interactive_session_list` to discover session ids.
2. `interactive_session_read` to collect pending output.
3. `interactive_session_write` with `session_id` and `input` to send commands.
4. `interactive_session_close` when done.

## Notes

- `wait_seconds` can be used on read/write to collect delayed output.
- Closed sessions cannot be written to.
