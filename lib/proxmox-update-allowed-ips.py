#!/usr/bin/env python3
"""Merge IP lines into Proxmox guest firewall [IPSET] blocks (managed sets or legacy single ipset)."""

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
_SECTION_OPEN = re.compile(r"^(\[[^\]]+\])(.*)$")

# Order for inserting missing managed IPSETs before [RULES]
_MANAGED_IPSET_ORDER = ("apt-names", "ntp-names", "reviewed-names")


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


def _opening_section(ln: str) -> tuple[str, str] | None:
    """If ln opens a [section], return (canonical bracket token, original line)."""
    s = ln.strip()
    m = _SECTION_OPEN.match(s)
    if not m:
        return None
    rest = m.group(2)
    rs = rest.strip()
    if rs and not rs.startswith("#"):
        return None
    return m.group(1), ln


def _parse_sections(text: str) -> list[tuple[str, str | None, list[str]]]:
    """(canonical_name, original_header_line or None for preamble, body lines)."""
    if not text.strip():
        return []
    out: list[tuple[str, str | None, list[str]]] = []
    name: str | None = None
    hdr_line: str | None = None
    buf: list[str] = []
    for ln in text.splitlines():
        op = _opening_section(ln)
        if op is not None:
            canon, hdr = op
            if name is not None:
                out.append((name, hdr_line, buf))
            name, hdr_line = canon, hdr
            buf = []
        else:
            if name is None:
                if not out:
                    name = "___PREAMBLE___"
                    hdr_line = None
                else:
                    continue
            buf.append(ln)
    if name is not None:
        out.append((name, hdr_line, buf))
    return out


def _serialize_sections(
    sections: list[tuple[str, str | None, list[str]]],
) -> str:
    parts: list[str] = []
    for canon, hdr, body in sections:
        if canon == "___PREAMBLE___":
            if body:
                parts.append("\n".join(body))
        else:
            line = hdr if hdr is not None else canon
            b = "\n".join(body)
            parts.append(f"{line}\n{b}" if b else f"{line}\n")
    s = "\n\n".join(parts)
    if s and not s.endswith("\n"):
        s += "\n"
    return s


def _ipset_short_name(canon: str) -> str | None:
    if canon.startswith("[IPSET ") and canon.endswith("]"):
        return canon[len("[IPSET ") : -1]
    return None


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


def merge_firewall_managed_ipsets(
    fw_text: str,
    staged_by_name: dict[str, str],
    strip_resolved: bool,
    sort_keys: bool,
) -> str:
    """Merge only apt-names / ntp-names / reviewed-names; other sections unchanged."""
    managed = frozenset(_MANAGED_IPSET_ORDER)
    sections = list(_parse_sections(fw_text))
    in_place: set[str] = set()
    out: list[tuple[str, str | None, list[str]]] = []

    for canon, hdr, body in sections:
        short = _ipset_short_name(canon)
        if short in managed and short not in in_place:
            in_place.add(short)
            staged = staged_by_name.get(short, "")
            new_body = _merge_block(body, staged, strip_resolved, sort_keys)
            plain_hdr = f"[IPSET {short}]"
            out.append((canon, plain_hdr, new_body))
        else:
            out.append((canon, hdr, body))

    to_add = [n for n in _MANAGED_IPSET_ORDER if n not in in_place]
    new_blocks: list[tuple[str, str | None, list[str]]] = []
    for n in to_add:
        staged = staged_by_name.get(n, "")
        body = _merge_block([], staged, strip_resolved, sort_keys)
        plain = f"[IPSET {n}]"
        new_blocks.append((plain, plain, body))

    ri = next((i for i, (c, _, _) in enumerate(out) if c == "[RULES]"), -1)
    if ri >= 0:
        for i, block in enumerate(new_blocks):
            out.insert(ri + i, block)
    else:
        out.extend(new_blocks)

    return _serialize_sections(out)


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
    for i, (canon, _, _) in enumerate(sections):
        if canon == header:
            idx = i
            break
    if idx < 0:
        sections.append(
            (header, header, _merge_block([], staged, strip_resolved, sort_keys))
        )
        return _serialize_sections(sections)
    canon, _hdr, body = sections[idx]
    new_body = _merge_block(body, staged, strip_resolved, sort_keys)
    sections[idx] = (canon, header, new_body)
    return _serialize_sections(sections)


def _parse_managed_ipset_arg(s: str) -> tuple[str, Path]:
    if ":" not in s:
        raise argparse.ArgumentTypeError(
            "expected name:path, e.g. apt-names:.pve-apt-names-staged.txt"
        )
    name, path = s.split(":", 1)
    name = name.strip()
    path = path.strip()
    if not name or not path:
        raise argparse.ArgumentTypeError(f"invalid --managed-ipset {s!r}")
    return name, Path(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firewall", type=Path, required=True, help="Path to VMID.fw")
    ap.add_argument(
        "--managed-ipset",
        type=_parse_managed_ipset_arg,
        action="append",
        dest="managed_ipsets",
        metavar="NAME:PATH",
        help=(
            "Managed IPSET (apt-names, ntp-names, reviewed-names) and staged IP file; "
            "repeat. When set, only these IPSET bodies are merged; other sections unchanged."
        ),
    )
    ap.add_argument(
        "--input",
        type=Path,
        help="Staged file for legacy single --ipset mode (default: stdin)",
    )
    ap.add_argument(
        "--ipset",
        default="allowed-ips",
        help="Legacy: name inside [IPSET <name>] (default: allowed-ips)",
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
        help=(
            "Do not run pve-firewall compile. When deploying via Ansible, the playbook "
            "can run the script with compile, then systemctl reload pve-firewall; use this "
            "for dry runs without PVE tools."
        ),
    )
    args = ap.parse_args()
    strip = not args.no_strip_systemd_resolved
    sort_keys = bool(args.sort)

    if args.managed_ipsets:
        staged_by: dict[str, str] = {}
        for name, path in args.managed_ipsets:
            if name not in _MANAGED_IPSET_ORDER:
                print(
                    f"error: unknown managed IPSET {name!r} "
                    f"(expected one of {list(_MANAGED_IPSET_ORDER)})",
                    file=sys.stderr,
                )
                return 1
            staged_by[name] = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        data = args.firewall.read_text(encoding="utf-8", errors="replace") if args.firewall.is_file() else ""
        out = merge_firewall_managed_ipsets(data, staged_by, strip, sort_keys)
    else:
        staged = args.input.read_text(encoding="utf-8", errors="replace") if args.input else sys.stdin.read()
        if not args.dry_run and not staged.strip():
            print(
                "error: no staged data on stdin; use --input or pipe a file",
                file=sys.stderr,
            )
            return 1
        data = args.firewall.read_text(encoding="utf-8", errors="replace") if args.firewall.is_file() else ""
        out = merge_ipset(data, staged, args.ipset, strip, sort_keys)

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
