#!/usr/bin/env python3
"""Extract HTTP(S) apt mirror hostnames and NTP time peers from local config; write sorted lists.

Intended to run on the target host (root) so /etc/apt and ntp config are read in place.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

# Classic one-line: deb [arch=amd64,…] http://host/path …
_RE_DEB = re.compile(
    r"^deb(?:-src)?\s+(?:\[[^\]]+\]\s+)?(https?://\S+)",
    re.IGNORECASE,
)
# Any http(s) token in a .sources file (Debian Deb822, incl. under URIs:)
_RE_HTTPS_TOKEN = re.compile(r"\bhttps?://[^/\s#][^\s#]*", re.IGNORECASE)

# chrony / ntpd: server|pool, optional minpoll etc.
_RE_NTP_SVC = re.compile(r"^(?:server|pool)\s+(\S+)", re.IGNORECASE)

_TIMESYNC_NTP = re.compile(r"^(NTP|FallbackNTP)\s*=\s*(.+)$", re.IGNORECASE)

_APT_DIRS = (Path("/etc/apt/sources.list"), Path("/etc/apt/sources.list.d"))


def _netloc_from_http_url(url: str) -> str | None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    host = p.netloc.rsplit("@", 1)[-1]
    if host.startswith("[") and "]" in host:
        if host.count(":") > 1:
            return host[1 : host.rindex("]")].lower()
    if not host.startswith("[") and host.count(":") == 1:
        h, port = host.rsplit(":", 1)
        if port.isdigit() and port in ("80", "443", "8080"):
            return h.lower()
    return host.lower().strip()


def _iter_apt_list_lines(path: Path) -> set[str]:
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"apt: skip {path}: {e}", file=sys.stderr)
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _RE_DEB.match(line)
        if not m:
            continue
        base = m.group(1)
        h = _netloc_from_http_url(base)
        if h:
            out.add(h)
    return out


def _iter_apt_sources_deb822(path: Path) -> set[str]:
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"apt: skip {path}: {e}", file=sys.stderr)
        return out
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        for m in _RE_HTTPS_TOKEN.finditer(line):
            u = m.group(0)
            h = _netloc_from_http_url(u)
            if h:
                out.add(h)
    return out


def collect_apt_hosts() -> set[str]:
    out: set[str] = set()
    sl = _APT_DIRS[0]
    if sl.is_file():
        out |= _iter_apt_list_lines(sl)
    d = _APT_DIRS[1]
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if not p.is_file():
                continue
            if p.suffix == ".list":
                out |= _iter_apt_list_lines(p)
            elif p.suffix == ".sources":
                out |= _iter_apt_sources_deb822(p)
    return out


def _parse_timesyncd(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            m = _TIMESYNC_NTP.match(line)
            if m:
                for tok in m.group(2).split():
                    tok = tok.strip()
                    if tok:
                        out.add(tok.lower() if re.match(r"^[a-z0-9._-]+$", tok, re.I) else tok)
    except OSError as e:
        print(f"ntp: skip {path}: {e}", file=sys.stderr)
    return out


def _parse_chrony_or_ntp(path: Path) -> set[str]:
    out: set[str] = set()
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.split("#", 1)[0].strip()
            if not s or s.startswith("!") or s.startswith("bindcmdaddress"):
                continue
            m = _RE_NTP_SVC.match(s)
            if m:
                h = m.group(1).split("#", 1)[0].strip()
                if h and not h.startswith("-"):
                    if re.match(r"^[\[0-9a-fA-F:.]+%[a-z0-9_-]+]$", h):
                        continue
                    out.add(h.lower() if re.match(r"^[a-z0-9._-]+$", h, re.I) else h)
    except OSError as e:
        print(f"ntp: skip {path}: {e}", file=sys.stderr)
    return out


def collect_ntp_peers() -> set[str]:
    out: set[str] = set()
    out |= _parse_timesyncd(Path("/etc/systemd/timesyncd.conf"))
    for p in (Path("/etc/chrony/chrony.conf"), Path("/etc/chrony.conf")):
        out |= _parse_chrony_or_ntp(p)
    out |= _parse_chrony_or_ntp(Path("/etc/ntp.conf"))
    return out


def _write_sorted(path: Path, items: set[str]) -> None:
    lines = [x for x in (s.strip() for s in items) if x]
    data = "\n".join(sorted(lines, key=str.lower)) + ("\n" if lines else "")
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/var/lib/dns-audit"),
        help="Directory for apt-names.txt and ntp.txt",
    )
    args = ap.parse_args()
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    apt = collect_apt_hosts()
    ntp = collect_ntp_peers()
    apt_path = out_dir / "apt-names.txt"
    ntp_path = out_dir / "ntp.txt"
    _write_sorted(apt_path, apt)
    _write_sorted(ntp_path, ntp)
    print(
        f"Wrote {apt_path} ({apt_path.stat().st_size} bytes), "
        f"{ntp_path} ({ntp_path.stat().st_size} bytes)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
