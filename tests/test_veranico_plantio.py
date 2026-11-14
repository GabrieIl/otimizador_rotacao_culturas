"""Testes: veranico calculado da chuva real, sorteio no Monte Carlo e textos por horizonte."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from crop_optimizer.accessibility.radio_tempo import compose_radio_script
from crop_optimizer.accessibility.whatsapp import build_whatsapp_summary_message
from crop_optimizer.analytics.views import loss_risk_label
from crop_optimizer.domain.models import SimulationConfig, TrafficLightLevel
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, crop_map, location_map
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.engine.rain_onset import (
    OnsetCriteria,
    OnsetReference,
    build_veranico_climatology,
    current_dry_days,
)
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats

CRIT = OnsetCriteria()


def _series(start: date, days: int):
    dates = np.arange(np.datetime64(start, "D"), np.datetime64(start, "D") + np.timedelta64(days, "D"),
                      dtype="datetime64[D]")
    return dates, np.zeros(days)


def _rain_every(precip, dates, start: date, end: date, step: int = 3) -> None:
    i0 = int(np.searchsorted(dates, np.datetime64(start)))
    i1 = int(np.searchsorted(dates, np.datetime64(end)))
    precip[i0:i1:step] = 10.0


def test_veranico_climatology_counts_dry_spell_after_onset() -> None:
    dates, precip = _series(date(2000, 9, 1), 3 * 365)
    # safra 2000: chuva a cada 3 dias de 01/01/2001 a 31/03, com 15 dias secos de 01/02 a 15/02
    _rain_every(precip, dates, date(2001, 1, 1), date(2001, 4, 1))
    i = int(np.searchsorted(dates, np.datetime64("2001-02-01")))
    precip[i : i + 15] = 0.0
    # safra 2001: chuva regular, sem veranico
    _rain_every(precip, dates, date(2002, 1, 1), date(2002, 4, 1))
    ref = OnsetReference(9, 2000, 2002, [2000, 2001, 2002], [122, 122, None], 122, 122, None)
    clim = build_veranico_climatology(dates, precip, ref, CRIT, min_days=10, window_days=90)
    assert clim.seasons_with_onset == 2  # safra sem chuva firme fica fora
    assert clim.longest_spells[0] >= 15 and clim.longest_spells[1] <= 3  # chuva a cada 3 dias
    assert clim.veranico_lengths == (clim.longest_spells[0],)
    assert clim.probability == pytest.approx(0.5) and clim.of_10 == 5


def test_current_dry_days() -> None:
    dates, precip = _series(date(2026, 1, 1), 30)
    precip[10] = 5.0
    assert current_dry_days(dates, precip, date(2026, 1, 20), CRIT.wet_day_mm) == 9
    assert current_dry_days(dates, precip, date(2026, 1, 11), CRIT.wet_day_mm) == 0
    precip[-1] = np.nan  # dia sem dado conta como seco
    assert current_dry_days(dates, precip, date(2026, 1, 30), CRIT.wet_day_mm) == 19


def _stats(**kw) -> SeasonalClimateStats:
    base = SeasonalClimateStats("x", 450, 140, 180, 80, 0.4, 0.0, 0.4, 0.3, 0.0)
    return replace(base, **kw)


def test_monte_carlo_uses_observed_veranico_lengths() -> None:
    engine = MonteCarloRotationEngine(crops_catalog=crop_map())
    so_milho = [s for s in DEFAULT_STRATEGIES if s.strategy_id == "so_milho_tradicional"]
    cfg = SimulationConfig(n_scenarios=2000)
    short = engine.simulate_portfolio(so_milho, _stats(veranico_prob=1.0, veranico_lengths=(5,)), cfg)[0]
    long = engine.simulate_portfolio(so_milho, _stats(veranico_prob=1.0, veranico_lengths=(30,)), cfg)[0]
    assert long.expected_food_kg_ha_year < short.expected_food_kg_ha_year


@pytest.mark.parametrize("horizon", [1, 2, 3, 5])
def test_all_horizons_run(horizon: int) -> None:
    engine = MonteCarloRotationEngine(crops_catalog=crop_map())
    res = engine.simulate_portfolio(DEFAULT_STRATEGIES, _stats(), SimulationConfig(n_scenarios=500, horizon_years=horizon))
    assert len(res) == len(DEFAULT_STRATEGIES)
    assert all(0 <= r.survival_score_of_10 <= 10 for r in res)


def test_texts_without_name_and_by_horizon() -> None:
    engine = MonteCarloRotationEngine(crops_catalog=crop_map())
    res = engine.simulate_portfolio(DEFAULT_STRATEGIES, _stats(), SimulationConfig(n_scenarios=300, horizon_years=1))
    loc = location_map()["petrolina_pe"]
    radio = compose_radio_script("", loc, 0, TrafficLightLevel.VERMELHO, res[0], res[1], horizon_years=1)
    assert radio.startswith("Alô, agricultora e agricultor!")
    assert "próximo ano" in radio and "atrasou 0 dias" not in radio and "dois anos seguidos" not in radio
    radio5 = compose_radio_script("Dona Maria", loc, 12, TrafficLightLevel.AMARELO, res[0], res[1], horizon_years=5)
    assert radio5.startswith("Alô, Dona Maria!") and "próximos 5 anos" in radio5 and "12 dias de atraso" in radio5
    wa = build_whatsapp_summary_message("", loc, 0, TrafficLightLevel.VERDE, res[0], res[1])
    assert "Olá!" in wa and "Seu João" not in wa
    assert loss_risk_label(1) == "risco de perder a safra no ano"
    assert loss_risk_label(3) == "risco de 2 anos seguidos de perda"
    assert SimulationConfig().farmer_name == ""
