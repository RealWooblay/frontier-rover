#!/usr/bin/env python3
"""Convert YOLO object detections into the rover's normalized target geometry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import time


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1_px: float
    y1_px: float
    x2_px: float
    y2_px: float
    horizontal_error: float
    area_ratio: float
    bottom_edge_ratio: float
    source: str = "yolo"

    def to_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def measure_box(
    class_id: int,
    class_name: str,
    confidence: float,
    xyxy: tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    source: str = "yolo",
) -> Detection:
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    x1, y1, x2, y2 = xyxy
    x1 = max(0.0, min(float(frame_width), x1))
    x2 = max(0.0, min(float(frame_width), x2))
    y1 = max(0.0, min(float(frame_height), y1))
    y2 = max(0.0, min(float(frame_height), y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("detection box must have positive width and height")
    center_x = (x1 + x2) / 2.0
    horizontal_error = (center_x - frame_width / 2.0) / (frame_width / 2.0)
    area_ratio = ((x2 - x1) * (y2 - y1)) / (frame_width * frame_height)
    return Detection(
        class_id=class_id,
        class_name=class_name,
        confidence=round(confidence, 6),
        x1_px=round(x1, 2),
        y1_px=round(y1, 2),
        x2_px=round(x2, 2),
        y2_px=round(y2, 2),
        horizontal_error=round(horizontal_error, 6),
        area_ratio=round(area_ratio, 6),
        bottom_edge_ratio=round(y2 / frame_height, 6),
        source=source,
    )


def select_primary(detections: list[Detection]) -> Detection | None:
    if not detections:
        return None
    return max(detections, key=lambda item: (item.confidence, item.area_ratio))


class YoloDetector:
    """Thin adapter around Ultralytics PyTorch or TensorRT detection models."""

    def __init__(
        self,
        model_path: Path,
        target_name: str,
        confidence: float = 0.4,
        device: str | None = None,
    ) -> None:
        if not 0.0 < confidence <= 1.0:
            raise ValueError("confidence threshold must be between 0 and 1")
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as error:
            raise RuntimeError("Ultralytics is required for YOLO detection") from error
        self.model = YOLO(str(model_path), task="detect")
        self.target_name = target_name
        self.confidence = confidence
        self.device = device
        names = self.model.names
        name_items = names.items() if isinstance(names, dict) else enumerate(names)
        matches = [int(class_id) for class_id, name in name_items if name == target_name]
        if not matches:
            raise ValueError(f"model does not contain target class {target_name!r}")
        self.target_id = matches[0]

    def detect(self, jpeg: bytes) -> tuple[Detection | None, dict[str, float]]:
        try:
            import cv2  # type: ignore
            import numpy  # type: ignore
        except ImportError as error:
            raise RuntimeError("OpenCV and NumPy are required for camera decoding") from error

        raw = cv2.imdecode(numpy.frombuffer(jpeg, dtype=numpy.uint8), cv2.IMREAD_COLOR)
        if raw is None:
            raise ValueError("camera response was not a valid JPEG")
        frame = cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)
        pipeline_started = time.monotonic()
        options: dict[str, object] = {
            "source": frame,
            "classes": [self.target_id],
            "conf": self.confidence,
            "verbose": False,
        }
        if self.device is not None:
            options["device"] = self.device
        result = self.model.predict(**options)[0]
        total_ms = (time.monotonic() - pipeline_started) * 1000.0
        detections = [
            measure_box(
                self.target_id,
                self.target_name,
                float(confidence),
                tuple(float(value) for value in xyxy),
                frame.shape[1],
                frame.shape[0],
            )
            for xyxy, confidence in zip(
                result.boxes.xyxy.cpu().tolist(),
                result.boxes.conf.cpu().tolist(),
            )
        ]
        speed = getattr(result, "speed", {})
        return select_primary(detections), {
            "preprocess_ms": round(float(speed.get("preprocess", 0.0)), 2),
            "inference_ms": round(float(speed.get("inference", total_ms)), 2),
            "postprocess_ms": round(float(speed.get("postprocess", 0.0)), 2),
            "total_ms": round(total_ms, 2),
        }
