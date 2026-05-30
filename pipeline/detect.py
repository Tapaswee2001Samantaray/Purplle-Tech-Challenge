from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .emit import make_event, validate_event, write_jsonl
from .tracker import CentroidTracker, Detection


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


@dataclass
class CameraConfig:
    camera_id: str
    role: str
    zones: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    entry_line: dict[str, Any] | None = None


@dataclass
class TrackState:
    visitor_id: str
    first_seen: datetime
    last_seen: datetime
    previous_centroid: tuple[float, float] | None = None
    current_zone: str | None = None
    zone_entered_at: datetime | None = None
    last_dwell_emit_at: datetime | None = None
    entry_emitted: bool = False
    billing_join_emitted: bool = False


def load_layout(path: Path) -> tuple[str, dict[str, CameraConfig]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    store_id = raw.get("store_id") or raw.get("storeId") or "STORE_UNKNOWN"
    cameras_raw = raw.get("cameras") or raw.get("camera_coverage") or []
    zones_raw = raw.get("zones") or raw.get("zone_definitions") or []

    global_zones = parse_zones(zones_raw)
    cameras: dict[str, CameraConfig] = {}
    if isinstance(cameras_raw, dict):
        camera_items = [
            {"camera_id": key, **value} if isinstance(value, dict) else {"camera_id": key}
            for key, value in cameras_raw.items()
        ]
    else:
        camera_items = cameras_raw if isinstance(cameras_raw, list) else []

    for item in camera_items:
        if not isinstance(item, dict):
            continue
        camera_id = str(
            item.get("camera_id")
            or item.get("cameraId")
            or item.get("id")
            or item.get("name")
            or f"CAM_{len(cameras) + 1}"
        )
        role = str(item.get("role") or item.get("type") or infer_camera_role(camera_id)).lower()
        camera_zones = parse_zones(item.get("zones") or item.get("coverage_zones") or {})
        if not camera_zones:
            camera_zones = global_zones
        cameras[camera_id] = CameraConfig(
            camera_id=camera_id,
            role=role,
            zones=camera_zones,
            entry_line=item.get("entry_line") or item.get("entry_threshold") or raw.get("entry_line"),
        )

    if not cameras:
        cameras["CAM_ENTRY"] = CameraConfig("CAM_ENTRY", "entry", global_zones, raw.get("entry_line"))
        cameras["CAM_FLOOR"] = CameraConfig("CAM_FLOOR", "floor", global_zones)
        cameras["CAM_BILLING"] = CameraConfig("CAM_BILLING", "billing", global_zones)

    return str(store_id), cameras


def parse_zones(raw: Any) -> dict[str, list[tuple[float, float]]]:
    zones: dict[str, list[tuple[float, float]]] = {}
    if isinstance(raw, dict):
        iterable = [{"zone_id": key, **value} if isinstance(value, dict) else {"zone_id": key, "polygon": value} for key, value in raw.items()]
    elif isinstance(raw, list):
        iterable = raw
    else:
        iterable = []
    for item in iterable:
        if not isinstance(item, dict):
            continue
        zone_id = str(item.get("zone_id") or item.get("zoneId") or item.get("name") or "").strip()
        polygon = item.get("polygon") or item.get("points") or item.get("vertices")
        if zone_id and isinstance(polygon, list):
            points = []
            for point in polygon:
                if isinstance(point, dict):
                    points.append((float(point["x"]), float(point["y"])))
                elif isinstance(point, (list, tuple)) and len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
            if len(points) >= 3:
                zones[zone_id] = points
    return zones


def validate_or_copy_events(source: Path, output: Path) -> int:
    events = []
    with source.open("r", encoding="utf-8") as src:
        for line_number, line in enumerate(src, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}:{line_number}: invalid JSONL row: {exc}") from exc
            events.append(validate_event(payload, line_number))
    return write_jsonl(events, output)


def run_video_detection(
    video_dir: Path,
    layout: Path,
    output: Path,
    model_path: str,
    sample_every: int,
    dwell_seconds: int,
    clip_start: str | None,
) -> None:
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "Video detection needs optional dependencies. Install with "
            "`pip install -r requirements-pipeline.txt`, or pass --events-jsonl "
            "to validate/replay precomputed events."
        ) from exc

    store_id, cameras = load_layout(layout)
    default_clip_start = parse_default_clip_start(layout, clip_start)
    model = YOLO(model_path)
    events: list[dict] = []
    video_files = sorted(path for path in video_dir.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS)
    if not video_files:
        raise SystemExit(f"No video clips found under {video_dir}")

    for video_path in video_files:
        camera = match_camera(video_path, cameras)
        events.extend(
            process_clip(
                cv2=cv2,
                model=model,
                video_path=video_path,
                store_id=store_id,
                camera=camera,
                sample_every=max(sample_every, 1),
                dwell_seconds=max(dwell_seconds, 1),
                default_clip_start=default_clip_start,
            )
        )
    count = write_jsonl(events, output)
    print(f"Wrote {count} events to {output}")


def process_clip(
    cv2: Any,
    model: Any,
    video_path: Path,
    store_id: str,
    camera: CameraConfig,
    sample_every: int,
    dwell_seconds: int,
    default_clip_start: datetime,
) -> list[dict]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open video clip: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    clip_start = infer_clip_start(video_path, default_clip_start)
    tracker = CentroidTracker(max_disappeared=20, max_distance=90)
    states: dict[int, TrackState] = {}
    events: list[dict] = []
    frame_index = -1

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_index += 1
        if frame_index % sample_every != 0:
            continue
        timestamp = clip_start + timedelta(seconds=frame_index / fps)
        detections = detect_people(model, frame)
        assignments = tracker.update(detections)
        queue_depth = estimate_queue_depth(assignments, camera)

        for track_id, detection in assignments.items():
            state = states.get(track_id)
            visitor_id = f"VIS_{camera.camera_id}_{track_id}"
            if state is None:
                state = TrackState(visitor_id=visitor_id, first_seen=timestamp, last_seen=timestamp)
                states[track_id] = state
            previous = state.previous_centroid
            centroid = detection.centroid
            zone_id = locate_zone(centroid, camera.zones)

            if is_entry_camera(camera) and not state.entry_emitted:
                if previous is None or crossed_entry_line(previous, centroid, camera.entry_line):
                    events.append(
                        make_event(
                            store_id,
                            camera.camera_id,
                            state.visitor_id,
                            "ENTRY",
                            timestamp,
                            confidence=detection.confidence,
                            metadata={"source_clip": video_path.name},
                        )
                    )
                    state.entry_emitted = True

            if zone_id != state.current_zone:
                if state.current_zone is not None:
                    events.append(
                        make_event(
                            store_id,
                            camera.camera_id,
                            state.visitor_id,
                            "ZONE_EXIT",
                            timestamp,
                            zone_id=state.current_zone,
                            confidence=detection.confidence,
                            metadata={"source_clip": video_path.name},
                        )
                    )
                if zone_id is not None:
                    events.append(
                        make_event(
                            store_id,
                            camera.camera_id,
                            state.visitor_id,
                            "ZONE_ENTER",
                            timestamp,
                            zone_id=zone_id,
                            confidence=detection.confidence,
                            metadata={"source_clip": video_path.name},
                        )
                    )
                    if zone_id.upper() == "BILLING" and not state.billing_join_emitted:
                        events.append(
                            make_event(
                                store_id,
                                camera.camera_id,
                                state.visitor_id,
                                "BILLING_QUEUE_JOIN",
                                timestamp,
                                zone_id=zone_id,
                                confidence=detection.confidence,
                                metadata={"queue_depth": queue_depth, "source_clip": video_path.name},
                            )
                        )
                        state.billing_join_emitted = True
                state.current_zone = zone_id
                state.zone_entered_at = timestamp if zone_id else None
                state.last_dwell_emit_at = timestamp if zone_id else None

            if state.current_zone and state.zone_entered_at:
                due = state.last_dwell_emit_at is None or (
                    timestamp - state.last_dwell_emit_at
                ).total_seconds() >= dwell_seconds
                if due:
                    dwell_ms = int((timestamp - state.zone_entered_at).total_seconds() * 1000)
                    events.append(
                        make_event(
                            store_id,
                            camera.camera_id,
                            state.visitor_id,
                            "ZONE_DWELL",
                            timestamp,
                            zone_id=state.current_zone,
                            dwell_ms=dwell_ms,
                            confidence=detection.confidence,
                            metadata={"source_clip": video_path.name},
                        )
                    )
                    state.last_dwell_emit_at = timestamp

            state.previous_centroid = centroid
            state.last_seen = timestamp

    capture.release()
    return events


def detect_people(model: Any, frame: Any) -> list[Detection]:
    results = model.predict(frame, classes=[0], verbose=False)
    detections: list[Detection] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            coords = box.xyxy[0].tolist()
            confidence = float(box.conf[0]) if getattr(box, "conf", None) is not None else 0.5
            detections.append(
                Detection(
                    bbox=(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3])),
                    confidence=confidence,
                )
            )
    return detections


def parse_default_clip_start(layout: Path, override: str | None) -> datetime:
    if override:
        return datetime.fromisoformat(override.replace("Z", "+00:00")).astimezone(timezone.utc)
    raw = json.loads(layout.read_text(encoding="utf-8"))
    value = raw.get("recording_start")
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime(2026, 4, 10, tzinfo=timezone.utc)


def infer_clip_start(video_path: Path, fallback: datetime) -> datetime:
    # Dataset filenames often carry timestamps. If absent, use a fixed UTC base
    # so repeated runs are deterministic.
    digits = "".join(ch for ch in video_path.stem if ch.isdigit())
    for fmt_len, fmt in ((14, "%Y%m%d%H%M%S"), (12, "%Y%m%d%H%M")):
        if len(digits) >= fmt_len:
            try:
                return datetime.strptime(digits[:fmt_len], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return fallback


def match_camera(video_path: Path, cameras: dict[str, CameraConfig]) -> CameraConfig:
    name = video_path.stem.lower()
    for camera_id, camera in cameras.items():
        if camera_id.lower() in name:
            return camera
    role = infer_camera_role(name)
    for camera in cameras.values():
        if camera.role == role:
            return camera
    return next(iter(cameras.values()))


def infer_camera_role(name: str) -> str:
    lowered = name.lower()
    if "entry" in lowered or "exit" in lowered:
        return "entry"
    if "bill" in lowered or "checkout" in lowered or "pos" in lowered:
        return "billing"
    return "floor"


def is_entry_camera(camera: CameraConfig) -> bool:
    return "entry" in camera.role or "exit" in camera.role


def locate_zone(point: tuple[float, float], zones: dict[str, list[tuple[float, float]]]) -> str | None:
    for zone_id, polygon in zones.items():
        if point_in_polygon(point, polygon):
            return zone_id
    return None


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def crossed_entry_line(
    previous: tuple[float, float],
    current: tuple[float, float],
    entry_line: dict[str, Any] | None,
) -> bool:
    if not entry_line:
        return True
    orientation = str(entry_line.get("orientation") or "horizontal").lower()
    position = float(entry_line.get("position") or entry_line.get("y") or entry_line.get("x") or 0)
    inbound = str(entry_line.get("inbound") or "down").lower()
    if orientation == "vertical":
        crossed = (previous[0] - position) * (current[0] - position) <= 0
        direction_ok = current[0] > previous[0] if inbound in {"right", "in"} else current[0] < previous[0]
    else:
        crossed = (previous[1] - position) * (current[1] - position) <= 0
        direction_ok = current[1] > previous[1] if inbound in {"down", "in"} else current[1] < previous[1]
    return crossed and direction_ok


def estimate_queue_depth(assignments: dict[int, Detection], camera: CameraConfig) -> int:
    billing_count = 0
    for detection in assignments.values():
        zone_id = locate_zone(detection.centroid, camera.zones)
        if zone_id and zone_id.upper() == "BILLING":
            billing_count += 1
    return billing_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce structured store events.")
    parser.add_argument("--events-jsonl", type=Path, help="Precomputed/sample events to validate.")
    parser.add_argument("--video-dir", type=Path, help="Directory containing CCTV clips.")
    parser.add_argument("--layout", type=Path, help="store_layout.json path.")
    parser.add_argument("--output", type=Path, default=Path("events/events.jsonl"))
    parser.add_argument("--api-url", default=None, help="Replay output to API after writing events.")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=100, help="Replay batch size when --api-url is set.")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLO model path/name.")
    parser.add_argument("--sample-every", type=int, default=5, help="Process every Nth frame.")
    parser.add_argument("--dwell-seconds", type=int, default=30, help="Emit dwell every N seconds.")
    parser.add_argument("--clip-start", default=None, help="Fallback clip start timestamp when filenames lack dates.")
    args = parser.parse_args()

    if args.events_jsonl:
        count = validate_or_copy_events(args.events_jsonl, args.output)
        print(f"Wrote {count} validated events to {args.output}")
    elif args.video_dir and args.layout:
        run_video_detection(
            args.video_dir,
            args.layout,
            args.output,
            args.model,
            args.sample_every,
            args.dwell_seconds,
            args.clip_start,
        )
    else:
        raise SystemExit("Provide either --events-jsonl or both --video-dir and --layout.")

    if args.api_url:
        from .emit import replay_jsonl

        replay_jsonl(
            args.output,
            args.api_url,
            batch_size=max(args.batch_size, 1),
            delay_seconds=args.delay_seconds,
        )


if __name__ == "__main__":
    main()
