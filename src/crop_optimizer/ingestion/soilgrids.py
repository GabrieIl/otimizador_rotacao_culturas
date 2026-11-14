"""ISRIC SoilGrids 2.0: atributos do solo (250 m) para um ponto, na camada 0-20 cm.

SoilGrids é um mapa global feito por aprendizado de máquina com ~240 mil perfis de solo e
camadas de satélite (relevo, clima, vegetação). Não é medição no ponto: é a melhor estimativa
do mapa, com faixa de incerteza (quantis 5% e 95%).

Resposta original guardada em data/bronze/soilgrids/. Área urbana e água vêm sem valor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "soilgrids"


class SoilGridsUnavailable(RuntimeError):
    """SoilGrids fora do ar e sem cache."""


@dataclass(frozen=True, slots=True)
class SoilGridsValue:
    mean: float
    q05: float
    q95: float
    unit: str


def _weighted(depths: list[dict], weights: dict[str, float], key: str, d_factor: float) -> float | None:
    total = acc = 0.0
    for depth in depths:
        w = weights.get(depth["label"])
        value = depth["values"].get(key)
        if w is None or value is None:
            continue
        acc += w * value / d_factor
        total += w
    return acc / total if total else None


def parse_soilgrids(payload: dict, weights: dict[str, float]) -> dict[str, SoilGridsValue]:
    """Propriedade -> média ponderada 0-20 cm (e quantis) nas unidades-alvo do SoilGrids."""
    out: dict[str, SoilGridsValue] = {}
    for layer in payload.get("properties", {}).get("layers", []):
        unit = layer["unit_measure"]
        d_factor = float(unit.get("d_factor", 1))
        mean = _weighted(layer["depths"], weights, "mean", d_factor)
        if mean is None:
            continue
        q05 = _weighted(layer["depths"], weights, "Q0.05", d_factor)
        q95 = _weighted(layer["depths"], weights, "Q0.95", d_factor)
        out[layer["name"]] = SoilGridsValue(
            mean=mean,
            q05=q05 if q05 is not None else mean,
            q95=q95 if q95 is not None else mean,
            unit=unit.get("target_units", ""),
        )
    return out


def fetch_soilgrids(lat: float, lon: float, settings: Settings | None = None) -> dict[str, SoilGridsValue]:
    cfg = load_yaml_config("aptidao")["soilgrids"]
    settings = settings or get_settings()
    cache = settings.paths.bronze_source(SOURCE_DIR) / f"soilgrids_{lat:.4f}_{lon:.4f}.json"
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        params: list[tuple[str, str]] = [("lon", f"{lon:.4f}"), ("lat", f"{lat:.4f}")]
        params += [("property", p) for p in cfg["propriedades"]]
        params += [("depth", d) for d in cfg["profundidades"]]
        params += [("value", v) for v in ("mean", "Q0.05", "Q0.95")]
        try:
            with httpx.Client(timeout=float(cfg["timeout_segundos"])) as client:
                response = client.get(cfg["url"], params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise SoilGridsUnavailable(f"SoilGrids indisponível: {exc}") from exc
        cache.write_text(json.dumps(payload), encoding="utf-8")
    return parse_soilgrids(payload, {k: float(v) for k, v in cfg["profundidades"].items()})


_DIRECTIONS = (("norte", 1, 0), ("sul", -1, 0), ("leste", 0, 1), ("oeste", 0, -1))


def fetch_soilgrids_nearby(
    lat: float, lon: float, radius_km: float = 3.0, settings: Settings | None = None
) -> tuple[dict[str, SoilGridsValue], str | None]:
    """Valores no ponto; se o mapa não tiver valor ali (área urbana, água), tenta o ponto com dado
    mais próximo a `radius_km` nas 4 direções. Devolve (valores, descrição do ponto usado ou None)."""
    import math

    values = fetch_soilgrids(lat, lon, settings)
    if values:
        return values, None
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(0.01, math.cos(math.radians(lat))))
    for name, sy, sx in _DIRECTIONS:
        alt = fetch_soilgrids(round(lat + sy * dlat, 4), round(lon + sx * dlon, 4), settings)
        if alt:
            return alt, f"a {radius_km:g} km ao {name}"
    return {}, None
