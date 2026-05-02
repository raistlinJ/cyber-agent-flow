# shell_dangerous tool guide

Tool name: `shell_dangerous`

## Purpose

- Execute less restricted shell commands for advanced workflows.

## Characteristics

- Uses `/bin/sh -lc` semantics.
- Supports pipes, redirects, and command chaining.
- Requires explicit human approval before execution.

## When to use

- Only when `shell` or `shell_extended` cannot express the required operation.
- For controlled write operations or complex command logic.

## Guardrails

- Keep command scope minimal and explicit.
- Prefer read-only operations unless write is explicitly required.
- Expect timeout checkpoints for long-running commands.
