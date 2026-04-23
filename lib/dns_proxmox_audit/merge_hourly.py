"""Merge hourly *dns-names.txt under the audit directory into names-review.txt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .names import load_hourly, write_names_review


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/var/lib/dns-audit"),
        help="Directory of hourly *dns-names.txt and destination names-review.txt",
    )
    args = ap.parse_args()
    d = args.output_dir
    if not d.is_dir():
        print(f"not a directory: {d}", file=sys.stderr)
        return 1
    last = load_hourly(d)
    if not last:
        print("warning: no names merged (empty or no matching files)", file=sys.stderr)
    out = d / "names-review.txt"
    write_names_review(out, last)
    print(f"Wrote {out} ({len(last)} names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
