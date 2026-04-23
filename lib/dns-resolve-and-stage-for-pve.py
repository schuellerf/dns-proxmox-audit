#!/usr/bin/env python3
"""
Merge per-hour *dns-names.txt (from a trusted pull) and optionally resolve to IPs
on this machine (controller / Ansible host). DNS uses this host's resolver, not
the target (audit) host.
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Optional _ between ymdh and offset: legacy 2026…_+0100-… vs current 2026…+0100-…
_FNAME = re.compile(r"^(\d{10})_?([+-]\d{4})-dns-names\.txt$")


def _parse_filename(path: Path) -> datetime | None:
    m = _FNAME.match(path.name)
    if not m:
        return None
    ymdh, off = m.group(1), m.group(2)
    try:
        base = datetime.strptime(ymdh, "%Y%m%d%H")
    except ValueError:
        return None
    sign = 1 if off[0] == "+" else -1
    h, mi = int(off[1:3]), int(off[3:5])
    delta = sign * (timedelta(hours=h, minutes=mi))
    return base.replace(tzinfo=timezone(delta))


def _format_last_request(dt: datetime) -> str:
    ymdh = dt.strftime("%Y%m%d%H")
    z = dt.strftime("%z")
    if not z:
        return f"{ymdh}+0000"
    return f"{ymdh}{z}"


def _load_hourly(
    input_dir: Path,
) -> dict[str, datetime]:
    """FQDN -> latest observed instant from filenames + contents."""
    last: dict[str, datetime] = {}
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        ts = _parse_filename(p)
        if ts is None:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"skip {p}: {e}", file=sys.stderr)
            continue
        for line in text.splitlines():
            n = line.strip().lower()
            if not n or n.startswith("#"):
                continue
            n = n.rstrip(".")
            if not n or "." not in n:
                continue
            if n not in last or last[n] < ts:
                last[n] = ts
    return last


def _resolve(name: str, ipv4_only: bool) -> tuple[list[str], str | None]:
    fam0 = socket.AF_INET if ipv4_only else 0
    try:
        infos = socket.getaddrinfo(name, None, fam0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return [], str(e)
    seen: set[str] = set()
    out: list[str] = []
    for fam, _, _, _, sa in infos:
        if fam not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = sa[0]
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory of hourly *dns-names.txt (YYYYMMDDHH+0000-dns-names.txt; legacy _+0000 also accepted)",
    )
    ap.add_argument(
        "--names-review",
        type=Path,
        required=True,
        help="Write: name # last request: YYYYMMDDHH+zzzz",
    )
    ap.add_argument(
        "--pve-staged",
        type=Path,
        help="With --emit-pve: write IP # name last request: ... (for proxmox-update-allowed-ips.py)",
    )
    ap.add_argument(
        "--emit-pve",
        action="store_true",
        help="Resolve names on this host and write --pve-staged",
    )
    ap.add_argument(
        "--ipv4-only",
        action="store_true",
        help="Only socket.AF_INET in getaddrinfo for --emit-pve",
    )
    args = ap.parse_args()
    if args.emit_pve and not args.pve_staged:
        ap.error("--emit-pve requires --pve-staged")
    if not args.input_dir.is_dir():
        print(f"not a directory: {args.input_dir}", file=sys.stderr)
        return 1
    last = _load_hourly(args.input_dir)
    if not last:
        print("warning: no names merged (empty or no matching files)", file=sys.stderr)
    lines = [
        f"{n} # last request: {_format_last_request(last[n])}" for n in sorted(last)
    ]
    data = "\n".join(lines) + ("\n" if lines else "")
    args.names_review.write_text(data, encoding="utf-8")
    print(f"Wrote {args.names_review} ({len(last)} names)")
    if not args.emit_pve:
        return 0
    pve_lines: list[str] = []
    for n in sorted(last):
        fr = _format_last_request(last[n])
        ips, err = _resolve(n, args.ipv4_only)
        if err:
            print(f"resolve fail {n}: {err}", file=sys.stderr)
            continue
        if not ips:
            print(f"no record: {n}", file=sys.stderr)
            continue
        for ip in ips:
            pve_lines.append(f"{ip} # {n} last request: {fr}")
    data2 = "\n".join(pve_lines) + ("\n" if pve_lines else "")
    sp = args.pve_staged
    assert sp is not None
    sp.write_text(data2, encoding="utf-8")
    print(f"Wrote {sp} ({len(pve_lines)} IP lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
