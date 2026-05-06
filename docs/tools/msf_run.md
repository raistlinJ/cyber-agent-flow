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
- For exploit modules, `msf_run` now defaults to `set AutoCheck false` before the first `run`/`exploit` unless you explicitly set `AutoCheck` yourself.
- If you need to confirm a payload or option change inside batch mode, add `show options` after the relevant `set` commands.

## Batch mode caveats

- `msf_run` executes `msfconsole -q -x`, so Metasploit may print startup or module-load output before later commands in the sequence run.
- An early line such as `Using configured payload cmd/unix/reverse_perl` can reflect the module's default payload at load time, not the final payload after a later `set PAYLOAD ...` command.
- Do not treat that first payload banner alone as proof that a later payload override failed. Prefer later console output, `show options`, or the resulting session type to confirm the effective payload.
- If you do want Metasploit's module check behavior, explicitly set it (for example, `set AutoCheck true`) in your command chain; explicit settings are preserved.
- `msf_run` is intended for deterministic batch execution, not for keeping an idle `msf >` console attached. If you specifically want a live Metasploit console tab, launch `msfconsole` through `shell_dangerous` instead.

## Session behavior

- If an interactive session is preserved (for example `isess-001`), continue using:
  - `interactive_session_write`
  - `interactive_session_read`
  - `interactive_session_close`
- Do not rerun the exploit only to regain interaction.
- If `msf_run` returns manual recreation guidance instead of a preserved session, that means the batch run completed but the backend did not keep the Metasploit console itself attached.

## Guardrails

- Keep command chains minimal and deterministic.
- Avoid noisy or repeated exploit loops without new evidence.
- Use scoped targets and authorized ranges only.
