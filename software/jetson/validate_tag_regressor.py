#!/usr/bin/env python3
"""Compare the trained PyTorch tag regressor with its TensorRT engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np
import pycuda.autoprimaryctx  # noqa: F401  Share CUDA's primary context with PyTorch.
import pycuda.driver as cuda
import tensorrt as trt
import torch

from train_synthetic_tag_regressor import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    TagRegressor,
    generate_dataset,
)


class TensorRTRegressor:
    def __init__(self, engine_path: Path) -> None:
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(engine_path.read_bytes())
        if self.engine is None:
            raise RuntimeError(f"could not deserialize {engine_path}")
        self.context = self.engine.create_execution_context()
        self.context.set_input_shape("image", (1, 1, FRAME_HEIGHT, FRAME_WIDTH))
        self.stream = cuda.Stream()
        self.output = np.empty((1, 1), dtype=np.float32)
        self.device_input = cuda.mem_alloc(FRAME_HEIGHT * FRAME_WIDTH * 4)
        self.device_output = cuda.mem_alloc(self.output.nbytes)
        self.context.set_tensor_address("image", int(self.device_input))
        self.context.set_tensor_address("horizontal_error", int(self.device_output))

    def infer(self, image: np.ndarray) -> float:
        cuda.memcpy_htod_async(self.device_input, image, self.stream)
        if not self.context.execute_async_v3(stream_handle=self.stream.handle):
            raise RuntimeError("TensorRT execution failed")
        cuda.memcpy_dtoh_async(self.output, self.device_output, self.stream)
        self.stream.synchronize()
        return float(self.output[0, 0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--count", type=int, default=512)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    images, targets = generate_dataset(args.count, seed=2007)

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    pytorch_model = TagRegressor().cuda().eval()
    pytorch_model.load_state_dict(checkpoint["model_state"])
    with torch.no_grad():
        pytorch_predictions = pytorch_model(images.cuda()).cpu().numpy().reshape(-1)

    tensorrt_model = TensorRTRegressor(args.engine)
    tensorrt_model.infer(np.ascontiguousarray(images[0].numpy()))
    started = time.perf_counter()
    tensorrt_predictions = np.array(
        [
            tensorrt_model.infer(np.ascontiguousarray(image.numpy()))
            for image in images
        ],
        dtype=np.float32,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    truth = targets.numpy().reshape(-1)
    pytorch_errors = np.abs(pytorch_predictions - truth)
    tensorrt_errors = np.abs(tensorrt_predictions - truth)
    disagreement = np.abs(pytorch_predictions - tensorrt_predictions)
    print(
        json.dumps(
            {
                "samples": args.count,
                "pytorch_mae": round(float(np.mean(pytorch_errors)), 6),
                "tensorrt_mae": round(float(np.mean(tensorrt_errors)), 6),
                "mean_implementation_disagreement": round(
                    float(np.mean(disagreement)), 6
                ),
                "maximum_implementation_disagreement": round(
                    float(np.max(disagreement)), 6
                ),
                "tensorrt_application_ms_per_image": round(
                    elapsed_ms / args.count, 4
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
