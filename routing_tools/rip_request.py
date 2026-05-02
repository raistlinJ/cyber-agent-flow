#!/usr/bin/env python3
"""
RIP packet sender using Scapy.

Sends a RIP Request to a target (default: RIPv2 multicast 224.0.0.9) asking
for the full routing table, then captures and parses RIP Response packets.

Requires root/CAP_NET_RAW and scapy.

Usage:
  python3 rip_request.py [--iface IFACE] [--target IP] [--version {1,2}]
                          [--timeout SECS] [--send-only]

Examples:
  # Enumerate routes from all RIPv2 neighbours on eth0
  python3 rip_request.py --iface eth0

  # Target a specific router with RIPv1 broadcast
  python3 rip_request.py --iface eth0 --target 192.168.1.1 --version 1

  # Just send the request without waiting for a response
  python3 rip_request.py --iface eth0 --send-only
"""

import argparse
import socket
import struct
import sys


def parse_args():
    p = argparse.ArgumentParser(
        description="Send RIP Request and capture route responses"
    )
    p.add_argument("--iface", default=None,
                   help="Network interface (default: scapy auto-detects)")
    p.add_argument("--target", default=None,
                   help="Target IP; default 224.0.0.9 (RIPv2 multicast) or "
                        "255.255.255.255 (RIPv1 broadcast)")
    p.add_argument("--version", type=int, choices=[1, 2], default=2,
                   help="RIP version (default: 2)")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="Seconds to listen for responses (default: 10)")
    p.add_argument("--send-only", action="store_true",
                   help="Only send the Request packet; skip response capture")
    return p.parse_args()


def build_rip_request(version: int) -> bytes:
    """
    Build a minimal RIP Request packet asking for the full routing table.
    Header: cmd=1 (request), version, unused=0
    Entry:  AFI=0 (address family unspecified), all zeros, metric=16
    This is the canonical 'give me everything' request per RFC 2453 §3.9.1.
    """
    header = struct.pack("!BBH", 1, version, 0)
    entry  = struct.pack("!HH4s4s4sI", 0, 0, b"\x00" * 4, b"\x00" * 4, b"\x00" * 4, 16)
    return header + entry


def parse_rip_response(payload: bytes, src: str, routes: list):
    """Parse raw UDP payload of a RIP Response (cmd=2) and print routes."""
    if len(payload) < 4:
        return
    cmd, ver, _ = struct.unpack("!BBH", payload[:4])
    if cmd != 2:
        return

    print(f"[+] RIP Response from {src}  (RIPv{ver})")
    count = 0
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
            line = f"    {net}/{mask}  nexthop={nexthop}  metric={metric}"
            print(line)
            routes.append({
                "src": src, "network": net, "mask": mask,
                "nexthop": nexthop, "metric": metric,
            })
            count += 1

    if count == 0:
        print("    (no AF_INET entries in this response)")


def main():
    args = parse_args()

    try:
        from scapy.all import conf, sendp, sniff, Ether, IP, UDP
    except ImportError:
        print("Error: scapy is not installed. Install with: pip3 install scapy",
              file=sys.stderr)
        sys.exit(1)

    version = args.version
    iface   = args.iface or conf.iface

    # Resolve destination
    if args.target:
        dst_ip  = args.target
        dst_mac = "ff:ff:ff:ff:ff:ff"
        if dst_ip == "224.0.0.9":
            dst_mac = "01:00:5e:00:00:09"
    else:
        if version == 2:
            dst_ip  = "224.0.0.9"
            dst_mac = "01:00:5e:00:00:09"
        else:
            dst_ip  = "255.255.255.255"
            dst_mac = "ff:ff:ff:ff:ff:ff"

    print(f"[*] RIP Request  interface={iface}  target={dst_ip}  "
          f"version=RIPv{version}  timeout={args.timeout}s")

    rip_data = build_rip_request(version)
    pkt = (
        Ether(dst=dst_mac)
        / IP(dst=dst_ip, ttl=1)
        / UDP(sport=520, dport=520)
        / rip_data
    )

    try:
        sendp(pkt, iface=iface, verbose=False)
        print("[+] RIP Request sent")
    except PermissionError:
        print("[!] Permission denied — re-run with sudo/root", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[!] Send failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.send_only:
        return

    print(f"[*] Listening for RIP Responses for {args.timeout}s ...")
    print()

    routes: list = []
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
        print("[*] No RIP routes received. Verify the target router is "
              "RIP-enabled, reachable on UDP/520, and that you are on the "
              "same broadcast/multicast segment.")


if __name__ == "__main__":
    main()
