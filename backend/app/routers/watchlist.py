from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from app.config import DATA_DIR, HISTORY_DIR, Settings
from app.dependencies import get_quicknode, get_settings_dep, get_zerion
from app.models import PortfolioSummary, Reason, WatchlistEntry, WatchlistSnapshot
from app.services.quicknode import QuickNodeClient
from app.services.telegram import send_alert
from app.services.zerion import ZerionClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

WATCHLIST_FILE = DATA_DIR / "watchlist.json"


def load_watchlist_config() -> list[dict]:
    if not WATCHLIST_FILE.exists():
        return []
    return json.loads(WATCHLIST_FILE.read_text())


def _history_path(address: str) -> Path:
    return Path(HISTORY_DIR) / f"{address.lower()}.jsonl"


def append_snapshot(address: str, snapshot: WatchlistSnapshot) -> None:
    path = _history_path(address)
    with path.open("a") as f:
        f.write(snapshot.model_dump_json() + "\n")


def read_history(address: str, limit: int = 200) -> list[WatchlistSnapshot]:
    path = _history_path(address)
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(WatchlistSnapshot.model_validate_json(line))
        except ValueError:
            continue
    return out


async def fetch_current_portfolio(
    address: str, zerion: ZerionClient, quicknode: QuickNodeClient, chain: str = "ethereum"
) -> PortfolioSummary:
    portfolio = await zerion.get_portfolio(address)
    if portfolio.source != "unavailable":
        return portfolio
    wei = await quicknode.get_native_balance_wei(address, chain=chain)
    if wei is not None:
        return PortfolioSummary(total_usd_value=None, tokens=[], source="quicknode")
    return portfolio


def _compute_alert(
    history: list[WatchlistSnapshot], settings: Settings
) -> tuple[float | None, bool, Reason | None]:
    """Returns (change_pct, alert_active, alert_reason) from the last two snapshots."""
    if len(history) < 2 or not history[-2].total_usd_value or history[-1].total_usd_value is None:
        return None, False, None
    prev, curr = history[-2].total_usd_value, history[-1].total_usd_value
    if prev <= 0:
        return None, False, None
    change_pct = ((curr - prev) / prev) * 100
    if change_pct > -settings.watchlist_drop_alert_pct:
        return change_pct, False, None
    reason = Reason(code="alert_reserve_drop", params={"pct": round(abs(change_pct), 1), "prev": prev, "curr": curr})
    return change_pct, True, reason


async def poll_once(
    zerion: ZerionClient, quicknode: QuickNodeClient, settings: Settings
) -> list[WatchlistEntry]:
    entries: list[WatchlistEntry] = []
    for cfg in load_watchlist_config():
        address, label, chain = cfg["address"], cfg["label"], cfg.get("chain", "ethereum")
        portfolio = await fetch_current_portfolio(address, zerion, quicknode, chain=chain)

        now = datetime.now(timezone.utc).isoformat()
        append_snapshot(address, WatchlistSnapshot(timestamp=now, total_usd_value=portfolio.total_usd_value))
        history = read_history(address)

        change_pct, alert_active, alert_reason = _compute_alert(history, settings)
        if alert_active and alert_reason:
            p = alert_reason.params
            await send_alert(
                settings,
                f"⚠️ <b>Watchdog alert</b>\n{label} ({address})\n"
                f"Резервы упали на {p['pct']}% за последний poll-интервал "
                f"({p['prev']:,.0f} → {p['curr']:,.0f} USD)",
            )

        entries.append(
            WatchlistEntry(
                address=address,
                label=label,
                chain=chain,
                portfolio=portfolio,
                history=history,
                change_24h_pct=change_pct,
                alert_active=alert_active,
                alert_reason=alert_reason,
            )
        )
    return entries


@router.get("", response_model=list[WatchlistEntry])
async def get_watchlist(
    zerion: ZerionClient = Depends(get_zerion),
    quicknode: QuickNodeClient = Depends(get_quicknode),
    settings: Settings = Depends(get_settings_dep),
) -> list[WatchlistEntry]:
    entries = []
    for cfg in load_watchlist_config():
        address, label, chain = cfg["address"], cfg["label"], cfg.get("chain", "ethereum")
        portfolio = await fetch_current_portfolio(address, zerion, quicknode, chain=chain)
        history = read_history(address)
        change_pct, alert_active, alert_reason = _compute_alert(history, settings)
        entries.append(
            WatchlistEntry(
                address=address,
                label=label,
                chain=chain,
                portfolio=portfolio,
                history=history,
                change_24h_pct=change_pct,
                alert_active=alert_active,
                alert_reason=alert_reason,
            )
        )
    return entries


@router.post("/poll", response_model=list[WatchlistEntry])
async def trigger_poll(
    zerion: ZerionClient = Depends(get_zerion),
    quicknode: QuickNodeClient = Depends(get_quicknode),
    settings: Settings = Depends(get_settings_dep),
) -> list[WatchlistEntry]:
    """Manual poll trigger — useful for demoing without waiting for the scheduler."""
    return await poll_once(zerion, quicknode, settings)
