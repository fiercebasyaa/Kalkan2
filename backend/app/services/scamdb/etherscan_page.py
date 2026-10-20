"""Etherscan-family address page scraper — community exploit/scam warnings.

These sites show a red warning banner + a name tag (e.g. "Kelp DAO
Exploiter 3", "Ostium Exploiter") for addresses the community has flagged
as involved in a hack/exploit/scam — sourced from investigators like
ZachXBT. Not exposed through any of these sites' public APIs at any tier.

Domain coverage, verified live (plain httpx client, no JS execution):
  ethereum   -> etherscan.io           200 OK, scrapable
  base       -> basescan.org           200 OK, scrapable
  polygon    -> polygonscan.com        200 OK, scrapable
  avalanche  -> snowscan.xyz           200 OK, scrapable (same platform
                                        family as the others; snowtrace.io,
                                        the other Avalanche explorer, is a
                                        JS-rendered SPA and returns nothing
                                        useful to a plain client)
  arbitrum   -> arbiscan.io            403 Cloudflare "Just a moment..."
  bsc        -> bscscan.com            403 Cloudflare "Just a moment..."
  optimism   -> optimistic.etherscan.io 403 Cloudflare "Just a moment..."

The three blocked chains get no live scrape here — defeating a Cloudflare
bot challenge would mean a full headless browser and deliberately working
around anti-bot protection, a different and more questionable thing than
scraping a plain public page. For a confirmed incident on one of those
chains, add it to app/data/manual_flags.json instead (see manual.py).

This is scraping, not an official API — fragile by nature (breaks on
markup changes, ToS grey area). ETHERSCAN_SCRAPE_ENABLED=false disables
all of it; everything else degrades gracefully without it.

Both pieces of data come from plain HTML, no JS needed:
  <meta property="og:title" content="{name_tag} | Address: ... | X">
  <div class='alert alert-danger ...'>{warning text}</div> when present
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"|]+?)\s*\|\s*Address:')
ALERT_DANGER_RE = re.compile(r"alert-danger[^>]*>(.*?)</div>", re.DOTALL)
TAG_STRIP_RE = re.compile(r"<[^>]+>")

SUSPICIOUS_KEYWORDS = (
    "exploiter", "exploit", "hack", "scam", "phish", "drainer",
    "stolen", "malicious", "fraud", "heist", "rug pull", "rugpull",
)

SCRAPABLE_DOMAINS: dict[str, str] = {
    "ethereum": "etherscan.io",
    "base": "basescan.org",
    "polygon": "polygonscan.com",
    "avalanche": "snowscan.xyz",
}
# arbitrum/bsc/optimism intentionally excluded — see module docstring.

_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 24 * 3600


async def check_etherscan_page(address: str, enabled: bool = True) -> list[dict]:
    """Returns a list of {"chain": str, "name_tag": str, "warning": str|None}
    — one entry per domain where the address looks flagged. Empty list if
    clean everywhere or disabled. Never raises."""
    if not enabled:
        return []

    addr = address.lower()
    cached = _cache.get(addr)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    results = await asyncio.gather(
        *(_fetch_and_parse(address, chain, domain) for chain, domain in SCRAPABLE_DOMAINS.items())
    )
    hits = [r for r in results if r is not None]
    _cache[addr] = (time.time(), hits)
    return hits


async def _fetch_and_parse(address: str, chain: str, domain: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                f"https://{domain}/address/{address}",
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                logger.info("%s scrape: %s returned %s", domain, address, resp.status_code)
                return None
            html = resp.text
    except httpx.HTTPError as exc:
        logger.warning("%s scrape failed for %s: %s", domain, address, exc)
        return None

    name_tag = None
    m = OG_TITLE_RE.search(html)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() != address.lower():
            name_tag = candidate

    warning = None
    m = ALERT_DANGER_RE.search(html)
    if m:
        warning = TAG_STRIP_RE.sub("", m.group(1)).strip()

    is_suspicious_tag = name_tag and any(k in name_tag.lower() for k in SUSPICIOUS_KEYWORDS)

    if not warning and not is_suspicious_tag:
        return None

    return {"chain": chain, "name_tag": name_tag, "warning": warning}
