"""Secure Profit (SP) — ratcheting stop-loss to lock unrealized gains."""

from __future__ import annotations


def compute_sp_target(
    unrealized_profit: float,
    threshold_half: float,
    threshold_three_quarter: float,
) -> tuple[float, float]:
    """Return target (secure_pct, secure_usd) from a position's unrealized profit.

    - profit > $10 → secure 75% via stop-loss
    - profit > $5  → secure 50% via stop-loss
    - otherwise   → no SP action
    """
    if unrealized_profit <= threshold_half:
        return 0.0, 0.0
    if unrealized_profit > threshold_three_quarter:
        return 0.75, unrealized_profit * 0.75
    return 0.50, unrealized_profit * 0.50


def ratchet_sp(
    previous_usd: float,
    previous_pct: float,
    target_usd: float,
    target_pct: float,
) -> tuple[float, float]:
    """SP never decreases — keep the highest secured level seen."""
    if target_usd > previous_usd:
        return target_usd, max(previous_pct, target_pct)
    return previous_usd, previous_pct
