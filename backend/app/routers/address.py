from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_quicknode, get_scamdb, get_zerion
from app.models import AddressCheckResponse, PortfolioSummary, Reason
from app.services.quicknode import QuickNodeClient
from app.services.risk import counterparties_from_transactions, score_address
from app.services.scamdb.aggregator import ScamDbAggregator
from app.services.zerion import ZerionClient

router = APIRouter(prefix="/api/address", tags=["address"])

EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

# in-memory cache so re-viewing / exporting the same address in a session
# doesn't refire every upstream call
_last_reports: dict[str, AddressCheckResponse] = {}


async def _build_report(
    address: str,
    zerion: ZerionClient,
    quicknode: QuickNodeClient,
    scamdb: ScamDbAggregator,
) -> AddressCheckResponse:
    warnings: list[Reason] = []
    is_valid_format = bool(EVM_ADDRESS_RE.match(address))
    if not is_valid_format:
        raise HTTPException(status_code=400, detail="invalid_address_format")

    portfolio = await zerion.get_portfolio(address)
    if portfolio.source == "zerion":
        positions = await zerion.get_positions(address, limit=20)
        portfolio = PortfolioSummary(
            total_usd_value=portfolio.total_usd_value,
            tokens=sorted(positions, key=lambda t: t.usd_value or 0, reverse=True)[:20],
            source="zerion",
        )
    elif portfolio.source == "unavailable":
        wei = await quicknode.get_native_balance_wei(address)
        if wei is not None:
            portfolio = PortfolioSummary(
                total_usd_value=None,
                tokens=[],
                source="quicknode",
            )
            warnings.append(Reason(code="warn_quicknode_fallback", params={"balance": wei / 1e18}))
        else:
            warnings.append(Reason(code="warn_no_portfolio_source"))

    transactions = await zerion.get_transactions(address, limit=50)
    if not transactions:
        if not zerion.enabled:
            warnings.append(Reason(code="warn_zerion_not_configured"))
        else:
            warnings.append(Reason(code="warn_zerion_no_tx"))

    direct_flags = await scamdb.check_address(address)

    counterparties = counterparties_from_transactions(transactions, limit=25)
    counterparty_flags = await scamdb.check_many(counterparties) if counterparties else {}

    risk = score_address(direct_flags, counterparty_flags)

    all_flags = list(direct_flags)
    for cp, flags in counterparty_flags.items():
        all_flags.extend(flags)

    report = AddressCheckResponse(
        address=address,
        checksum_valid_format=is_valid_format,
        portfolio=portfolio,
        recent_transactions=transactions[:20],
        flags=all_flags,
        counterparties_checked=len(counterparties),
        risk=risk,
        warnings=warnings,
    )
    _last_reports[address.lower()] = report
    return report


@router.get("/{address}", response_model=AddressCheckResponse)
async def check_address(
    address: str,
    request: Request,
    zerion: ZerionClient = Depends(get_zerion),
    quicknode: QuickNodeClient = Depends(get_quicknode),
    scamdb: ScamDbAggregator = Depends(get_scamdb),
) -> AddressCheckResponse:
    request.app.state.daily_counter.increment()
    return await _build_report(address, zerion, quicknode, scamdb)


@router.get("/{address}/export")
async def export_address(
    address: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    zerion: ZerionClient = Depends(get_zerion),
    quicknode: QuickNodeClient = Depends(get_quicknode),
    scamdb: ScamDbAggregator = Depends(get_scamdb),
):
    """Exports the full address report — portfolio, tokens, transactions,
    every flag, and risk score. (Originally this only exported the flags
    table, so a clean or single-flag address produced an almost-empty
    file; not worth clicking.)"""
    report = _last_reports.get(address.lower()) or await _build_report(address, zerion, quicknode, scamdb)

    if format == "json":
        return report.model_dump()

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["Crypto Reserve Watchdog — address report"])
    writer.writerow(["Address", report.address])
    writer.writerow(["Risk score (0-100)", report.risk.score])
    writer.writerow(["Risk level", report.risk.level])
    for reason in report.risk.reasons:
        writer.writerow(["Risk reason", reason])
    writer.writerow([])

    writer.writerow(["Portfolio"])
    writer.writerow(["Total USD value", report.portfolio.total_usd_value])
    writer.writerow(["Source", report.portfolio.source])
    writer.writerow([])
    writer.writerow(["Symbol", "Name", "Quantity", "USD value"])
    for t in report.portfolio.tokens:
        writer.writerow([t.symbol, t.name, t.quantity, t.usd_value])
    writer.writerow([])

    writer.writerow(["Flags", f"{len(report.flags)} total"])
    writer.writerow(["Source", "Label", "Severity", "Flagged address", "Reference URL"])
    for f in report.flags:
        writer.writerow([f.source, f.label, f.severity, f.address, f.reference_url])
    writer.writerow([])

    writer.writerow(["Recent transactions", f"{len(report.recent_transactions)} shown"])
    writer.writerow(["Hash", "Timestamp", "Direction", "Counterparty", "Value USD", "Asset"])
    for tx in report.recent_transactions:
        writer.writerow([tx.hash, tx.timestamp, tx.direction, tx.counterparty, tx.value_usd, tx.asset])

    if report.warnings:
        writer.writerow([])
        writer.writerow(["Warnings"])
        for w in report.warnings:
            writer.writerow([w])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={address}_report.csv"},
    )
