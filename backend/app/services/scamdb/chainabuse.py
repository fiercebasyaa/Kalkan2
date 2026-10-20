"""Chainabuse API client — community-reported scam addresses.

Requires an API key (Chainabuse gates access). Exact base URL/auth header
format is unconfirmed in this session (no network access at build time) —
this client is written defensively: if `CHAINABUSE_API_KEY` is unset or the
request fails for any reason, it returns None and the aggregator just skips
this source rather than failing the whole address check.
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


async def check_chainabuse(settings: Settings, address: str) -> dict | None:
    if not settings.chainabuse_enabled:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{settings.chainabuse_base_url}/v0/reports",
                params={"address": address},
                headers={"Authorization": f"Bearer {settings.chainabuse_api_key}"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Chainabuse check failed for %s: %s", address, exc)
        return None

    reports = payload.get("data") or payload.get("reports") or []
    if not reports:
        return None
    categories = {r.get("category", "abuse") for r in reports if isinstance(r, dict)}
    return {
        "report_count": len(reports),
        "categories": sorted(categories),
    }
