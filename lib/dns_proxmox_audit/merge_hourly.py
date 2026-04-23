"""Merge hourly *dns-names.txt under the audit directory into names-review.txt."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .names import (
    load_hourly,
    load_names_review_merge_state,
    merge_names_review_hourly,
    write_names_review,
)


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
    out = d / "names-review.txt"
    previous = (
        load_names_review_merge_state(out) if out.is_file() else {}
    )
    merged = merge_names_review_hourly(last, previous)
    if not last:
        if not previous:
            print(
                "warning: no names merged (empty or no matching files)",
                file=sys.stderr,
            )
        else:
            print(
                "warning: no names from hourly files; names-review kept from existing file only",
                file=sys.stderr,
            )
    write_names_review(out, merged)
    print(f"Wrote {out} ({len(merged)} names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
