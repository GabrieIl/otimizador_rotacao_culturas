"""Valor de uma camada do NASA GIBS no ponto da roça, lido pela cor do pixel.

O GIBS não devolve números, só imagens coloridas. Cada cor, porém, corresponde a uma faixa de valores
publicada no colormap oficial da camada (XML em gibs.earthdata.nasa.gov/colormaps/v1.3/). Pedimos um
recorte pequeno em volta do ponto (WMS, EPSG:4326), lemos a cor do pixel central e devolvemos o meio
da faixa. A precisão é a da faixa (ex.: SMAP de 0,003 em 0,003 m³/m³; NDVI de 0,01 em 0,01).

Por que assim: a API de recortes da ORNL DAAC devolve o número exato, mas leva ~50 s por consulta;
aqui são ~1 s, sem login.

Cache (arquivo original) em data/bronze/gibs_colormaps/ e data/bronze/gibs_pixels/<camada>/.
Imagens dos últimos 30 dias não ficam em cache se vierem vazias (o dado pode ainda não ter chegado).
"""

from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import httpx
import numpy as np
from PIL import Image

from crop_optimizer.config import Settings, get_settings

COLORMAP_DIR = "gibs_colormaps"
PIXEL_DIR = "gibs_pixels"
_COLORMAP_URL = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/{colormap}.xml"
_WMS_URL = (
    "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
    "&LAYERS={layer}&CRS=EPSG:4326&BBOX={s:.5f},{w:.5f},{n:.5f},{e:.5f}&WIDTH={size}&HEIGHT={size}"
    "&FORMAT=image/png&STYLES="
)
_SIZE = 9  # pixels do recorte; o do meio é o da roça
_ENTRY = re.compile(r'<ColorMapEntry\s+rgb="(\d+),(\d+),(\d+)"([^>]*)/>')
_VALUE = re.compile(r'value="([^"]+)"')


class GibsValueUnavailable(RuntimeError):
    """Não foi possível ler o valor da camada (rede fora e sem cache)."""


@dataclass(frozen=True, slots=True)
class Colormap:
    units: str
    rgb: np.ndarray  # (n, 3)
    low: np.ndarray
    high: np.ndarray

    def decode(self, rgb: tuple[int, int, int]) -> float | None:
        dist = np.abs(self.rgb - np.asarray(rgb)).sum(axis=1)
        i = int(np.argmin(dist))
        if dist[i] > 6:  # cor que não está na legenda (borda, rótulo): sem valor
            return None
        lo, hi = self.low[i], self.high[i]
        if not np.isfinite(lo):
            return float(hi)
        if not np.isfinite(hi):
            return float(lo)
        return float((lo + hi) / 2)


def parse_colormap(xml: str) -> Colormap:
    """Lê as faixas do colormap (ignora o bloco "No Data")."""
    blocks = re.split(r"<ColorMap\b", xml)[1:]
    rgb, low, high, units = [], [], [], ""
    for block in blocks:
        head = block.split(">", 1)[0]
        if 'title="No Data"' in head:
            continue
        m = re.search(r'units="([^"]*)"', head)
        units = units or (m.group(1) if m else "")
        for r, g, b, attrs in _ENTRY.findall(block):
            if 'nodata="true"' in attrs or 'transparent="true"' in attrs:
                continue
            value = _VALUE.search(attrs)
            if value is None:
                continue
            nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", value.group(1))]
            if not nums:
                continue
            text = value.group(1)
            lo = nums[0] if not text.lstrip("[(").startswith("-INF") else -np.inf
            hi = nums[-1] if len(nums) > 1 and not text.rstrip(")]").endswith("INF") else (
                np.inf if text.rstrip(")]").endswith("INF") else nums[0])
            rgb.append((int(r), int(g), int(b)))
            low.append(lo)
            high.append(hi)
    if not rgb:
        raise GibsValueUnavailable("Colormap do GIBS sem faixas de valor.")
    return Colormap(units, np.asarray(rgb), np.asarray(low, dtype=float), np.asarray(high, dtype=float))


def load_colormap(colormap: str, settings: Settings | None = None) -> Colormap:
    settings = settings or get_settings()
    path = settings.paths.bronze_source(COLORMAP_DIR) / f"{colormap}.xml"
    if not path.exists():
        try:
            response = httpx.get(_COLORMAP_URL.format(colormap=colormap), timeout=60.0)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise GibsValueUnavailable(f"Colormap {colormap} do GIBS indisponível: {exc}") from exc
        path.write_bytes(response.content)
    return parse_colormap(path.read_text(encoding="utf-8"))


def _pixel_rgba(layer: str, day: date | None, lat: float, lon: float, half_deg: float,
                settings: Settings, today: date) -> tuple[int, int, int, int] | None:
    folder = settings.paths.bronze_source(PIXEL_DIR) / layer
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day.isoformat() if day else "fixo"
    path = folder / f"{lat:.4f}_{lon:.4f}_{half_deg:g}_{stamp}.png"
    if path.exists():
        content = path.read_bytes()
    else:
        url = _WMS_URL.format(layer=layer, s=lat - half_deg, n=lat + half_deg, w=lon - half_deg,
                              e=lon + half_deg, size=_SIZE)
        if day is not None:
            url += f"&TIME={day.isoformat()}"
        try:
            response = httpx.get(url, timeout=60.0)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise GibsValueUnavailable(f"NASA GIBS indisponível ({layer}): {exc}") from exc
        if not response.headers.get("content-type", "").startswith("image/"):
            return None
        content = response.content
    rgba = Image.open(io.BytesIO(content)).convert("RGBA").getpixel((_SIZE // 2, _SIZE // 2))
    recent = day is not None and (today - day).days < 30
    if not path.exists() and not (recent and rgba[3] == 0):
        path.write_bytes(content)
    return None if rgba[3] == 0 else rgba


def values_at(
    layer: str, colormap: str, days: list[date | None], lat: float, lon: float, pixel_km: float,
    settings: Settings | None = None, today: date | None = None, workers: int = 8,
) -> dict[date | None, float | None]:
    """Valor da camada no ponto em cada data (None = sem dado: nuvem, falha da órbita, fora da série)."""
    settings = settings or get_settings()
    today = today or date.today()
    cmap = load_colormap(colormap, settings)
    half = max(pixel_km * 2.0 / 111.0, 0.01)

    def one(day: date | None) -> float | None:
        rgba = _pixel_rgba(layer, day, lat, lon, half, settings, today)
        return None if rgba is None else cmap.decode(rgba[:3])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(days, pool.map(one, days), strict=True))


def units_of(colormap: str, settings: Settings | None = None) -> str:
    return load_colormap(colormap, settings).units
