#!/usr/bin/env python3
"""Export systemd-resolved journal lines for a time range: FQDNs only (no IPs; trust merge on a controller).

Default (no time flags): start of the current clock hour through now — for interactive runs.
Use --previous-hour for the last completed local clock hour (used by the systemd timer).
Optionally set an explicit range with --since and --until together.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
from audit_export_common import (  # noqa: E402
    current_hour_through_now_range,
    filename_for_hour_start,
    parse_iso_dt,
    previous_hour_range,
)

OUT_SUFFIX = "dns-names.txt"

# Name-only: capture qnames; never copy answer RDATA into output
_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?P<name>[a-zA-Z0-9*](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?)"
        r":\s*IN AAAA?"
    ),
    re.compile(
        r"IN AAAA?\s+(?P<name>[^\s#;]+)"
    ),
]

_FQDN = re.compile(
    r"(?<![0-9A-Za-z._-])"
    r"((?:[a-zA-Z0-9_](?:[a-zA-Z0-9_.-]*[a-zA-Z0-9])?)\."
    r"(?:[a-zA-Z0-9_-]{1,63}\.)*[a-zA-Z]{2,63})"
    r"(?![0-9A-Za-z._-])"
)
_DEFAULT_LINE_SUBSTR = (
    "IN A",
    "IN AAAA",
    "IN ",
    "lookup key",
    "Looking up",
    "Transaction",
    "Varlink",
    "cache for",
    "Received DNS",
)


def _normalize_name(name: str) -> str:
    n = name.strip().rstrip(".").lower()
    if n.endswith("*)"):
        n = n[:-2]
    n = n.replace("\\032", " ").split()[0] if n else n
    return n or name


def _is_plausible_fqdn(name: str) -> bool:
    if not name or len(name) < 3 or ".." in name:
        return False
    if not re.match(r"^[a-z0-9._-]+$", name, re.I):
        return False
    if name.count(".") < 1:
        return False
    return True


def extract_names_from_line(text: str) -> set[str]:
    out: set[str] = set()
    for pat in _LINE_PATTERNS:
        for m in pat.finditer(text):
            try:
                name = m.group("name")
            except (IndexError, KeyError):
                continue
            n = _normalize_name(name)
            if _is_plausible_fqdn(n) or n.count(".") >= 1:
                out.add(n)
    for m in _FQDN.finditer(text):
        n = _normalize_name(m.group(1))
        if _is_plausible_fqdn(n):
            out.add(n)
    return out


def _journal_message_lines(
    unit: str,
    since: datetime,
    until: datetime,
) -> list[str]:
    if since.tzinfo is None or until.tzinfo is None:
        raise SystemExit("internal error: use timezone-aware since/until")
    s = since.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    u = until.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    cmd = [
        "journalctl",
        f"-u{unit}",
        "--since",
        s,
        "--until",
        u,
        "-o",
        "cat",
        "--no-pager",
    ]
    p = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if p.returncode != 0:
        err = p.stderr.strip() or f"journalctl exited {p.returncode}"
        print(err, file=sys.stderr)
        sys.exit(p.returncode)
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def _filter_substrings(
    lines: list[str], substr: tuple[str, ...] | None, disable: bool
) -> list[str]:
    if disable or not substr:
        return lines
    return [ln for ln in lines if any(s in ln for s in substr)]


def run_export(
    output_dir: Path,
    start: datetime,
    end: datetime,
    unit: str,
    substr: tuple[str, ...] | None,
    no_substr_filter: bool,
) -> Path:
    lines = _journal_message_lines(unit, start, end)
    lines = _filter_substrings(lines, substr, no_substr_filter)
    out_lines: set[str] = set()
    for line in lines:
        for n in extract_names_from_line(line):
            out_lines.add(n)
    out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = filename_for_hour_start(start, OUT_SUFFIX)
    out_path = out_dir / name
    tmp = out_path.with_name(f".{out_path.name}.tmp")
    data = "\n".join(sorted(out_lines)) + ("\n" if out_lines else "")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, out_path)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/var/lib/dns-audit"),
        help=f"Directory for YYYYMMDDHH+oooo-{OUT_SUFFIX} (%%z at hour start, no separator before offset)",
    )
    ap.add_argument(
        "--since",
        help="With --until: custom window (not combined with --previous-hour; ISO, naive uses --timezone).",
    )
    ap.add_argument(
        "--until",
        help="With --since: custom window (not combined with --previous-hour).",
    )
    ap.add_argument(
        "--previous-hour",
        action="store_true",
        help="Export the previous full local clock hour (systemd timer mode). Incompatible with --since/--until.",
    )
    ap.add_argument(
        "--timezone",
        default="local",
        help="Zone for default time ranges (e.g. Europe/Berlin). 'local' = system local.",
    )
    ap.add_argument(
        "-u",
        "--journal-unit",
        default="systemd-resolved.service",
        help="journalctl -u (default: systemd-resolved.service)",
    )
    ap.add_argument(
        "--no-substr-filter",
        action="store_true",
        help="Do not filter by substring (use if journal is already LogFilterPatterns-only).",
    )
    ap.add_argument(
        "--line-substr",
        action="append",
        help="Extra substring: keep journal lines that contain it (repeatable).",
    )
    args = ap.parse_args()
    if args.timezone == "local":
        tzi = datetime.now().astimezone().tzinfo
        tz = tzi if tzi is not None else timezone.utc
    else:
        tz = ZoneInfo(args.timezone)
    if args.previous_hour and (args.since or args.until):
        ap.error("use --previous-hour without --since/--until")
    if args.since and args.until:
        start = parse_iso_dt(args.since, tz)
        end = parse_iso_dt(args.until, tz)
    elif args.since or args.until:
        ap.error("pass both --since and --until, or neither")
    elif args.previous_hour:
        start, end = previous_hour_range(tz)
    else:
        start, end = current_hour_through_now_range(tz)
    sub = tuple(_DEFAULT_LINE_SUBSTR)
    if args.line_substr:
        sub = sub + tuple(args.line_substr)
    out = run_export(
        args.output_dir,
        start,
        end,
        args.journal_unit,
        sub,
        args.no_substr_filter,
    )
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
