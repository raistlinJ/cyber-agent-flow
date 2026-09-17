"""Harmless reference tool used to verify the container testing integration."""
import argparse
import json
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description="Inspect an HTTP endpoint")
parser.add_argument("url")
args = parser.parse_args()
try:
    with urllib.request.urlopen(args.url, timeout=3) as response:
        print(json.dumps({"status": response.status, "body": response.read().decode()}))
except (urllib.error.URLError, ValueError) as exc:
    parser.exit(1, f"Request failed: {exc}\n")
