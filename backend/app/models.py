from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["green", "yellow", "red", "unknown"]


class Reason(BaseModel):
    """A machine-readable reason: a translation-key `code` plus the
    interpolation params the frontend's i18n templates need. Keeps the
    backend language-neutral — the RU/EN/TR text lives entirely in
    frontend/i18n/*.json, not here."""

    code: str
    params: dict[str, str | int | float | None] = Field(default_factory=dict)


class TokenBalance(BaseModel):
    symbol: str
    name: str | None = None
    quantity: float
    usd_value: float | None = None
    chain: str | None = None


class PortfolioSummary(BaseModel):
    total_usd_value: float | None = None
    tokens: list[TokenBalance] = Field(default_factory=list)
    source: Literal["zerion", "quicknode", "unavailable"] = "unavailable"


class Transaction(BaseModel):
    hash: str
    timestamp: str | None = None
    direction: Literal["in", "out", "self", "unknown"] = "unknown"
    counterparty: str | None = None
    value_usd: float | None = None
    asset: str | None = None


class ScamFlag(BaseModel):
    address: str
    source: str  # "OFAC SDN", "CryptoScamDB", "Chainabuse", "Etherscan labels"
    label: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    reference_url: str | None = None


class RiskReport(BaseModel):
    score: int  # 0-100, higher = riskier
    level: RiskLevel
    reasons: list[Reason] = Field(default_factory=list)


class AddressCheckResponse(BaseModel):
    address: str
    checksum_valid_format: bool
    portfolio: PortfolioSummary
    recent_transactions: list[Transaction] = Field(default_factory=list)
    flags: list[ScamFlag] = Field(default_factory=list)
    counterparties_checked: int = 0
    risk: RiskReport
    warnings: list[Reason] = Field(default_factory=list)


class WatchlistSnapshot(BaseModel):
    timestamp: str
    total_usd_value: float | None
    native_balance: float | None = None


class WatchlistEntry(BaseModel):
    address: str
    label: str
    chain: str = "ethereum"
    portfolio: PortfolioSummary
    history: list[WatchlistSnapshot] = Field(default_factory=list)
    change_24h_pct: float | None = None
    alert_active: bool = False
    alert_reason: Reason | None = None
