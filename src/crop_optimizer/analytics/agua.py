"""Água no solo e na lavoura (FAO-56): quantos dias a terra segura a lavoura e a água no solo hoje.

- Ra: radiação extraterrestre pela latitude e dia do ano (FAO-56 eq. 21), em mm/dia (x 0,408).
- ET0: Hargreaves (FAO-56 eq. 52) com a temperatura do NASA POWER.
- Dias que a lavoura aguenta sem chuva = RAW / ETc na fase média (floração), com
  TAW = CAD x Zr, RAW = p x TAW, ETc = Kc_média x ET0 da época. É a conta do turno de rega.
- Água no solo hoje: balanço diário de um reservatório (FAO-56) do solo nu, com a chuva e a ET0
  do NASA POWER, rodado sem parar desde 1981. O "normal da data" é a mediana de 1991-2020.

Parâmetros em config/agua.yaml (CAD em config/aptidao.yaml).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from crop_optimizer.config import load_yaml_config
from crop_optimizer.engine.rain_onset import OnsetReference

# --- ET0 ------------------------------------------------------------------------------------------

GSC = 0.0820  # constante solar, MJ m-2 min-1


def extraterrestrial_radiation(lat_deg: float, doy: np.ndarray | int) -> np.ndarray:
    """Ra em MJ m-2 dia-1 (FAO-56 eq. 21)."""
    j = np.asarray(doy, dtype=np.float64)
    phi = np.deg2rad(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * j / 365)
    delta = 0.409 * np.sin(2 * np.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    return (24 * 60 / np.pi) * GSC * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws)
    )


def et0_hargreaves(tmax: np.ndarray, tmin: np.ndarray, ra_mj: np.ndarray) -> np.ndarray:
    """ET0 em mm/dia (FAO-56 eq. 52), com Ra convertida para mm/dia (x 0,408)."""
    tmax, tmin = np.asarray(tmax, dtype=np.float64), np.asarray(tmin, dtype=np.float64)
    tmean = (tmax + tmin) / 2
    return 0.0023 * (tmean + 17.8) * np.sqrt(np.clip(tmax - tmin, 0.0, None)) * 0.408 * ra_mj


def daily_et0(dates: np.ndarray, tmax: np.ndarray, tmin: np.ndarray, lat_deg: float) -> np.ndarray:
    doy = (dates - dates.astype("datetime64[Y]")).astype(int) + 1
    return et0_hargreaves(tmax, tmin, extraterrestrial_radiation(lat_deg, doy))


# --- parâmetros -------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CropWater:
    crop_id: str
    phases: tuple[int, int, int, int] = (0, 0, 0, 0)
    kc: tuple[float, float, float] = (0.0, 0.0, 0.0)
    zr_m: float = 0.0
    p: float = 0.0
    reserve_in_plant: bool = False  # palma: guarda água na raquete

    @property
    def critical_start(self) -> int:
        """Dias depois do plantio em que começa a fase média (floração)."""
        return self.phases[0] + self.phases[1]

    @property
    def critical_length(self) -> int:
        return self.phases[2]


def crop_water(crop_id: str) -> CropWater:
    raw = load_yaml_config("agua")["culturas"][crop_id]
    if raw.get("reserva_na_planta"):
        return CropWater(crop_id, reserve_in_plant=True)
    return CropWater(crop_id, tuple(raw["fases_dias"]), tuple(raw["kc"]), float(raw["zr_m"]), float(raw["p"]))


def cad_mm_per_m(texture_group: str) -> float:
    return float(load_yaml_config("aptidao")["cad_mm_por_m"][texture_group])


# --- dias que a lavoura aguenta -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HoldDays:
    crop_id: str
    days: int | None  # None = planta que guarda água (palma)
    raw_mm: float
    taw_mm: float
    etc_mm_day: float
    zr_m: float
    limited_by_depth: bool


def critical_et0(dates: np.ndarray, et0: np.ndarray, ref: OnsetReference, crop: CropWater) -> float | None:
    """ET0 média na fase média da cultura, plantando no dia em que a chuva firmou em cada ano de referência."""
    if crop.reserve_in_plant:
        return None
    values: list[float] = []
    for year, offset in zip(ref.season_years, ref.offsets, strict=True):
        onset = ref.date_in(date(year, ref.hydro_start_month, 1), offset)
        if onset is None:
            continue
        start = np.datetime64(onset + timedelta(days=crop.critical_start), "D")
        end = start + np.timedelta64(max(1, crop.critical_length), "D")
        window = et0[(dates >= start) & (dates < end)]
        if window.size and np.isfinite(window).any():
            values.append(float(np.nanmean(window)))
    return float(np.median(values)) if values else None


def hold_days(crop_id: str, cad_mm_m: float, et0_mid: float | None, depth_m: float | None = None) -> HoldDays:
    """Quantos dias sem chuva a lavoura passa na floração antes de começar a sofrer (RAW / ETc)."""
    crop = crop_water(crop_id)
    if crop.reserve_in_plant or et0_mid is None:
        return HoldDays(crop_id, None, 0.0, 0.0, 0.0, 0.0, False)
    zr = crop.zr_m if depth_m is None else min(crop.zr_m, depth_m)
    taw = cad_mm_m * zr
    raw = crop.p * taw
    etc = crop.kc[1] * et0_mid
    return HoldDays(crop_id, int(np.floor(raw / etc)), raw, taw, etc, zr,
                    depth_m is not None and depth_m < crop.zr_m)


# --- água no solo hoje ----------------------------------------------------------------------------

def bare_soil_depletion(precip: np.ndarray, et0: np.ndarray, taw: float, kc: float, p: float) -> np.ndarray:
    """Depleção Dr (mm) no fim de cada dia, solo nu, um reservatório (FAO-56).

    Dia sem dado (NaN) mantém a depleção do dia anterior. Começa com o solo cheio (Dr = 0).
    """
    raw = p * taw
    out = np.empty(precip.size, dtype=np.float64)
    dr = 0.0
    for i in range(precip.size):
        rain, ref = precip[i], et0[i]
        if np.isfinite(rain) and np.isfinite(ref):
            ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / (taw - raw))
            dr = min(taw, max(0.0, dr - rain + ks * kc * ref))
        out[i] = dr
    return out


@dataclass(frozen=True, slots=True)
class SoilWaterToday:
    day: date  # último dia com chuva e temperatura
    fraction: float  # água no solo / o que ele segura (0-1)
    normal_fraction: float | None  # mediana dos anos de referência na mesma data
    missing_mm: float  # chuva que falta para a camada da raiz ficar sem falta de água
    taw_mm: float
    raw_mm: float


def soil_water_today(
    dates: np.ndarray, precip: np.ndarray, et0: np.ndarray, cad_mm_m: float, crop_id: str,
    today: date, depth_m: float | None = None,
) -> SoilWaterToday | None:
    cfg = load_yaml_config("agua")["balanco"]
    crop = crop_water(crop_id)
    zr = crop.zr_m if not crop.reserve_in_plant else 0.3
    if depth_m is not None:
        zr = min(zr, depth_m)
    taw = cad_mm_m * zr
    dr = bare_soil_depletion(precip, et0, taw, float(cfg["kc_solo_nu"]), float(cfg["p_solo_nu"]))
    valid = np.isfinite(precip) & np.isfinite(et0) & (dates <= np.datetime64(today, "D"))
    if not valid.any():
        return None
    last = int(np.flatnonzero(valid)[-1])
    day = dates[last].astype(object)
    first, last_year = (int(y) for y in cfg["referencia"])
    same_day = [np.datetime64(date(y, day.month, min(day.day, 28 if day.month == 2 else day.day)), "D")
                for y in range(first, last_year + 1)]
    idx = np.searchsorted(dates, same_day)
    idx = idx[(idx < dates.size)]
    normal = float(np.median(1 - dr[idx] / taw)) if idx.size else None
    raw = (crop.p if not crop.reserve_in_plant else float(cfg["p_solo_nu"])) * taw
    return SoilWaterToday(day, float(1 - dr[last] / taw), normal, float(max(0.0, dr[last] - raw)), taw, raw)
