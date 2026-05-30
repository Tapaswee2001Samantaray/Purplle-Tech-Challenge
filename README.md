# Store Intelligence Challenge

This repository implements the PDF's suggested Store Intelligence layout: `pipeline/` turns CCTV-derived observations into events, and `app/` serves the production-aware analytics API.

## Quick Start

```bash
docker compose up --build
```

The API starts on `http://localhost:8000`.
Swagger Doc on `http://localhost:8000/docs`

## Dataset Policy

The CCTV clips, downloaded challenge archive, generated event files, local SQLite databases, and model weights are intentionally not committed. The PDF marks the footage as challenge-use only, so `clips/` is kept in the repository with a placeholder while video files such as `.mp4`, `.avi`, `.mov`, and `.mkv` are ignored.

Place local clips in:

```text
clips/
```

Generated detector output goes to:

```text
events/events.jsonl
```

## Run Tests

```bash
python -m pip install -r requirements.txt
pytest
```

## API

```bash
POST /events/ingest
GET  /stores/{store_id}/metrics
GET  /stores/{store_id}/funnel
GET  /stores/{store_id}/heatmap
GET  /stores/{store_id}/anomalies
GET  /health
```

`POST /pos/ingest` is included so POS rows can be loaded before conversion-rate queries. The provided Brigade sales CSV is a line-item export, so use the loader below to aggregate invoice rows into transactions.

```bash
python -m pipeline.pos_loader --csv "C:/Users/tapaswees/Downloads/Brigade_Bangalore_10_April_26 (1)bc6219c.csv" --api-url http://localhost:8000
```

## Detection Pipeline

Verified CCTV command:

```bash
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --api-url http://localhost:8000 --model yolov8n.pt
```

This command reads MP4 clips from `clips/`, uses the camera and zone definitions from `store_layout.json`, emits `events/events.jsonl`, and replays the generated events into the running API. Because the Brigade clip filenames do not include timestamps, `store_layout.json` provides `recording_start` as the fallback timestamp; override it with `--clip-start` if needed.

For provided `sample_events.jsonl` or detector output:

```bash
python -m pipeline.detect --events-jsonl sample_events.jsonl --output events/events.jsonl --api-url http://localhost:8000 --delay-seconds 0.2
```

For actual CCTV clips, put clips under `clips/`, put the challenge layout file at `store_layout.json`, install the optional CV dependencies, and run:

```bash
python -m pip install -r requirements-pipeline.txt
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --api-url http://localhost:8000 --model yolov8n.pt
```

Note:- Complete Execution of this command takes some time to complete. After executing this command please wait some time to complete. The time depends based on the clips i.e clip duration and number of clips.

Load the provided POS CSV after or before detection:

```bash
python -m pipeline.pos_loader --csv "C:/Users/tapaswees/Downloads/Brigade_Bangalore_10_April_26 (1)bc6219c.csv" --api-url http://localhost:8000
```

Or with the required one-command script:

```bash
EVENTS_JSONL=sample_events.jsonl API_URL=http://localhost:8000 bash pipeline/run.sh
```

For CCTV mode:

```bash
VIDEO_DIR=clips LAYOUT=store_layout.json API_URL=http://localhost:8000 MODEL=yolov8n.pt bash pipeline/run.sh
```

The detector uses YOLO person detection, centroid tracking, zone polygons from `store_layout.json`, and optional entry-line settings to emit structured events. Full CCTV processing can take several minutes on CPU. For best accuracy, calibrate `store_layout.json` with camera IDs matching clip filenames, zone polygons, and an entry threshold line.

After the detector finishes, validate results in Swagger UI at `http://localhost:8000/docs` with:

```text
GET /stores/ST1008/metrics
GET /stores/ST1008/funnel
GET /stores/ST1008/heatmap
GET /stores/ST1008/anomalies
```

## Live Dashboard Bonus

Part E is implemented as a terminal dashboard that polls the live API while detector events are replayed in simulated real time.

Terminal 1: start the API.

```bash
docker compose up --build
```

Terminal 2: start the dashboard.

```bash
python -m dashboard.terminal --api-url http://localhost:8000 --store-id ST1008 --start 2026-04-10T00:00:00Z --end 2026-04-11T00:00:00Z
```

Terminal 3: replay detector output one event at a time.

```bash
python -m pipeline.detect --events-jsonl events/events.jsonl --output events/live_replay.jsonl --api-url http://localhost:8000 --batch-size 1 --delay-seconds 1
```

If you want to regenerate events from CCTV first:

```bash
python -m pipeline.detect --video-dir clips --layout store_layout.json --output events/events.jsonl --model yolov8n.pt
```
Note:- Complete Execution of this command takes some time to complete. After executing this command please wait some time to complete. The time depends based on the clips i.e clip duration and number of clips.

The dashboard updates unique visitors, conversion rate, queue depth, funnel counts, anomalies, and feed health as events arrive.

## Repository Layout

```text
pipeline/
  detect.py
  tracker.py
  emit.py
  run.sh
app/
  main.py
  models.py
  ingestion.py
  metrics.py
  funnel.py
  anomalies.py
  health.py
tests/
docs/
docker-compose.yml
README.md
```

## Event Schema

Each event uses:

```json
{
  "event_id": "uuid",
  "store_id": "ST1008",
  "camera_id": "CAM 3",
  "visitor_id": "VIS_caf",
  "event_type": "ZONE_DWELL",
  "timestamp": "2026-05-30T10:00:00Z",
  "zone_id": "SKINCARE",
  "dwell_ms": 30000,
  "is_staff": false,
  "confidence": 0.91,
  "metadata": {"queue_depth": null, "session_seq": 3}
}
```
