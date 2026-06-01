"""
PROMPT:
Create edge-case tests for retail store analytics: staff exclusion, zero purchases,
POS correlation by billing-zone timing, funnel de-duplication, and heatmap confidence.

CHANGES MADE:
Used explicit timestamps and compact fixture events so the business rules are readable.
"""


def test_ingest_is_idempotent(client, event):
    payload = {
        "events": [
            event("evt-1", "VIS_1", "ENTRY", "2026-05-30T10:00:00Z"),
        ]
    }

    first = client.post("/events/ingest", json=payload)
    second = client.post("/events/ingest", json=payload)

    assert first.status_code == 200
    assert first.json()["accepted"] == 1
    assert second.status_code == 200
    assert second.json()["duplicates"] == 1


def test_ingest_partial_success(client, event):
    response = client.post(
        "/events/ingest",
        json={
            "events": [
                event("evt-1", "VIS_1", "ENTRY", "2026-05-30T10:00:00Z"),
                {"event_id": "bad-row"},
            ]
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["errors"][0]["index"] == 1


def test_ingest_rejects_batches_over_500(client, event):
    payload = {
        "events": [
            event(f"evt-{index}", f"VIS_{index}", "ENTRY", "2026-05-30T10:00:00Z")
            for index in range(501)
        ]
    }

    response = client.post("/events/ingest", json=payload)

    body = response.json()
    assert body["accepted"] == 0
    assert body["rejected"] == 501
    assert "500" in body["errors"][0]["reason"]


def seed_purchase_flow(client, event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                event("evt-1", "VIS_1", "ENTRY", "2026-05-30T10:00:00Z"),
                event(
                    "evt-2",
                    "VIS_1",
                    "ZONE_ENTER",
                    "2026-05-30T10:01:00Z",
                    zone_id="SKINCARE",
                ),
                event(
                    "evt-3",
                    "VIS_1",
                    "ZONE_DWELL",
                    "2026-05-30T10:02:00Z",
                    zone_id="SKINCARE",
                    dwell_ms=45000,
                ),
                event(
                    "evt-4",
                    "VIS_1",
                    "BILLING_QUEUE_JOIN",
                    "2026-05-30T10:03:30Z",
                    camera_id="CAM_BILLING",
                    zone_id="BILLING",
                    metadata={"queue_depth": 3},
                ),
                event(
                    "evt-5",
                    "STAFF_1",
                    "ENTRY",
                    "2026-05-30T10:04:00Z",
                    is_staff=True,
                ),
                event("evt-6", "VIS_1", "REENTRY", "2026-05-30T10:05:00Z"),
            ]
        },
    )
    client.post(
        "/pos/ingest",
        json={
            "transactions": [
                {
                    "store_id": "ST1008",
                    "transaction_id": "TXN_1",
                    "timestamp": "2026-05-30T10:04:00Z",
                    "basket_value_inr": 1299,
                }
            ]
        },
    )


def test_metrics_exclude_staff_and_correlate_pos(client, event):
    seed_purchase_flow(client, event)

    response = client.get(
        "/stores/ST1008/metrics",
        params={
            "start": "2026-05-30T00:00:00Z",
            "end": "2026-05-31T00:00:00Z",
        },
    )

    body = response.json()
    assert body["unique_visitors"] == 1
    assert body["converted_visitors"] == 1
    assert body["conversion_rate"] == 1
    assert body["avg_dwell_per_zone_ms"]["SKINCARE"] == 45000
    assert body["queue_depth"] == 3


def test_metrics_without_window_uses_latest_event_day(client, event):
    seed_purchase_flow(client, event)

    response = client.get("/stores/ST1008/metrics")

    body = response.json()
    assert body["unique_visitors"] == 1
    assert body["converted_visitors"] == 1
    assert body["queue_depth"] == 3


def test_funnel_uses_session_not_raw_events(client, event):
    seed_purchase_flow(client, event)

    response = client.get(
        "/stores/ST1008/funnel",
        params={
            "start": "2026-05-30T00:00:00Z",
            "end": "2026-05-31T00:00:00Z",
        },
    )

    stages = {stage["stage"]: stage["count"] for stage in response.json()["stages"]}
    assert stages == {
        "entry": 1,
        "zone_visit": 1,
        "billing_queue": 1,
        "purchase": 1,
    }
    purchase_stage = response.json()["stages"][-1]
    assert "dropoff_pct_from_previous" in purchase_stage


def test_heatmap_uses_0_to_100_normalization_and_confidence(client, event):
    seed_purchase_flow(client, event)

    response = client.get("/stores/ST1008/heatmap")

    zones = {zone["zone_id"]: zone for zone in response.json()["zones"]}
    assert zones["SKINCARE"]["normalized_visit_frequency"] == 100
    assert zones["SKINCARE"]["data_confidence"] == "LOW"


def test_zero_purchase_store_returns_zero_not_null(client, event):
    client.post(
        "/events/ingest",
        json={"events": [event("evt-1", "VIS_1", "ENTRY", "2026-05-30T10:00:00Z")]},
    )

    response = client.get(
        "/stores/ST1008/metrics",
        params={
            "start": "2026-05-30T00:00:00Z",
            "end": "2026-05-31T00:00:00Z",
        },
    )

    body = response.json()
    assert body["unique_visitors"] == 1
    assert body["converted_visitors"] == 0
    assert body["conversion_rate"] == 0
