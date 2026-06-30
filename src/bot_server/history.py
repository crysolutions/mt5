"""Group closed trades and bot events by day, week, or month."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

GroupBy = Literal["day", "week", "month"]


def parse_local_dt(iso_time: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except (TypeError, ValueError):
        return None


def local_today() -> datetime.date:
    return datetime.now().astimezone().date()


def period_key(dt: datetime, group_by: GroupBy) -> str:
    if group_by == "day":
        return dt.date().isoformat()
    if group_by == "week":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    return f"{dt.year}-{dt.month:02d}"


def period_label(key: str, group_by: GroupBy) -> str:
    if group_by == "day":
        d = datetime.fromisoformat(key).date()
        return d.strftime("%a, %b %d, %Y")
    if group_by == "week":
        year_s, week_s = key.split("-W")
        year, week = int(year_s), int(week_s)
        start = datetime.fromisocalendar(year, week, 1).date()
        end = start + timedelta(days=6)
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    year_s, month_s = key.split("-")
    d = datetime(int(year_s), int(month_s), 1)
    return d.strftime("%B %Y")


def build_history_periods(
    closed_trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    group_by: GroupBy,
    *,
    exclude_today: bool = True,
) -> list[dict[str, Any]]:
    """Aggregate trades and orders into sorted periods (newest first)."""
    today = local_today()
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "closed_trades": [],
            "orders": [],
            "total_pnl": 0.0,
            "closed_count": 0,
            "order_count": 0,
        }
    )

    for trade in closed_trades:
        dt = parse_local_dt(str(trade.get("time", "")))
        if dt is None:
            continue
        if exclude_today and group_by == "day" and dt.date() == today:
            continue
        key = period_key(dt, group_by)
        bucket = buckets[key]
        bucket["closed_trades"].append(trade)
        bucket["closed_count"] += 1
        bucket["total_pnl"] += float(trade.get("pnl", 0))

    for order in orders:
        dt = parse_local_dt(str(order.get("time", "")))
        if dt is None:
            continue
        if exclude_today and group_by == "day" and dt.date() == today:
            continue
        key = period_key(dt, group_by)
        bucket = buckets[key]
        bucket["orders"].append(order)
        bucket["order_count"] += 1

    periods: list[dict[str, Any]] = []
    for key in sorted(buckets.keys(), reverse=True):
        data = buckets[key]
        data["closed_trades"].sort(key=lambda t: t.get("time", ""), reverse=True)
        data["orders"].sort(key=lambda o: o.get("time", ""), reverse=True)
        periods.append(
            {
                "key": key,
                "label": period_label(key, group_by),
                "group_by": group_by,
                "total_pnl": round(data["total_pnl"], 2),
                "closed_count": data["closed_count"],
                "order_count": data["order_count"],
                "closed_trades": data["closed_trades"],
                "orders": data["orders"],
            }
        )

    return periods
