"""Publishes watchlist anomaly alerts to a public Telegram channel.

No per-user configuration — one fixed broadcast channel for the demo
watchlist, per the product brief (Telegram is not a bot with user settings).
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


async def send_alert(settings: Settings, text: str) -> bool:
    if not settings.telegram_enabled:
        logger.info("Telegram alert skipped (not configured): %s", text)
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": settings.telegram_channel_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.warning("Telegram alert send failed: %s", exc)
        return False
