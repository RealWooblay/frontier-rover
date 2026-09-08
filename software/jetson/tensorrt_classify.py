#!/usr/bin/env python3
"""Run an ImageNet classifier through TensorRT and expose each timing stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
import pycuda.autoinit  # noqa: F401  Creates the CUDA context used by TensorRT.
import pycuda.driver as cuda
import tensorrt as trt


IMAGE_SIZE = 224
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def preprocess(image_path: Path) -> np.ndarray:
    image = Image.open(image_path).convert("RGB")
    scale = 256 / min(image.size)
    resampling = getattr(Image, "Resampling", Image)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        resampling.BILINEAR,
    )
    left = (resized.width - IMAGE_SIZE) // 2
    top = (resized.height - IMAGE_SIZE) // 2
    cropped = resized.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))

    pixels = np.asarray(cropped, dtype=np.float32) / 255.0
    normalized = (pixels - IMAGENET_MEAN) / IMAGENET_STD
    nchw = normalized.transpose(2, 0, 1)[np.newaxis, ...]
    return np.ascontiguousarray(nchw, dtype=np.float32)


def softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    probabilities = np.exp(shifted)
    return probabilities / np.sum(probabilities)


class TensorRTClassifier:
    def __init__(self, engine_path: Path) -> None:
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:
            raise RuntimeError(f"could not deserialize {engine_path}")
        self.context = self.engine.create_execution_context()
        self.stream = cuda.Stream()

        tensor_names = [
            self.engine.get_tensor_name(index)
            for index in range(self.engine.num_io_tensors)
        ]
        self.input_name = next(
            name
            for name in tensor_names
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
        )
        self.output_name = next(
            name
            for name in tensor_names
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.OUTPUT
        )
        self.context.set_input_shape(self.input_name, (1, 3, IMAGE_SIZE, IMAGE_SIZE))

        output_shape = tuple(self.context.get_tensor_shape(self.output_name))
        output_dtype = trt.nptype(self.engine.get_tensor_dtype(self.output_name))
        self.output = np.empty(output_shape, dtype=output_dtype)

        self.device_input = cuda.mem_alloc(1 * 3 * IMAGE_SIZE * IMAGE_SIZE * 4)
        self.device_output = cuda.mem_alloc(self.output.nbytes)
        self.context.set_tensor_address(self.input_name, int(self.device_input))
        self.context.set_tensor_address(self.output_name, int(self.device_output))

    def infer(self, input_tensor: np.ndarray) -> tuple[np.ndarray, float]:
        started = time.perf_counter()
        cuda.memcpy_htod_async(self.device_input, input_tensor, self.stream)
        if not self.context.execute_async_v3(stream_handle=self.stream.handle):
            raise RuntimeError("TensorRT execution failed")
        cuda.memcpy_dtoh_async(self.output, self.device_output, self.stream)
        self.stream.synchronize()
        elapsed_ms = (time.perf_counter() - started) * 1000
        return self.output.copy(), elapsed_ms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--runs", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preprocess_started = time.perf_counter()
    input_tensor = preprocess(args.image)
    preprocess_ms = (time.perf_counter() - preprocess_started) * 1000
    labels = [line.strip() for line in args.labels.read_text().splitlines()]

    classifier = TensorRTClassifier(args.engine)
    scores, cold_inference_ms = classifier.infer(input_tensor)
    for _ in range(args.warmup):
        classifier.infer(input_tensor)

    warm_times = []
    for _ in range(args.runs):
        scores, elapsed_ms = classifier.infer(input_tensor)
        warm_times.append(elapsed_ms)

    probabilities = softmax(scores.reshape(-1).astype(np.float32))
    top_indices = probabilities.argsort()[-5:][::-1]
    result = {
        "image": str(args.image),
        "input_shape": list(input_tensor.shape),
        "input_range": [float(input_tensor.min()), float(input_tensor.max())],
        "preprocess_ms": round(preprocess_ms, 3),
        "cold_inference_ms": round(cold_inference_ms, 3),
        "warm_inference_ms": {
            "mean": round(float(np.mean(warm_times)), 3),
            "median": round(float(np.median(warm_times)), 3),
            "p95": round(float(np.percentile(warm_times, 95)), 3),
        },
        "top5": [
            {
                "index": int(index),
                "label": labels[index] if index < len(labels) else "unknown",
                "probability": round(float(probabilities[index]), 6),
            }
            for index in top_indices
        ],
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
