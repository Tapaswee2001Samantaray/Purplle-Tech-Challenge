from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from .models import EventType, parse_dt


def default_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def customer_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if not event["is_staff"]]


def session_ids(events: list[dict[str, Any]]) -> set[str]:
    entries = {
        event["visitor_id"]
        for event in events
        if event["event_type"] == EventType.ENTRY.value
    }
    return entries or {event["visitor_id"] for event in events}


def billing_visitors(events: list[dict[str, Any]]) -> dict[str, list[datetime]]:
    by_visitor: dict[str, list[datetime]] = defaultdict(list)
    for event in events:
        zone = (event.get("zone_id") or "").upper()
        if event["event_type"] == EventType.BILLING_QUEUE_JOIN.value or zone == "BILLING":
            by_visitor[event["visitor_id"]].append(parse_dt(event["timestamp"]))
    return by_visitor


def converted_visitors(
    events: list[dict[str, Any]],
    pos_transactions: list[dict[str, Any]],
    window_seconds: int = 60,
) -> set[str]:
    billing = billing_visitors(events)
    converted: set[str] = set()
    for transaction in pos_transactions:
        tx_time = parse_dt(transaction["timestamp"])
        start = tx_time - timedelta(seconds=window_seconds)
        candidates: list[tuple[datetime, str]] = []
        for visitor_id, timestamps in billing.items():
            if visitor_id in converted:
                continue
            for seen_at in timestamps:
                if start <= seen_at <= tx_time:
                    candidates.append((seen_at, visitor_id))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            converted.add(candidates[0][1])
    return converted


def compute_metrics(
    events: list[dict[str, Any]],
    pos_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    customers = customer_events(events)
    sessions = session_ids(customers)
    converted = converted_visitors(customers, pos_transactions)

    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    for event in customers:
        if event["event_type"] == EventType.ZONE_DWELL.value and event.get("zone_id"):
            dwell_by_zone[event["zone_id"]].append(int(event.get("dwell_ms") or 0))
    avg_dwell = {
        zone_id: round(mean(values), 2) if values else 0.0
        for zone_id, values in sorted(dwell_by_zone.items())
    }

    queue_joins = [
        event for event in customers if event["event_type"] == EventType.BILLING_QUEUE_JOIN.value
    ]
    abandons = [
        event
        for event in customers
        if event["event_type"] == EventType.BILLING_QUEUE_ABANDON.value
    ]
    latest_queue_depth = 0
    if queue_joins:
        latest = max(queue_joins, key=lambda event: event["timestamp"])
        latest_queue_depth = int((latest.get("metadata") or {}).get("queue_depth") or 0)

    unique_visitors = len(sessions)
    return {
        "unique_visitors": unique_visitors,
        "converted_visitors": len(converted),
        "conversion_rate": round(len(converted) / unique_visitors, 4)
        if unique_visitors
        else 0.0,
        "avg_dwell_per_zone_ms": avg_dwell,
        "queue_depth": latest_queue_depth,
        "abandonment_rate": round(len(abandons) / len(queue_joins), 4)
        if queue_joins
        else 0.0,
        "event_count": len(events),
        "customer_event_count": len(customers),
    }


def compute_heatmap(events: list[dict[str, Any]]) -> dict[str, Any]:
    customers = customer_events(events)
    zone_visitors: dict[str, set[str]] = defaultdict(set)
    dwell_by_zone: dict[str, list[int]] = defaultdict(list)
    for event in customers:
        zone_id = event.get("zone_id")
        if not zone_id:
            continue
        if event["event_type"] in {
            EventType.ZONE_ENTER.value,
            EventType.ZONE_DWELL.value,
            EventType.BILLING_QUEUE_JOIN.value,
        }:
            zone_visitors[zone_id].add(event["visitor_id"])
        if event["event_type"] == EventType.ZONE_DWELL.value:
            dwell_by_zone[zone_id].append(int(event.get("dwell_ms") or 0))

    max_visits = max((len(visitors) for visitors in zone_visitors.values()), default=0)
    zones = []
    for zone_id in sorted(zone_visitors):
        visits = len(zone_visitors[zone_id])
        zones.append(
            {
                "zone_id": zone_id,
                "visit_frequency": visits,
                "normalized_visit_frequency": round((visits / max_visits) * 100, 2)
                if max_visits
                else 0.0,
                "avg_dwell_ms": round(mean(dwell_by_zone[zone_id]), 2)
                if dwell_by_zone[zone_id]
                else 0.0,
                "data_confidence": "LOW" if visits < 20 else "OK",
            }
        )
    return {"zones": zones}
