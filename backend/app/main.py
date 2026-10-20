from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import address, watchlist
from app.services.quicknode import QuickNodeClient
from app.services.scamdb.aggregator import ScamDbAggregator
from app.services.stats import DailyCounter
from app.services.zerion import ZerionClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


async def _watchlist_poll_loop(app: FastAPI) -> None:
    settings = app.state.settings
    while True:
        try:
            await watchlist.poll_once(app.state.zerion, app.state.quicknode, settings)
        except Exception:  # noqa: BLE001 — background loop must never die silently
            logger.exception("Watchlist poll cycle failed")
        await asyncio.sleep(settings.watchlist_poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.zerion = ZerionClient(settings)
    app.state.quicknode = QuickNodeClient(settings)
    app.state.scamdb = ScamDbAggregator(settings)
    app.state.daily_counter = DailyCounter()

    await app.state.scamdb.ensure_loaded()
    poll_task = asyncio.create_task(_watchlist_poll_loop(app))

    yield

    poll_task.cancel()
    await app.state.zerion.aclose()
    await app.state.quicknode.aclose()


app = FastAPI(title="Kalkan", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(address.router)
app.include_router(watchlist.router)


QUICKNODE_KNOWN_CHAINS = ["ethereum", "arbitrum", "base", "polygon", "optimism", "bsc", "avalanche"]


@app.get("/api/health")
async def health():
    settings = get_settings()
    configured = set(settings.quicknode_urls)
    return {
        "status": "ok",
        "zerion_configured": settings.zerion_enabled,
        "quicknode_networks": {
            chain: ("configured" if chain in configured else "not configured")
            for chain in QUICKNODE_KNOWN_CHAINS
        },
        "chainabuse_configured": settings.chainabuse_enabled,
        "telegram_configured": settings.telegram_enabled,
    }


@app.get("/api/stats")
async def stats(request: Request):
    settings = get_settings()
    watchlist_count = len(watchlist.load_watchlist_config())
    return {
        "checks_today": request.app.state.daily_counter.count,
        "platforms_monitored": watchlist_count,
        "chains_configured": len(settings.quicknode_urls),
        "languages": 3,
    }


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
