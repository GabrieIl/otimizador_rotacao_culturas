"""Uma frase sobre a roça para cada lente da página Satélite, com o lugar do app onde o número é usado.

- Chuva: o ano até hoje comparado com os 25 anteriores (NASA POWER, a mesma chuva do motor).
- Água no solo: SMAP L4 (camada da raiz) hoje x a mediana da mesma data desde 2015.
- Verde: NDVI MODIS da última composição x a mediana da mesma época desde 2001, e os meses em que a
  vegetação fica seca nos últimos anos.
- Calor: em quantos de cada 10 anos o chão passa do limite na floração da cultura de referência.
- Relevo: classe de declividade (Embrapa) e o risco de enxurrada.

Os valores das camadas do GIBS vêm de `ingestion.gibs_values` (cor do pixel -> faixa do colormap).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from crop_optimizer.analytics.agua import crop_water
from crop_optimizer.analytics.rain_delay import fmt_date
from crop_optimizer.config import load_yaml_config
from crop_optimizer.engine.rain_onset import OnsetReference
from crop_optimizer.ingestion.gibs import GibsLayer, snap_date
from crop_optimizer.ingestion.gibs_values import values_at
from crop_optimizer.ingestion.rain_history import RainSeries

MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTHS_FULL = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
               "outubro", "novembro", "dezembro"]


def _n(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


@dataclass(frozen=True, slots=True)
class LensInsight:
    text: str  # a frase sobre a roça
    detail: str  # de onde vem e como foi calculada
    page: str  # página onde o número é usado ("plantio", "inicio")
    used_in: str  # rótulo do link
    numbers: dict = field(default_factory=dict)


def _cfg() -> dict:
    return load_yaml_config("agua")["lentes"]


def _pct(value: float, normal: float) -> int:
    return round((value / normal - 1) * 100) if normal else 0


# --- chuva --------------------------------------------------------------------------------------

def rain_insight(series: RainSeries, today: date) -> LensInsight | None:
    n_years = int(_cfg()["chuva"]["anos_comparacao"])
    valid = np.flatnonzero(np.isfinite(series.precip_mm) & (series.dates <= np.datetime64(today, "D")))
    if valid.size == 0:
        return None
    until = series.dates[valid[-1]].astype(object)
    if until.year != today.year:
        return None
    day_of_year = (until - date(until.year, 1, 1)).days

    def total(year: int) -> float:
        start = np.datetime64(date(year, 1, 1), "D")
        mask = (series.dates >= start) & (series.dates <= start + np.timedelta64(day_of_year, "D"))
        return float(np.nansum(series.precip_mm[mask]))

    past = {y: total(y) for y in range(until.year - n_years, until.year)}
    now = total(until.year)
    drier = sum(v < now for v in past.values())  # anos anteriores mais secos que este
    rank_dry = drier + 1
    median = float(np.median(list(past.values())))
    if rank_dry <= 5:
        head = (f"Este ano está entre os 5 mais secos dos últimos {n_years + 1}: "
                f"é o {rank_dry}º mais seco.")
    elif rank_dry >= n_years - 3:
        head = f"Este ano está entre os 5 mais chuvosos dos últimos {n_years + 1}."
    else:
        head = f"Este ano está perto do normal: o {rank_dry}º mais seco dos últimos {n_years + 1}."
    text = (f"{head} Choveu {now:.0f} mm de 1º/jan até {fmt_date(until)}; a mediana dos {n_years} anos "
            f"anteriores no mesmo período é {median:.0f} mm.")
    return LensInsight(
        text, f"Chuva do NASA POWER no ponto, a mesma que o motor usa ({until.year - n_years}-{until.year}).",
        "plantio", "Usado no Plantio: a chuva desta safra e o aviso de cada cultura",
        {"rank_dry": rank_dry, "total_mm": now, "median_mm": median},
    )


# --- água no solo (SMAP) --------------------------------------------------------------------------

def soil_moisture_insight(layer: GibsLayer, colormap: str, lat: float, lon: float, pixel_km: float,
                          today: date) -> LensInsight | None:
    latest = snap_date(layer, today)
    if latest is None or layer.first_date is None:
        return None
    day = latest.start
    years = range(layer.first_date.year, day.year)
    same = [s.start for y in years if (s := snap_date(layer, date(y, day.month, min(day.day, 28)))) is not None
            and s.start.year == y]
    vals = values_at(layer.identifier, colormap, [day, *same], lat, lon, pixel_km, today=today)
    now = vals.get(day)
    past = [v for d, v in vals.items() if d != day and v is not None]
    if now is None or len(past) < 3:
        return None
    normal = float(np.median(past))
    diff = _pct(now, normal)
    if diff <= -10:
        state = f"mais seca que o normal desta data ({abs(diff)}% abaixo)"
    elif diff >= 10:
        state = f"mais úmida que o normal desta data ({diff}% acima)"
    else:
        state = "perto do normal desta data"
    text = (f"A terra da região está {state}: {_n(now)} m³ de água por m³ de terra na camada da raiz "
            f"em {fmt_date(day)}, contra {_n(normal)} na mediana de {len(past)} anos.")
    return LensInsight(
        text, f"SMAP L4, umidade da camada da raiz (até 1 m), pixel de ~9 km, {layer.first_date.year} em diante.",
        "plantio", "No Plantio, a água no solo de hoje entra no aviso de cada cultura (balanço com a chuva do POWER)",
        {"now": now, "normal": normal, "diff_pct": diff},
    )


# --- verde (NDVI) ---------------------------------------------------------------------------------

def green_insight(layer: GibsLayer, colormap: str, lat: float, lon: float, pixel_km: float,
                  today: date) -> LensInsight | None:
    cfg = _cfg()["verde"]
    latest = snap_date(layer, today)
    if latest is None or layer.first_date is None:
        return None
    comp = latest.start
    first = max(layer.first_date.year + 1, 2001)
    same = [s.start for y in range(first, comp.year)
            if (s := snap_date(layer, date(y, comp.month, comp.day))) is not None]
    n_clim = int(cfg["anos_climatologia"])
    clim_days: list[date] = []
    for y in range(comp.year - n_clim, comp.year):
        d = date(y, 1, 1)
        while d.year == y:
            s = snap_date(layer, d)
            if s is not None and s.start not in clim_days:
                clim_days.append(s.start)
            d += timedelta(days=16)
    vals = values_at(layer.identifier, colormap, list(dict.fromkeys([comp, *same, *clim_days])),
                     lat, lon, pixel_km, today=today)
    now = vals.get(comp)
    past = [vals[d] for d in same if vals.get(d) is not None]
    if now is None or len(past) < 5:
        return None
    normal = float(np.median(past))
    diff = _pct(now, normal)
    month = MONTHS_FULL[comp.month - 1]
    if abs(diff) < 10:
        head = f"O verde da região está perto do normal para {month}"
    else:
        head = f"O verde da região está {abs(diff)}% {'abaixo' if diff < 0 else 'acima'} do normal para {month}"
    by_month: dict[int, float] = {}
    for m in range(1, 13):
        month_vals = [vals[d] for d in clim_days if d.month == m and vals.get(d) is not None]
        if month_vals:
            by_month[m] = float(np.median(month_vals))
    limit = float(cfg["ndvi_vegetacao_seca"])
    dry = sorted(sorted(by_month, key=by_month.get)[:3])  # os 3 meses de verde mais baixo
    if by_month and max(by_month.values()) < limit:
        dry_txt = (f" Nos últimos {n_clim} anos, o verde do ponto ficou baixo o ano todo (NDVI abaixo de "
                   f"{_n(limit)}): pode ser cidade, solo à mostra ou caatinga rala. O mais seco é em "
                   f"{_month_list(dry)}.")
    elif dry:
        below = [m for m in dry if by_month[m] < limit]
        dry_txt = (f" Nos últimos {n_clim} anos, a vegetação fica mais seca em {_month_list(dry)}"
                   + (f" (NDVI abaixo de {_n(limit)}, solo quase descoberto)." if below else "."))
    else:
        dry_txt = ""
    text = f"{head} (NDVI {_n(now)}, mediana {_n(normal)} desde {first}).{dry_txt}"
    return LensInsight(
        text, f"MODIS Terra NDVI de 16 dias, pixel de 250 m no ponto da roça (composição de {fmt_date(comp)}).",
        "plantio", "Ainda não entra na conta do Plantio: serve para conferir a seca na região",
        {"now": now, "normal": normal, "diff_pct": diff, "dry_months": dry},
    )


def _month_list(months: list[int]) -> str:
    names = [MONTHS[m - 1] for m in months]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]


# --- calor (LST) ---------------------------------------------------------------------------------

def heat_insight(layer: GibsLayer, colormap: str, lat: float, lon: float, pixel_km: float, today: date,
                 ref: OnsetReference, crop_name: str) -> LensInsight | None:
    cfg = _cfg()["calor"]
    crop = crop_water(cfg["cultura_referencia"])
    if ref.median_offset is None or layer.first_date is None or crop.reserve_in_plant:
        return None
    limit_c = float(cfg["limite_c"])
    windows: dict[int, list[date]] = {}
    last = snap_date(layer, today)
    for y in range(max(layer.first_date.year, 2000), today.year):
        onset = date(y, ref.hydro_start_month, 1) + timedelta(days=ref.median_offset)
        start = onset + timedelta(days=crop.critical_start)
        end = start + timedelta(days=crop.critical_length)
        if last is not None and end > last.end:
            continue
        days, d = [], start
        while d <= end:
            s = snap_date(layer, d)
            if s is not None and s.start not in days:
                days.append(s.start)
            d += timedelta(days=8)
        if days:
            windows[y] = days
    flat = [d for ds in windows.values() for d in ds]
    if not flat:
        return None
    vals = values_at(layer.identifier, colormap, flat, lat, lon, pixel_km, today=today)
    hot, seen = 0, 0
    for ds in windows.values():
        temps = [vals[d] - 273.15 for d in ds if vals.get(d) is not None]
        if not temps:
            continue
        seen += 1
        hot += max(temps) > limit_c
    if seen < 5:
        return None
    of10 = round(10 * hot / seen)
    any_window = next(iter(windows.values()))
    period = f"{fmt_date(any_window[0])} a {fmt_date(any_window[-1] + timedelta(days=7))}"
    text = (f"Em {of10} de cada 10 anos, o chão passa de {limit_c:.0f} °C na época da floração do "
            f"{crop_name.lower()} (por volta de {period}, plantando quando a chuva costuma firmar).")
    return LensInsight(
        text, f"MODIS Terra, temperatura da superfície de dia (média de 8 dias), pixel de 1 km; {seen} anos.",
        "plantio", "Ainda não entra no motor: é um alerta a mais para a floração, no aviso da cultura",
        {"of10": of10, "years": seen},
    )


# --- relevo -------------------------------------------------------------------------------------

def relief_insight(slope_pct: float) -> LensInsight:
    classes = load_yaml_config("aptidao")["relevo_classes"]
    risk = load_yaml_config("lentes")["insights"]["enxurrada"]
    cls = next(c for c in classes if slope_pct <= c["max"])
    text = (f"O ponto da roça tem {slope_pct:.0f}% de declividade: relevo {cls['nome']}. "
            f"{risk[cls['nome']]}")
    return LensInsight(
        text, "Declividade calculada do relevo SRTM (Terrain Tiles), pixel de ~30 m; classes da Embrapa.",
        "inicio", "Usado na Início: o fator erosão do solo por cultura",
        {"slope_pct": slope_pct, "classe": cls["nome"]},
    )
