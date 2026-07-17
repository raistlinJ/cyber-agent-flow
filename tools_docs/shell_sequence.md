# shell_sequence tool guide

Tool name: `shell_sequence`

## Purpose

- Run up to 3 `shell_extended`-compatible commands in sequence.

## Input formats

- JSON array of command strings.
- Newline-separated command list.

## Rules

- Each step is validated like `shell_extended`.
- Stops on first failed step by default.
- If dangerous shell is enabled, fallback may occur for blocked steps.

## Example

- `[
  "curl -I https://example.com",
  "host example.com",
  "dig example.com"
]`
