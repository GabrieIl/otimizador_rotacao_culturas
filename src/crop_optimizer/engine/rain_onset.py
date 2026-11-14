"""Início da estação chuvosa e atraso da chuva a partir da série diária real.

Critério agronômico (Sivakumar, 1988): a chuva "firma" no primeiro dia, após o início do ano
hidrológico, em que a soma de 3 dias atinge o limiar e não vem veranico longo nos dias
seguintes. Parâmetros em config/chuva.yaml.

Referência: mediana da data de início nos anos do período normal (1991-2020). Anos em que a
chuva nunca firmou entram como "depois de qualquer data" (censura), não são descartados.

Atraso da safra atual = data em que firmou (ou hoje, se ainda não firmou) - data de referência.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import numpy as np

from crop_optimizer.config import load_yaml_config

SeasonState = Literal["antes_da_epoca", "firmou", "firmando", "atrasada", "sem_referencia"]


@dataclass(frozen=True, slots=True)
class OnsetCriteria:
    rain_3d_mm: float = 20.0
    wet_day_mm: float = 1.0
    max_dry_spell_days: int = 7
    check_window_days: int = 30
    max_search_days: int = 240

    @classmethod
    def from_config(cls) -> OnsetCriteria:
        c = load_yaml_config("chuva")["inicio_chuva"]
        return cls(
            rain_3d_mm=float(c["chuva_minima_3_dias_mm"]),
            wet_day_mm=float(c["dia_chuvoso_mm"]),
            max_dry_spell_days=int(c["veranico_max_dias"]),
            check_window_days=int(c["janela_verificacao_dias"]),
            max_search_days=int(c["busca_max_dias"]),
        )


@dataclass(frozen=True, slots=True)
class OnsetDetection:
    onset: date | None
    provisional: bool = False  # chuva forte caiu, mas a janela anti-veranico ainda não fechou


def _longest_dry_run(values: np.ndarray, wet_day_mm: float) -> int:
    best = run = 0
    for v in values:
        # dia sem dado conta como seco (conservador)
        run = run + 1 if (np.isnan(v) or v < wet_day_mm) else 0
        best = max(best, run)
    return best


def _slice(dates: np.ndarray, precip: np.ndarray, start: date, end: date) -> np.ndarray:
    lo = int(np.searchsorted(dates, np.datetime64(start)))
    hi = int(np.searchsorted(dates, np.datetime64(end), side="right"))
    return precip[lo:hi]


def detect_onset(
    dates: np.ndarray,
    precip: np.ndarray,
    season_start: date,
    until: date,
    criteria: OnsetCriteria,
) -> OnsetDetection:
    """Primeiro dia em que a chuva firmou entre `season_start` e `until` (inclusive)."""
    horizon = season_start + timedelta(days=criteria.max_search_days + criteria.check_window_days + 2)
    seg = _slice(dates, precip, season_start, min(until, horizon))
    n = seg.size
    for i in range(min(criteria.max_search_days, n - 2)):
        day_rain = seg[i]
        if np.isnan(day_rain) or day_rain < criteria.wet_day_mm:
            continue
        if np.nansum(seg[i : i + 3]) < criteria.rain_3d_mm:
            continue
        after = seg[i + 3 : i + 3 + criteria.check_window_days]
        if _longest_dry_run(after, criteria.wet_day_mm) > criteria.max_dry_spell_days:
            continue
        provisional = after.size < criteria.check_window_days
        return OnsetDetection(season_start + timedelta(days=i), provisional)
    return OnsetDetection(None)


def hydro_year_start_month(dates: np.ndarray, precip: np.ndarray, first_year: int, last_year: int) -> int:
    """Mês seguinte ao mês mais seco da normal: é ali que começa a procura pela chuva."""
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    months = dates.astype("datetime64[M]").astype(int) % 12 + 1
    mask = (years >= first_year) & (years <= last_year)
    totals = [np.nansum(precip[mask & (months == m)]) for m in range(1, 13)]
    driest = int(np.argmin(totals)) + 1
    return driest % 12 + 1


@dataclass(slots=True)
class OnsetReference:
    """Distribuição histórica da data em que a chuva firmou (em dias após o início do ano hidrológico)."""

    hydro_start_month: int
    first_year: int
    last_year: int
    season_years: list[int]
    offsets: list[int | None]  # None = a chuva não firmou naquela safra
    median_offset: int | None
    p25_offset: int | None
    p75_offset: int | None

    @property
    def n_years(self) -> int:
        return len(self.offsets)

    @property
    def years_without_onset(self) -> int:
        return sum(o is None for o in self.offsets)

    def date_in(self, season_start: date, offset: int | None) -> date | None:
        return None if offset is None else season_start + timedelta(days=offset)


def _censored_quantile(offsets: list[int | None], q: float) -> int | None:
    arr = np.array([np.inf if o is None else o for o in offsets], dtype=np.float64)
    val = float(np.quantile(arr, q, method="inverted_cdf"))
    return None if np.isinf(val) else int(val)


def season_start_for(day: date, hydro_start_month: int) -> date:
    start = date(day.year, hydro_start_month, 1)
    return start if day >= start else date(day.year - 1, hydro_start_month, 1)


def season_label(season_start: date) -> str:
    if season_start.month >= 7:
        return f"{season_start.year}/{season_start.year + 1}"
    return str(season_start.year)


def build_reference(
    dates: np.ndarray,
    precip: np.ndarray,
    criteria: OnsetCriteria,
    first_year: int,
    last_year: int,
) -> OnsetReference:
    start_month = hydro_year_start_month(dates, precip, first_year, last_year)
    years = list(range(first_year, last_year + 1))
    offsets: list[int | None] = []
    for y in years:
        start = date(y, start_month, 1)
        end = date(y + 1, start_month, 1) - timedelta(days=1)
        det = detect_onset(dates, precip, start, end, criteria)
        offsets.append(None if det.onset is None else (det.onset - start).days)
    return OnsetReference(
        hydro_start_month=start_month,
        first_year=first_year,
        last_year=last_year,
        season_years=years,
        offsets=offsets,
        median_offset=_censored_quantile(offsets, 0.5),
        p25_offset=_censored_quantile(offsets, 0.25),
        p75_offset=_censored_quantile(offsets, 0.75),
    )


@dataclass(slots=True)
class RainSeasonStatus:
    """Situação da chuva na safra corrente, pronta para a interface e para o motor."""

    as_of: date
    data_until: date
    season_start: date
    season_label: str
    state: SeasonState
    onset_date: date | None
    reference_date: date | None
    reference_early: date | None  # P25: em 1 de cada 4 anos firmou antes disso
    reference_late: date | None  # P75; None = em mais de 1 de cada 4 anos não firmou
    delay_days: int  # >0 atrasada, <0 adiantada, 0 antes da época
    rain_season_mm: float
    still_came_of_10: int | None  # se atrasada: nos anos atrasados até aqui, em quantos de 10 ainda firmou
    reference: OnsetReference

    def motor_delay_days(self, max_days: int | None = None) -> int:
        limit = max_days if max_days is not None else int(load_yaml_config("chuva")["atraso_max_motor_dias"])
        return int(np.clip(self.delay_days, 0, limit))


def assess_season(
    dates: np.ndarray,
    precip: np.ndarray,
    as_of: date,
    reference: OnsetReference,
    criteria: OnsetCriteria,
) -> RainSeasonStatus:
    valid = np.flatnonzero(~np.isnan(precip) & (dates <= np.datetime64(as_of)))
    if valid.size == 0:
        raise ValueError("Sem dados de chuva até a data informada.")
    data_until: date = dates[valid[-1]].astype(object)

    start = season_start_for(as_of, reference.hydro_start_month)
    det = detect_onset(dates, precip, start, data_until, criteria)
    rain_mm = float(np.nansum(_slice(dates, precip, start, data_until)))
    ref_date = reference.date_in(start, reference.median_offset)
    common = dict(
        as_of=as_of,
        data_until=data_until,
        season_start=start,
        season_label=season_label(start),
        onset_date=det.onset,
        reference_date=ref_date,
        reference_early=reference.date_in(start, reference.p25_offset),
        reference_late=reference.date_in(start, reference.p75_offset),
        rain_season_mm=rain_mm,
        reference=reference,
    )

    if ref_date is None:
        return RainSeasonStatus(state="sem_referencia", delay_days=0, still_came_of_10=None, **common)

    if det.onset is not None:
        state: SeasonState = "firmando" if det.provisional else "firmou"
        return RainSeasonStatus(
            state=state, delay_days=(det.onset - ref_date).days, still_came_of_10=None, **common
        )

    if data_until <= ref_date:
        return RainSeasonStatus(state="antes_da_epoca", delay_days=0, still_came_of_10=None, **common)

    # Passou da data normal e não firmou: quantos anos parecidos ainda tiveram chuva depois?
    elapsed = (data_until - start).days
    late = [o for o in reference.offsets if o is None or o > elapsed]
    still = round(10 * sum(o is not None for o in late) / len(late)) if late else None
    return RainSeasonStatus(
        state="atrasada", delay_days=(data_until - ref_date).days, still_came_of_10=still, **common
    )


# --- veranico -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class VeranicoClimatology:
    """Veranicos da normal: a maior sequência de dias secos depois que a chuva firmou, por safra."""

    min_days: int
    window_days: int
    seasons_with_onset: int
    longest_spells: tuple[int, ...]  # maior sequência seca de cada safra com chuva firme

    @property
    def veranico_lengths(self) -> tuple[int, ...]:
        """Só as safras que tiveram veranico (sequência >= min_days)."""
        return tuple(s for s in self.longest_spells if s >= self.min_days)

    @property
    def probability(self) -> float:
        if not self.seasons_with_onset:
            return 0.0
        return len(self.veranico_lengths) / self.seasons_with_onset

    @property
    def of_10(self) -> int:
        return round(10 * self.probability)

    @property
    def typical_longest(self) -> int:
        """Mediana da maior sequência seca (todas as safras com chuva firme)."""
        return int(np.median(self.longest_spells)) if self.longest_spells else 0

    @classmethod
    def from_config(cls, reference: OnsetReference, dates: np.ndarray, precip: np.ndarray,
                    criteria: OnsetCriteria) -> VeranicoClimatology:
        cfg = load_yaml_config("chuva")["veranico"]
        return build_veranico_climatology(
            dates, precip, reference, criteria, int(cfg["dias_minimos"]), int(cfg["janela_apos_inicio_dias"])
        )


def build_veranico_climatology(
    dates: np.ndarray,
    precip: np.ndarray,
    reference: OnsetReference,
    criteria: OnsetCriteria,
    min_days: int,
    window_days: int,
) -> VeranicoClimatology:
    spells: list[int] = []
    for year, offset in zip(reference.season_years, reference.offsets, strict=True):
        if offset is None:
            continue  # sem chuva firme: é seca da safra inteira, já entra pela chuva total
        onset = date(year, reference.hydro_start_month, 1) + timedelta(days=offset)
        # conta a partir do fim dos 3 dias de chuva que firmaram a estação
        seg = _slice(dates, precip, onset + timedelta(days=3), onset + timedelta(days=window_days))
        spells.append(_longest_dry_run(seg, criteria.wet_day_mm))
    return VeranicoClimatology(min_days, window_days, len(spells), tuple(spells))


def current_dry_days(dates: np.ndarray, precip: np.ndarray, until: date, wet_day_mm: float) -> int:
    """Dias seguidos sem chuva terminando em `until` (inclusive)."""
    end = int(np.searchsorted(dates, np.datetime64(until), side="right"))
    count = 0
    for v in precip[:end][::-1]:
        if np.isnan(v) or v < wet_day_mm:
            count += 1
        else:
            break
    return count
