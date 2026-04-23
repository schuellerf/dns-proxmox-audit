"""Merge hourly DNS name exports and resolve names-review lines for Proxmox staging."""

from __future__ import annotations

import ipaddress
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Matches audit_export_common.filename_for_hour_start: YYYYMMDDHH+oooo-dns-names.txt
_HOURLY_FNAME = re.compile(r"^(\d{10})([+-]\d{4})-dns-names\.txt$")

_NAMES_REVIEW_MARKER = " # last request: "


def parse_hourly_filename(path: Path) -> datetime | None:
    m = _HOURLY_FNAME.match(path.name)
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


def format_last_request(dt: datetime) -> str:
    ymdh = dt.strftime("%Y%m%d%H")
    z = dt.strftime("%z")
    if not z:
        return f"{ymdh}+0000"
    return f"{ymdh}{z}"


def load_hourly(input_dir: Path) -> dict[str, datetime]:
    """FQDN -> latest observed instant from hourly filenames + file contents."""
    last: dict[str, datetime] = {}
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        ts = parse_hourly_filename(p)
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


def load_names_review(path: Path) -> dict[str, datetime]:
    """Parse names-review.txt lines into FQDN -> last-request instant."""
    last: dict[str, datetime] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"read {path}: {e}", file=sys.stderr)
        return last
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _NAMES_REVIEW_MARKER not in line:
            continue
        name, ts_part = line.split(_NAMES_REVIEW_MARKER, 1)
        name = name.strip().lower().rstrip(".")
        ts_s = ts_part.strip()
        if not name or "." not in name:
            continue
        try:
            ts = datetime.strptime(ts_s, "%Y%m%d%H%z")
        except ValueError:
            continue
        last[name] = ts
    return last


def write_names_review(path: Path, last: dict[str, datetime]) -> None:
    lines = [
        f"{n} # last request: {format_last_request(last[n])}" for n in sorted(last)
    ]
    data = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(data, encoding="utf-8")


def resolve_name(name: str, ipv4_only: bool) -> tuple[list[str], str | None]:
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


def write_pve_staged(path: Path, last: dict[str, datetime], ipv4_only: bool) -> int:
    pve_lines: list[str] = []
    for n in sorted(last):
        fr = format_last_request(last[n])
        ips, err = resolve_name(n, ipv4_only)
        if err:
            print(f"resolve fail {n}: {err}", file=sys.stderr)
            continue
        if not ips:
            print(f"no record: {n}", file=sys.stderr)
            continue
        for ip in ips:
            pve_lines.append(f"{ip} # {n} last request: {fr}")
    data = "\n".join(pve_lines) + ("\n" if pve_lines else "")
    path.write_text(data, encoding="utf-8")
    return len(pve_lines)


def load_plain_hostnames(path: Path) -> list[str]:
    """One FQDN per line (comments and empty lines ignored)."""
    names: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"read {path}: {e}", file=sys.stderr)
        return names
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        n = line.lower().rstrip(".")
        if not n or "." not in n:
            continue
        names.append(n)
    return names


def write_pve_staged_plain_names(
    path: Path, hostnames: list[str], ipv4_only: bool
) -> int:
    """Resolve plain hostname list to IP lines (ip # hostname)."""
    pve_lines: list[str] = []
    for n in sorted(set(hostnames)):
        ips, err = resolve_name(n, ipv4_only)
        if err:
            print(f"resolve fail {n}: {err}", file=sys.stderr)
            continue
        if not ips:
            print(f"no record: {n}", file=sys.stderr)
            continue
        for ip in ips:
            pve_lines.append(f"{ip} # {n}")
    data = "\n".join(pve_lines) + ("\n" if pve_lines else "")
    path.write_text(data, encoding="utf-8")
    return len(pve_lines)


def write_pve_staged_ip_literals(
    path: Path, input_path: Path, ipv4_only: bool
) -> int:
    """Read lines with address/CIDR tokens (e.g. dns-ips.txt); no getaddrinfo.

    Preserves a trailing line comment (``#`` …) when present. Drops IPv6 when
    ``ipv4_only`` is true. Invalid or empty lines are skipped.
    """
    pve_lines: list[str] = []
    if not input_path.is_file():
        path.write_text("", encoding="utf-8")
        return 0
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"read {input_path}: {e}", file=sys.stderr)
        path.write_text("", encoding="utf-8")
        return 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cmt = ""
        if "#" in s:
            s, cmt = s.split("#", 1)
            s, cmt = s.strip(), cmt.strip()
        tok = s.split()[0] if s else ""
        if not tok:
            continue
        if "/" in tok:
            try:
                net = ipaddress.ip_network(tok, strict=False)
            except ValueError:
                continue
            if ipv4_only and net.version != 4:
                continue
            left = str(net)
        else:
            try:
                addr = ipaddress.ip_address(tok)
            except ValueError:
                continue
            if ipv4_only and addr.version == 6:
                continue
            left = str(addr)
        pve_lines.append(f"{left} # {cmt}" if cmt else left)
    data = "\n".join(pve_lines) + ("\n" if pve_lines else "")
    path.write_text(data, encoding="utf-8")
    return len(pve_lines)
