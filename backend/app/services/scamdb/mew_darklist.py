"""MyEtherWallet darklist — official, actively maintained malicious-address list.

Verified live: array of {"address", "comment", "date"} records, ~700
entries, each with a human-written reason (usually which phishing site the
funds came from).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_mew_darklist(url: str) -> dict[str, dict]:
    """Returns {lowercased_address: {"comment": str, "date": str}}."""
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("MEW darklist fetch/parse failed: %s", exc)
        return out

    if not isinstance(payload, list):
        logger.warning("MEW darklist: unexpected top-level JSON type %s", type(payload))
        return out

    for rec in payload:
        if not isinstance(rec, dict):
            continue
        addr = (rec.get("address") or "").strip().lower()
        if not addr:
            continue
        out[addr] = {"comment": rec.get("comment", ""), "date": rec.get("date")}

    logger.info("MEW darklist: loaded %d addresses", len(out))
    return out
