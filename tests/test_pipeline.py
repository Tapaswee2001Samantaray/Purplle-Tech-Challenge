"""
PROMPT:
Generate tests for the CCTV event pipeline emission layer. Validate required fields,
event type enforcement, default values, and tracker identity stability.

CHANGES MADE:
Kept the tests dependency-free so they run without OpenCV, YOLO weights, or sample clips.
"""

from datetime import datetime, timezone

import pytest

from pipeline.emit import make_event, validate_event
from pipeline.pos_loader import csv_to_transactions
from pipeline.tracker import CentroidTracker, Detection


def test_make_event_emits_required_schema():
    payload = make_event(
        "ST1008",
        "CAM_ENTRY",
        "VIS_1",
        "ENTRY",
        datetime(2026, 5, 30, 10, 0, tzinfo=timezone.utc),
        confidence=1.7,
    )

    assert payload["event_id"]
    assert payload["timestamp"] == "2026-05-30T10:00:00Z"
    assert payload["confidence"] == 1.0
    assert payload["metadata"] == {}


def test_validate_event_rejects_unknown_type():
    with pytest.raises(ValueError):
        validate_event(
            {
                "store_id": "ST1008",
                "camera_id": "CAM_ENTRY",
                "visitor_id": "VIS_1",
                "event_type": "BAD_EVENT",
                "timestamp": "2026-05-30T10:00:00Z",
            }
        )


def test_tracker_keeps_identity_for_nearby_detection():
    tracker = CentroidTracker(max_distance=50)

    first = tracker.update([Detection((0, 0, 20, 20), 0.9)])
    second = tracker.update([Detection((4, 3, 24, 23), 0.88)])

    assert list(first.keys()) == list(second.keys())


def test_pos_loader_aggregates_invoice_rows(tmp_path):
    csv_path = tmp_path / "pos.csv"
    csv_path.write_text(
        "order_id,invoice_number,invoice_type,order_date,order_time,store_id,total_amount,NMV,GMV\n"
        "1,INV_1,sales,10-04-2026,12:00:00,ST1008,100,100,100\n"
        "1,INV_1,sales,10-04-2026,12:00:00,ST1008,50,50,50\n",
        encoding="utf-8",
    )

    transactions = csv_to_transactions(csv_path)

    assert transactions == [
        {
            "store_id": "ST1008",
            "transaction_id": "INV_1",
            "timestamp": "2026-04-10T12:00:00+05:30",
            "basket_value_inr": 150.0,
        }
    ]
