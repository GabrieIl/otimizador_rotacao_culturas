"""Série diária de chuva REAL do NASA POWER (PRECTOTCORR) com cache na bronze.

Diferente de `NasaPowerClient`, este módulo nunca gera dados sintéticos: se a API falhar
e não houver cache, levanta `RainDataUnavailable` para a interface avisar o usuário.

Cache em data/bronze/nasa_power/ com a resposta JSON original:
- histórico fechado (até 31/12 de dois anos atrás): baixado uma única vez;
- trecho recente (de 1º/jan do ano anterior até hoje): baixado no máximo uma vez por dia.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import numpy as np

from crop_optimizer.config import Settings, get_settings, load_yaml_config
from crop_optimizer.domain.models import LocationSpec

logger = logging.getLogger(__name__)

SOURCE_DIR = "nasa_power"
PARAMETER = "PRECTOTCORR"
FILL_VALUE = -999.0


class RainDataUnavailable(RuntimeError):
    """A chuva real não pôde ser obtida (API fora do ar e sem cache)."""


@dataclass(slots=True)
class RainSeries:
    """Chuva diária (mm/dia) contínua, NaN onde a fonte não tem valor."""

    location_id: str
    dates: np.ndarray  # datetime64[D]
    precip_mm: np.ndarray  # float64
    source: str

    @property
    def last_valid_date(self) -> date | None:
        valid = np.flatnonzero(~np.isnan(self.precip_mm))
        if valid.size == 0:
            return None
        return self.dates[valid[-1]].astype(object)


def _cache_path(cache_dir: Path, location: LocationSpec, start: date, end: date) -> Path:
    return cache_dir / f"{location.location_id}_{PARAMETER}_{start:%Y%m%d}_{end:%Y%m%d}.json"


def _download(location: LocationSpec, start: date, end: date, cfg: dict) -> dict:
    params = {
        "parameters": PARAMETER,
        "community": "AG",
        "longitude": f"{location.longitude:.4f}",
        "latitude": f"{location.latitude:.4f}",
        "start": f"{start:%Y%m%d}",
        "end": f"{end:%Y%m%d}",
        "format": "JSON",
    }
    with httpx.Client(timeout=float(cfg["timeout_segundos"])) as client:
        response = client.get(cfg["url"], params=params)
        response.raise_for_status()
        return response.json()


def _load_or_download(
    location: LocationSpec, start: date, end: date, cache_dir: Path, cfg: dict
) -> dict:
    path = _cache_path(cache_dir, location, start, end)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        payload = _download(location, start, end, cfg)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede vira aviso na tela
        raise RainDataUnavailable(
            f"NASA POWER indisponível para {location.name}/{location.state} "
            f"({start:%d/%m/%Y} a {end:%d/%m/%Y}): {exc}"
        ) from exc
    if PARAMETER not in payload.get("properties", {}).get("parameter", {}):
        raise RainDataUnavailable(f"Resposta do NASA POWER sem {PARAMETER} para {location.name}.")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _parse(payload: dict) -> dict[date, float]:
    values = payload["properties"]["parameter"][PARAMETER]
    out: dict[date, float] = {}
    for key, raw in values.items():
        day = date(int(key[:4]), int(key[4:6]), int(key[6:8]))
        val = float(raw)
        out[day] = np.nan if val <= FILL_VALUE else max(0.0, val)
    return out


def fetch_rain_series(
    location: LocationSpec,
    today: date | None = None,
    settings: Settings | None = None,
) -> RainSeries:
    """Chuva diária real de `inicio_historico` até `today`, usando o cache da bronze."""
    cfg = load_yaml_config("chuva")["nasa_power"]
    settings = settings or get_settings()
    today = today or date.today()
    cache_dir = settings.paths.bronze_source(SOURCE_DIR)

    hist_start = date.fromisoformat(cfg["inicio_historico"])
    hist_end = date(today.year - 2, 12, 31)
    recent_start = date(today.year - 1, 1, 1)

    merged: dict[date, float] = {}
    merged.update(_parse(_load_or_download(location, hist_start, hist_end, cache_dir, cfg)))
    merged.update(_parse(_load_or_download(location, recent_start, today, cache_dir, cfg)))

    all_days = np.arange(
        np.datetime64(hist_start, "D"), np.datetime64(today, "D") + np.timedelta64(1, "D"), dtype="datetime64[D]"
    )
    precip = np.array([merged.get(d.astype(object), np.nan) for d in all_days], dtype=np.float64)
    return RainSeries(
        location_id=location.location_id,
        dates=all_days,
        precip_mm=precip,
        source="NASA POWER PRECTOTCORR (MERRA-2/GEOS-IT)",
    )
