from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]
    confidence: float

    @property
    def centroid(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)


class CentroidTracker:
    """Small deterministic tracker used as a fallback when ReID is unavailable."""

    def __init__(self, max_disappeared: int = 20, max_distance: float = 80.0) -> None:
        self.max_disappeared = max_disappeared
        self.max_distance = max_distance
        self._next_id = 1
        self._objects: dict[int, tuple[float, float]] = {}
        self._missing: dict[int, int] = {}

    def update(self, detections: list[Detection]) -> dict[int, Detection]:
        assignments: dict[int, Detection] = {}
        unused_detections = set(range(len(detections)))

        for object_id, old_centroid in list(self._objects.items()):
            best_index = None
            best_distance = self.max_distance
            for index in unused_detections:
                distance = hypot(
                    old_centroid[0] - detections[index].centroid[0],
                    old_centroid[1] - detections[index].centroid[1],
                )
                if distance < best_distance:
                    best_index = index
                    best_distance = distance
            if best_index is None:
                self._missing[object_id] = self._missing.get(object_id, 0) + 1
                if self._missing[object_id] > self.max_disappeared:
                    self._objects.pop(object_id, None)
                    self._missing.pop(object_id, None)
                continue
            detection = detections[best_index]
            assignments[object_id] = detection
            self._objects[object_id] = detection.centroid
            self._missing[object_id] = 0
            unused_detections.remove(best_index)

        for index in unused_detections:
            object_id = self._next_id
            self._next_id += 1
            self._objects[object_id] = detections[index].centroid
            self._missing[object_id] = 0
            assignments[object_id] = detections[index]

        return assignments

