# RIPv2 tool guide

Tool name: `RIPv2`
Script: `routing_tools/rip_request.py`

## Purpose

- Enumerate RIP routes with request mode.
- Inject crafted RIPv2 response entries in inject mode.

## Modes

- Request mode (default): sends RIP Request and can capture responses.
- Inject mode (`--inject`): sends RIP Response payload entries.

## Key arguments

- `--iface IFACE`: network interface.
- `--target IP`: destination IP. Default multicast for v2.
- `--version {1,2}`: RIP version.
- `--count N`: send count.
- `--timeout SECS`: capture timeout in request mode.
- `--send-only`: send without capture.
- `--inject`: switch to response/injection mode.
- `--entry NET/MASK[:NEXTHOP[:TAG[:METRIC]]]`: route entry, repeatable.

## Good defaults

- Keep `--version 2` for injection workflows.
- Keep `--count` low unless repeatedly advertising is required.
- In request mode, set realistic `timeout_seconds` in tool params.

## Examples

- Route enumeration:
  - `--iface eth0 --target 224.0.0.9 --version 2`
- Unicast request to known router:
  - `--iface eth0 --target 10.0.0.1 --entry 10.1.0.0/255.255.0.0`
- Inject route:
  - `--iface eth0 --inject --entry 192.168.99.0/255.255.255.0:10.0.0.254:0:1`
- Poison route:
  - `--iface eth0 --inject --entry 10.0.0.0/255.0.0.0:0.0.0.0:0:16`

## Guardrails

- Requires root privileges for raw/socket operations.
- Injection can alter neighbor routing behavior; use only in authorized scope.
- Avoid excessive repeated injection without explicit need.
