from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EventIn, IngestError, IngestResponse, POSIn, utc_iso


class StoreDatabase:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def init_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    visitor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    zone_id TEXT,
                    dwell_ms INTEGER NOT NULL DEFAULT 0,
                    is_staff INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_store_time
                    ON events (store_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_store_visitor
                    ON events (store_id, visitor_id);
                CREATE INDEX IF NOT EXISTS idx_events_store_type
                    ON events (store_id, event_type);

                CREATE TABLE IF NOT EXISTS pos_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    store_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    basket_value_inr REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pos_store_time
                    ON pos_transactions (store_id, timestamp);
                """
            )
            self._connection.commit()

    def insert_event(self, event: EventIn) -> bool:
        now = utc_iso(datetime.now(timezone.utc))
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO events (
                        event_id, store_id, camera_id, visitor_id, event_type,
                        timestamp, zone_id, dwell_ms, is_staff, confidence,
                        metadata_json, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.store_id,
                        event.camera_id,
                        event.visitor_id,
                        event.event_type.value,
                        utc_iso(event.timestamp),
                        event.zone_id,
                        event.dwell_ms,
                        int(event.is_staff),
                        event.confidence,
                        json.dumps(event.metadata, sort_keys=True),
                        now,
                    ),
                )
                self._connection.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def insert_pos(self, pos: POSIn) -> bool:
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO pos_transactions (
                        transaction_id, store_id, timestamp, basket_value_inr
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        pos.transaction_id,
                        pos.store_id,
                        utc_iso(pos.timestamp),
                        pos.basket_value_inr,
                    ),
                )
                self._connection.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def fetch_events(
        self,
        store_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["store_id = ?"]
        params: list[Any] = [store_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(utc_iso(start))
        if end is not None:
            clauses.append("timestamp < ?")
            params.append(utc_iso(end))
        query = f"""
            SELECT * FROM events
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp ASC, received_at ASC
        """
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._event_row_to_dict(row) for row in rows]

    def fetch_pos(
        self,
        store_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["store_id = ?"]
        params: list[Any] = [store_id]
        if start is not None:
            clauses.append("timestamp >= ?")
            params.append(utc_iso(start))
        if end is not None:
            clauses.append("timestamp < ?")
            params.append(utc_iso(end))
        query = f"""
            SELECT * FROM pos_transactions
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp ASC
        """
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def last_event_by_store(self) -> dict[str, str]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT store_id, MAX(timestamp) AS last_event_timestamp
                FROM events
                GROUP BY store_id
                ORDER BY store_id
                """
            ).fetchall()
        return {row["store_id"]: row["last_event_timestamp"] for row in rows}

    def last_event_timestamp(self, store_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT MAX(timestamp) AS last_event_timestamp
                FROM events
                WHERE store_id = ?
                """,
                (store_id,),
            ).fetchone()
        if row is None:
            return None
        return row["last_event_timestamp"]

    @staticmethod
    def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["is_staff"] = bool(payload["is_staff"])
        try:
            payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            payload["metadata"] = {}
        return payload


def ingest_event_batch(db: StoreDatabase, raw_events: Any) -> IngestResponse:
    if not isinstance(raw_events, list):
        return IngestResponse(
            accepted=0,
            duplicates=0,
            rejected=1,
            errors=[IngestError(index=0, reason="Payload must contain an events list.")],
        )
    if len(raw_events) > 500:
        return IngestResponse(
            accepted=0,
            duplicates=0,
            rejected=len(raw_events),
            errors=[IngestError(index=0, reason="Batch size exceeds 500 events.")],
        )

    accepted = duplicates = 0
    errors: list[IngestError] = []
    for index, raw_event in enumerate(raw_events):
        try:
            event = EventIn.model_validate(raw_event)
        except Exception as exc:
            errors.append(
                IngestError(
                    index=index,
                    event_id=raw_event.get("event_id") if isinstance(raw_event, dict) else None,
                    reason=str(exc),
                )
            )
            continue
        if db.insert_event(event):
            accepted += 1
        else:
            duplicates += 1
    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
    )


def ingest_pos_batch(db: StoreDatabase, raw_items: Any) -> IngestResponse:
    if not isinstance(raw_items, list):
        return IngestResponse(
            accepted=0,
            duplicates=0,
            rejected=1,
            errors=[IngestError(index=0, reason="Payload must contain a transactions list.")],
        )

    accepted = duplicates = 0
    errors: list[IngestError] = []
    for index, raw_pos in enumerate(raw_items):
        try:
            pos = POSIn.model_validate(raw_pos)
        except Exception as exc:
            errors.append(
                IngestError(
                    index=index,
                    event_id=raw_pos.get("transaction_id") if isinstance(raw_pos, dict) else None,
                    reason=str(exc),
                )
            )
            continue
        if db.insert_pos(pos):
            accepted += 1
        else:
            duplicates += 1
    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
    )
