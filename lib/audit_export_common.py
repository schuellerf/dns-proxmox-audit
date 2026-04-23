"""Shared filename patterns and time ranges for dns-proxmox-audit export scripts."""

from __future__ import annotations

from datetime import datetime, timedelta


def offset_in_filename(dt: datetime) -> str:
    off = dt.strftime("%z")
    return off if off else "+0000"


def filename_for_hour_start(start: datetime, suffix: str) -> str:
    """e.g. 2026042310+0100-{suffix}"""
    ymdh = start.strftime("%Y%m%d%H")
    return f"{ymdh}{offset_in_filename(start)}-{suffix}"


def previous_hour_range(tz: datetime.tzinfo) -> tuple[datetime, datetime]:
    now = datetime.now(tz)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    return start, end


def current_hour_through_now_range(tz: datetime.tzinfo) -> tuple[datetime, datetime]:
    now = datetime.now(tz)
    start = now.replace(minute=0, second=0, microsecond=0)
    return start, now


def parse_iso_dt(s: str, default_tz: datetime.tzinfo) -> datetime:
    s0 = s.strip()
    if s0.endswith("Z"):
        d = datetime.fromisoformat(s0.replace("Z", "+00:00", 1))
    else:
        d = datetime.fromisoformat(s0)
        if d.tzinfo is None:
            d = d.replace(tzinfo=default_tz)
    return d
