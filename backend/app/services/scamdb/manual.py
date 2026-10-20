"""Manually curated flagged addresses.

For cases the automated sources miss or haven't caught up to yet: a fresh
incident (bulk datasets lag by days/weeks), or an address on a chain whose
explorer blocks scraping (Arbiscan returns a Cloudflare challenge to plain
HTTP clients — unlike etherscan.io itself, which doesn't). When you
independently confirm an incident (news coverage, a security firm writeup,
etc.), add an entry here rather than trying to force an automated source to
cover it.

Edit app/data/manual_flags.json directly — {"address", "label", "severity",
"source_url"} per entry. Reloaded fresh on every check (cheap local file,
no reason to cache it stale).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_manual_flags(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        logger.warning("Manual flags file unreadable: %s", exc)
        return {}

    out: dict[str, dict] = {}
    for rec in records:
        addr = (rec.get("address") or "").strip().lower()
        if not addr:
            continue
        out[addr] = {
            "label": rec.get("label", "Manually flagged"),
            "severity": rec.get("severity", "high"),
            "source_url": rec.get("source_url"),
        }
    return out
