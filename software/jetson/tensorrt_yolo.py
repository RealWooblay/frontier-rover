#!/usr/bin/env python3
"""Execute a YOLOv8 detection engine directly with TensorRT and PyCUDA."""

from __future__ import annotations

from pathlib import Path
import time

from yolo_perception import Detection, measure_box, select_primary


COCO_NAMES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
)


def detect_orange_color(frame, cv2, numpy) -> Detection | None:
    """Measure a floor-level orange component when semantic YOLO recall drops."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        numpy.array((3, 170, 45), dtype=numpy.uint8),
        numpy.array((12, 255, 255), dtype=numpy.uint8),
    )
    kernel = numpy.ones((3, 3), dtype=numpy.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, numpy.ones((5, 5), dtype=numpy.uint8)
    )
    contours, _hierarchy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    height, width = frame.shape[:2]
    frame_area = width * height
    candidates = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        box_area = box_width * box_height
        area_ratio = box_area / frame_area
        aspect_ratio = box_width / box_height
        fill_ratio = cv2.contourArea(contour) / box_area
        if not 0.005 <= area_ratio <= 0.18:
            continue
        if not 0.5 <= aspect_ratio <= 1.8 or fill_ratio < 0.45:
            continue
        if y + box_height / 2.0 < height * 0.30:
            continue
        candidates.append(
            measure_box(
                COCO_NAMES.index("orange"),
                "orange",
                min(0.99, max(0.2, fill_ratio)),
                (x, y, x + box_width, y + box_height),
                width,
                height,
                source="hsv",
            )
        )
    return max(candidates, key=lambda item: item.area_ratio, default=None)


def non_maximum_suppression(detections: list[Detection], threshold: float) -> list[Detection]:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("NMS threshold must be between 0 and 1")
    remaining = sorted(detections, key=lambda item: item.confidence, reverse=True)
    kept: list[Detection] = []
    while remaining:
        selected = remaining.pop(0)
        kept.append(selected)
        survivors = []
        for candidate in remaining:
            intersection_width = max(
                0.0,
                min(selected.x2_px, candidate.x2_px)
                - max(selected.x1_px, candidate.x1_px),
            )
            intersection_height = max(
                0.0,
                min(selected.y2_px, candidate.y2_px)
                - max(selected.y1_px, candidate.y1_px),
            )
            intersection = intersection_width * intersection_height
            selected_area = (selected.x2_px - selected.x1_px) * (
                selected.y2_px - selected.y1_px
            )
            candidate_area = (candidate.x2_px - candidate.x1_px) * (
                candidate.y2_px - candidate.y1_px
            )
            union = selected_area + candidate_area - intersection
            if intersection / union <= threshold:
                survivors.append(candidate)
        remaining = survivors
    return kept


def decode_output(
    output,
    target_id: int,
    confidence_threshold: float,
    source_width: int,
    source_height: int,
    scale: float,
    pad_x: float,
    pad_y: float,
    nms_threshold: float = 0.45,
) -> Detection | None:
    import numpy

    predictions = numpy.asarray(output)
    if predictions.ndim == 3 and predictions.shape[0] == 1:
        predictions = predictions[0]
    if predictions.ndim != 2:
        raise ValueError(f"expected two-dimensional YOLO output, got {predictions.shape}")
    feature_count = 4 + len(COCO_NAMES)
    if predictions.shape[0] == feature_count:
        predictions = predictions.T
    elif predictions.shape[1] != feature_count:
        raise ValueError(f"expected {feature_count} YOLO features, got {predictions.shape}")
    class_column = 4 + target_id
    if class_column >= predictions.shape[1]:
        raise ValueError("target class is outside the YOLO output")
    selected = predictions[predictions[:, class_column] >= confidence_threshold]
    detections = []
    for row in selected:
        center_x, center_y, width, height = (float(value) for value in row[:4])
        xyxy = (
            (center_x - width / 2.0 - pad_x) / scale,
            (center_y - height / 2.0 - pad_y) / scale,
            (center_x + width / 2.0 - pad_x) / scale,
            (center_y + height / 2.0 - pad_y) / scale,
        )
        try:
            detections.append(
                measure_box(
                    target_id,
                    COCO_NAMES[target_id],
                    float(row[class_column]),
                    xyxy,
                    source_width,
                    source_height,
                )
            )
        except ValueError:
            continue
    return select_primary(non_maximum_suppression(detections, nms_threshold))


class TensorRTYoloDetector:
    def __init__(
        self,
        engine_path: Path,
        target_name: str,
        confidence: float = 0.4,
        _device: str | None = None,
    ) -> None:
        if target_name not in COCO_NAMES:
            raise ValueError(f"COCO model does not contain target class {target_name!r}")
        if not 0.0 < confidence <= 1.0:
            raise ValueError("confidence threshold must be between 0 and 1")
        try:
            import cv2
            import numpy
            import pycuda.autoinit  # noqa: F401
            import pycuda.driver as cuda
            import tensorrt as trt
        except ImportError as error:
            raise RuntimeError("OpenCV, NumPy, TensorRT, and PyCUDA are required") from error

        self.cv2 = cv2
        self.numpy = numpy
        self.cuda = cuda
        self.trt = trt
        self.target_id = COCO_NAMES.index(target_name)
        self.target_name = target_name
        self.confidence = confidence
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:
            raise RuntimeError(f"could not deserialize {engine_path}")
        self.context = self.engine.create_execution_context()
        self.stream = cuda.Stream()
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.input_name = next(
            name for name in names if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
        )
        self.output_name = next(
            name for name in names if self.engine.get_tensor_mode(name) == trt.TensorIOMode.OUTPUT
        )
        self.input_shape = tuple(self.engine.get_tensor_shape(self.input_name))
        if len(self.input_shape) != 4 or any(dimension <= 0 for dimension in self.input_shape):
            raise ValueError(f"engine needs a fixed NCHW input, got {self.input_shape}")
        self.input_height = self.input_shape[2]
        self.input_width = self.input_shape[3]
        output_shape = tuple(self.engine.get_tensor_shape(self.output_name))
        output_dtype = trt.nptype(self.engine.get_tensor_dtype(self.output_name))
        self.output = numpy.empty(output_shape, dtype=output_dtype)
        input_dtype = trt.nptype(self.engine.get_tensor_dtype(self.input_name))
        self.input = numpy.empty(self.input_shape, dtype=input_dtype)
        self.device_input = cuda.mem_alloc(self.input.nbytes)
        self.device_output = cuda.mem_alloc(self.output.nbytes)
        self.context.set_tensor_address(self.input_name, int(self.device_input))
        self.context.set_tensor_address(self.output_name, int(self.device_output))

    def _preprocess(self, jpeg: bytes):
        cv2 = self.cv2
        numpy = self.numpy
        raw = cv2.imdecode(numpy.frombuffer(jpeg, dtype=numpy.uint8), cv2.IMREAD_COLOR)
        if raw is None:
            raise ValueError("camera response was not a valid JPEG")
        frame = cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)
        source_height, source_width = frame.shape[:2]
        scale = min(self.input_width / source_width, self.input_height / source_height)
        resized_width = round(source_width * scale)
        resized_height = round(source_height * scale)
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.input_width - resized_width) / 2.0
        pad_y = (self.input_height - resized_height) / 2.0
        canvas = numpy.full((self.input_height, self.input_width, 3), 114, dtype=numpy.uint8)
        left = int(round(pad_x - 0.1))
        top = int(round(pad_y - 0.1))
        canvas[top : top + resized_height, left : left + resized_width] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        tensor = rgb.transpose(2, 0, 1)[numpy.newaxis].astype(self.input.dtype) / 255.0
        return numpy.ascontiguousarray(tensor), frame, scale, float(left), float(top)

    def detect(self, jpeg: bytes) -> tuple[Detection | None, dict[str, float]]:
        pipeline_started = time.perf_counter()
        preprocess_started = time.perf_counter()
        tensor, frame, scale, pad_x, pad_y = self._preprocess(jpeg)
        preprocess_ms = (time.perf_counter() - preprocess_started) * 1000.0

        inference_started = time.perf_counter()
        self.cuda.memcpy_htod_async(self.device_input, tensor, self.stream)
        if not self.context.execute_async_v3(stream_handle=self.stream.handle):
            raise RuntimeError("TensorRT execution failed")
        self.cuda.memcpy_dtoh_async(self.output, self.device_output, self.stream)
        self.stream.synchronize()
        inference_ms = (time.perf_counter() - inference_started) * 1000.0

        postprocess_started = time.perf_counter()
        detection = decode_output(
            self.output,
            self.target_id,
            self.confidence,
            frame.shape[1],
            frame.shape[0],
            scale,
            pad_x,
            pad_y,
        )
        if detection is None and self.target_name == "orange":
            detection = detect_orange_color(frame, self.cv2, self.numpy)
        postprocess_ms = (time.perf_counter() - postprocess_started) * 1000.0
        return detection, {
            "preprocess_ms": round(preprocess_ms, 2),
            "inference_ms": round(inference_ms, 2),
            "postprocess_ms": round(postprocess_ms, 2),
            "total_ms": round((time.perf_counter() - pipeline_started) * 1000.0, 2),
        }
