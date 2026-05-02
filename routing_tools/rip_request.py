#!/usr/bin/env python3
"""
RIPv2 packet sender using Scapy.

Sends a properly formed RIP Request over UDP with source and destination
port 520, asking for the full routing table, then captures and parses RIP
Response packets.

Requires root/CAP_NET_RAW and scapy (pip3 install scapy).

Usage:
  python3 rip_request.py [options]

Options:
  --iface IFACE        Network interface (default: scapy auto-detect)
  --src-ip IP          Source IP address (default: auto-detect from interface)
  --src-mac MAC        Source MAC address (default: auto-detect from interface)
  --target IP          Destination IP (default: 224.0.0.9 for RIPv2,
                       255.255.255.255 for RIPv1)
  --dst-mac MAC        Destination MAC (default: auto-set for multicast/broadcast)
  --version {1,2}      RIP version (default: 2)
  --sport PORT         UDP source port (default: 520, required by RFC 2453)
  --dport PORT         UDP destination port (default: 520)
  --ttl N              IP TTL (default: 1; RFC 2453 mandates TTL=1 for multicast)
  --count N            Number of Request packets to send (default: 1)
  --timeout SECS       Seconds to listen for responses (default: 10)
  --send-only          Only send the Request; skip response capture

Route entry options (RIP Request body):
  By default a single "wildcard" entry (AFI=0, metric=16) is sent, asking
  the router to return its full routing table (RFC 2453 §3.9.1).
  Use the options below to query specific prefixes instead.

  --entry NET/MASK[:NEXTHOP[:TAG[:METRIC]]]
                       Add a specific route entry. Repeatable.
                       NEXTHOP defaults to 0.0.0.0, TAG to 0, METRIC to 16.
                       Example: --entry 10.0.0.0/255.255.255.0
                                --entry 10.0.0.0/255.255.0.0:192.168.1.1:0:1

  Single-entry convenience flags (used when --entry is absent):
  --entry-network IP   Route network address (default: 0.0.0.0)
  --entry-mask    IP   Subnet mask           (default: 0.0.0.0)
  --entry-nexthop IP   Next-hop address      (default: 0.0.0.0)
  --entry-tag     N    Route tag             (default: 0)
  --entry-metric  N    Metric 1-16; 16=wildcard full-table request (default: 16)

Examples:
  # Enumerate routes from all RIPv2 neighbours on eth0
  python3 rip_request.py --iface eth0

  # Target a specific router with RIPv1 broadcast
  python3 rip_request.py --iface eth0 --target 192.168.1.1 --version 1

  # Send 3 requests, listen 30 s, custom source IP
  python3 rip_request.py --iface eth0 --src-ip 10.0.0.5 --count 3 --timeout 30

  # Ask for a specific prefix (unicast to router)
  python3 rip_request.py --iface eth0 --target 10.0.0.1 \
      --entry 192.168.10.0/255.255.255.0:0.0.0.0:0:16

  # Multiple specific prefixes
  python3 rip_request.py --iface eth0 --target 10.0.0.1 \
      --entry 10.1.0.0/255.255.0.0 --entry 172.16.0.0/255.240.0.0
"""

import argparse
import socket
import struct
import sys


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Send properly formed RIPv1/v2 Request packets (UDP/520) "
                    "and capture route responses"
    )
    p.add_argument("--iface",   default=None,
                   help="Network interface (default: scapy auto-detect)")
    p.add_argument("--src-ip",  default=None,
                   help="Source IP address (default: auto-detect from interface)")
    p.add_argument("--src-mac", default=None,
                   help="Source MAC address (default: auto-detect from interface)")
    p.add_argument("--target",  default=None,
                   help="Destination IP; default 224.0.0.9 (RIPv2 multicast) "
                        "or 255.255.255.255 (RIPv1 broadcast)")
    p.add_argument("--dst-mac", default=None,
                   help="Destination MAC (default: 01:00:5e:00:00:09 for multicast, "
                        "ff:ff:ff:ff:ff:ff for broadcast/unicast)")
    p.add_argument("--version", type=int, choices=[1, 2], default=2,
                   help="RIP version (default: 2)")
    p.add_argument("--sport",   type=int, default=520,
                   help="UDP source port (default: 520, required by RFC 2453)")
    p.add_argument("--dport",   type=int, default=520,
                   help="UDP destination port (default: 520)")
    p.add_argument("--ttl",     type=int, default=1,
                   help="IP TTL (default: 1; RFC 2453 mandates TTL=1 for multicast)")
    p.add_argument("--count",   type=int, default=1,
                   help="Number of Request packets to send (default: 1)")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="Seconds to listen for responses (default: 10)")
    p.add_argument("--send-only", action="store_true",
                   help="Only send the Request packet; skip response capture")

    # --- Route entry arguments ---
    ent = p.add_argument_group(
        "Route entry options",
        "Control the RIP route entry/entries in the Request body. "
        "Default: single wildcard entry (AFI=0, metric=16) asking for the "
        "full routing table (RFC 2453 §3.9.1)."
    )
    ent.add_argument(
        "--entry", metavar="NET/MASK[:NEXTHOP[:TAG[:METRIC]]]",
        action="append", dest="entries", default=None,
        help="Add a specific route entry (repeatable). "
             "Example: --entry 10.0.0.0/255.255.255.0:192.168.1.1:0:1"
    )
    ent.add_argument("--entry-network", default="0.0.0.0",
                     help="Single-entry network address (default: 0.0.0.0)")
    ent.add_argument("--entry-mask",    default="0.0.0.0",
                     help="Single-entry subnet mask (default: 0.0.0.0)")
    ent.add_argument("--entry-nexthop", default="0.0.0.0",
                     help="Single-entry next-hop address (default: 0.0.0.0)")
    ent.add_argument("--entry-tag",     type=int, default=0,
                     help="Single-entry route tag (default: 0)")
    ent.add_argument("--entry-metric",  type=int, default=16,
                     help="Single-entry metric 1-16; 16 = wildcard full-table "
                          "request (default: 16)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# RIP packet construction helpers
# ---------------------------------------------------------------------------
def _build_entry(afi: int, tag: int, network: str, mask: str,
                 nexthop: str, metric: int) -> bytes:
    """
    Build one 20-byte RIP route entry (RFC 2453 §4).
    AFI 0  = wildcard (no address family); used in full-table Requests.
    AFI 2  = AF_INET; used for specific-prefix Requests and all Responses.
    """
    return struct.pack("!HH4s4s4sI",
                       afi, tag,
                       socket.inet_aton(network),
                       socket.inet_aton(mask),
                       socket.inet_aton(nexthop),
                       metric)


def _parse_entry_arg(raw: str):
    """
    Parse one --entry value: NET/MASK[:NEXTHOP[:TAG[:METRIC]]]
    Returns (network, mask, nexthop, tag, metric).
    Raises ValueError or OSError on bad input.
    """
    parts = raw.split(":")
    nm = parts[0].split("/")
    if len(nm) != 2:
        raise ValueError(f"Expected NET/MASK, got: {parts[0]!r}")
    network = nm[0].strip()
    mask    = nm[1].strip()
    nexthop = parts[1].strip() if len(parts) > 1 else "0.0.0.0"
    tag     = int(parts[2])    if len(parts) > 2 else 0
    metric  = int(parts[3])    if len(parts) > 3 else 16
    # validate IPs (raises OSError on bad address)
    for val in (network, mask, nexthop):
        socket.inet_aton(val)
    return network, mask, nexthop, tag, metric


def build_rip_request(version: int, entries=None) -> bytes:
    """
    Build a RIP Request packet.

    entries : list of dicts with keys: network, mask, nexthop, tag, metric.
              If None/empty → defaults to the RFC 2453 §3.9.1 wildcard
              (single AFI=0, metric=16 entry = "send me your full table").
    """
    header = struct.pack("!BBH", 1, version, 0)
    if not entries:
        # Wildcard: ask for the entire routing table
        body = _build_entry(0, 0, "0.0.0.0", "0.0.0.0", "0.0.0.0", 16)
    else:
        body = b""
        for e in entries:
            body += _build_entry(
                2,                       # AF_INET
                e.get("tag",     0),
                e.get("network", "0.0.0.0"),
                e.get("mask",    "0.0.0.0"),
                e.get("nexthop", "0.0.0.0"),
                e.get("metric",  16),
            )
    return header + body


# ---------------------------------------------------------------------------
# RIP response parsing
# ---------------------------------------------------------------------------
def parse_rip_response(payload: bytes, src: str, routes: list):
    """Parse raw UDP payload of a RIP Response (cmd=2) and print routes."""
    if len(payload) < 4:
        return
    cmd, ver, _ = struct.unpack("!BBH", payload[:4])
    if cmd != 2:
        return

    print(f"[+] RIP Response from {src}  (RIPv{ver})")
    count  = 0
    offset = 4
    while offset + 20 <= len(payload):
        afi, tag = struct.unpack("!HH", payload[offset:offset + 4])
        ip_b   = payload[offset + 4:offset + 8]
        mask_b = payload[offset + 8:offset + 12]
        nh_b   = payload[offset + 12:offset + 16]
        metric, = struct.unpack("!I", payload[offset + 16:offset + 20])
        offset += 20

        if afi == 2:  # AF_INET
            try:
                net     = socket.inet_ntoa(ip_b)
                mask    = socket.inet_ntoa(mask_b)
                nexthop = socket.inet_ntoa(nh_b)
            except OSError:
                continue
            print(f"    {net}/{mask}  nexthop={nexthop}  metric={metric}")
            routes.append({
                "src": src, "network": net, "mask": mask,
                "nexthop": nexthop, "metric": metric,
            })
            count += 1

    if count == 0:
        print("    (no AF_INET entries in this response)")


# ---------------------------------------------------------------------------
# Interface IP helper
# ---------------------------------------------------------------------------
def _get_iface_ip(iface):
    try:
        import fcntl
        import struct as _struct
        sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packed = fcntl.ioctl(sock.fileno(), 0x8915,
                             _struct.pack("256s", iface[:15].encode()))
        sock.close()
        return socket.inet_ntoa(packed[20:24])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    try:
        from scapy.all import conf, sendp, sniff, Ether, IP, UDP, Raw, get_if_hwaddr
    except ImportError:
        print("Error: scapy is not installed. Install with: pip3 install scapy",
              file=sys.stderr)
        sys.exit(1)

    version = args.version
    iface   = args.iface or conf.iface

    # --- Source addresses ---
    src_ip = args.src_ip or _get_iface_ip(iface) or conf.route.route("0.0.0.0")[1]
    try:
        src_mac = args.src_mac or get_if_hwaddr(iface)
    except Exception:
        src_mac = None  # Scapy will fill in

    # --- Destination addresses ---
    if args.target:
        dst_ip = args.target
        if args.dst_mac:
            dst_mac = args.dst_mac
        elif dst_ip == "224.0.0.9":
            dst_mac = "01:00:5e:00:00:09"
        else:
            dst_mac = "ff:ff:ff:ff:ff:ff"
    else:
        if version == 2:
            dst_ip  = "224.0.0.9"
            dst_mac = args.dst_mac or "01:00:5e:00:00:09"
        else:
            dst_ip  = "255.255.255.255"
            dst_mac = args.dst_mac or "ff:ff:ff:ff:ff:ff"

    print(f"[*] RIPv{version} Request")
    print(f"    iface   : {iface}")
    print(f"    src     : {src_ip}:{args.sport}  ({src_mac or 'auto'})")
    print(f"    dst     : {dst_ip}:{args.dport}  ({dst_mac})")
    print(f"    ttl     : {args.ttl}")
    print(f"    count   : {args.count}")
    print(f"    timeout : {args.timeout}s")
    print()

    # --- Build route entry list from CLI ---
    route_entries = None
    if args.entries:
        route_entries = []
        for raw in args.entries:
            try:
                net, mask, nh, tag, metric = _parse_entry_arg(raw)
            except (ValueError, OSError) as exc:
                print(f"[!] Bad --entry value {raw!r}: {exc}", file=sys.stderr)
                sys.exit(1)
            route_entries.append(
                {"network": net, "mask": mask, "nexthop": nh,
                 "tag": tag, "metric": metric}
            )
    elif (args.entry_network != "0.0.0.0"
          or args.entry_mask    != "0.0.0.0"
          or args.entry_nexthop != "0.0.0.0"
          or args.entry_tag     != 0
          or args.entry_metric  != 16):
        route_entries = [{
            "network": args.entry_network,
            "mask":    args.entry_mask,
            "nexthop": args.entry_nexthop,
            "tag":     args.entry_tag,
            "metric":  args.entry_metric,
        }]

    if route_entries:
        print(f"[*] Request entries ({len(route_entries)}):")
        for e in route_entries:
            print(f"    {e['network']}/{e['mask']}  nexthop={e['nexthop']}  "
                  f"tag={e['tag']}  metric={e['metric']}")
    else:
        print("[*] Request entry: wildcard (AFI=0, metric=16) — full routing table")
    print()

    rip_data = build_rip_request(version, route_entries)

    # Build the packet.
    # Key points:
    #   - IP(proto=17) is set EXPLICITLY so Scapy never guesses ICMP (proto=1)
    #     from the first byte of the RIP payload (\x01 = RIP Request command).
    #   - Raw(load=...) is used instead of passing raw bytes directly via /,
    #     which prevents Scapy from trying to bind-detect the payload type and
    #     avoids the bug where raw bytes starting with \x01 get treated as ICMP.
    ether_kwargs = {"dst": dst_mac}
    if src_mac:
        ether_kwargs["src"] = src_mac

    pkt = (
        Ether(**ether_kwargs)
        / IP(src=src_ip, dst=dst_ip, ttl=args.ttl, proto=17)
        / UDP(sport=args.sport, dport=args.dport)
        / Raw(load=rip_data)
    )

    try:
        for i in range(args.count):
            sendp(pkt, iface=iface, verbose=False)
            if args.count > 1:
                print(f"[+] RIP Request sent ({i + 1}/{args.count})")
        if args.count == 1:
            print("[+] RIP Request sent")
    except PermissionError:
        print("[!] Permission denied — re-run with sudo/root", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[!] Send failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.send_only:
        return

    print(f"[*] Listening for RIP Responses on UDP/520 for {args.timeout}s ...")
    print()

    routes: list      = []
    seen_sources: set = set()

    def handle_pkt(pkt):
        if not (pkt.haslayer(IP) and pkt.haslayer(UDP)):
            return
        if pkt[UDP].sport != 520:
            return
        src = pkt[IP].src
        if src not in seen_sources:
            seen_sources.add(src)
        parse_rip_response(bytes(pkt[UDP].payload), src, routes)

    sniff(
        iface=iface,
        filter="udp port 520",
        timeout=args.timeout,
        prn=handle_pkt,
        store=False,
    )

    print()
    print(f"[*] Capture complete — {len(routes)} route(s) from "
          f"{len(seen_sources)} source(s)")
    if not routes:
        print("[*] No RIP routes received.")
        print("[*] Tips:")
        print("    - Verify the target router is RIP-enabled and reachable on UDP/520")
        print("    - Ensure you are on the same broadcast/multicast L2 segment")
        print("    - Try --target <router-ip> to unicast directly to a known router")
        print("    - Try --version 1 --target 255.255.255.255 for RIPv1 broadcast")


if __name__ == "__main__":
    main()
