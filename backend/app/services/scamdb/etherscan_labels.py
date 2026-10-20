"""Community-maintained Etherscan-family label datasets (brianleect/etherscan-labels).

The repo covers several chains under separate top-level dirs, each with its
own risk-relevant category taxonomy (verified live — they're not uniform):

  ethereum (data/etherscan)   -> ofac-sanctions-lists, something-fishy,
                                  high-risk, blocked, flagged-by-sec, opportunist
  arbitrum (data/arbiscan)    -> exploit, phish-hack
  avalanche (data/avalanche)  -> exploit, phish-hack
  bsc (data/bscscan)          -> scam
  optimism (data/optimism)    -> exploit, phish-hack
  polygon (data/polygonscan)  -> blocked, exploit, scam

No Base directory exists in this dataset — Base has no bulk-label source
here, only the live etherscan_page scrape (basescan.org).

Schema per chain file: {"0xaddress": {"name": "...", "labels": ["...", ...]}}.
All chains fetched in parallel and merged into one address -> info map; an
address flagged on multiple chains keeps the worst severity and lists every
chain that flagged it.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}

CHAIN_SOURCES: dict[str, dict] = {
    "ethereum": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/etherscan/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {
            "ofac-sanctions-lists": "critical",
            "something-fishy": "high",
            "high-risk": "high",
            "blocked": "high",
            "flagged-by-sec": "medium",
            "opportunist": "medium",
        },
    },
    "arbitrum": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/arbiscan/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {"exploit": "critical", "phish-hack": "critical"},
    },
    "avalanche": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/avalanche/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {"exploit": "critical", "phish-hack": "critical"},
    },
    "bsc": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/bscscan/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {"scam": "critical"},
    },
    "optimism": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/optimism/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {"exploit": "critical", "phish-hack": "critical"},
    },
    "polygon": {
        "url": (
            "https://raw.githubusercontent.com/brianleect/etherscan-labels/main/"
            "data/polygonscan/combined/combinedAccountLabels.json"
        ),
        "risk_labels": {"blocked": "high", "exploit": "critical", "scam": "critical"},
    },
}


async def _fetch_one_chain(chain: str, url: str, risk_labels: dict[str, str]) -> dict[str, dict]:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Etherscan labels (%s) fetch/parse failed: %s", chain, exc)
        return {}

    if not isinstance(payload, dict):
        logger.warning("Etherscan labels (%s): unexpected top-level JSON type %s", chain, type(payload))
        return {}

    out: dict[str, dict] = {}
    for addr, rec in payload.items():
        if not isinstance(rec, dict):
            continue
        labels = rec.get("labels") or []
        severity = None
        for label in labels:
            if label in risk_labels:
                severity = risk_labels[label]
                break
        out[addr.strip().lower()] = {
            "name": rec.get("name", ""),
            "labels": labels,
            "severity": severity,
            "chain": chain,
        }

    logger.info("Etherscan labels (%s): loaded %d addresses", chain, len(out))
    return out


async def fetch_etherscan_labels(_url: str | None = None) -> dict[str, dict]:
    """Fetches and merges all configured chains.

    Kept a single positional/optional arg for interface compatibility with
    the generic `_load_with_cache(filename, fetch_fn, url)` caller in
    aggregator.py — the real per-chain URLs live in CHAIN_SOURCES above.
    """
    results = await asyncio.gather(
        *(
            _fetch_one_chain(chain, cfg["url"], cfg["risk_labels"])
            for chain, cfg in CHAIN_SOURCES.items()
        )
    )

    merged: dict[str, dict] = {}
    for chain_data in results:
        for addr, info in chain_data.items():
            existing = merged.get(addr)
            if existing is None:
                merged[addr] = {**info, "chains": [info["chain"]]}
                continue
            existing["chains"].append(info["chain"])
            existing_rank = SEVERITY_RANK.get(existing["severity"] or "", -1)
            new_rank = SEVERITY_RANK.get(info["severity"] or "", -1)
            if new_rank > existing_rank:
                existing["severity"] = info["severity"]
            existing["labels"] = list({*existing["labels"], *info["labels"]})
            if not existing["name"] and info["name"]:
                existing["name"] = info["name"]

    return merged
