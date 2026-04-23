#!/usr/bin/env python3
"""Resolve hostname lists to IPs, stage dns-ips (no GAI), write staged files for PVE merge (controller)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from dns_audit_names_lib import (  # noqa: E402
    load_names_review,
    load_plain_hostnames,
    write_pve_staged,
    write_pve_staged_ip_literals,
    write_pve_staged_plain_names,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--apt-names",
        type=Path,
        default=Path("apt-names.txt"),
        help="Input: one FQDN per line (APT mirrors, etc.)",
    )
    ap.add_argument(
        "--ntp-names",
        type=Path,
        default=Path("ntp.txt"),
        help="Input: one FQDN per line (NTP servers)",
    )
    ap.add_argument(
        "--names-review",
        type=Path,
        default=Path("names-review.txt"),
        help="Input: merged FQDN list with last-request timestamps",
    )
    ap.add_argument(
        "--apt-staged",
        type=Path,
        default=Path(".pve-apt-names-staged.txt"),
        help="Output: IP lines for [IPSET apt-names]",
    )
    ap.add_argument(
        "--ntp-staged",
        type=Path,
        default=Path(".pve-ntp-names-staged.txt"),
        help="Output: IP lines for [IPSET ntp-names]",
    )
    ap.add_argument(
        "--pve-staged",
        type=Path,
        default=Path(".pve-allowed-staged.txt"),
        help="Output: IP lines for [IPSET reviewed-names]",
    )
    ap.add_argument(
        "--dns-ips",
        type=Path,
        default=Path("dns-ips.txt"),
        help="Input: one address or CIDR per line (DNS resolvers; no resolution on controller)",
    )
    ap.add_argument(
        "--dns-ips-staged",
        type=Path,
        default=Path(".pve-dns-ips-staged.txt"),
        help="Output: IP lines for [IPSET dns-ips]",
    )
    ap.add_argument(
        "--ipv4-only",
        action="store_true",
        help="Only IPv4 addresses from getaddrinfo; for --dns-ips, drop IPv6 lines",
    )
    args = ap.parse_args()

    ipv4 = args.ipv4_only

    if args.apt_names.is_file():
        hosts = load_plain_hostnames(args.apt_names)
        n_apt = write_pve_staged_plain_names(args.apt_staged, hosts, ipv4)
        print(f"Wrote {args.apt_staged} ({n_apt} IP lines) from {args.apt_names}")
    else:
        args.apt_staged.write_text("", encoding="utf-8")
        print(
            f"skip apt: not a file {args.apt_names}; wrote empty {args.apt_staged}",
            file=sys.stderr,
        )

    if args.ntp_names.is_file():
        hosts = load_plain_hostnames(args.ntp_names)
        n_ntp = write_pve_staged_plain_names(args.ntp_staged, hosts, ipv4)
        print(f"Wrote {args.ntp_staged} ({n_ntp} IP lines) from {args.ntp_names}")
    else:
        args.ntp_staged.write_text("", encoding="utf-8")
        print(
            f"skip ntp: not a file {args.ntp_names}; wrote empty {args.ntp_staged}",
            file=sys.stderr,
        )

    if args.names_review.is_file():
        last = load_names_review(args.names_review)
        if not last:
            print(f"warning: no names in {args.names_review}", file=sys.stderr)
        n_rev = write_pve_staged(args.pve_staged, last, ipv4)
        print(f"Wrote {args.pve_staged} ({n_rev} IP lines) from {args.names_review}")
    else:
        args.pve_staged.write_text("", encoding="utf-8")
        print(
            f"skip reviewed: not a file {args.names_review}; wrote empty {args.pve_staged}",
            file=sys.stderr,
        )

    if not args.dns_ips.is_file():
        args.dns_ips_staged.write_text("", encoding="utf-8")
        print(
            f"skip dns-ips: not a file {args.dns_ips}; wrote empty {args.dns_ips_staged}",
            file=sys.stderr,
        )
    else:
        n_dns = write_pve_staged_ip_literals(
            args.dns_ips_staged, args.dns_ips, ipv4
        )
        print(
            f"Wrote {args.dns_ips_staged} ({n_dns} IP lines) from {args.dns_ips} "
            "(no getaddrinfo)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
