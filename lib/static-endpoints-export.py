#!/usr/bin/env python3
"""Extract HTTP(S) apt mirror hostnames, NTP time peers, and DNS resolver IPs; write lists.

Reads /etc/apt and NTP-related config files, then augments NTP peers from runtime when
available: timedatectl show / timesync-status, systemd-analyze cat-config, and chronyc
if chronyd is active. Intended to run on the target host (root).

``ntp.txt`` lists FQDN-style hostnames only (at least one dot, not an IP literal); IP-only
NTP peers from config or runtime are omitted.

``dns-ips.txt`` lists resolvers the host uses (``resolvectl`` first, then resolv files).
Loopback and the systemd-resolved stub (127.0.0.53) are excluded so entries work as
outbound firewall destination addresses.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import subprocess
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
_RE_TIMESYNC_STATUS_SERVER = re.compile(r"^\s*Server:\s*(.+)$", re.MULTILINE)
_RE_CHRONY_REF_HOST = re.compile(r"\(([^)]+)\)\s*$")

_APT_DIRS = (Path("/etc/apt/sources.list"), Path("/etc/apt/sources.list.d"))

# resolvectl(1): "Link 2 (eth0)"-style; Global block for resolvers
_RE_RESOLVECTL_LINK = re.compile(r"^Link \d+ \(([^)]+)\)\s*$")
_RE_RESOLVECTL_DNS_SERVER = re.compile(
    r"^\s*DNS Servers?:\s*(.+?)\s*$", re.IGNORECASE
)


def _dns_resolvers_skip_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(ip.is_loopback or ip.is_unspecified)


def _normalize_ip_token(raw: str) -> str | None:
    t = raw.strip()
    if not t or t == "Global:":
        return None
    if t.endswith("%") or t.endswith("(") or t.endswith(")"):
        return None
    if "%" in t and not t.startswith("["):
        t = t.split("%", 1)[0]
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    try:
        a = ipaddress.ip_address(t)
    except ValueError:
        return None
    if _dns_resolvers_skip_ip(a):
        return None
    return str(a)


def _add_dns_from_line(
    line: str,
    label: str,
    out: dict[str, str],
) -> None:
    if not line or line.lstrip().startswith("#"):
        return
    for raw in re.split(r"\s+", line.strip()):
        if not raw or raw in (":", "(", ")"):
            continue
        norm = _normalize_ip_token(raw.rstrip(".,;:"))
        if not norm:
            continue
        if label:
            if norm not in out:
                out[norm] = label
            elif label not in out[norm].split(", "):
                out[norm] = f"{out[norm]}, {label}"
        else:
            out.setdefault(norm, "")


def _merge_resolvectl_dns(out: dict[str, str]) -> None:
    text = _run_text(["resolvectl", "dns"], timeout=8.0, err_prefix="resolvectl")
    if not text:
        return
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "Global:" or s == "Global (IPv4 and IPv6 only):":
            cur = "global"
            continue
        m = _RE_RESOLVECTL_LINK.match(line)
        if m:
            cur = m.group(1)
            continue
        if s.lower().startswith("global:") and len(s) > 7:
            cur = "global"
            _add_dns_from_line(s.split(":", 1)[1].strip(), "global", out)
            continue
        miface = re.match(
            r"^([^:\s][^:]*?):\s*(\S.*)$",
            s,
        )
        if miface and not s.lower().startswith("nameserver") and s.count(":") <= 1:
            # e.g. "wlp0s20f3: 1.1.1.1" (ifname; not IPv6 lines with many colons)
            cur, rest = miface.group(1).strip(), miface.group(2).strip()
            if cur.lower() != "global":
                _add_dns_from_line(rest, cur, out)
            continue
        if line[0].isspace() or (s and s[0].isdigit()) or s.startswith("[") or (
            ":" in s and any(c.isdigit() for c in s)
        ):
            _add_dns_from_line(s, cur, out)


def _merge_resolvectl_status(out: dict[str, str]) -> None:
    text = _run_text(
        ["resolvectl", "status", "--no-pager"],
        timeout=10.0,
        err_prefix="resolvectl",
    )
    if not text:
        return
    cur = ""
    for line in text.splitlines():
        m = _RE_RESOLVECTL_LINK.match(line.strip())
        if m:
            cur = m.group(1)
            continue
        m2 = _RE_RESOLVECTL_DNS_SERVER.match(line)
        if m2:
            _add_dns_from_line(m2.group(1), cur, out)


def _merge_resolv_file(path: Path, label: str, out: dict[str, str]) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"dns-ips: skip {path}: {e}", file=sys.stderr)
        return
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line.lower().startswith("nameserver "):
            continue
        _add_dns_from_line(line.split("nameserver", 1)[1].strip(), label, out)


def collect_dns_resolvers() -> set[str]:
    """Upstream DNS resolvers; loopback / stub 127.0.0.53 excluded via :func:`_dns_resolvers_skip_ip`."""
    by_ip: dict[str, str] = {}
    _merge_resolvectl_dns(by_ip)
    if not by_ip:
        _merge_resolvectl_status(by_ip)
    # Best-effort if resolvectl was empty: real servers sometimes appear only in per-netif resolv
    _netif = Path("/run/systemd/resolve/netif")
    if _netif.is_dir():
        for p in sorted(_netif.glob("*/resolv.conf")):
            _merge_resolv_file(p, f"netif {p.parent.name}", by_ip)
    if not by_ip:
        for path, label in (
            (Path("/run/systemd/resolve/resolv.conf"), "resolv"),
            (Path("/etc/resolv.conf"), "etc"),
        ):
            _merge_resolv_file(path, label, by_ip)
    lines: set[str] = set()
    for ip, cmt in sorted(by_ip.items(), key=lambda t: t[0]):
        lines.add(f"{ip} # {cmt}" if cmt else ip)
    return lines


def _is_ip_literal(tok: str) -> bool:
    t = tok.strip()
    if not t:
        return False
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    t = t.split("%", 1)[0]
    try:
        ipaddress.ip_address(t)
        return True
    except ValueError:
        return False


def _add_ntp_hostname(out: set[str], tok: str) -> None:
    tok = tok.strip()
    if not tok or tok.startswith("#"):
        return
    if _is_ip_literal(tok):
        return
    if "." not in tok:
        return
    out.add(tok.lower() if re.match(r"^[a-z0-9._-]+$", tok, re.I) else tok)


def _run_text(
    argv: list[str], timeout: float = 12.0, err_prefix: str = "ntp"
) -> str | None:
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(
            f"{err_prefix}: skip {' '.join(argv[:2])}…: {e}",
            file=sys.stderr,
        )
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _merge_timedatectl_show(out: set[str]) -> None:
    text = _run_text(["timedatectl", "show"])
    if not text:
        return
    for line in text.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key not in ("NTPServers", "FallbackNTP") or not val:
            continue
        for tok in val.split():
            _add_ntp_hostname(out, tok)


def _merge_timedatectl_timesync_status(out: set[str]) -> None:
    text = _run_text(["timedatectl", "timesync-status"])
    if not text:
        return
    m = _RE_TIMESYNC_STATUS_SERVER.search(text)
    if not m:
        return
    raw = m.group(1).strip()
    pair = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", raw)
    if pair:
        left, right = pair.group(1).strip(), pair.group(2).strip()
        lip, rip = _is_ip_literal(left), _is_ip_literal(right)
        # e.g. "185.x (ntp.ubuntu.com)" or "ntp.ubuntu.com (185.x)"
        if lip and not rip:
            _add_ntp_hostname(out, right)
        elif not lip and rip:
            _add_ntp_hostname(out, left)
        elif not lip and not rip:
            _add_ntp_hostname(out, left)
            _add_ntp_hostname(out, right)
        # both IPs: omit
    else:
        _add_ntp_hostname(out, raw)


def _merge_systemd_analyze_timesyncd(out: set[str]) -> None:
    text = _run_text(["systemd-analyze", "cat-config", "systemd/timesyncd.conf"])
    if not text:
        return
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        m = _TIMESYNC_NTP.match(line)
        if m:
            for tok in m.group(2).split():
                _add_ntp_hostname(out, tok)


def _chronyd_active() -> bool:
    text = _run_text(["systemctl", "is-active", "chronyd"], timeout=5.0)
    return bool(text and text.strip() == "active")


def _merge_chronyc_sources(out: set[str]) -> None:
    text = _run_text(["chronyc", "sources"])
    if not text:
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("=") or "Name/IP address" in s or s.startswith("MS "):
            continue
        if s.startswith("Number of sources"):
            continue
        parts = s.split()
        if len(parts) < 2:
            continue
        # Column 0 = mode (^*, ^-, …); column 1 = Name/IP address
        name = parts[1]
        if name.startswith("#"):
            continue
        _add_ntp_hostname(out, name)


def _merge_chronyc_tracking(out: set[str]) -> None:
    text = _run_text(["chronyc", "tracking"])
    if not text:
        return
    for line in text.splitlines():
        if "Reference ID" not in line:
            continue
        m = _RE_CHRONY_REF_HOST.search(line)
        if m:
            host = m.group(1).strip()
            if host:
                _add_ntp_hostname(out, host)
        break


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
                        _add_ntp_hostname(out, tok)
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
                    _add_ntp_hostname(out, h)
    except OSError as e:
        print(f"ntp: skip {path}: {e}", file=sys.stderr)
    return out


def collect_ntp_peers() -> set[str]:
    out: set[str] = set()
    out |= _parse_timesyncd(Path("/etc/systemd/timesyncd.conf"))
    tsd = Path("/etc/systemd/timesyncd.conf.d")
    if tsd.is_dir():
        for p in sorted(tsd.glob("*.conf")):
            out |= _parse_timesyncd(p)
    for p in (Path("/etc/chrony/chrony.conf"), Path("/etc/chrony.conf")):
        out |= _parse_chrony_or_ntp(p)
    out |= _parse_chrony_or_ntp(Path("/etc/ntp.conf"))
    _merge_timedatectl_show(out)
    _merge_timedatectl_timesync_status(out)
    _merge_systemd_analyze_timesyncd(out)
    if _chronyd_active():
        _merge_chronyc_sources(out)
        _merge_chronyc_tracking(out)
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
        help="Directory for apt-names.txt, ntp.txt, and dns-ips.txt",
    )
    args = ap.parse_args()
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    apt = collect_apt_hosts()
    ntp = collect_ntp_peers()
    dns = collect_dns_resolvers()
    apt_path = out_dir / "apt-names.txt"
    ntp_path = out_dir / "ntp.txt"
    dns_path = out_dir / "dns-ips.txt"
    _write_sorted(apt_path, apt)
    _write_sorted(ntp_path, ntp)
    _write_sorted(dns_path, dns)
    print(
        f"Wrote {apt_path} ({apt_path.stat().st_size} bytes), "
        f"{ntp_path} ({ntp_path.stat().st_size} bytes), "
        f"{dns_path} ({dns_path.stat().st_size} bytes)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
