#!/usr/bin/env python3
"""Merge IP lines into a Proxmox guest firewall [IPSET <name>] block."""

from __future__ import annotations

import argparse
import ipaddress
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_TAG = re.compile(r"\s*\(systemd-resolved\)\s*$")


def _parse_line(
    line: str, strip_resolved: bool
) -> tuple[str, str, str] | None:
    """(norm_key, left token, comment) for one IP/CIDR + optional comment, else None."""
    t = line.strip()
    if not t or t.startswith("#"):
        return None
    if "#" in t:
        left, cmt = t.split("#", 1)
        cmt = cmt.strip()
        if strip_resolved and cmt:
            cmt = _TAG.sub("", cmt).rstrip()
    else:
        left, cmt = t, ""
    left = left.split()[0].strip()
    if not left:
        return None
    try:
        if "/" in left:
            key = str(ipaddress.ip_network(left, strict=False))
        else:
            key = str(ipaddress.ip_address(left))
    except ValueError:
        return None
    return key, left, cmt


def _line_from_parts(left: str, cmt: str) -> str:
    return f"{left} # {cmt}" if cmt else left


def _parse_sections(text: str) -> list[tuple[str, list[str]]]:
    if not text.strip():
        return []
    out: list[tuple[str, list[str]]] = []
    name: str | None = None
    buf: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("[") and s.endswith("]") and s.count("[") == 1:
            if name is not None:
                out.append((name, buf))
            name = s
            buf = []
        else:
            if name is None:
                if not out:
                    name = "___PREAMBLE___"
                else:
                    continue
            buf.append(ln)
    if name is not None:
        out.append((name, buf))
    return out


def _serialize(sections: list[tuple[str, list[str]]]) -> str:
    parts: list[str] = []
    for name, body in sections:
        if name == "___PREAMBLE___":
            if body:
                parts.append("\n".join(body))
        else:
            b = "\n".join(body)
            parts.append(f"{name}\n{b}" if b else f"{name}\n")
    s = "\n\n".join(parts)
    if s and not s.endswith("\n"):
        s += "\n"
    return s


def _merge_block(
    body: list[str],
    staged: str,
    strip_resolved: bool,
    sort_keys: bool,
) -> list[str]:
    """Preamble (non-IP) lines, then one line per key (file order, then new from staged)."""
    meta: list[str] = []
    order: list[str] = []
    by: dict[str, str] = {}
    for ln in body:
        p = _parse_line(ln, strip_resolved)
        if p:
            k, left, cmt = p
            if k not in by:
                order.append(k)
            by[k] = _line_from_parts(left, cmt)
        else:
            meta.append(ln)
    for ln in staged.splitlines():
        p = _parse_line(ln, strip_resolved)
        if p:
            k, left, cmt = p
            if k in by:
                continue
            by[k] = _line_from_parts(left, cmt)
            order.append(k)
    out = [by[k] for k in order]
    if sort_keys:
        out = sorted(
            out, key=lambda r: (r.split("#", 1)[0].strip().lower(), r)
        )
    return meta + out


def merge_ipset(
    fw_text: str,
    staged: str,
    ipset: str,
    strip_resolved: bool,
    sort_keys: bool,
) -> str:
    header = f"[IPSET {ipset}]"
    sections = _parse_sections(fw_text)
    idx = -1
    for i, (n, _) in enumerate(sections):
        if n.split("#", 1)[0].strip() == header or n == header:
            idx = i
            break
    if idx < 0:
        sections.append(
            (header, _merge_block([], staged, strip_resolved, sort_keys))
        )
        return _serialize(sections)
    name, body = sections[idx]
    new_body = _merge_block(body, staged, strip_resolved, sort_keys)
    sections[idx] = (name, new_body)
    return _serialize(sections)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firewall", type=Path, required=True, help="Path to VMID.fw")
    ap.add_argument(
        "--input",
        type=Path,
        help="Staged file (IP # comment). Default: read stdin",
    )
    ap.add_argument(
        "--ipset",
        default="allowed-ips",
        help="Name inside [IPSET <name>] (default: allowed-ips)",
    )
    ap.add_argument(
        "--no-strip-systemd-resolved",
        action="store_true",
        help="Keep ' (systemd-resolved)' in the comment",
    )
    ap.add_argument(
        "--sort",
        action="store_true",
        help="Sort generated IP lines (meta lines from the file stay first)",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Write merged to stdout; no file IO"
    )
    ap.add_argument(
        "--no-backup", action="store_true", help="Do not create .fw.bak.<timestamp>"
    )
    ap.add_argument(
        "--no-compile",
        action="store_true",
        help="Do not run pve-firewall compile (e.g. on a dev box without PVE tools)",
    )
    args = ap.parse_args()
    staged = args.input.read_text() if args.input else sys.stdin.read()
    if not args.dry_run and not staged.strip():
        print("error: no staged data on stdin; use --input or pipe a file", file=sys.stderr)
        return 1
    data = args.firewall.read_text() if args.firewall.is_file() else ""
    out = merge_ipset(
        data,
        staged,
        args.ipset,
        strip_resolved=not args.no_strip_systemd_resolved,
        sort_keys=bool(args.sort),
    )
    if args.dry_run:
        sys.stdout.write(out)
        return 0
    bak: Path | None = None
    if not args.no_backup and args.firewall.is_file():
        bak = args.firewall.with_name(
            f"{args.firewall.name}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}UTC"
        )
        shutil.copy2(args.firewall, bak)
    t = args.firewall.with_name(f".{args.firewall.name}.tmp")
    t.write_text(out, encoding="utf-8")
    t.replace(args.firewall)
    if not args.no_compile:
        r = subprocess.run(
            ["pve-firewall", "compile"],
            check=False,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            print(f"pve-firewall compile failed: {msg}", file=sys.stderr)
            if bak is not None and bak.is_file():
                try:
                    shutil.copy2(bak, args.firewall)
                except OSError as e:
                    print(f"rollback copy failed: {e}", file=sys.stderr)
            return r.returncode or 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
