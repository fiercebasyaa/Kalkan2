"""CryptoScamDB blacklist dataset.

Checked live during development: the project appears defunct as of 2026 —
its live API (api.cryptoscamdb.org) returns 502, and its GitHub org only
hosts the API server source code, not a data dump (no `blacklist` repo with
a JSON/YAML dataset exists anymore). This client is kept for when/if the
project comes back or a fork publishes a dataset again; until then it just
logs a warning and contributes no flags, which the aggregator handles
gracefully. Real red-flag coverage currently comes from OFAC SDN,
Etherscan labels' risk categories, and Chainabuse (once a key is added).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_cryptoscamdb_addresses(url: str) -> dict[str, dict]:
    """Returns {lowercased_address: {"name": str, "category": str, "url": str}}."""
    out: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("CryptoScamDB fetch/parse failed: %s", exc)
        return out

    try:
        if isinstance(payload, dict):
            # shape: {"0xabc...": {...}} or {"result": [...]}
            if "result" in payload and isinstance(payload["result"], list):
                for rec in payload["result"]:
                    _ingest_record(out, rec)
            else:
                for addr, rec in payload.items():
                    if isinstance(rec, dict):
                        _ingest_record(out, {**rec, "address": addr})
        elif isinstance(payload, list):
            for rec in payload:
                _ingest_record(out, rec)
        else:
            logger.warning("CryptoScamDB: unexpected top-level JSON type %s", type(payload))
    except Exception as exc:  # defensive — unknown schema shouldn't crash startup
        logger.warning("CryptoScamDB: schema mismatch while parsing: %s", exc)
        return {}

    logger.info("CryptoScamDB: loaded %d addresses", len(out))
    return out


def _ingest_record(out: dict[str, dict], rec: dict) -> None:
    addr = rec.get("address") or rec.get("addr")
    if not addr or not isinstance(addr, str):
        return
    out[addr.strip().lower()] = {
        "name": rec.get("name") or rec.get("entity") or "Reported scam",
        "category": rec.get("category") or rec.get("type") or "scam",
        "url": rec.get("url") or rec.get("reporter_url"),
    }
