from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.db.close()


@pytest.fixture()
def event():
    def build_event(
        event_id: str,
        visitor_id: str,
        event_type: str,
        timestamp: str,
        **overrides,
    ) -> dict:
        payload = {
            "event_id": event_id,
            "store_id": "ST1008",
            "camera_id": "CAM_ENTRY",
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.92,
            "metadata": {},
        }
        payload.update(overrides)
        return payload

    return build_event
