# Choices

## 1. Detection Model

Options considered:

- YOLOv8/YOLOv11 with centroid tracking, ByteTrack, StrongSORT, or a ReID model
- RT-DETR with a tracker
- VLM-only frame interpretation

Chosen path: YOLOv8n person detection plus centroid tracking, with `pipeline/emit.py` as the stable event contract. This is the most practical baseline for CCTV person counting because it runs locally, avoids requiring GPU-specific ReID dependencies, and can be calibrated per camera through `store_layout.json`.

ByteTrack, StrongSORT, or OSNet-style ReID would be the next upgrade for crowded re-entry cases. I did not make those mandatory in the submitted path because the challenge API should remain runnable from a clean clone, and the current centroid tracker is enough to produce structured events for endpoint validation.

AI suggested using a VLM for more of the pipeline. I would use a VLM only where it helps classify ambiguous staff uniforms or validate zones, not as the main detector.

## 2. Event Schema

Options considered:

- Store aggregate counters only
- Store frame-level detections only
- Store behavioural events with confidence and metadata

Chosen path: behavioural events. Aggregates lose too much information for funnel, re-entry, and queue-abandonment logic. Frame-level detections are too low-level for a clean API. Events preserve business meaning while still carrying confidence and metadata for debugging.

Low-confidence events are not suppressed. They are stored with confidence values so the API can remain honest about uncertainty and the detector can be improved later.

## 3. API Architecture

Options considered:

- FastAPI + SQLite
- FastAPI + PostgreSQL
- Node.js service with in-memory storage

Chosen path: FastAPI + SQLite. The PDF recommends Python/FastAPI for best harness coverage and explicitly allows SQLite. SQLite keeps `docker compose up` simple while supporting durable storage, idempotent uniqueness constraints, and queryable analytics.

The API computes metrics at request time. For the challenge data volume this is simpler and less error-prone than background rollups. In production, the same event schema can feed materialized aggregates without changing the external endpoints.
