#!/usr/bin/env python3
"""Estimate frame-to-frame image motion without inventing metric scale."""

from __future__ import annotations

import math
from typing import Any


class VisualMotionEstimator:
    """ORB feature matching plus a robust planar homography estimate.

    The camera has not been geometrically calibrated and the rover has no
    metric odometry. Outputs therefore remain in pixels and image degrees.
    """

    def __init__(self, maximum_features: int = 500) -> None:
        self.previous_keypoints: Any = None
        self.previous_descriptors: Any = None
        self.frame_count = 0
        self.keyframe_count = 0
        self.total_image_rotation_degrees = 0.0
        self.total_image_travel_pixels = 0.0
        self._status: dict[str, object] = {
            "state": "starting",
            "source": "live_camera_features",
            "method": "ORB + RANSAC homography",
            "metric_scale": "unobservable_without_calibration_or_odometry",
            "frame_count": 0,
            "keyframe_count": 0,
            "features": 0,
            "matches": 0,
            "inliers": 0,
            "inlier_ratio": 0.0,
            "delta_x_px": 0.0,
            "delta_y_px": 0.0,
            "image_rotation_degrees": 0.0,
            "tracks": [],
        }
        try:
            import cv2
            import numpy

            self.cv2 = cv2
            self.numpy = numpy
            self.orb = cv2.ORB_create(nfeatures=maximum_features)
            self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        except ImportError as error:
            self.cv2 = None
            self.numpy = None
            self.orb = None
            self.matcher = None
            self._status = {**self._status, "state": "unavailable", "error": str(error)}

    def status(self) -> dict[str, object]:
        return dict(self._status)

    def reset(self) -> None:
        self.previous_keypoints = None
        self.previous_descriptors = None
        self.frame_count = 0
        self.keyframe_count = 0
        self.total_image_rotation_degrees = 0.0
        self.total_image_travel_pixels = 0.0

    def process(self, jpeg: bytes) -> dict[str, object]:
        if self.cv2 is None or self.numpy is None:
            return self.status()
        cv2 = self.cv2
        numpy = self.numpy
        raw = cv2.imdecode(numpy.frombuffer(jpeg, dtype=numpy.uint8), cv2.IMREAD_GRAYSCALE)
        if raw is None:
            self._status = {**self._status, "state": "invalid_frame"}
            return self.status()
        frame = cv2.rotate(raw, cv2.ROTATE_90_COUNTERCLOCKWISE)
        keypoints, descriptors = self.orb.detectAndCompute(frame, None)
        self.frame_count += 1
        base = {
            **self._status,
            "frame_count": self.frame_count,
            "keyframe_count": self.keyframe_count,
            "features": len(keypoints),
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
        }
        if descriptors is None or len(keypoints) < 8:
            self.previous_keypoints = keypoints
            self.previous_descriptors = descriptors
            self._status = {**base, "state": "insufficient_features", "matches": 0, "inliers": 0}
            return self.status()
        if self.previous_descriptors is None or self.previous_keypoints is None:
            self.previous_keypoints = keypoints
            self.previous_descriptors = descriptors
            self.keyframe_count = 1
            self._status = {**base, "state": "initialized", "keyframe_count": 1}
            return self.status()

        matches = sorted(
            self.matcher.match(self.previous_descriptors, descriptors),
            key=lambda match: match.distance,
        )[:160]
        if len(matches) < 8:
            self.previous_keypoints = keypoints
            self.previous_descriptors = descriptors
            self._status = {**base, "state": "insufficient_matches", "matches": len(matches), "inliers": 0}
            return self.status()

        previous = numpy.float32(
            [self.previous_keypoints[match.queryIdx].pt for match in matches]
        ).reshape(-1, 1, 2)
        current = numpy.float32(
            [keypoints[match.trainIdx].pt for match in matches]
        ).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(previous, current, cv2.RANSAC, 3.0)
        if homography is None or mask is None:
            self.previous_keypoints = keypoints
            self.previous_descriptors = descriptors
            self._status = {**base, "state": "geometry_rejected", "matches": len(matches), "inliers": 0}
            return self.status()

        inlier_flags = mask.ravel().astype(bool)
        inliers = int(inlier_flags.sum())
        ratio = inliers / len(matches)
        dx = float(homography[0, 2])
        dy = float(homography[1, 2])
        rotation = math.degrees(math.atan2(homography[1, 0], homography[0, 0]))
        displacement = math.hypot(dx, dy)
        if ratio >= 0.35:
            self.total_image_rotation_degrees += rotation
            self.total_image_travel_pixels += displacement
        if displacement >= 12.0 or abs(rotation) >= 4.0:
            self.keyframe_count += 1

        tracks = []
        for old, new, keep in zip(previous[:, 0], current[:, 0], inlier_flags):
            if keep and len(tracks) < 24:
                tracks.append(
                    {
                        "x0": round(float(old[0]), 1),
                        "y0": round(float(old[1]), 1),
                        "x1": round(float(new[0]), 1),
                        "y1": round(float(new[1]), 1),
                    }
                )
        self.previous_keypoints = keypoints
        self.previous_descriptors = descriptors
        self._status = {
            **base,
            "state": "tracking" if ratio >= 0.35 else "low_confidence",
            "keyframe_count": self.keyframe_count,
            "matches": len(matches),
            "inliers": inliers,
            "inlier_ratio": round(ratio, 3),
            "delta_x_px": round(dx, 2),
            "delta_y_px": round(dy, 2),
            "image_rotation_degrees": round(rotation, 3),
            "total_image_rotation_degrees": round(self.total_image_rotation_degrees, 2),
            "total_image_travel_pixels": round(self.total_image_travel_pixels, 2),
            "tracks": tracks,
        }
        return self.status()
