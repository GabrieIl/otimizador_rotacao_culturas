"""Temperatura do ar diária (máxima e mínima a 2 m) do NASA POWER, com cache na bronze.

Serve para a evapotranspiração de referência (Hargreaves, FAO-56 eq. 52). Mesmo esquema de cache
da chuva (rain_history.py): histórico fechado baixado uma vez; trecho recente no máximo uma vez por dia.
Nunca gera dado sintético: sem API e sem cache, levanta `TemperatureUnavailable`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import numpy as np

from crop_optimizer.config import Settings, get_settings, load_yaml_config
from crop_optimizer.domain.models import LocationSpec

SOURCE_DIR = "nasa_power"
PARAMETERS = ("T2M_MAX", "T2M_MIN")
FILL_VALUE = -999.0


class TemperatureUnavailable(RuntimeError):
    """A temperatura não pôde ser obtida (API fora do ar e sem cache)."""


@dataclass(slots=True)
class TemperatureSeries:
    dates: np.ndarray  # datetime64[D]
    tmax_c: np.ndarray
    tmin_c: np.ndarray
    source: str = "NASA POWER T2M_MAX/T2M_MIN (MERRA-2/GEOS-IT)"


def _cache_path(cache_dir: Path, location: LocationSpec, start: date, end: date) -> Path:
    return cache_dir / f"{location.location_id}_T2M_MAX-T2M_MIN_{start:%Y%m%d}_{end:%Y%m%d}.json"


def _load_or_download(location: LocationSpec, start: date, end: date, cache_dir: Path, cfg: dict) -> dict:
    path = _cache_path(cache_dir, location, start, end)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "AG",
        "longitude": f"{location.longitude:.4f}",
        "latitude": f"{location.latitude:.4f}",
        "start": f"{start:%Y%m%d}",
        "end": f"{end:%Y%m%d}",
        "format": "JSON",
    }
    try:
        with httpx.Client(timeout=float(cfg["timeout_segundos"])) as client:
            response = client.get(cfg["url"], params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede vira aviso na tela
        raise TemperatureUnavailable(
            f"NASA POWER (temperatura) indisponível para {location.name}/{location.state}: {exc}"
        ) from exc
    found = payload.get("properties", {}).get("parameter", {})
    if not all(p in found for p in PARAMETERS):
        raise TemperatureUnavailable(f"Resposta do NASA POWER sem temperatura para {location.name}.")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _parse(payload: dict, name: str) -> dict[date, float]:
    out: dict[date, float] = {}
    for key, raw in payload["properties"]["parameter"][name].items():
        val = float(raw)
        out[date(int(key[:4]), int(key[4:6]), int(key[6:8]))] = np.nan if val <= FILL_VALUE else val
    return out


def fetch_temperature_series(
    location: LocationSpec, today: date | None = None, settings: Settings | None = None
) -> TemperatureSeries:
    cfg = load_yaml_config("chuva")["nasa_power"]
    settings = settings or get_settings()
    today = today or date.today()
    cache_dir = settings.paths.bronze_source(SOURCE_DIR)
    hist_start = date.fromisoformat(cfg["inicio_historico"])
    chunks = [
        _load_or_download(location, hist_start, date(today.year - 2, 12, 31), cache_dir, cfg),
        _load_or_download(location, date(today.year - 1, 1, 1), today, cache_dir, cfg),
    ]
    tmax: dict[date, float] = {}
    tmin: dict[date, float] = {}
    for payload in chunks:
        tmax.update(_parse(payload, "T2M_MAX"))
        tmin.update(_parse(payload, "T2M_MIN"))
    days = np.arange(np.datetime64(hist_start, "D"), np.datetime64(today, "D") + 1, dtype="datetime64[D]")
    as_dates = [d.astype(object) for d in days]
    return TemperatureSeries(
        dates=days,
        tmax_c=np.array([tmax.get(d, np.nan) for d in as_dates]),
        tmin_c=np.array([tmin.get(d, np.nan) for d in as_dates]),
    )
