"""Zerion API client.

Wraps the wallet portfolio / positions / transactions endpoints so callers
never touch raw HTTP. Auth is HTTP Basic with the API key as the username
and an empty password, per Zerion's documented convention.

Verified live with a real key: portfolio, positions and transactions all
return real data. Two things worth knowing:
- Zerion can reject an address as "untrackable" (400, seen on very
  high-throughput exchange hot wallets) — callers should treat a failed
  transactions call the same as "no history", not as "no key".
- An address with zero on-chain activity legitimately returns an empty
  transactions list even with a valid key — that's not a misconfiguration.
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.models import PortfolioSummary, Transaction, TokenBalance

logger = logging.getLogger(__name__)


class ZerionClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.zerion_base_url,
            auth=(settings.zerion_api_key, ""),
            timeout=15.0,
            follow_redirects=True,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.zerion_enabled

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_portfolio(self, address: str) -> PortfolioSummary:
        if not self._settings.zerion_enabled:
            return PortfolioSummary(source="unavailable")
        try:
            resp = await self._client.get(
                f"/wallets/{address}/portfolio",
                params={"currency": "usd"},
            )
            resp.raise_for_status()
            return self._parse_portfolio(resp.json())
        except httpx.HTTPError as exc:
            logger.warning("Zerion portfolio fetch failed for %s: %s", address, exc)
            return PortfolioSummary(source="unavailable")

    async def get_positions(self, address: str, limit: int = 50) -> list[TokenBalance]:
        if not self._settings.zerion_enabled:
            return []
        try:
            resp = await self._client.get(
                f"/wallets/{address}/positions/",
                params={
                    "currency": "usd",
                    "filter[positions]": "only_simple",
                    "page[size]": limit,
                },
            )
            resp.raise_for_status()
            return self._parse_positions(resp.json())
        except httpx.HTTPError as exc:
            logger.warning("Zerion positions fetch failed for %s: %s", address, exc)
            return []

    async def get_transactions(self, address: str, limit: int = 50) -> list[Transaction]:
        if not self._settings.zerion_enabled:
            return []
        try:
            resp = await self._client.get(
                f"/wallets/{address}/transactions/",
                params={"currency": "usd", "page[size]": limit},
            )
            resp.raise_for_status()
            return self._parse_transactions(resp.json(), address)
        except httpx.HTTPError as exc:
            logger.warning("Zerion transactions fetch failed for %s: %s", address, exc)
            return []

    @staticmethod
    def _parse_portfolio(payload: dict) -> PortfolioSummary:
        data = payload.get("data", {})
        attrs = data.get("attributes", {})
        total = attrs.get("total", {}).get("positions") if isinstance(attrs.get("total"), dict) else attrs.get("total")
        return PortfolioSummary(total_usd_value=total, tokens=[], source="zerion")

    @staticmethod
    def _parse_positions(payload: dict) -> list[TokenBalance]:
        out: list[TokenBalance] = []
        for item in payload.get("data", []):
            attrs = item.get("attributes", {})
            fungible = attrs.get("fungible_info", {})
            quantity = attrs.get("quantity", {})
            # One position per (asset, chain) — a wallet holding ETH on
            # both mainnet and Base gets two separate entries here, each
            # with its own relationships.chain.data.id. (Earlier note in
            # this spot said positions had no per-chain field — wrong,
            # that's `fungible_info.implementations[]`, which lists every
            # chain the *token contract* exists on, not which chain *this*
            # balance is on. relationships.chain is the real answer.)
            chain = (
                item.get("relationships", {})
                .get("chain", {})
                .get("data", {})
                .get("id")
            )
            out.append(
                TokenBalance(
                    symbol=fungible.get("symbol", "?"),
                    name=fungible.get("name"),
                    quantity=float(quantity.get("float", 0) or 0),
                    usd_value=attrs.get("value"),
                    chain=chain,
                )
            )
        return out

    @staticmethod
    def _parse_transactions(payload: dict, address: str) -> list[Transaction]:
        out: list[Transaction] = []
        addr_lower = address.lower()
        for item in payload.get("data", []):
            attrs = item.get("attributes", {})
            transfers = attrs.get("transfers", [])
            counterparty = None
            direction = "unknown"
            value_usd = None
            asset = None
            if transfers:
                t0 = transfers[0]
                sender = (t0.get("sender") or "").lower()
                recipient = (t0.get("recipient") or "").lower()
                if sender == addr_lower:
                    direction, counterparty = "out", recipient
                elif recipient == addr_lower:
                    direction, counterparty = "in", sender
                value_usd = t0.get("value")
                fungible = t0.get("fungible_info", {})
                asset = fungible.get("symbol") if isinstance(fungible, dict) else None
            out.append(
                Transaction(
                    hash=attrs.get("hash", item.get("id", "")),
                    timestamp=attrs.get("mined_at"),
                    direction=direction,
                    counterparty=counterparty,
                    value_usd=value_usd,
                    asset=asset,
                )
            )
        return out
