"""ScamSniffer blacklist — actively maintained community phishing/scam list.

Scam Sniffer is a web3 wallet-security browser extension; this repo backs
their blocklist. Verified live: flat JSON array of lowercase addresses,
~2500 entries, no per-entry metadata (just "this address was reported").
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_scamsniffer_addresses(url: str) -> dict[str, dict]:
    """Returns {lowercased_address: {}} — presence alone is the signal."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ScamSniffer fetch/parse failed: %s", exc)
        return {}

    if not isinstance(payload, list):
        logger.warning("ScamSniffer: unexpected top-level JSON type %s", type(payload))
        return {}

    out = {addr.strip().lower(): {} for addr in payload if isinstance(addr, str)}
    logger.info("ScamSniffer: loaded %d addresses", len(out))
    return out
