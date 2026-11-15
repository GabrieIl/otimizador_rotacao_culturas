"""Solo da REGIÃO em volta do ponto: recorte dos mapas do SoilGrids pelo serviço WCS do ISRIC.

A API REST do SoilGrids tem limite de 5 chamadas por minuto; amostrar vários pontos levaria minutos.
O WCS devolve o mapa inteiro de um quadrado (GeoTIFF) em uma chamada por camada (~1 s). Usamos o mesmo
cálculo do ponto (média ponderada 0-20 cm: 5/10/5 cm) para comparar o local com a região.

Arquivos originais em data/bronze/soilgrids_wcs/<lat>_<lon>/.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import numpy as np
from PIL import Image

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "soilgrids_wcs"
_URL = (
    "https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
    "&COVERAGEID={prop}_{depth}_mean&FORMAT=GEOTIFF_INT16"
    "&SUBSET=long({w:.4f},{e:.4f})&SUBSET=lat({s:.4f},{n:.4f})"
    "&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
    "&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
)
# propriedade -> divisor para a unidade-alvo (mesmos d_factor da API REST)
PROPS = {"clay": 10.0, "sand": 10.0, "soc": 10.0, "phh2o": 10.0, "nitrogen": 100.0, "cec": 10.0}


class RegionUnavailable(RuntimeError):
    """Mapa regional indisponível."""


@dataclass(frozen=True, slots=True)
class RegionStats:
    p10: float
    p50: float
    p90: float
    low: float  # percentil 2 (ponta da régua)
    high: float  # percentil 98
    n: int

    def percentile_of(self, value: float, values: np.ndarray) -> float:
        return float(np.mean(values < value) * 100.0)


def _download(url: str, path) -> np.ndarray:
    if not path.exists():
        try:
            with httpx.Client(timeout=90.0) as client:
                response = client.get(url)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise RegionUnavailable(f"Mapa regional do SoilGrids indisponível: {exc}") from exc
        if not response.headers.get("content-type", "").startswith("image/tiff"):
            raise RegionUnavailable("O serviço de mapas do SoilGrids não devolveu uma imagem.")
        path.write_bytes(response.content)
    return np.asarray(Image.open(path)).astype(float)


def region_values(lat: float, lon: float, half_deg: float = 0.25, settings: Settings | None = None) -> dict[str, np.ndarray]:
    """Valores 0-20 cm de cada pixel da região (só pixels com dado nas 3 profundidades)."""
    settings = settings or get_settings()
    weights = {k: float(v) for k, v in load_yaml_config("aptidao")["soilgrids"]["profundidades"].items()}
    folder = settings.paths.bronze_source(SOURCE_DIR) / f"{lat:.3f}_{lon:.3f}_{half_deg:g}"
    folder.mkdir(parents=True, exist_ok=True)
    box = {"w": lon - half_deg, "e": lon + half_deg, "s": lat - half_deg, "n": lat + half_deg}
    jobs = [(p, d) for p in PROPS for d in weights]
    with ThreadPoolExecutor(max_workers=4) as pool:
        arrays = list(pool.map(
            lambda job: _download(_URL.format(prop=job[0], depth=job[1], **box), folder / f"{job[0]}_{job[1]}.tif"),
            jobs,
        ))
    by_job = dict(zip(jobs, arrays, strict=True))
    out: dict[str, np.ndarray] = {}
    total_w = sum(weights.values())
    for prop, divisor in PROPS.items():
        layers = [by_job[(prop, d)] for d in weights]
        valid = np.all([layer > 0 for layer in layers], axis=0)
        weighted = sum(layer * w for layer, w in zip(layers, weights.values(), strict=True)) / total_w
        out[prop] = (weighted[valid] / divisor).ravel()
    return out


def stats(values: np.ndarray) -> RegionStats | None:
    if values.size < 20:
        return None
    p = np.percentile(values, [2, 10, 50, 90, 98])
    return RegionStats(p10=float(p[1]), p50=float(p[2]), p90=float(p[3]), low=float(p[0]), high=float(p[4]), n=int(values.size))
