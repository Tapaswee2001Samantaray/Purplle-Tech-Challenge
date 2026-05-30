from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ingestion import StoreDatabase


def service_health(db: StoreDatabase, stale_feed_seconds: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stores = {}
    warnings = []
    for store_id, last_event in db.last_event_by_store().items():
        last = datetime.fromisoformat(last_event.replace("Z", "+00:00"))
        lag_seconds = int((now - last).total_seconds())
        store_status = "ok"
        if lag_seconds > stale_feed_seconds:
            store_status = "stale"
            warnings.append({"store_id": store_id, "code": "STALE_FEED"})
        stores[store_id] = {
            "status": store_status,
            "last_event_timestamp": last_event,
            "lag_seconds": lag_seconds,
        }
    return {
        "status": "ok" if not warnings else "warn",
        "stores": stores,
        "warnings": warnings,
    }

