# ospf_sniff tool guide

Tool name: `ospf_sniff`
Script: `routing_tools/ospf_sniff.py`

## Purpose

- Discover OSPF activity and neighbors.
- Passively capture OSPF packets with tshark.
- Optionally trigger immediate responses with active hello injection.

## Key arguments

- `--iface IFACE`: interface.
- `--timeout SECS`: capture duration.
- `--verbose`: more packet details.
- `--active`: send OSPF hello to provoke responses.
- `--router-id ID`, `--area AREA`, `--src-ip IP`, `--netmask MASK`: active mode controls.

## Usage guidance

- Start passive first, then use `--active` only if needed.
- Keep short time windows first (for example 30-60s), then extend if quiet.
- Prefer same-segment interfaces where multicast 224.0.0.5 is reachable.

## Guardrails

- Requires root.
- Active mode can be noisy and may be logged by network monitoring.
