from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4


VALID_EVENT_TYPES = {
    "ENTRY",
    "EXIT",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "ZONE_DWELL",
    "BILLING_QUEUE_JOIN",
    "BILLING_QUEUE_ABANDON",
    "REENTRY",
}


def make_event(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    *,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 1.0,
    metadata: dict | None = None,
) -> dict:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event_type}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {
        "event_id": str(uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "zone_id": zone_id,
        "dwell_ms": max(int(dwell_ms), 0),
        "is_staff": bool(is_staff),
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "metadata": metadata or {},
    }


def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc


def validate_event(payload: dict, line_number: int | None = None) -> dict:
    required = {"store_id", "camera_id", "visitor_id", "event_type", "timestamp"}
    missing = sorted(required - payload.keys())
    if missing:
        prefix = f"row {line_number}: " if line_number else ""
        raise ValueError(f"{prefix}missing fields {missing}")
    if payload["event_type"] not in VALID_EVENT_TYPES:
        prefix = f"row {line_number}: " if line_number else ""
        raise ValueError(f"{prefix}unknown event_type {payload['event_type']}")
    payload.setdefault("event_id", str(uuid4()))
    payload.setdefault("zone_id", None)
    payload.setdefault("dwell_ms", 0)
    payload.setdefault("is_staff", False)
    payload.setdefault("confidence", 1.0)
    payload.setdefault("metadata", {})
    return payload


def write_jsonl(events: Iterable[dict], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(validate_event(event), sort_keys=True) + "\n")
            count += 1
    return count


def post_batch(api_url: str, batch: list[dict]) -> dict:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/events/ingest",
        data=json.dumps({"events": batch}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not post events to {api_url}: {exc}") from exc


def replay_jsonl(path: Path, api_url: str, batch_size: int = 100, delay_seconds: float = 0.0) -> None:
    batch: list[dict] = []
    for event in read_jsonl(path):
        batch.append(validate_event(event))
        if len(batch) >= batch_size:
            print(post_batch(api_url, batch))
            batch.clear()
            if delay_seconds:
                time.sleep(delay_seconds)
    if batch:
        print(post_batch(api_url, batch))

