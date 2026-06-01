from __future__ import annotations

from typing import Any

from .metrics import converted_visitors, customer_events, session_ids
from .models import EventType


def compute_funnel(
    events: list[dict[str, Any]],
    pos_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    customers = customer_events(events)
    entry = session_ids(customers)
    zone_visit = {
        event["visitor_id"]
        for event in customers
        if event["event_type"] in {EventType.ZONE_ENTER.value, EventType.ZONE_DWELL.value}
    }
    billing_queue = {
        event["visitor_id"]
        for event in customers
        if event["event_type"] == EventType.BILLING_QUEUE_JOIN.value
        or (event.get("zone_id") or "").upper() == "BILLING"
    }
    purchase = converted_visitors(customers, pos_transactions)

    stages = [
        ("entry", entry),
        ("zone_visit", entry & zone_visit if entry else zone_visit),
        ("billing_queue", entry & billing_queue if entry else billing_queue),
        ("purchase", entry & purchase if entry else purchase),
    ]
    response = []
    previous_count: int | None = None
    for name, visitors in stages:
        count = len(visitors)
        response.append(
            {
                "stage": name,
                "count": count,
                "dropoff_from_previous": 0
                if previous_count is None
                else max(previous_count - count, 0),
                "dropoff_pct_from_previous": 0.0
                if previous_count in (None, 0)
                else round((max(previous_count - count, 0) / previous_count) * 100, 2),
            }
        )
        previous_count = count
    return {"stages": response}
