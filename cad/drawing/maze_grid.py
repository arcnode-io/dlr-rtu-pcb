"""Grid window shared by the escape router and its clearance fields."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np

GRID_MM: Final = 0.05


@dataclass(frozen=True)
class Window:
    """Grid window in board millimetres."""

    x0: float
    y0: float
    nx: int
    ny: int

    def centres(self) -> tuple[np.ndarray, np.ndarray]:
        """Meshgrid of cell-centre x and y, shaped (ny, nx)."""
        xs = self.x0 + np.arange(self.nx) * GRID_MM
        ys = self.y0 + np.arange(self.ny) * GRID_MM
        return np.meshgrid(xs, ys)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """Nearest cell (row, col) to a board point."""
        col = min(max(round((x - self.x0) / GRID_MM), 0), self.nx - 1)
        row = min(max(round((y - self.y0) / GRID_MM), 0), self.ny - 1)
        return row, col

    def point_of(self, row: int, col: int) -> tuple[float, float]:
        """Board point at the centre of a cell."""
        return self.x0 + col * GRID_MM, self.y0 + row * GRID_MM


def window_around(
    points: list[tuple[float, float]], margin_mm: float, limit: int
) -> Window:
    """Grid window covering `points` with `margin_mm` of slack on every side."""
    x0 = min(p[0] for p in points) - margin_mm
    y0 = min(p[1] for p in points) - margin_mm
    nx = math.ceil((max(p[0] for p in points) + margin_mm - x0) / GRID_MM) + 1
    ny = math.ceil((max(p[1] for p in points) + margin_mm - y0) / GRID_MM) + 1
    if nx * ny > limit:
        raise ValueError(f"window {nx}x{ny} exceeds the {limit}-cell budget")
    return Window(x0, y0, nx, ny)
