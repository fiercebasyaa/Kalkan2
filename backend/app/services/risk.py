"""Risk scoring — turns scam-db flags + tx-history exposure into 0-100 + light."""

from __future__ import annotations

from app.models import Reason, RiskReport, ScamFlag, Transaction

SEVERITY_WEIGHT = {"critical": 100, "high": 55, "medium": 30, "low": 12}


def score_address(
    direct_flags: list[ScamFlag],
    counterparty_flags: dict[str, list[ScamFlag]],
) -> RiskReport:
    reasons: list[Reason] = []
    score = 0

    if direct_flags:
        score = max(score, max(SEVERITY_WEIGHT.get(f.severity, 20) for f in direct_flags))
        # A real incident (e.g. "Ronin Bridge Exploiter") often shows up
        # in 3-5 of our sources at once (OFAC + Etherscan labels + the
        # scrape on 3 chains) — one bullet per flag turned into a wall of
        # near-identical sentences. One address, one line.
        if len(direct_flags) == 1:
            f = direct_flags[0]
            reasons.append(Reason(code="risk_direct_flag", params={"source": f.source, "label": f.label}))
        else:
            worst = max(direct_flags, key=lambda f: SEVERITY_WEIGHT.get(f.severity, 0))
            sources = ", ".join(dict.fromkeys(f.source for f in direct_flags))  # de-duped, order preserved
            reasons.append(
                Reason(
                    code="risk_direct_flags_multi",
                    params={"count": len(direct_flags), "sources": sources, "label": worst.label},
                )
            )

    tainted_counterparties = 0
    for cp_addr, flags in counterparty_flags.items():
        if not flags:
            continue
        tainted_counterparties += 1
        worst = max(flags, key=lambda f: SEVERITY_WEIGHT.get(f.severity, 0))
        contribution = min(SEVERITY_WEIGHT.get(worst.severity, 20), 40)
        score = max(score, contribution)

    if tainted_counterparties:
        reasons.append(
            Reason(
                code="risk_counterparty_flags",
                params={
                    "count": tainted_counterparties,
                    "flag_count": sum(len(f) for f in counterparty_flags.values()),
                },
            )
        )

    score = min(score, 100)
    if score >= 70:
        level = "red"
    elif score >= 30:
        level = "yellow"
    elif not reasons:
        level = "green"
    else:
        level = "yellow"

    if not reasons:
        reasons.append(Reason(code="risk_clean"))

    return RiskReport(score=score, level=level, reasons=reasons)


NULL_ADDRESS = "0x0000000000000000000000000000000000000000"


def counterparties_from_transactions(transactions: list[Transaction], limit: int = 25) -> list[str]:
    """Distinct counterparties, excluding the null address.

    0x000...000 shows up constantly as the "sender" on NFT/token mints and
    as the "recipient" on burns — completely routine activity, not a real
    counterparty entity. Flagging it (Etherscan labels tags it
    "blocked, burn, genesis") would put a false red flag on almost any
    wallet that has ever minted an NFT or burned a token.
    """
    seen: list[str] = []
    for tx in transactions:
        if not tx.counterparty or tx.counterparty.lower() == NULL_ADDRESS:
            continue
        if tx.counterparty not in seen:
            seen.append(tx.counterparty)
        if len(seen) >= limit:
            break
    return seen
