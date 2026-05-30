from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .anomalies import detect_anomalies
from .funnel import compute_funnel
from .health import service_health
from .ingestion import StoreDatabase, ingest_event_batch, ingest_pos_batch
from .metrics import compute_heatmap, compute_metrics, default_window


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("store_intelligence")


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Store Intelligence API", version="1.0.0")
    app.state.db = StoreDatabase(db_path or os.getenv("DB_PATH", "store_intelligence.db"))

    @app.middleware("http")
    async def structured_logging(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id", str(uuid4()))
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-trace-id"] = trace_id
            return response
        finally:
            logger.info(
                json.dumps(
                    {
                        "trace_id": trace_id,
                        "method": request.method,
                        "endpoint": request.url.path,
                        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                        "status_code": status_code,
                    }
                )
            )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, exc: Exception):
        logger.exception("Unhandled application error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The service could not complete the request.",
                }
            },
        )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "store-intelligence", "status": "ok"}

    @app.post("/events/ingest")
    async def ingest_events(request: Request):
        payload = await request.json()
        raw_events = payload if isinstance(payload, list) else payload.get("events")
        return ingest_event_batch(request.app.state.db, raw_events)

    @app.post("/pos/ingest")
    async def ingest_pos(request: Request):
        payload = await request.json()
        raw_items = payload if isinstance(payload, list) else payload.get("transactions")
        return ingest_pos_batch(request.app.state.db, raw_items)

    @app.get("/stores/{store_id}/metrics")
    def metrics(store_id: str, request: Request, start: str | None = None, end: str | None = None):
        window_start, window_end = parse_window(start, end)
        db: StoreDatabase = request.app.state.db
        return compute_metrics(
            db.fetch_events(store_id, window_start, window_end),
            db.fetch_pos(store_id, window_start, window_end),
        )

    @app.get("/stores/{store_id}/funnel")
    def funnel(store_id: str, request: Request, start: str | None = None, end: str | None = None):
        window_start, window_end = parse_window(start, end)
        db: StoreDatabase = request.app.state.db
        return compute_funnel(
            db.fetch_events(store_id, window_start, window_end),
            db.fetch_pos(store_id, window_start, window_end),
        )

    @app.get("/stores/{store_id}/heatmap")
    def heatmap(store_id: str, request: Request, start: str | None = None, end: str | None = None):
        window_start, window_end = parse_window(start, end)
        db: StoreDatabase = request.app.state.db
        return compute_heatmap(db.fetch_events(store_id, window_start, window_end))

    @app.get("/stores/{store_id}/anomalies")
    def anomalies(
        store_id: str,
        request: Request,
        start: str | None = None,
        end: str | None = None,
    ):
        window_start, window_end = parse_window(start, end)
        db: StoreDatabase = request.app.state.db
        return detect_anomalies(
            db.fetch_events(store_id, window_start, window_end),
            db.fetch_pos(store_id, window_start, window_end),
            stale_feed_seconds=int(os.getenv("STALE_FEED_SECONDS", "300")),
        )

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        return service_health(
            request.app.state.db,
            stale_feed_seconds=int(os.getenv("STALE_FEED_SECONDS", "300")),
        )

    return app


def parse_window(start: str | None, end: str | None):
    if start is None and end is None:
        return default_window()
    window_start = (
        datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
        if start
        else None
    )
    window_end = (
        datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(timezone.utc)
        if end
        else None
    )
    return window_start, window_end


app = create_app()

