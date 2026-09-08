#!/usr/bin/env python3
"""Serve a local YOLO annotation tool backed by a dataset directory."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


UI_PATH = Path(__file__).with_name("annotator.html")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
SESSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
MAX_CAPTURE_BYTES = 5 * 1024 * 1024


class Dataset:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.raw = (self.root / "raw").resolve()
        self.labels = (self.root / "labels").resolve()
        self.capture_lock = threading.Lock()

    def list_images(self) -> list[str]:
        if not self.raw.exists():
            return []
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.raw.rglob("*")
            if path.is_file()
            and path.suffix.lower() in IMAGE_SUFFIXES
            and not path.stem.endswith("-raw")
        )

    def image_path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.raw) or not path.is_file():
            raise ValueError("invalid image path")
        return path

    def label_path(self, relative: str) -> Path:
        image = self.image_path(relative)
        label = self.labels / image.relative_to(self.raw).with_suffix(".txt")
        return label

    def read_boxes(self, relative: str) -> list[dict[str, float | int]]:
        path = self.label_path(relative)
        if not path.exists():
            return []
        boxes: list[dict[str, float | int]] = []
        for line in path.read_text().splitlines():
            class_id, x_center, y_center, width, height = line.split()
            boxes.append(
                {
                    "class_id": int(class_id),
                    "x_center": float(x_center),
                    "y_center": float(y_center),
                    "width": float(width),
                    "height": float(height),
                }
            )
        return boxes

    def save_boxes(self, relative: str, boxes: object) -> Path:
        path = self.label_path(relative)
        if not isinstance(boxes, list) or len(boxes) > 100:
            raise ValueError("boxes must be a list with at most 100 entries")
        lines = []
        for box in boxes:
            if not isinstance(box, dict):
                raise ValueError("each box must be an object")
            class_id = box.get("class_id")
            if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id < 0:
                raise ValueError("class_id must be a non-negative integer")
            values = [box.get(name) for name in ("x_center", "y_center", "width", "height")]
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= float(value) <= 1.0
                for value in values
            ):
                raise ValueError("normalized box values must be between 0 and 1")
            if float(values[2]) == 0.0 or float(values[3]) == 0.0:
                raise ValueError("box width and height must be greater than zero")
            lines.append(
                f"{class_id} " + " ".join(f"{float(value):.6f}" for value in values)
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + ("\n" if lines else ""))
        return path

    def save_capture(self, session: str, jpeg: bytes) -> Path:
        if not SESSION_PATTERN.fullmatch(session):
            raise ValueError("session must contain only letters, numbers, hyphens, or underscores")
        if not 4 <= len(jpeg) <= MAX_CAPTURE_BYTES:
            raise ValueError("capture must be a JPEG no larger than 5 MiB")
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("capture was not a complete JPEG")

        directory = self.raw / session
        with self.capture_lock:
            directory.mkdir(parents=True, exist_ok=True)
            existing = [
                int(match.group(1))
                for path in directory.glob("capture-*.jpg")
                if (match := re.fullmatch(r"capture-(\d{4})\.jpg", path.name))
            ]
            sequence = max(existing, default=0) + 1
            path = directory / f"capture-{sequence:04d}.jpg"
            path.write_bytes(jpeg)
        return path


def make_handler(
    dataset: Dataset,
    ui_path: Path = UI_PATH,
    camera_url: str = "http://192.168.0.87:8765",
):
    class AnnotationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            query = parse_qs(request.query)
            try:
                if request.path == "/":
                    self._send(HTTPStatus.OK, ui_path.read_bytes(), "text/html; charset=utf-8")
                elif request.path == "/api/images":
                    images = dataset.list_images()
                    self._json(HTTPStatus.OK, {"images": images})
                elif request.path == "/api/image":
                    path = dataset.image_path(query.get("path", [""])[0])
                    content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                    self._send(HTTPStatus.OK, path.read_bytes(), content_type)
                elif request.path == "/api/label":
                    relative = query.get("path", [""])[0]
                    self._json(HTTPStatus.OK, {"boxes": dataset.read_boxes(relative)})
                elif request.path == "/api/live-frame":
                    with urlopen(
                        f"{camera_url.rstrip('/')}/api/camera/frame.jpg?after=-1",
                        timeout=2.0,
                    ) as response:
                        self._send(
                            HTTPStatus.OK,
                            response.read(),
                            "image/jpeg",
                            {
                                "X-Frame-Id": response.headers.get("X-Frame-Id", "--"),
                                "X-Frame-Age-Ms": response.headers.get("X-Frame-Age-Ms", "--"),
                            },
                        )
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (OSError, ValueError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_POST(self) -> None:
            request = urlsplit(self.path)
            if request.path == "/api/capture":
                try:
                    if self.headers.get_content_type() != "image/jpeg":
                        raise ValueError("capture content type must be image/jpeg")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 4 <= length <= MAX_CAPTURE_BYTES:
                        raise ValueError("invalid capture size")
                    session = parse_qs(request.query).get("session", [""])[0]
                    path = dataset.save_capture(session, self.rfile.read(length))
                    self._json(
                        HTTPStatus.CREATED,
                        {"saved": path.relative_to(dataset.root).as_posix()},
                    )
                except (OSError, ValueError) as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            if request.path != "/api/label":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 64 * 1024:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("label payload must be an object")
                path = dataset.save_boxes(payload.get("path", ""), payload.get("boxes"))
                self._json(
                    HTTPStatus.OK,
                    {"saved": path.relative_to(dataset.root).as_posix()},
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _send(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string: str, *args: object) -> None:
            print(format_string % args)

    return AnnotationHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--camera-url", default="http://192.168.0.87:8765")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = Dataset(args.dataset)
    server = ThreadingHTTPServer(
        (args.host, args.port),
        make_handler(dataset, camera_url=args.camera_url),
    )
    print(f"annotation tool listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
