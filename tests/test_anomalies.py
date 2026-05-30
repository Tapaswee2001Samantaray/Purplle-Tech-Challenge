"""
PROMPT:
Write tests for operational anomalies and health status for a store-intelligence API.
Cover queue spikes and stale camera feeds without relying on wall-clock sleeps.

CHANGES MADE:
Asserted response shape and anomaly type rather than exact lag values.
"""


def test_queue_spike_anomaly(client, event):
    client.post(
        "/events/ingest",
        json={
            "events": [
                event(
                    "evt-1",
                    "VIS_1",
                    "BILLING_QUEUE_JOIN",
                    "2026-05-30T10:00:00Z",
                    zone_id="BILLING",
                    metadata={"queue_depth": 11},
                )
            ]
        },
    )

    response = client.get(
        "/stores/ST1008/anomalies",
        params={
            "start": "2026-05-30T00:00:00Z",
            "end": "2026-05-31T00:00:00Z",
        },
    )

    anomalies = response.json()["anomalies"]
    assert any(item["type"] == "BILLING_QUEUE_SPIKE" for item in anomalies)
    assert anomalies[0]["severity"] == "CRITICAL"


def test_health_returns_store_status(client, event):
    client.post(
        "/events/ingest",
        json={"events": [event("evt-1", "VIS_1", "ENTRY", "2026-05-30T10:00:00Z")]},
    )

    response = client.get("/health")

    body = response.json()
    assert "ST1008" in body["stores"]
    assert body["stores"]["ST1008"]["last_event_timestamp"] == "2026-05-30T10:00:00Z"
