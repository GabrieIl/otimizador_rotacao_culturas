"""Altitude e declividade de um ponto a partir dos Terrain Tiles (formato terrarium) no AWS.

Os tiles têm a altitude codificada nas cores: altitude = R*256 + G + B/256 - 32768 (metros).
A declividade sai do método de Horn (3x3), calculada nos 9 pixels em volta do ponto; usamos a
mediana para não depender de um pixel só. Tiles guardados em data/bronze/terrain_tiles/.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import httpx
import numpy as np
from PIL import Image

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "terrain_tiles"


class TerrainUnavailable(RuntimeError):
    """Tiles de altitude indisponíveis."""


@dataclass(frozen=True, slots=True)
class TerrainInfo:
    elevation_m: float
    slope_pct: float
    pixel_m: float


def decode_terrarium(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype(np.float64)
    return rgb[..., 0] * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0 - 32768.0


def horn_slope_pct(window: np.ndarray, pixel_m: float) -> float:
    """Declividade (%) no centro de uma janela 3x3 de altitudes (método de Horn)."""
    a, b, c = window[0]
    d, _, f = window[1]
    g, h, i = window[2]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * pixel_m)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * pixel_m)
    return 100.0 * math.hypot(dzdx, dzdy)


def pixel_size_m(lat: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2**zoom)


def _global_pixel(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom * 256
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return int(x), int(y)


class _TileReader:
    def __init__(self, zoom: int, settings: Settings) -> None:
        self.zoom = zoom
        self.cfg = load_yaml_config("aptidao")["terreno"]
        self.folder = settings.paths.bronze_source(SOURCE_DIR)
        self._tiles: dict[tuple[int, int], np.ndarray] = {}

    def _tile(self, tx: int, ty: int) -> np.ndarray:
        if (tx, ty) not in self._tiles:
            path = self.folder / f"{self.zoom}_{tx}_{ty}.png"
            if not path.exists():
                url = self.cfg["url"].format(z=self.zoom, x=tx, y=ty)
                try:
                    with httpx.Client(timeout=float(self.cfg["timeout_segundos"])) as client:
                        response = client.get(url)
                        response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    raise TerrainUnavailable(f"Tiles de altitude indisponíveis: {exc}") from exc
                path.write_bytes(response.content)
            image = Image.open(io.BytesIO(path.read_bytes())).convert("RGB")
            self._tiles[(tx, ty)] = decode_terrarium(np.asarray(image))
        return self._tiles[(tx, ty)]

    def elevation(self, px: int, py: int) -> float:
        tile = self._tile(px // 256, py // 256)
        return float(tile[py % 256, px % 256])


def terrain_at(lat: float, lon: float, settings: Settings | None = None) -> TerrainInfo:
    settings = settings or get_settings()
    zoom = int(load_yaml_config("aptidao")["terreno"]["zoom"])
    reader = _TileReader(zoom, settings)
    px, py = _global_pixel(lat, lon, zoom)
    grid = np.array([[reader.elevation(px + dx, py + dy) for dx in range(-2, 3)] for dy in range(-2, 3)])
    pix = pixel_size_m(lat, zoom)
    slopes = [horn_slope_pct(grid[r - 1 : r + 2, c - 1 : c + 2], pix) for r in range(1, 4) for c in range(1, 4)]
    return TerrainInfo(elevation_m=float(grid[2, 2]), slope_pct=float(np.median(slopes)), pixel_m=pix)
