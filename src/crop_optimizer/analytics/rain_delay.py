"""Atraso da chuva calculado (satélite x referência histórica) e janelas oficiais do ZARC.

Junta as três peças da Feature 1 para a interface:
1. chuva diária real (NASA POWER, cache na bronze);
2. referência: data mediana em que a chuva firmou em 1991-2020, no mesmo pixel;
3. janela oficial de plantio do ZARC por cultura, para dizer se ainda dá tempo.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from crop_optimizer.config import Settings, load_yaml_config
from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import location_map
from crop_optimizer.engine.rain_onset import (
    OnsetCriteria,
    RainSeasonStatus,
    VeranicoClimatology,
    assess_season,
    build_reference,
    current_dry_days,
)
from crop_optimizer.ingestion.rain_history import fetch_rain_series
from crop_optimizer.ingestion.zarc_tabua import (
    ZarcDataUnavailable,
    ZarcWindow,
    load_zarc_table,
    zarc_windows_for,
)

_MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
WindowState = Literal["sem_indicacao", "ainda_nao_abriu", "aberta", "fechou"]


def fmt_date(d: date | None) -> str:
    return "—" if d is None else f"{d.day:02d}/{_MONTHS_PT[d.month - 1]}"


@dataclass(slots=True)
class CropWindowStatus:
    crop_id: str
    window: ZarcWindow | None
    state: WindowState
    opens: date | None = None
    closes: date | None = None
    days_left: int | None = None

    @property
    def phrase(self) -> str:
        if self.window is None:
            return "Sem indicação oficial de plantio de sequeiro neste município (risco acima de 40% ou não zoneado)."
        risk = f"risco a partir de {self.window.best_risk_pct}%, depende do solo e do ciclo"
        if self.state == "ainda_nao_abriu":
            return f"Janela abre em {fmt_date(self.opens)} e fecha em {fmt_date(self.closes)} ({risk})."
        if self.state == "aberta":
            return f"Janela aberta até {fmt_date(self.closes)}: faltam {self.days_left} dias ({risk})."
        return f"Janela fechou em {fmt_date(self.closes)}."


@dataclass(slots=True)
class RainDelayReport:
    location: LocationSpec
    status: RainSeasonStatus
    source: str
    crop_windows: list[CropWindowStatus] = field(default_factory=list)
    zarc_safra: str | None = None
    zarc_error: str | None = None
    veranico: VeranicoClimatology | None = None
    dry_days_now: int = 0  # dias seguidos sem chuva até o último dado

    @property
    def veranico_alert(self) -> str | None:
        """Aviso de veranico na safra em curso (só depois que a chuva firmou)."""
        if self.veranico is None or self.status.state not in ("firmou", "firmando"):
            return None
        warn = int(load_yaml_config("chuva")["veranico"]["aviso_dias_secos"])
        if self.dry_days_now < warn:
            return None
        if self.dry_days_now >= self.veranico.min_days:
            return f"Veranico em curso: {self.dry_days_now} dias seguidos sem chuva."
        return f"Atenção: {self.dry_days_now} dias seguidos sem chuva."

    @property
    def motor_delay_days(self) -> int:
        return self.status.motor_delay_days()


def _dec_start(year: int, dec: int) -> date:
    return date(year, (dec - 1) // 3 + 1, (1, 11, 21)[(dec - 1) % 3])


def _dec_end(year: int, dec: int) -> date:
    month, part = (dec - 1) // 3 + 1, (dec - 1) % 3
    day = (10, 20, calendar.monthrange(year, month)[1])[part]
    return date(year, month, day)


def _window_dates(window: ZarcWindow, season_start: date) -> tuple[date, date]:
    """Datas concretas da janela dentro da safra que começa em `season_start`."""
    opens = _dec_start(season_start.year, window.start_dec)
    if opens < season_start:
        opens = _dec_start(season_start.year + 1, window.start_dec)
    closes = _dec_end(opens.year, window.end_dec)
    if closes < opens:
        closes = _dec_end(opens.year + 1, window.end_dec)
    return opens, closes


def crop_window_status(window: ZarcWindow | None, crop_id: str, season_start: date, today: date) -> CropWindowStatus:
    if window is None:
        return CropWindowStatus(crop_id, None, "sem_indicacao")
    opens, closes = _window_dates(window, season_start)
    if today < opens:
        state: WindowState = "ainda_nao_abriu"
    elif today <= closes:
        state = "aberta"
    else:
        state = "fechou"
    days_left = (closes - today).days if state == "aberta" else None
    return CropWindowStatus(crop_id, window, state, opens, closes, days_left)


def build_rain_delay_report(
    location: LocationSpec, as_of: date, settings: Settings | None = None
) -> RainDelayReport:
    """Calcula a situação da chuva em `as_of`. Levanta RainDataUnavailable se não houver chuva real."""
    cfg = load_yaml_config("chuva")["referencia"]
    criteria = OnsetCriteria.from_config()
    # sempre baixa até hoje (cache diário) e corta em `as_of`: trocar a data na tela não gera download
    series = fetch_rain_series(location, today=date.today(), settings=settings)
    reference = build_reference(
        series.dates, series.precip_mm, criteria, int(cfg["ano_inicio"]), int(cfg["ano_fim"])
    )
    status = assess_season(series.dates, series.precip_mm, as_of, reference, criteria)
    report = RainDelayReport(
        location=location,
        status=status,
        source=series.source,
        veranico=VeranicoClimatology.from_config(reference, series.dates, series.precip_mm, criteria),
        dry_days_now=current_dry_days(series.dates, series.precip_mm, status.data_until, criteria.wet_day_mm),
    )

    ibge = location.ibge_code or getattr(location_map().get(location.location_id), "ibge_code", None)
    if ibge is None:
        report.zarc_error = f"Município {location.name} sem código IBGE: não dá para cruzar com o ZARC."
        return report
    try:
        table = load_zarc_table([ibge], settings)
    except ZarcDataUnavailable as exc:
        report.zarc_error = str(exc)
        return report
    report.zarc_safra = load_yaml_config("zarc")["safra"]
    report.crop_windows = [
        crop_window_status(w, crop_id, status.season_start, status.data_until)
        for crop_id, w in zarc_windows_for(table, ibge).items()
    ]
    return report


def describe_status(status: RainSeasonStatus) -> tuple[str, str, Literal["info", "success", "warning", "error"]]:
    """(título, explicação, nível visual) em linguagem simples."""
    ref = fmt_date(status.reference_date)
    if status.reference_late is None:
        faixa = f"em ano normal firma por volta de {ref}, mas em mais de 1 de cada 4 anos ela nem firma"
    else:
        faixa = (
            f"em ano normal firma por volta de {ref} "
            f"(metade dos anos entre {fmt_date(status.reference_early)} e {fmt_date(status.reference_late)})"
        )
    chuva = f"{status.rain_season_mm:.0f} mm de chuva desde {fmt_date(status.season_start)}"

    if status.state == "sem_referencia":
        return (
            "Sem referência para esta região",
            "Na maioria dos anos de 1991 a 2020 a chuva não chegou a firmar aqui, "
            "então não dá para falar em atraso.",
            "warning",
        )
    if status.state == "antes_da_epoca":
        return ("Ainda não é tempo de chuva", f"A chuva {faixa}. Até agora: {chuva}.", "info")
    if status.state == "atrasada":
        extra = (
            f" Nos anos em que atrasou assim, ela ainda firmou em {status.still_came_of_10} de cada 10."
            if status.still_came_of_10 is not None
            else ""
        )
        return (
            f"A chuva está atrasada {status.delay_days} dias",
            f"A chuva {faixa}. Até agora: {chuva}.{extra}",
            "error" if status.delay_days > 30 else "warning",
        )

    onset = fmt_date(status.onset_date)
    if status.delay_days > 0:
        quando = f"{status.delay_days} dias depois do normal ({ref})"
    elif status.delay_days < 0:
        quando = f"{-status.delay_days} dias antes do normal ({ref})"
    else:
        quando = f"na data normal ({ref})"
    if status.state == "firmando":
        return (
            f"Caiu chuva boa em {onset}, {quando}",
            f"Ainda falta confirmar que não vem veranico nos próximos dias. {chuva.capitalize()}.",
            "warning",
        )
    level = "success" if status.delay_days <= 15 else "warning"
    return (f"A chuva firmou em {onset}, {quando}", f"{chuva.capitalize()}.", level)
