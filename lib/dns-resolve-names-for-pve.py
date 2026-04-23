#!/usr/bin/env python3
"""Resolve names in names-review.txt to IPs and write pve-allowed-staged.txt (controller)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from dns_audit_names_lib import load_names_review, write_pve_staged  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--names-review",
        type=Path,
        default=Path("names-review.txt"),
        help="Input: merged FQDN list with last-request timestamps",
    )
    ap.add_argument(
        "--pve-staged",
        type=Path,
        default=Path(".pve-allowed-staged.txt"),
        help="Output: IP lines for proxmox-update-allowed-ips.py",
    )
    ap.add_argument(
        "--ipv4-only",
        action="store_true",
        help="Only IPv4 addresses from getaddrinfo",
    )
    args = ap.parse_args()
    nr = args.names_review
    if not nr.is_file():
        print(f"not a file: {nr}", file=sys.stderr)
        return 1
    last = load_names_review(nr)
    if not last:
        print(f"warning: no names in {nr}", file=sys.stderr)
    n_lines = write_pve_staged(args.pve_staged, last, args.ipv4_only)
    print(f"Wrote {args.pve_staged} ({n_lines} IP lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
