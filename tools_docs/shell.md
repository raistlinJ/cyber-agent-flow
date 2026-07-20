# shell tool guide

Tool name: `shell`

## Purpose

- Run low-risk local host inspection commands from a strict allowlist.

## Allowed commands

- `ls`, `cat`, `grep`, `docker`, `ip`, `ss`, `ps`, `uname`, `id`, `pwd`, `whoami`, `find`, `netstat`

## Constraints

- No shell chaining or redirection (`|`, `&&`, `;`, `>`, etc.).
- Input is tokenized and validated before execution.

## Behavior

- If command is not allowlisted, it may escalate only when `shell_dangerous` is enabled.
- Use simple read-only inspection sequences.

## Examples

- `ls -la`
- `ip addr`
- `ss -lntp`
