#!/usr/bin/env python3
"""Train a CNN to estimate AprilTag horizontal error from synthetic images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


FRAME_WIDTH = 160
FRAME_HEIGHT = 96


def make_tag_source(size: int = 256) -> np.ndarray:
    dictionary = cv2.aruco.Dictionary_get(cv2.aruco.DICT_APRILTAG_36h11)
    marker_size = round(size * 0.7)
    marker = cv2.aruco.drawMarker(dictionary, 0, marker_size)
    tag = np.full((size, size), 255, dtype=np.uint8)
    offset = (size - marker_size) // 2
    tag[offset : offset + marker_size, offset : offset + marker_size] = marker
    return tag


TAG_SOURCE = make_tag_source()


def render_example(rng: np.random.Generator) -> tuple[np.ndarray, float]:
    background_level = rng.uniform(155, 245)
    horizontal_gradient = np.linspace(
        rng.uniform(-25, 25), rng.uniform(-25, 25), FRAME_WIDTH
    )
    canvas = np.full((FRAME_HEIGHT, FRAME_WIDTH), background_level, dtype=np.float32)
    canvas += horizontal_gradient[np.newaxis, :]

    tag_size = int(rng.integers(28, 70))
    tag = cv2.resize(TAG_SOURCE, (tag_size, tag_size), interpolation=cv2.INTER_NEAREST)
    rotation = cv2.getRotationMatrix2D(
        ((tag_size - 1) / 2, (tag_size - 1) / 2),
        float(rng.uniform(-18, 18)),
        1.0,
    )
    tag = cv2.warpAffine(
        tag,
        rotation,
        (tag_size, tag_size),
        flags=cv2.INTER_NEAREST,
        borderValue=255,
    )

    half = tag_size // 2
    center_x = int(rng.integers(half + 2, FRAME_WIDTH - (tag_size - half) - 1))
    center_y = int(rng.integers(half + 2, FRAME_HEIGHT - (tag_size - half) - 1))
    left = center_x - half
    top = center_y - half
    canvas[top : top + tag_size, left : left + tag_size] = tag

    canvas *= rng.uniform(0.75, 1.15)
    canvas += rng.normal(0, rng.uniform(1, 8), canvas.shape)
    if rng.random() < 0.35:
        canvas = cv2.GaussianBlur(canvas, (3, 3), rng.uniform(0.2, 0.8))

    image = np.clip(canvas, 0, 255).astype(np.uint8)
    horizontal_error = (center_x - FRAME_WIDTH / 2) / (FRAME_WIDTH / 2)
    return image, float(horizontal_error)


def generate_dataset(count: int, seed: int) -> tuple[torch.Tensor, torch.Tensor]:
    rng = np.random.default_rng(seed)
    images = np.empty((count, 1, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint8)
    targets = np.empty((count, 1), dtype=np.float32)
    for index in range(count):
        image, horizontal_error = render_example(rng)
        images[index, 0] = image
        targets[index, 0] = horizontal_error
    normalized_images = torch.from_numpy(images).float().sub_(127.5).div_(127.5)
    return normalized_images, torch.from_numpy(targets)


class TagRegressor(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 8, kernel_size=5, stride=2, padding=2),
            nn.ReLU(),
            nn.Conv2d(8, 16, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
        )
        self.regressor = nn.Sequential(
            nn.Flatten(),
            nn.Linear(32 * 12 * 20, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Tanh(),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.regressor(self.features(images))


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, float]:
    errors = []
    model.eval()
    with torch.no_grad():
        for images, targets in loader:
            predictions = model(images.to(device))
            errors.append((predictions.cpu() - targets).abs())
    absolute_errors = torch.cat(errors).numpy().reshape(-1)
    return float(np.mean(absolute_errors)), float(np.percentile(absolute_errors, 95))


def save_montage(path: Path, images: torch.Tensor, targets: torch.Tensor) -> None:
    tiles = []
    for image, target in zip(images[:12], targets[:12]):
        pixels = image[0].mul(127.5).add(127.5).byte().numpy()
        tile = cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR)
        cv2.putText(
            tile,
            f"e={float(target[0]):+.2f}",
            (3, 13),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
        tiles.append(tile)
    montage = np.vstack([np.hstack(tiles[index : index + 4]) for index in range(0, 12, 4)])
    if not cv2.imwrite(str(path), montage):
        raise RuntimeError(f"could not write {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--train-count", type=int, default=6000)
    parser.add_argument("--validation-count", type=int, default=1200)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--output", type=Path, default=Path("tag-regressor.pt"))
    parser.add_argument("--onnx-output", type=Path, default=Path("tag-regressor.onnx"))
    parser.add_argument("--montage", type=Path, default=Path("synthetic-tags.jpg"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    torch.manual_seed(7)
    np.random.seed(7)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    generation_started = time.perf_counter()
    train_images, train_targets = generate_dataset(args.train_count, seed=7)
    validation_images, validation_targets = generate_dataset(
        args.validation_count, seed=1007
    )
    generation_seconds = time.perf_counter() - generation_started
    save_montage(args.montage, validation_images, validation_targets)

    train_loader = DataLoader(
        TensorDataset(train_images, train_targets),
        batch_size=args.batch_size,
        shuffle=True,
    )
    validation_loader = DataLoader(
        TensorDataset(validation_images, validation_targets),
        batch_size=args.batch_size,
    )

    model = TagRegressor().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_function = nn.MSELoss()

    training_started = time.perf_counter()
    final_metrics = {}
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_squared_error = 0.0
        sample_count = 0
        for images, targets in train_loader:
            images = images.to(device)
            targets = targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            predictions = model(images)
            loss = loss_function(predictions, targets)
            loss.backward()
            optimizer.step()
            total_squared_error += float(loss.item()) * len(images)
            sample_count += len(images)

        validation_mae, validation_p95 = evaluate(model, validation_loader, device)
        final_metrics = {
            "epoch": epoch,
            "train_mse": round(total_squared_error / sample_count, 6),
            "validation_mae": round(validation_mae, 6),
            "validation_p95": round(validation_p95, 6),
        }
        print(json.dumps(final_metrics), flush=True)

    training_seconds = time.perf_counter() - training_started
    torch.save(
        {
            "model_state": model.state_dict(),
            "frame_size": [FRAME_WIDTH, FRAME_HEIGHT],
            "metrics": final_metrics,
        },
        args.output,
    )

    model.eval()
    example = torch.zeros((1, 1, FRAME_HEIGHT, FRAME_WIDTH), device=device)
    torch.onnx.export(
        model,
        example,
        args.onnx_output,
        input_names=["image"],
        output_names=["horizontal_error"],
        dynamic_axes={"image": {0: "batch"}, "horizontal_error": {0: "batch"}},
        opset_version=17,
    )
    print(
        json.dumps(
            {
                "device": str(device),
                "parameters": sum(parameter.numel() for parameter in model.parameters()),
                "dataset_generation_seconds": round(generation_seconds, 3),
                "training_seconds": round(training_seconds, 3),
                "checkpoint": str(args.output),
                "onnx": str(args.onnx_output),
                "montage": str(args.montage),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
