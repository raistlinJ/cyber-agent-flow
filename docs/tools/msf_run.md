# msf_run tool guide

Tool name: `msf_run`

## Purpose

- Execute a Metasploit command sequence in batch mode through `msfconsole -q -x`.
- Support exploit workflows while preserving real interactive sessions when detected.

## Input format

- Provide semicolon-separated Metasploit console commands.
- Example:
  - `use auxiliary/scanner/http/http_version; set RHOSTS 10.0.0.0/24; run`

## Operational guidance

- For Meterpreter or shell sessions, start with `help` in the current context to list valid commands.
- Do not assume Linux shell commands are valid in Meterpreter without entering a shell.
- Prefer explicit module setup (`set RHOSTS`, `set RPORT`, `set LHOST/LPORT`) before `run` or `exploit`.

## Session behavior

- If an interactive session is preserved (for example `isess-001`), continue using:
  - `interactive_session_write`
  - `interactive_session_read`
  - `interactive_session_close`
- Do not rerun the exploit only to regain interaction.

## Guardrails

- Keep command chains minimal and deterministic.
- Avoid noisy or repeated exploit loops without new evidence.
- Use scoped targets and authorized ranges only.
