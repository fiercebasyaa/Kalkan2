"""Combines all scam-db sources into one address-flag lookup.

Static datasets (OFAC, CryptoScamDB, Etherscan labels) are loaded once at
startup, cached to disk with a TTL, and refreshed lazily on access.
Chainabuse and the Etherscan page scrape are queried live per-address
(lookups, not bulk datasets).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from app.config import CACHE_DIR, MANUAL_FLAGS_PATH, Settings
from app.models import ScamFlag
from app.services.scamdb import (
    chainabuse,
    cryptoscamdb,
    etherscan_labels,
    etherscan_page,
    manual,
    mew_darklist,
    ofac,
    scamsniffer,
)

logger = logging.getLogger(__name__)


class ScamDbAggregator:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._ofac: dict[str, dict] = {}
        self._cryptoscamdb: dict[str, dict] = {}
        self._etherscan_labels: dict[str, dict] = {}
        self._scamsniffer: dict[str, dict] = {}
        self._mew_darklist: dict[str, dict] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        async with self._lock:
            if time.time() - self._loaded_at < self._settings.scam_db_cache_ttl_seconds:
                return
            (
                self._ofac,
                self._cryptoscamdb,
                self._etherscan_labels,
                self._scamsniffer,
                self._mew_darklist,
            ) = await asyncio.gather(
                self._load_with_cache("ofac.json", ofac.fetch_ofac_addresses, self._settings.ofac_sdn_xml_url),
                self._load_with_cache(
                    "cryptoscamdb.json",
                    cryptoscamdb.fetch_cryptoscamdb_addresses,
                    self._settings.cryptoscamdb_addresses_url,
                ),
                self._load_with_cache(
                    "etherscan_labels.json",
                    etherscan_labels.fetch_etherscan_labels,
                    None,  # per-chain URLs live in CHAIN_SOURCES inside the module
                ),
                self._load_with_cache(
                    "scamsniffer.json",
                    scamsniffer.fetch_scamsniffer_addresses,
                    self._settings.scamsniffer_addresses_url,
                ),
                self._load_with_cache(
                    "mew_darklist.json", mew_darklist.fetch_mew_darklist, self._settings.mew_darklist_url
                ),
            )
            self._loaded_at = time.time()

    async def _load_with_cache(self, filename: str, fetch_fn, url: str) -> dict:
        cache_path: Path = CACHE_DIR / filename
        try:
            fresh = await fetch_fn(url)
            if fresh:
                cache_path.write_text(json.dumps(fresh))
                return fresh
        except Exception as exc:  # noqa: BLE001 — never let one source break startup
            logger.warning("%s: live fetch failed (%s), falling back to disk cache", filename, exc)

        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text())
            except (ValueError, OSError):
                pass
        return {}

    async def check_address(self, address: str, include_page_scrape: bool = True) -> list[ScamFlag]:
        """include_page_scrape=False skips the etherscan.io scrape (used for
        the batch of counterparties in check_many — up to 25 concurrent
        scrape requests per single user lookup would be far too aggressive
        against Etherscan; the directly-checked address still gets it)."""
        await self.ensure_loaded()
        addr = address.lower()
        flags: list[ScamFlag] = []

        manual_flags = manual.load_manual_flags(MANUAL_FLAGS_PATH)
        if addr in manual_flags:
            info = manual_flags[addr]
            flags.append(
                ScamFlag(
                    address=address,
                    source="Manual (curated)",
                    label=info["label"],
                    severity=info["severity"],
                    reference_url=info.get("source_url"),
                )
            )

        if addr in self._ofac:
            info = self._ofac[addr]
            flags.append(
                ScamFlag(
                    address=address,
                    source="OFAC SDN",
                    label=f"Sanctioned entity: {info['entity']} ({info['program']})",
                    severity="critical",
                    reference_url="https://sanctionssearch.ofac.treas.gov/",
                )
            )

        if addr in self._cryptoscamdb:
            info = self._cryptoscamdb[addr]
            flags.append(
                ScamFlag(
                    address=address,
                    source="CryptoScamDB",
                    label=f"{info['category']}: {info['name']}",
                    severity="high",
                    reference_url=info.get("url"),
                )
            )

        if addr in self._scamsniffer:
            flags.append(
                ScamFlag(
                    address=address,
                    source="ScamSniffer",
                    label="Reported phishing/scam address",
                    severity="high",
                    reference_url="https://github.com/scamsniffer/scam-database",
                )
            )

        if addr in self._mew_darklist:
            info = self._mew_darklist[addr]
            comment = info.get("comment") or "Reported malicious address"
            date = info.get("date")
            flags.append(
                ScamFlag(
                    address=address,
                    source="MyEtherWallet darklist",
                    label=f"{comment} ({date})" if date else comment,
                    severity="high",
                )
            )

        if addr in self._etherscan_labels:
            info = self._etherscan_labels[addr]
            # Only a red flag if it carries a risk-relevant label per that
            # chain's taxonomy (see CHAIN_SOURCES in etherscan_labels.py) —
            # most entries here are neutral entity tags (exchange, DeFi
            # protocol, etc.), not scam markers.
            if info["severity"]:
                chains = "/".join(info["chains"])
                base = f"{', '.join(info['labels'])} ({info['name']})" if info["name"] else ", ".join(info["labels"])
                flags.append(
                    ScamFlag(
                        address=address,
                        source=f"Etherscan labels [{chains}]",
                        label=base,
                        severity=info["severity"],
                    )
                )

        ca_result = await chainabuse.check_chainabuse(self._settings, address)
        if ca_result:
            flags.append(
                ScamFlag(
                    address=address,
                    source="Chainabuse",
                    label=f"{ca_result['report_count']} community report(s): {', '.join(ca_result['categories'])}",
                    severity="high",
                )
            )

        page_results = (
            await etherscan_page.check_etherscan_page(
                address, enabled=self._settings.etherscan_scrape_enabled
            )
            if include_page_scrape
            else []
        )
        for hit in page_results:
            label = hit["name_tag"] or "flagged address"
            if hit["warning"]:
                label = f"{label} — {hit['warning']}"
            domain = etherscan_page.SCRAPABLE_DOMAINS.get(hit["chain"], "etherscan.io")
            flags.append(
                ScamFlag(
                    address=address,
                    source=f"Etherscan-family scrape [{hit['chain']}]",
                    label=label,
                    severity="critical" if hit["warning"] else "high",
                    reference_url=f"https://{domain}/address/{address}",
                )
            )

        return flags

    async def check_many(self, addresses: list[str]) -> dict[str, list[ScamFlag]]:
        results = await asyncio.gather(
            *(self.check_address(a, include_page_scrape=False) for a in addresses)
        )
        return dict(zip(addresses, results))
