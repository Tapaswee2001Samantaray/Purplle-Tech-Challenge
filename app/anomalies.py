from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .metrics import compute_metrics, customer_events
from .models import EventType, parse_dt


def detect_anomalies(
    events: list[dict[str, Any]],
    pos_transactions: list[dict[str, Any]],
    stale_feed_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    anomalies: list[dict[str, Any]] = []
    metrics = compute_metrics(events, pos_transactions)

    if metrics["queue_depth"] >= 10:
        anomalies.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL",
                "value": metrics["queue_depth"],
                "suggested_action": "Open another billing counter or move staff to checkout.",
            }
        )
    elif metrics["queue_depth"] >= 5:
        anomalies.append(
            {
                "type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "value": metrics["queue_depth"],
                "suggested_action": "Monitor queue and prepare checkout support.",
            }
        )

    latest_by_zone: dict[str, datetime] = {}
    for event in customer_events(events):
        if event.get("zone_id") and event["event_type"] in {
            EventType.ZONE_ENTER.value,
            EventType.ZONE_DWELL.value,
        }:
            latest_by_zone[event["zone_id"]] = parse_dt(event["timestamp"])
    for zone_id, last_seen in sorted(latest_by_zone.items()):
        if now - last_seen > timedelta(minutes=30):
            anomalies.append(
                {
                    "type": "DEAD_ZONE",
                    "severity": "WARN",
                    "zone_id": zone_id,
                    "last_seen": last_seen.isoformat().replace("+00:00", "Z"),
                    "suggested_action": "Check merchandising, signage, or camera coverage.",
                }
            )

    if events:
        last_event = max(parse_dt(event["timestamp"]) for event in events)
        lag_seconds = int((now - last_event).total_seconds())
        if lag_seconds > stale_feed_seconds:
            anomalies.append(
                {
                    "type": "STALE_FEED",
                    "severity": "WARN",
                    "lag_seconds": lag_seconds,
                    "suggested_action": "Verify camera stream and detection worker health.",
                }
            )

    return {"anomalies": anomalies}

