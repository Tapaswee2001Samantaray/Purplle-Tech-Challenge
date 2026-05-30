# Design

## Architecture

The submission follows the PDF's suggested layout:

- `pipeline/`: raw footage to structured events. It contains YOLO detection orchestration, centroid tracking, event emission, and the one-command `run.sh` entry point.
- `app/`: the production-facing FastAPI service. It validates events, deduplicates by `event_id`, persists events/POS rows, computes metrics, builds funnels, detects anomalies, and reports health.
- `tests/`: focused scoring and edge-case tests with prompt headers.

The system is event-first. The detection layer emits immutable behavioural events, and every API query computes from the latest persisted event store. That keeps the API real-time and avoids stale rollups.

## Data Flow

1. `pipeline/detect.py` processes clips with YOLO person detection and centroid tracking, or validates provided JSONL events.
2. `pipeline/emit.py` enforces the event schema and can replay batches into the API.
3. `POST /events/ingest` validates each event independently, deduplicates by `event_id`, and returns partial-success errors for malformed rows.
4. `pipeline/pos_loader.py` aggregates the provided Brigade line-item POS CSV by invoice and posts transactions to `POST /pos/ingest`.
5. Query endpoints read events and transactions from SQLite and compute responses on demand.

## Metric Logic

Staff events remain stored but are excluded from customer metrics. The visitor session token is the unit for funnel counts, so `REENTRY` does not inflate traffic. POS has no customer identity, so conversion is inferred by time: a visitor seen in the billing zone within 60 seconds before a POS timestamp counts as converted.

Empty stores, all-staff clips, and zero-purchase stores return numeric zeroes and empty collections instead of `null` or errors.

## CCTV Validation

The CCTV path was exercised with:

```bash
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --api-url http://localhost:8000 --model yolov8n.pt
```

The detector emits JSONL events and posts them into the API. The API endpoints can then be checked from Swagger UI using the generated `ST1008` events.

The provided POS file `Brigade_Bangalore_10_April_26 (1)bc6219c.csv` is a line-item export rather than the simplified challenge schema. The loader aggregates rows by `invoice_number`, combines `order_date` and `order_time` in `Asia/Kolkata`, and sums `total_amount` into `basket_value_inr`. This keeps conversion correlation aligned with the CCTV event store ID `ST1008`.

The provided clip filenames are camera labels rather than timestamps, so `store_layout.json` includes `recording_start` as the fallback event timestamp base. The detector also supports `--clip-start` to override this when a reviewer wants to align a specific clip with the POS window.

## Live Dashboard

Part E is covered by `dashboard/terminal.py`. It polls the running API every second and redraws a terminal dashboard with unique visitors, conversion rate, queue depth, funnel counts, anomalies, and health. To prove the pipeline and API are connected, generated detector events can be replayed with `--batch-size 1 --delay-seconds 1`, causing the dashboard to update as each event is ingested.

## Dataset Handling

Raw CCTV clips, downloaded challenge archives, source CSV/XLSX datasets, generated JSONL events, local databases, and YOLO weight files are excluded from Git. This follows the PDF's challenge-use-only footage license and keeps the repository reviewable without redistributing private data.

## AI Assisted Decisions

AI helped shape the separation between computer vision and API scoring. I kept the API independent of heavy model dependencies because automated evaluation should not require GPU libraries or model downloads before the REST service can start.

AI suggested an ORM. I chose direct SQLite queries because the schema is small, uniqueness constraints are central to the challenge, and the repository is easier to reason about during follow-up questions.

AI also suggested a VLM-heavy detector. I rejected that as the primary path because frame-by-frame VLM calls are slower, more expensive, and harder to reproduce. A VLM is better as an optional aid for staff classification or zone-label validation after the detector has produced candidates.
