#!/usr/bin/env python3
"""Small inspectable occupancy-grid, frontier, and pose-estimation primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import deque
import heapq
import math


@dataclass(frozen=True)
class Pose2D:
    x_m: float
    y_m: float
    heading_rad: float


@dataclass(frozen=True)
class PoseEstimate:
    pose: Pose2D
    position_uncertainty_m: float
    heading_uncertainty_degrees: float

    def to_dict(self) -> dict[str, object]:
        return {
            "pose": asdict(self.pose),
            "position_uncertainty_m": round(self.position_uncertainty_m, 4),
            "heading_uncertainty_degrees": round(self.heading_uncertainty_degrees, 3),
        }


class DeadReckoningEstimator:
    """Integrate forward speed and gyro yaw; uncertainty grows without landmarks."""

    def __init__(self, initial_pose: Pose2D = Pose2D(0.0, 0.0, 0.0)) -> None:
        self.x_m = initial_pose.x_m
        self.y_m = initial_pose.y_m
        self.heading_rad = initial_pose.heading_rad
        self.position_uncertainty_m = 0.02
        self.heading_uncertainty_degrees = 1.0

    def update(
        self,
        forward_speed_mps: float,
        yaw_rate_rps: float,
        duration_s: float,
    ) -> PoseEstimate:
        if duration_s < 0.0:
            raise ValueError("duration_s must not be negative")
        midpoint = self.heading_rad + yaw_rate_rps * duration_s * 0.5
        distance = forward_speed_mps * duration_s
        self.x_m += distance * math.cos(midpoint)
        self.y_m += distance * math.sin(midpoint)
        self.heading_rad = wrap_angle(self.heading_rad + yaw_rate_rps * duration_s)
        self.position_uncertainty_m += abs(distance) * 0.035 + duration_s * 0.001
        self.heading_uncertainty_degrees += (
            abs(math.degrees(yaw_rate_rps * duration_s)) * 0.012
            + duration_s * 0.04
        )
        return self.estimate()

    def estimate(self) -> PoseEstimate:
        return PoseEstimate(
            Pose2D(self.x_m, self.y_m, self.heading_rad),
            self.position_uncertainty_m,
            self.heading_uncertainty_degrees,
        )


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def bresenham(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return every integer grid cell crossed by a line."""

    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    result = []
    while True:
        result.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return result
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


class OccupancyGrid:
    """Log-odds map: zero unknown, negative free, positive occupied."""

    def __init__(
        self,
        width: int = 80,
        height: int = 60,
        resolution_m: float = 0.05,
        origin_x_m: float = -2.0,
        origin_y_m: float = -1.5,
    ) -> None:
        if width < 2 or height < 2 or resolution_m <= 0.0:
            raise ValueError("grid dimensions and resolution must be positive")
        self.width = width
        self.height = height
        self.resolution_m = resolution_m
        self.origin_x_m = origin_x_m
        self.origin_y_m = origin_y_m
        self.values = [[0.0 for _ in range(width)] for _ in range(height)]

    def contains(self, cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def world_to_cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        return (
            math.floor((x_m - self.origin_x_m) / self.resolution_m),
            math.floor((y_m - self.origin_y_m) / self.resolution_m),
        )

    def cell_to_world(self, cell: tuple[int, int]) -> tuple[float, float]:
        x, y = cell
        return (
            self.origin_x_m + (x + 0.5) * self.resolution_m,
            self.origin_y_m + (y + 0.5) * self.resolution_m,
        )

    def update_scan(
        self,
        pose: Pose2D,
        ranges_m: list[float],
        bearings_rad: list[float],
        maximum_range_m: float,
    ) -> None:
        if len(ranges_m) != len(bearings_rad):
            raise ValueError("each range requires one bearing")
        start = self.world_to_cell(pose.x_m, pose.y_m)
        if not self.contains(start):
            return
        for measured, relative_bearing in zip(ranges_m, bearings_rad):
            distance = max(0.0, min(maximum_range_m, measured))
            angle = pose.heading_rad + relative_bearing
            endpoint = self.world_to_cell(
                pose.x_m + distance * math.cos(angle),
                pose.y_m + distance * math.sin(angle),
            )
            cells = [cell for cell in bresenham(start, endpoint) if self.contains(cell)]
            if not cells:
                continue
            hit = measured < maximum_range_m - self.resolution_m
            free_cells = cells[:-1] if hit else cells
            for x, y in free_cells:
                self.values[y][x] = max(-4.0, self.values[y][x] - 0.35)
            if hit:
                x, y = cells[-1]
                self.values[y][x] = min(4.0, self.values[y][x] + 0.85)

    def state(self, cell: tuple[int, int]) -> int:
        if not self.contains(cell):
            return 100
        value = self.values[cell[1]][cell[0]]
        if value >= 0.7:
            return 100
        if value <= -0.25:
            return 0
        return -1

    @staticmethod
    def neighbors(cell: tuple[int, int]) -> tuple[tuple[int, int], ...]:
        x, y = cell
        return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))

    def frontier_cells(self) -> list[tuple[int, int]]:
        result = []
        for y in range(1, self.height - 1):
            for x in range(1, self.width - 1):
                cell = (x, y)
                if self.state(cell) != 0:
                    continue
                if any(self.state(neighbor) == -1 for neighbor in self.neighbors(cell)):
                    result.append(cell)
        return result

    def traversable(self, cell: tuple[int, int], clearance_cells: int = 5) -> bool:
        """Require known free space around the rover footprint."""

        if self.state(cell) != 0:
            return False
        x, y = cell
        for dy in range(-clearance_cells, clearance_cells + 1):
            for dx in range(-clearance_cells, clearance_cells + 1):
                if dx * dx + dy * dy > clearance_cells * clearance_cells:
                    continue
                if self.state((x + dx, y + dy)) == 100:
                    return False
        return True

    def plan(self, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
        if self.state(start) == 100 or self.state(goal) == 100:
            return []
        frontier = [(0.0, start)]
        cost = {start: 0.0}
        parent: dict[tuple[int, int], tuple[int, int]] = {}
        while frontier:
            _priority, current = heapq.heappop(frontier)
            if current == goal:
                path = [current]
                while current in parent:
                    current = parent[current]
                    path.append(current)
                return list(reversed(path))
            for neighbor in self.neighbors(current):
                if not self.contains(neighbor) or not self.traversable(neighbor):
                    continue
                new_cost = cost[current] + 1.0
                if new_cost >= cost.get(neighbor, math.inf):
                    continue
                cost[neighbor] = new_cost
                parent[neighbor] = current
                heuristic = abs(goal[0] - neighbor[0]) + abs(goal[1] - neighbor[1])
                heapq.heappush(frontier, (new_cost + heuristic, neighbor))
        return []

    def choose_frontier(
        self,
        start: tuple[int, int],
        minimum_distance_cells: int = 5,
    ) -> tuple[int, int] | None:
        candidates = sorted(
            self.frontier_cells(),
            key=lambda cell: (
                (cell[0] - start[0]) ** 2 + (cell[1] - start[1]) ** 2,
                cell,
            ),
        )
        for cell in candidates:
            distance = abs(cell[0] - start[0]) + abs(cell[1] - start[1])
            if distance >= minimum_distance_cells and self.plan(start, cell):
                return cell
        return candidates[0] if candidates else None

    def plan_to_frontier(
        self,
        start: tuple[int, int],
        minimum_distance_cells: int = 5,
    ) -> list[tuple[int, int]]:
        """Find the nearest reachable frontier with one breadth-first search.

        Calling A* independently for every frontier grows poorly as the map
        expands. This search establishes reachability once and reconstructs the
        first suitably distant frontier path.
        """
        frontiers = set(self.frontier_cells())
        queue = deque([start])
        parent: dict[tuple[int, int], tuple[int, int]] = {}
        visited = {start}
        goal: tuple[int, int] | None = None
        while queue:
            current = queue.popleft()
            distance = abs(current[0] - start[0]) + abs(current[1] - start[1])
            if current in frontiers and distance >= minimum_distance_cells:
                goal = current
                break
            for neighbor in self.neighbors(current):
                if neighbor in visited or not self.contains(neighbor):
                    continue
                if neighbor != start and not self.traversable(neighbor):
                    continue
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)
        if goal is None:
            return []
        path = [goal]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        return list(reversed(path))

    def plan_toward_world(
        self,
        start: tuple[int, int],
        goal_x_m: float,
        goal_y_m: float,
    ) -> list[tuple[int, int]]:
        """Plan to the closest currently known-free cell near a world goal."""

        if not self.contains(start) or self.state(start) == 100:
            return []
        queue = deque([start])
        parent: dict[tuple[int, int], tuple[int, int]] = {}
        visited = {start}
        best = start
        best_distance = math.inf
        while queue:
            current = queue.popleft()
            world_x, world_y = self.cell_to_world(current)
            distance = (world_x - goal_x_m) ** 2 + (world_y - goal_y_m) ** 2
            if distance < best_distance:
                best = current
                best_distance = distance
            for neighbor in self.neighbors(current):
                if neighbor in visited or not self.contains(neighbor):
                    continue
                if neighbor != start and not self.traversable(neighbor):
                    continue
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)
        path = [best]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        return list(reversed(path))

    def to_dict(self) -> dict[str, object]:
        cells = [[self.state((x, y)) for x in range(self.width)] for y in range(self.height)]
        counts = {
            "unknown": sum(value == -1 for row in cells for value in row),
            "free": sum(value == 0 for row in cells for value in row),
            "occupied": sum(value == 100 for row in cells for value in row),
        }
        return {
            "width": self.width,
            "height": self.height,
            "resolution_m": self.resolution_m,
            "origin_x_m": self.origin_x_m,
            "origin_y_m": self.origin_y_m,
            "cells": cells,
            "counts": counts,
        }
