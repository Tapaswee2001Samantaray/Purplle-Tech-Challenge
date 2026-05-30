#!/usr/bin/env bash
set -euo pipefail

EVENTS_JSONL="${EVENTS_JSONL:-}"
VIDEO_DIR="${VIDEO_DIR:-clips}"
LAYOUT="${LAYOUT:-store_layout.json}"
OUTPUT="${OUTPUT:-events/events.jsonl}"
API_URL="${API_URL:-http://localhost:8000}"
DELAY_SECONDS="${DELAY_SECONDS:-0}"
BATCH_SIZE="${BATCH_SIZE:-100}"
MODEL="${MODEL:-yolov8n.pt}"
SAMPLE_EVERY="${SAMPLE_EVERY:-5}"
DWELL_SECONDS="${DWELL_SECONDS:-30}"
CLIP_START="${CLIP_START:-}"

if [[ -n "$EVENTS_JSONL" ]]; then
  python -m pipeline.detect \
    --events-jsonl "$EVENTS_JSONL" \
    --output "$OUTPUT" \
    --api-url "$API_URL" \
    --delay-seconds "$DELAY_SECONDS" \
    --batch-size "$BATCH_SIZE"
else
  args=(
    --video-dir "$VIDEO_DIR"
    --layout "$LAYOUT"
    --output "$OUTPUT"
    --api-url "$API_URL"
    --delay-seconds "$DELAY_SECONDS"
    --batch-size "$BATCH_SIZE"
    --model "$MODEL"
    --sample-every "$SAMPLE_EVERY"
    --dwell-seconds "$DWELL_SECONDS"
  )
  if [[ -n "$CLIP_START" ]]; then
    args+=(--clip-start "$CLIP_START")
  fi
  python -m pipeline.detect "${args[@]}"
fi
