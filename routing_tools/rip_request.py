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

Examples:
  # Enumerate routes from all RIPv2 neighbours on eth0
  python3 rip_request.py --iface eth0

  # Target a specific router with RIPv1 broadcast
  python3 rip_request.py --iface eth0 --target 192.168.1.1 --version 1

  # Send 3 requests, listen 30 s, custom source IP
  python3 rip_request.py --iface eth0 --src-ip 10.0.0.5 --count 3 --timeout 30
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
    return p.parse_args()


# ---------------------------------------------------------------------------
# RIP packet construction
# ---------------------------------------------------------------------------
def build_rip_request(version: int) -> bytes:
    """
    Build a minimal RIP Request asking for the full routing table.

    Per RFC 2453 §3.9.1 a single entry with AFI=0 and metric=16 means
    "please send me your entire routing table".

    Wire layout
    -----------
    Header (4 bytes):  cmd=1, version, reserved=0
    Entry  (20 bytes): AFI=0, tag=0, addr=0, mask=0, nexthop=0, metric=16
    """
    header = struct.pack("!BBH", 1, version, 0)
    entry  = struct.pack("!HH4s4s4sI",
                         0, 0,
                         b"\x00\x00\x00\x00",
                         b"\x00\x00\x00\x00",
                         b"\x00\x00\x00\x00",
                         16)
    return header + entry


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

    rip_data = build_rip_request(version)

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
