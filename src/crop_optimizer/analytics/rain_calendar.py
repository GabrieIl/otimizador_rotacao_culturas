"""Chuva do ano até hoje x média, e os dados do calendário de chuva.

Calendário: cada dia traz
- a chance histórica de chover naquele dia (marca d'água): fração dos anos de 1991-2020 com chuva
  >= 1 mm, numa janela de 15 dias em volta da data (suaviza o ruído de um dia só);
- a chuva que de fato caiu (NASA POWER), ou "sem dado" / "futuro";
- marcas: dia em que a chuva firmou, data normal de início, dias de veranico e hoje.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from crop_optimizer.ingestion.rain_history import RainSeries

MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _years(series: RainSeries) -> np.ndarray:
    return series.dates.astype("datetime64[Y]").astype(int) + 1970


def _sum_between(series: RainSeries, start: date, end: date) -> float:
    lo = int(np.searchsorted(series.dates, np.datetime64(start)))
    hi = int(np.searchsorted(series.dates, np.datetime64(end), side="right"))
    return float(np.nansum(series.precip_mm[lo:hi]))


@dataclass(frozen=True, slots=True)
class YearToDate:
    year: int
    until: date
    total_mm: float  # chuva de 1º/jan até `until`
    normal_mm: float  # média 1991-2020 do mesmo período (1º/jan até o mesmo dia)
    normal_annual_mm: float

    @property
    def diff_pct(self) -> float:
        return 0.0 if self.normal_mm <= 0 else 100.0 * (self.total_mm - self.normal_mm) / self.normal_mm


def year_to_date(series: RainSeries, today: date, first_year: int = 1991, last_year: int = 2020) -> YearToDate:
    last = series.last_valid_date or today
    until = min(today, last)
    start = date(until.year, 1, 1)
    offset = (until - start).days
    totals = [_sum_between(series, date(y, 1, 1), date(y, 1, 1) + timedelta(days=offset))
              for y in range(first_year, last_year + 1)]
    years = _years(series)
    mask = (years >= first_year) & (years <= last_year)
    annual = float(np.nansum(series.precip_mm[mask])) / (last_year - first_year + 1)
    return YearToDate(until.year, until, _sum_between(series, start, until), float(np.mean(totals)), annual)


def rain_chance_by_day(
    series: RainSeries, first_year: int = 1991, last_year: int = 2020, wet_mm: float = 1.0, half_window: int = 7
) -> np.ndarray:
    """Chance (0-1) de chover em cada dia do ano (índice 0 = 1º/jan; 366 posições)."""
    years = _years(series)
    mask = (years >= first_year) & (years <= last_year)
    doy = (series.dates - series.dates.astype("datetime64[Y]")).astype(int)  # 0..365
    wet = (series.precip_mm >= wet_mm) & ~np.isnan(series.precip_mm)
    hits = np.bincount(doy[mask], weights=wet[mask].astype(float), minlength=366)
    count = np.bincount(doy[mask], minlength=366).astype(float)
    kernel = np.ones(2 * half_window + 1)
    wrap = lambda a: np.concatenate([a[-half_window:], a, a[:half_window]])  # noqa: E731
    smooth_hits = np.convolve(wrap(hits), kernel, mode="valid")
    smooth_count = np.convolve(wrap(count), kernel, mode="valid")
    return np.divide(smooth_hits, smooth_count, out=np.zeros(366), where=smooth_count > 0)


def dry_spells(series: RainSeries, start: date, end: date, min_days: int, wet_mm: float = 1.0) -> list[tuple[date, date]]:
    """Sequências de >= min_days dias sem chuva entre start e end (inclusive)."""
    lo = int(np.searchsorted(series.dates, np.datetime64(start)))
    hi = int(np.searchsorted(series.dates, np.datetime64(end), side="right"))
    out: list[tuple[date, date]] = []
    run_start = None
    for i in range(lo, hi):
        v = series.precip_mm[i]
        dry = np.isnan(v) or v < wet_mm
        if dry and run_start is None:
            run_start = i
        if not dry and run_start is not None:
            if i - run_start >= min_days:
                out.append((series.dates[run_start].astype(object), series.dates[i - 1].astype(object)))
            run_start = None
    if run_start is not None and hi - run_start >= min_days:
        out.append((series.dates[run_start].astype(object), series.dates[hi - 1].astype(object)))
    return out


def calendar_months(
    series: RainSeries,
    start: date,
    n_months: int,
    today: date,
    chance: np.ndarray,
    *,
    onset: date | None = None,
    normal_onset: date | None = None,
    veranicos: list[tuple[date, date]] | None = None,
    wet_mm: float = 1.0,
) -> list[dict]:
    """Meses para o componente de calendário (semana começando no domingo)."""
    last = series.last_valid_date
    veranico_days: set[date] = set()
    for a, b in veranicos or []:
        d = a
        while d <= b:
            veranico_days.add(d)
            d += timedelta(days=1)
    months: list[dict] = []
    y, m = start.year, start.month
    for _ in range(n_months):
        n_days = calendar.monthrange(y, m)[1]
        first_weekday = (date(y, m, 1).weekday() + 1) % 7  # domingo = 0
        days = []
        for d in range(1, n_days + 1):
            day = date(y, m, d)
            idx = int(np.searchsorted(series.dates, np.datetime64(day)))
            mm = None
            if idx < series.dates.size and series.dates[idx] == np.datetime64(day):
                v = series.precip_mm[idx]
                mm = None if np.isnan(v) else round(float(v), 1)
            if day > today:
                state = "futuro"
            elif mm is None or (last is not None and day > last):
                state = "sem_dado"
            else:
                state = "chuva" if mm >= wet_mm else "seco"
            marks = []
            if onset == day:
                marks.append("inicio")
            if normal_onset == day:
                marks.append("normal")
            if day in veranico_days:
                marks.append("veranico")
            if day == today:
                marks.append("hoje")
            doy = (day - date(y, 1, 1)).days
            days.append({"d": d, "p": round(float(chance[min(doy, 365)]), 3), "mm": mm, "s": state, "m": marks})
        months.append({"titulo": f"{MONTHS_SHORT[m - 1]} {y}", "offset": first_weekday, "dias": days})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months
