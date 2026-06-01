# Store Intelligence Challenge

This is an end-to-end Store Intelligence submission: CCTV-derived events are ingested by a FastAPI service, correlated with POS transactions, and exposed as live business metrics.

## Quick Evaluation Path

Use this path when you want to verify the API quickly without private CCTV/POS files.

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000/docs
```

In another terminal, seed the API with synthetic sample data:

```bash
python -m pipeline.detect --events-jsonl sample_data/sample_events.jsonl --output events/sample_events.jsonl --api-url http://localhost:8000
```

```bash
python - <<'PY'
import json, urllib.request
body = open("sample_data/sample_pos.json", "rb").read()
req = urllib.request.Request(
    "http://localhost:8000/pos/ingest",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
PY
```

Check these Swagger endpoints with `store_id = ST1008`:

```text
GET /stores/ST1008/metrics
GET /stores/ST1008/funnel
GET /stores/ST1008/heatmap
GET /stores/ST1008/anomalies
GET /health
```

`start` and `end` are optional. If omitted, the API uses the latest event day for that store.

## Full CCTV Pipeline

Private challenge files are not committed. Put local files in these locations:

```text
clips/                         # CCTV mp4 files
store_layout.json              # included, calibrated for ST1008 / CAM 1..CAM 5
<path-to-pos-csv>              # provided Brigade POS CSV
```

Install optional CV dependencies:

```bash
python -m pip install -r requirements-pipeline.txt
```

Generate events from CCTV:

```bash
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --model yolov8n.pt
```

Note: complete execution of this command can take several minutes. Please wait for it to finish. Runtime depends on the number of clips, clip duration, CPU/GPU availability, and model download time on the first run.

For a faster smoke test:

```bash
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --model yolov8n.pt --sample-every 60 --max-frames-per-clip 300
```

Load POS data:

```bash
python -m pipeline.pos_loader --csv "<path-to-pos-csv>" --output data/pos_transactions.json
```

Start or restart Docker:

```bash
docker compose down -v
docker compose up --build
```

When Docker starts, it automatically loads these generated files if they exist:

```text
events/events.jsonl
data/pos_transactions.json
```

The loading is idempotent, so restarts do not double-count events.

## API

```text
POST /events/ingest
POST /pos/ingest
GET  /stores/{store_id}/metrics
GET  /stores/{store_id}/funnel
GET  /stores/{store_id}/heatmap
GET  /stores/{store_id}/anomalies
GET  /health
```

Key behavior:

- `POST /events/ingest` accepts batches up to 500 events.
- Event ingestion is idempotent by `event_id`.
- Staff events are stored but excluded from customer metrics.
- POS conversion is inferred by billing-zone presence within 60 seconds of a transaction.
- Metrics are computed from the current event store, not stale cached values.

## Live Dashboard Bonus

Terminal 1:

```bash
docker compose up --build
```

Terminal 2:

```bash
python -m dashboard.terminal
```

Terminal 3:

```bash
python -m pipeline.detect --events-jsonl events/events.jsonl --output events/live_replay.jsonl --api-url http://localhost:8000 --batch-size 1 --delay-seconds 1
```

The terminal dashboard updates unique visitors, conversion rate, queue depth, funnel counts, anomalies, and feed health as events arrive.

## Dataset Policy

The following are intentionally ignored and must not be committed:

```text
clips/*.mp4
events/
data/
*.csv
*.xlsx
*.pt
*.db
```

This follows the challenge-use-only license for CCTV footage and supporting datasets. The repository includes only code, docs, layout metadata, tests, and small synthetic sample data.

## Tests

```bash
python -m pip install -r requirements.txt
pytest -q
```

## Repository Layout

```text
pipeline/
  detect.py
  tracker.py
  emit.py
  pos_loader.py
  run.sh
app/
  main.py
  models.py
  ingestion.py
  metrics.py
  funnel.py
  anomalies.py
  health.py
dashboard/
  terminal.py
sample_data/
tests/
docs/
docker-compose.yml
README.md
```
