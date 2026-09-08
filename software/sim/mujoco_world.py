#!/usr/bin/env python3
"""MuJoCo world geometry and simulated exteroceptive sensors.

The classes in this module deliberately read MuJoCo geometry or rendered pixels.
They do not read target/obstacle coordinates after the model is compiled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import mujoco
import numpy


MODEL_PATH = Path(__file__).resolve().parents[2] / "simulation" / "frontier_rover.xml"
WORLD_GEOM_GROUP = 1
TARGET_GEOM_GROUP = 2


@dataclass(frozen=True)
class CameraDetection:
    target_visible: bool
    horizontal_error: float
    area_ratio: float
    bottom_edge_ratio: float
    pixel_count: int
    bbox_xyxy: tuple[int, int, int, int] | None
    estimated_distance_m: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_world_xml(world: object, model_path: Path = MODEL_PATH) -> str:
    """Inject room, obstacles, target, lidar site, and camera into the rover MJCF."""
    root = ET.parse(model_path).getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise ValueError("MuJoCo model has no worldbody")

    minimum_x = float(getattr(world, "minimum_x_m"))
    maximum_x = float(getattr(world, "maximum_x_m"))
    minimum_y = float(getattr(world, "minimum_y_m"))
    maximum_y = float(getattr(world, "maximum_y_m"))
    wall_thickness = 0.04
    wall_height = 0.24
    x_mid = (minimum_x + maximum_x) * 0.5
    y_mid = (minimum_y + maximum_y) * 0.5
    x_half = (maximum_x - minimum_x) * 0.5
    y_half = (maximum_y - minimum_y) * 0.5

    walls = (
        ("wall_west", minimum_x - wall_thickness, y_mid, wall_thickness, y_half),
        ("wall_east", maximum_x + wall_thickness, y_mid, wall_thickness, y_half),
        ("wall_south", x_mid, minimum_y - wall_thickness, x_half, wall_thickness),
        ("wall_north", x_mid, maximum_y + wall_thickness, x_half, wall_thickness),
    )
    for name, x_m, y_m, sx, sy in walls:
        ET.SubElement(
            worldbody,
            "geom",
            name=name,
            type="box",
            pos=f"{x_m} {y_m} {wall_height}",
            size=f"{sx} {sy} {wall_height}",
            group=str(WORLD_GEOM_GROUP),
            rgba="0.24 0.27 0.25 1",
            friction="1.0 0.01 0.001",
        )

    for index, obstacle in enumerate(getattr(world, "obstacles")):
        radius = float(obstacle.radius_m)
        half_height = 0.18
        ET.SubElement(
            worldbody,
            "geom",
            name=f"obstacle_{index}",
            type="cylinder",
            pos=f"{float(obstacle.x_m)} {float(obstacle.y_m)} {half_height}",
            size=f"{radius} {half_height}",
            group=str(WORLD_GEOM_GROUP),
            rgba="0.12 0.30 0.72 1",
            friction="1.0 0.01 0.001",
        )

    target = getattr(world, "target")
    ET.SubElement(
        worldbody,
        "geom",
        name="visual_target",
        type="sphere",
        pos=f"{float(target.x_m)} {float(target.y_m)} 0.06",
        size="0.06",
        group=str(TARGET_GEOM_GROUP),
        contype="0",
        conaffinity="0",
        rgba="1.0 0.30 0.01 1",
    )

    rover = worldbody.find("./body[@name='rover']")
    if rover is None:
        raise ValueError("MuJoCo model has no rover body")
    ET.SubElement(
        rover,
        "site",
        name="range_origin",
        pos="0.10 0 0.085",
        size="0.006",
        rgba="0.95 0.72 0.15 1",
    )
    ET.SubElement(
        rover,
        "camera",
        name="front_camera",
        pos="0.115 0 0.090",
        xyaxes="0 -1 0 0 0 1",
        fovy="42",
    )
    ET.SubElement(
        rover,
        "camera",
        name="chase_camera",
        pos="-0.55 0 0.38",
        xyaxes="0 -1 0 0.33 0 0.94",
        fovy="58",
    )
    ET.SubElement(
        worldbody,
        "camera",
        name="overview_camera",
        pos="0 0 4.6",
        xyaxes="1 0 0 0 1 0",
        fovy="44",
    )
    return ET.tostring(root, encoding="unicode")


class GeometrySensors:
    """Read ideal rays, physical contacts, and rendered camera pixels from MuJoCo."""

    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData) -> None:
        self.model = model
        self.data = data
        self.range_site_id = model.site("range_origin").id
        self._ray_groups = numpy.zeros(6, dtype=numpy.uint8)
        self._ray_groups[WORLD_GEOM_GROUP] = 1
        self.renderer: mujoco.Renderer | None = None

    def ranges(
        self,
        heading_rad: float,
        bearings_rad: list[float],
        maximum_range_m: float,
    ) -> list[float]:
        origin = self.data.site_xpos[self.range_site_id]
        result: list[float] = []
        geom_id = numpy.array([-1], dtype=numpy.int32)
        for bearing in bearings_rad:
            angle = heading_rad + bearing
            direction = numpy.array(
                [math.cos(angle), math.sin(angle), 0.0], dtype=numpy.float64
            )
            distance = mujoco.mj_ray(
                self.model,
                self.data,
                origin,
                direction,
                self._ray_groups,
                1,
                -1,
                geom_id,
            )
            result.append(
                maximum_range_m
                if distance < 0.0
                else min(maximum_range_m, float(distance))
            )
        return result

    def contacts(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            geom1 = int(contact.geom1)
            geom2 = int(contact.geom2)
            group1 = int(self.model.geom_group[geom1])
            group2 = int(self.model.geom_group[geom2])
            if WORLD_GEOM_GROUP not in (group1, group2):
                continue
            name1 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom1)
            name2 = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, geom2)
            result.append((name1 or str(geom1), name2 or str(geom2)))
        return sorted(set(result))

    def open_renderer(self, width: int = 320, height: int = 180) -> None:
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=height, width=width)

    def render(self, camera_name: str = "front_camera") -> numpy.ndarray:
        if self.renderer is None:
            self.open_renderer()
        assert self.renderer is not None
        self.renderer.update_scene(self.data, camera=camera_name)
        return self.renderer.render().copy()

    def render_camera(self) -> numpy.ndarray:
        return self.render("front_camera")

    def close(self) -> None:
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None


def detect_orange_target(frame_rgb: numpy.ndarray) -> CameraDetection:
    """Derive the target observation from pixels, not virtual coordinates."""
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(
        hsv,
        numpy.array([2, 115, 70], dtype=numpy.uint8),
        numpy.array([28, 255, 255], dtype=numpy.uint8),
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, numpy.ones((3, 3), dtype=numpy.uint8)
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return CameraDetection(False, 0.0, 0.0, 0.0, 0, None, None)
    contour = max(contours, key=cv2.contourArea)
    pixel_count = int(cv2.contourArea(contour))
    if pixel_count < 12:
        return CameraDetection(False, 0.0, 0.0, 0.0, pixel_count, None, None)
    x, y, width, height = cv2.boundingRect(contour)
    if width < 6 or height < 6:
        return CameraDetection(False, 0.0, 0.0, 0.0, pixel_count, None, None)
    frame_height, frame_width = mask.shape
    center_x = x + width * 0.5
    # Shared controller contract: positive means the target is image-right.
    horizontal_error = max(-1.0, min(1.0, (center_x - frame_width * 0.5) / (frame_width * 0.5)))
    horizontal_fov_rad = 2.0 * math.atan(
        (frame_width / frame_height) * math.tan(math.radians(42.0) * 0.5)
    )
    focal_length_px = frame_width / (2.0 * math.tan(horizontal_fov_rad * 0.5))
    estimated_distance_m = focal_length_px * 0.12 / max(width, 1)
    return CameraDetection(
        target_visible=True,
        horizontal_error=float(horizontal_error),
        area_ratio=float(pixel_count / (frame_width * frame_height)),
        bottom_edge_ratio=float((y + height) / frame_height),
        pixel_count=pixel_count,
        bbox_xyxy=(x, y, x + width, y + height),
        estimated_distance_m=float(estimated_distance_m),
    )


def encode_jpeg(frame_rgb: numpy.ndarray, quality: int = 78) -> bytes:
    success, encoded = cv2.imencode(
        ".jpg",
        cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not success:
        raise RuntimeError("failed to encode MuJoCo camera frame")
    return bytes(encoded)
