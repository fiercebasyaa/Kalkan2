"""QuickNode JSON-RPC client — one endpoint per EVM chain.

Used as a fallback / complement to Zerion: native balance, tx trace for
watchlist reserve wallets, and (if the Token API marketplace add-on is
enabled on the endpoint) token balances via `qn_getWalletTokenBalance`.

Every method takes a `chain` slug (ethereum/arbitrum/base/polygon/optimism/
bsc/avalanche) matching `QUICKNODE_RPC_URL_*` in `.env`. A chain with no
configured URL just returns None — callers fall back to Zerion or skip.

NOTE: `qn_getWalletTokenBalance` is a QuickNode Marketplace add-on method —
it only works if that add-on is enabled on the given endpoint. If it's not,
calls fail gracefully.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class QuickNodeClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._clients: dict[str, httpx.AsyncClient] = {
            chain: httpx.AsyncClient(base_url=url, timeout=15.0, follow_redirects=True)
            for chain, url in settings.quicknode_urls.items()
        }

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()

    @property
    def available_chains(self) -> list[str]:
        return list(self._clients.keys())

    async def _rpc(self, chain: str, method: str, params: list[Any]) -> Any | None:
        client = self._clients.get(chain)
        if client is None:
            return None
        try:
            resp = await client.post(
                "", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            )
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload:
                logger.warning("QuickNode RPC %s (%s) error: %s", method, chain, payload["error"])
                return None
            return payload.get("result")
        except httpx.HTTPError as exc:
            logger.warning("QuickNode RPC %s (%s) failed: %s", method, chain, exc)
            return None

    async def get_native_balance_wei(self, address: str, chain: str = "ethereum") -> int | None:
        result = await self._rpc(chain, "eth_getBalance", [address, "latest"])
        return int(result, 16) if result else None

    async def get_tx_count(self, address: str, chain: str = "ethereum") -> int | None:
        result = await self._rpc(chain, "eth_getTransactionCount", [address, "latest"])
        return int(result, 16) if result else None

    async def get_token_balances(self, address: str, chain: str = "ethereum") -> list[dict] | None:
        """QuickNode Token API add-on. Returns None if unavailable."""
        result = await self._rpc(chain, "qn_getWalletTokenBalance", [{"wallet": address}])
        if not result:
            return None
        return result.get("result", []) if isinstance(result, dict) else None

    async def trace_transaction(self, tx_hash: str, chain: str = "ethereum") -> dict | None:
        return await self._rpc(chain, "debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
