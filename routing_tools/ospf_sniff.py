#!/usr/bin/env python3
"""
OSPF discovery tool: tshark-based passive capture with optional active
Hello injection (Scapy) to elicit immediate neighbour responses.

Passive mode (default)
----------------------
Uses tshark for full OSPF dissection:
  - All message types: Hello, DBD, LSRequest, LSUpdate, LSAck
  - All LSA types including Opaque (9/10/11) and OSPFv3
  - Structured JSON field extraction; more reliable than manual struct parsing

Active mode  (--active)
-----------------------
Sends a crafted OSPF Hello to the AllSPFRouters multicast (224.0.0.5) via
Scapy before the passive capture begins.  Any OSPF-enabled router on the
segment will reply with its own Hello, immediately revealing itself rather
than waiting for its periodic Hello timer to fire.

Requires root/CAP_NET_RAW. Requires tshark. Active mode additionally
requires scapy with the OSPF contrib module (pip3 install scapy).

Usage
-----
  python3 ospf_sniff.py [--iface IFACE] [--timeout SECS] [--verbose]
                         [--active [--router-id ID] [--area AREA]
                          [--src-ip IP] [--netmask MASK]]

Examples
--------
  # Passive capture on eth0 for 60 seconds
  python3 ospf_sniff.py --iface eth0

  # Active probe: send Hello then listen for responses
  python3 ospf_sniff.py --iface eth0 --active

  # Active probe with custom router-ID and area
  python3 ospf_sniff.py --iface eth0 --active --router-id 10.0.0.254 --area 0.0.0.1

  # Verbose: print every OSPF message, not just summaries
  python3 ospf_sniff.py --iface eth0 --verbose --timeout 120
"""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from collections import defaultdict

OSPF_TYPE_NAMES = {
    "1": "Hello", "2": "DBD", "3": "LSReq", "4": "LSUpdate", "5": "LSAck",
}
LSA_TYPE_NAMES = {
    "1": "Router", "2": "Network", "3": "SummaryIP", "4": "SummaryASBR",
    "5": "ASExternal", "7": "NSSA-External",
    "9": "Opaque-Link", "10": "Opaque-Area", "11": "Opaque-AS",
}


def _find(d, *keys, default="?"):
    for key in keys:
        if isinstance(d, dict):
            if key in d:
                return str(d[key])
            for v in d.values():
                if isinstance(v, dict):
                    result = _find(v, key, default=None)
                    if result is not None:
                        return result
    return default


def _find_list(d, *keys):
    for key in keys:
        if isinstance(d, dict):
            if key in d:
                val = d[key]
                if isinstance(val, list):
                    return [str(x) for x in val]
                if val is not None:
                    return [str(val)]
            for v in d.values():
                if isinstance(v, dict):
                    result = _find_list(v, key)
                    if result:
                        return result
    return []


def _ospf_layers(layers):
    raw = layers.get("ospf")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _get_iface_ip(iface):
    try:
        import fcntl, struct
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packed = fcntl.ioctl(sock.fileno(), 0x8915,
                             struct.pack("256s", iface[:15].encode()))
        sock.close()
        return socket.inet_ntoa(packed[20:24])
    except Exception:
        return "1.1.1.1"


def _get_iface_mask(iface):
    try:
        import fcntl, struct
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packed = fcntl.ioctl(sock.fileno(), 0x891b,
                             struct.pack("256s", iface[:15].encode()))
        sock.close()
        return socket.inet_ntoa(packed[20:24])
    except Exception:
        return "255.255.255.0"


def send_ospf_hello(iface, router_id, area, src_ip, netmask):
    """Send a single OSPF Hello to 224.0.0.5 (AllSPFRouters) via Scapy."""
    try:
        from scapy.contrib.ospf import OSPF_Hdr, OSPF_Hello
        from scapy.all import Ether, IP, sendp, conf
    except ImportError:
        print("[!] scapy with OSPF contrib not available. "
              "Install with: pip3 install scapy", file=sys.stderr)
        sys.exit(1)

    if not iface:
        iface = conf.iface

    pkt = (
        Ether(dst="01:00:5e:00:00:05")
        / IP(src=src_ip, dst="224.0.0.5", ttl=1, proto=89)
        / OSPF_Hdr(version=2, type=1, src=router_id, area=area)
        / OSPF_Hello(
            mask=netmask,
            hellointerval=10,
            prio=0,
            deadinterval=40,
            router=0,
            backup=0,
        )
    )

    try:
        sendp(pkt, iface=iface, verbose=False)
        print(f"[+] OSPF Hello sent: src={src_ip} router_id={router_id} "
              f"area={area} iface={iface}")
    except PermissionError:
        print("[!] Permission denied — run with sudo/root", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[!] Failed to send OSPF Hello: {exc}", file=sys.stderr)
        sys.exit(1)


def run_tshark(iface, timeout):
    if not shutil.which("tshark"):
        print("Error: tshark not found. Install with: apt-get install tshark",
              file=sys.stderr)
        sys.exit(1)

    iface_args = ["-i", iface] if iface else ["-i", "any"]
    cmd = [
        "tshark", *iface_args,
        "-f", "ip proto 89",
        "-a", f"duration:{max(1, int(timeout))}",
        "-T", "json",
        "-Y", "ospf",
        "-l",
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except PermissionError:
        print("[!] Permission denied — run with sudo/root", file=sys.stderr)
        sys.exit(1)

    try:
        stdout, stderr = proc.communicate(timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()

    if not stdout.strip():
        if "permission" in stderr.lower() or "promiscuous" in stderr.lower():
            print("[!] tshark permission error — run as root/sudo", file=sys.stderr)
        return []

    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        trimmed = stdout.strip().rstrip(",").rstrip("]") + "]"
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            print("[!] Could not parse tshark JSON", file=sys.stderr)
            return []


def process_packets(packets, verbose):
    neighbours = {}
    lsa_db = {}
    type_counts = defaultdict(int)

    for pkt in packets:
        layers = pkt.get("_source", {}).get("layers", {})
        ip = layers.get("ip", {})
        src_ip = ip.get("ip.src", "?")

        for msg in _ospf_layers(layers):
            msg_type  = _find(msg, "ospf.msg", "ospf.header.msg", default="?")
            type_name = OSPF_TYPE_NAMES.get(msg_type, f"Type{msg_type}")
            router_id = _find(msg, "ospf.srcid", "ospf.header.router_id")
            area_id   = _find(msg, "ospf.area_id", "ospf.header.area_id")
            type_counts[type_name] += 1

            if msg_type == "1":
                if router_id not in neighbours:
                    netmask   = _find(msg, "ospf.hello.network_mask",
                                      "ospf.v2.hello.network_mask")
                    hello_int = _find(msg, "ospf.hello.hellointerval",
                                      "ospf.v2.hello.hello_interval")
                    dead_int  = _find(msg, "ospf.hello.router_dead_interval",
                                      "ospf.v2.hello.router_dead_interval",
                                      "ospf.hello.dead_interval")
                    prio      = _find(msg, "ospf.hello.router_priority",
                                      "ospf.v2.hello.router_priority")
                    dr        = _find(msg, "ospf.hello.designated_router",
                                      "ospf.v2.hello.designated_router")
                    bdr       = _find(msg, "ospf.hello.backup_designated_router",
                                      "ospf.v2.hello.backup_designated_router",
                                      "ospf.hello.backup")
                    nbrs      = _find_list(msg, "ospf.hello.active_neighbor",
                                           "ospf.v2.hello.active_neighbor")
                    print(f"[+] OSPF neighbour discovered")
                    print(f"    Router ID : {router_id}")
                    print(f"    Area      : {area_id}")
                    print(f"    Src IP    : {src_ip}")
                    print(f"    Netmask   : {netmask}")
                    print(f"    Intervals : hello={hello_int}s  dead={dead_int}s")
                    print(f"    Priority  : {prio}")
                    print(f"    DR        : {dr}")
                    print(f"    BDR       : {bdr}")
                    if nbrs:
                        print(f"    Neighbours: {', '.join(nbrs)}")
                    print()
                    neighbours[router_id] = {
                        "router_id": router_id, "area_id": area_id,
                        "src_ip": src_ip, "netmask": netmask,
                        "hello_interval": hello_int, "dead_interval": dead_int,
                        "priority": prio, "dr": dr, "bdr": bdr,
                    }

            elif msg_type == "4":
                lsa_list = msg.get("ospf.v2.lsa") or msg.get("ospf.lsa") or []
                if isinstance(lsa_list, dict):
                    lsa_list = [lsa_list]
                for lsa in lsa_list:
                    if not isinstance(lsa, dict):
                        continue
                    ls_type = _find(lsa, "ospf.lsa.type", "ospf.v2.lsa.type")
                    ls_id   = _find(lsa, "ospf.lsa.id", "ospf.v2.lsa.id",
                                    "ospf.link_state_id")
                    adv_rtr = _find(lsa, "ospf.lsa.adv_router",
                                    "ospf.v2.lsa.adv_router", "ospf.advrouter")
                    ls_seq  = _find(lsa, "ospf.lsa.seqnum", "ospf.v2.lsa.seqnum")
                    ls_age  = _find(lsa, "ospf.lsa.age", "ospf.v2.lsa.age")
                    key     = (ls_type, ls_id, adv_rtr)
                    if key not in lsa_db:
                        tname_lsa = LSA_TYPE_NAMES.get(ls_type, f"Type{ls_type}")
                        print(f"[+] LSA {tname_lsa:<14}  ls_id={ls_id:<15}  "
                              f"adv={adv_rtr:<15}  seq={ls_seq}  age={ls_age}s")
                        fwd = _find(lsa, "ospf.v2.lsa.ase.fwd_addr",
                                    "ospf.lsa.ase.fwd_addr", default=None)
                        if fwd and fwd != "?":
                            mask   = _find(lsa, "ospf.v2.lsa.ase.netmask",
                                           "ospf.lsa.ase.netmask")
                            metric = _find(lsa, "ospf.v2.lsa.ase.metric",
                                           "ospf.lsa.ase.metric")
                            print(f"    mask={mask}  metric={metric}  fwd={fwd}")
                        lsa_db[key] = {
                            "type": ls_type, "ls_id": ls_id,
                            "adv_router": adv_rtr, "seq": ls_seq,
                        }

            elif verbose:
                print(f"[.] {type_name:<10} router_id={router_id}  "
                      f"area={area_id}  src={src_ip}")

    return neighbours, lsa_db, dict(type_counts)


def parse_args():
    p = argparse.ArgumentParser(
        description="OSPF passive sniffer (tshark) with optional active Hello probe (Scapy)"
    )
    p.add_argument("--iface",     default=None,
                   help="Network interface (default: tshark 'any')")
    p.add_argument("--timeout",   type=float, default=60.0,
                   help="Capture duration in seconds (default: 60)")
    p.add_argument("--verbose",   action="store_true",
                   help="Print all OSPF message types, not just Hello/LSUpdate")

    act = p.add_argument_group("Active probe options")
    act.add_argument("--active",    action="store_true",
                     help="Send a crafted OSPF Hello to elicit immediate responses")
    act.add_argument("--router-id", default=None,
                     help="Router-ID for Hello (default: interface primary IP)")
    act.add_argument("--area",      default="0.0.0.0",
                     help="OSPF area for Hello (default: 0.0.0.0 backbone)")
    act.add_argument("--src-ip",    default=None,
                     help="Source IP for Hello (default: interface primary IP)")
    act.add_argument("--netmask",   default=None,
                     help="Netmask for Hello (default: interface netmask)")
    return p.parse_args()


def main():
    args = parse_args()

    print(f"[*] OSPF discovery  iface={args.iface or 'any'}  "
          f"timeout={args.timeout}s  "
          f"mode={'active+passive' if args.active else 'passive'}")
    print()

    if args.active:
        iface     = args.iface or ""
        src_ip    = args.src_ip   or (iface and _get_iface_ip(iface))   or "1.1.1.1"
        netmask   = args.netmask  or (iface and _get_iface_mask(iface)) or "255.255.255.0"
        router_id = args.router_id or src_ip
        print(f"[*] Sending OSPF Hello to 224.0.0.5 (AllSPFRouters) ...")
        send_ospf_hello(iface or None, router_id, args.area, src_ip, netmask)
        time.sleep(1)
        print()

    print(f"[*] Listening for OSPF (IP proto 89) via tshark ...")
    if args.active:
        print(f"[*] Neighbours should respond promptly to the Hello probe.")
    print()

    packets = run_tshark(args.iface, args.timeout)

    if not packets:
        print("[*] No OSPF traffic captured.")
        print("[*] Tips:")
        print("    - Confirm you are on the same L2 segment as an OSPF router")
        print("    - Try --active to send a Hello and elicit immediate responses")
        print("    - Use --iface to select the correct interface")
        return

    neighbours, lsa_db, type_counts = process_packets(packets, args.verbose)

    print()
    print(f"[*] Capture complete")
    print(f"[*] Packet types: " +
          ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items())))
    print(f"[*] Neighbours discovered: {len(neighbours)}")
    for rid, info in neighbours.items():
        print(f"    {rid}  area={info['area_id']}  src={info['src_ip']}")
    print(f"[*] LSA entries seen: {len(lsa_db)}")
    by_type = defaultdict(int)
    for (t, _lid, _adv) in lsa_db:
        by_type[LSA_TYPE_NAMES.get(t, f"Type{t}")] += 1
    for tname, count in sorted(by_type.items()):
        print(f"    {tname}: {count}")


if __name__ == "__main__":
    main()
