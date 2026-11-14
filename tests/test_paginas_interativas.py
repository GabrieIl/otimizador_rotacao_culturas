"""Testes da reformulação das páginas: chuva do ano, calendário, textura, veredito, ranking, região."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from crop_optimizer.analytics.crop_advice import crop_verdict
from crop_optimizer.analytics.rain_calendar import (
    calendar_months,
    dry_spells,
    rain_chance_by_day,
    year_to_date,
)
from crop_optimizer.analytics.rain_delay import CropWindowStatus
from crop_optimizer.analytics.soil_texture import texture_class
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import BalancePriority, SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, crop_map
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.engine.pareto import rank_by_balance_priority, select_by_balance_priority
from crop_optimizer.engine.rain_onset import OnsetReference, RainSeasonStatus
from crop_optimizer.ingestion import soilgrids_wcs
from crop_optimizer.ingestion.rain_history import RainSeries
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _series(start: str, end: str, rain_every: int | None = None, mm: float = 5.0) -> RainSeries:
    dates = np.arange(np.datetime64(start), np.datetime64(end) + np.timedelta64(1, "D"), dtype="datetime64[D]")
    precip = np.zeros(dates.size)
    if rain_every:
        precip[::rain_every] = mm
    return RainSeries("x", dates, precip, "teste")


# --- chuva do ano e calendário --------------------------------------------------------

def test_year_to_date_compares_same_period() -> None:
    s = _series("1991-01-01", "2026-03-31", rain_every=10, mm=10.0)
    s.precip_mm[s.dates >= np.datetime64("2026-01-01")] = 0.0  # 2026 seco
    ytd = year_to_date(s, date(2026, 3, 31))
    assert ytd.total_mm == 0.0 and ytd.normal_mm > 0
    assert ytd.diff_pct == pytest.approx(-100.0)
    assert ytd.until == date(2026, 3, 31)


def test_rain_chance_is_a_probability_per_day() -> None:
    s = _series("1991-01-01", "2020-12-31", rain_every=2)
    chance = rain_chance_by_day(s)
    assert chance.shape == (366,)
    assert np.all((chance >= 0) & (chance <= 1))
    assert chance.mean() == pytest.approx(0.5, abs=0.05)


def test_dry_spells_and_calendar_marks() -> None:
    s = _series("2026-01-01", "2026-03-31")
    s.precip_mm[:5] = 10.0  # chove 1 a 5/jan, depois seca
    s.precip_mm[30] = 10.0  # chove 31/jan
    spells = dry_spells(s, date(2026, 1, 1), date(2026, 1, 31), min_days=10)
    assert spells == [(date(2026, 1, 6), date(2026, 1, 30))]
    months = calendar_months(s, date(2026, 1, 1), 2, date(2026, 1, 20), np.full(366, 0.3),
                             onset=date(2026, 1, 1), normal_onset=date(2026, 1, 10), veranicos=spells)
    jan = months[0]
    assert jan["titulo"] == "jan 2026" and jan["offset"] == 4  # 1º/jan/2026 é quinta (domingo = 0)
    d1, d10, d20, d25 = (jan["dias"][i] for i in (0, 9, 19, 24))
    assert d1["s"] == "chuva" and "inicio" in d1["m"]
    assert "normal" in d10["m"] and "veranico" in d10["m"]
    assert "hoje" in d20["m"] and d25["s"] == "futuro"


# --- textura -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("sand", "clay", "expected"),
    [
        (90, 5, "areia"),
        (80, 8, "areia franca"),
        (65, 12, "franco-arenosa"),
        (40, 20, "franca"),
        (58, 22, "franco-argiloarenosa"),
        (30, 33, "franco-argilosa"),
        (50, 40, "argiloarenosa"),
        (20, 50, "argila"),
        (10, 70, "muito argilosa"),
    ],
)
def test_texture_triangle(sand: float, clay: float, expected: str) -> None:
    assert texture_class(sand, clay) == expected


# --- veredito por cultura -----------------------------------------------------------------

def _status(state: str, delay: int = 0) -> RainSeasonStatus:
    ref = OnsetReference(9, 1991, 2020, [1991], [120], 120, 100, 140)
    return RainSeasonStatus(date(2026, 1, 1), date(2026, 1, 1), date(2025, 9, 1), "2025/2026", state,
                            date(2025, 12, 1) if state in ("firmou", "firmando") else None,
                            date(2025, 12, 30), None, None, delay, 100.0, None, ref)


def _window(state: str) -> CropWindowStatus:
    return CropWindowStatus("milho_sertanejo", object(), state, date(2026, 1, 21), date(2026, 3, 10), 30)


def test_verdict_rules_in_order() -> None:
    assert crop_verdict("milho_sertanejo", 10, _status("firmou"), CropWindowStatus("milho_sertanejo", None, "sem_indicacao"), 0).word == "Não plante"
    assert crop_verdict("milho_sertanejo", 10, _status("antes_da_epoca"), _window("aberta"), 0).level == "espera"
    assert crop_verdict("milho_sertanejo", 10, _status("firmou"), _window("ainda_nao_abriu"), 0).word == "Espere a janela abrir"
    assert crop_verdict("milho_sertanejo", 10, _status("firmou"), _window("fechou"), 0).word == "Fora da janela"
    ok = crop_verdict("milho_sertanejo", 10, _status("firmou"), _window("aberta"), 0)
    assert ok.word == "Pode plantar" and ok.risk_of_10 == 1
    risky = crop_verdict("milho_sertanejo", 70, _status("firmou", 20), _window("aberta"), 20)
    assert risky.level == "vermelho" and "20 dias de atraso" in risky.reason and "7 de cada 10" in risky.reason
    # perene sem janela no ZARC: só o risco
    assert crop_verdict("palma_forrageira", 10, _status("firmou"), None, 0).word == "Pode plantar"
    # nada de termo relativo como "chuva boa"
    assert "boa" not in crop_verdict("milho_sertanejo", 10, _status("firmando"), _window("aberta"), 0).reason


# --- ranking ------------------------------------------------------------------------------

def test_ranking_follows_priority_and_matches_selection() -> None:
    stats = SeasonalClimateStats("x", 450, 140, 180, 80, 0.4, 0.0, 0.4, 0.3, 0.0)
    results = MonteCarloRotationEngine(crops_catalog=crop_map()).simulate_portfolio(
        DEFAULT_STRATEGIES, stats, SimulationConfig(n_scenarios=500, horizon_years=10))
    for priority in BalancePriority:
        ranked = rank_by_balance_priority(results, priority)
        scores = [score for _, score in ranked]
        assert scores == sorted(scores, reverse=True) and len(ranked) == len(results)
        assert ranked[0][0] is select_by_balance_priority(results, priority)
    food_first = rank_by_balance_priority(results, BalancePriority.COMIDA)[0][0]
    forage_first = rank_by_balance_priority(results, BalancePriority.FORRAGEM)[0][0]
    assert food_first.expected_food_kg_ha_year >= forage_first.expected_food_kg_ha_year


# --- solo da região (WCS) ---------------------------------------------------------------------

def test_region_values_weights_depths_and_drops_nodata(tmp_path, monkeypatch) -> None:
    from crop_optimizer.config import get_settings

    def fake_download(url, path):
        depth = url.split("_mean")[0].rsplit("_", 1)[-1]
        layer = {"0-5cm": 100.0, "5-15cm": 200.0, "15-30cm": 300.0}[depth]
        arr = np.full((10, 10), layer)
        arr[0, 0] = 0.0  # sem dado (área urbana/água)
        return arr

    monkeypatch.setattr(soilgrids_wcs, "_download", fake_download)
    values = soilgrids_wcs.region_values(-9.0, -40.0, settings=get_settings(tmp_path))
    assert values["clay"].size == 99  # o pixel sem dado sai
    # pesos 5/10/5 cm: (100*5 + 200*10 + 300*5)/20 = 200, dividido pelo d_factor 10
    assert values["clay"][0] == pytest.approx(20.0)
    assert values["nitrogen"][0] == pytest.approx(2.0)  # d_factor 100
    st = soilgrids_wcs.stats(values["clay"])
    assert st.p10 == st.p50 == st.p90 == pytest.approx(20.0)


def test_region_stats_need_enough_pixels() -> None:
    assert soilgrids_wcs.stats(np.ones(5)) is None


# --- ícones -------------------------------------------------------------------------------------

def test_every_crop_has_svg_icon_and_description() -> None:
    crops = set(load_yaml_config("aptidao")["culturas"])
    assert crops == set(CROP_ICONS)
    assert crops == set(load_yaml_config("aptidao")["descricao_culturas"])
    for svg in CROP_ICONS.values():
        assert svg.startswith("<svg") and 'viewBox="0 0 64 64"' in svg
        assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in svg)
