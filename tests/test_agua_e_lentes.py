"""Água no solo e na lavoura (FAO-56), valores das lentes do GIBS, frases das lentes e prioridade Renda."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from crop_optimizer.analytics import agua, lens_insights
from crop_optimizer.domain.models import BalancePriority, SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, crop_map
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.engine.pareto import annual_profit, rank_by_balance_priority
from crop_optimizer.engine.rain_onset import OnsetReference
from crop_optimizer.ingestion import gibs_values
from crop_optimizer.ingestion.gibs import GibsLayer, TimeInterval
from crop_optimizer.ingestion.rain_history import RainSeries
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats

# --- ET0 (FAO-56) -------------------------------------------------------------------------------------


def test_ra_matches_fao56_example_8() -> None:
    # FAO-56, exemplo 8: 20° S, 3 de setembro (dia 246) -> Ra = 32,2 MJ m-2 dia-1
    assert float(agua.extraterrestrial_radiation(-20.0, 246)) == pytest.approx(32.2, abs=0.1)


def test_hargreaves_formula() -> None:
    ra = np.array([40.0])
    expected = 0.0023 * (25 + 17.8) * np.sqrt(10) * 0.408 * 40.0
    assert float(agua.et0_hargreaves(np.array([30.0]), np.array([20.0]), ra)[0]) == pytest.approx(expected)


# --- dias que a lavoura aguenta ------------------------------------------------------------------------


def test_hold_days_is_raw_over_etc() -> None:
    h = agua.hold_days("milho_sertanejo", 70.0, 5.0)  # TAW 70, RAW 38,5; ETc 1,2 x 5 = 6
    assert (h.taw_mm, h.raw_mm, h.etc_mm_day, h.days) == (pytest.approx(70), pytest.approx(38.5), pytest.approx(6.0), 6)
    raso = agua.hold_days("milho_sertanejo", 70.0, 5.0, depth_m=0.5)
    assert raso.limited_by_depth and raso.days < h.days
    assert agua.hold_days("palma_forrageira", 70.0, 5.0).days is None
    # solo que segura mais água -> aguenta mais
    assert agua.hold_days("milho_sertanejo", 140.0, 5.0).days > h.days


def test_critical_et0_uses_flowering_of_each_year() -> None:
    dates = np.arange(np.datetime64("2000-01-01"), np.datetime64("2002-12-31"), dtype="datetime64[D]")
    et0 = np.full(dates.size, 3.0)
    ref = OnsetReference(1, 2000, 2001, [2000, 2001], [10, None], 10, 10, 10)
    crop = agua.crop_water("milho_sertanejo")
    start = np.datetime64("2000-01-11") + np.timedelta64(crop.critical_start, "D")
    et0[(dates >= start) & (dates < start + np.timedelta64(crop.critical_length, "D"))] = 7.0
    assert agua.critical_et0(dates, et0, ref, crop) == pytest.approx(7.0)


# --- balanço do solo nu -----------------------------------------------------------------------------------


def test_bare_soil_depletion_stays_in_bounds() -> None:
    rng = np.random.default_rng(1)
    rain = rng.choice([0.0, 0.0, 0.0, 30.0], size=400)
    et0 = np.full(400, 6.0)
    dr = agua.bare_soil_depletion(rain, et0, 70.0, 0.3, 0.5)
    assert np.all((dr >= 0) & (dr <= 70.0))
    dry = agua.bare_soil_depletion(np.zeros(2000), np.full(2000, 6.0), 70.0, 0.3, 0.5)
    assert dry[-1] == pytest.approx(70.0, abs=1.0)
    wet = agua.bare_soil_depletion(np.full(50, 40.0), np.full(50, 6.0), 70.0, 0.3, 0.5)
    assert wet[-1] == 0.0


def test_soil_water_today_missing_rain() -> None:
    dates = np.arange(np.datetime64("1990-01-01"), np.datetime64("2026-11-12"), dtype="datetime64[D]")
    rain = np.zeros(dates.size)
    et0 = np.full(dates.size, 6.0)
    sw = agua.soil_water_today(dates, rain, et0, 70.0, "milho_sertanejo", date(2026, 11, 11))
    assert sw is not None and sw.day == date(2026, 11, 11)
    assert sw.fraction == pytest.approx(0.0, abs=0.02)
    assert sw.missing_mm == pytest.approx(70.0 - 38.5, abs=1.5)  # depleção - RAW


# --- valor do pixel do GIBS ------------------------------------------------------------------------------------

_XML = """<ColorMaps>
  <ColorMap title="No Data"><Entries>
    <ColorMapEntry rgb="0,0,0" transparent="true" sourceValue="[-9999]" value="[-9999]" nodata="true" ref="0"/>
  </Entries></ColorMap>
  <ColorMap title="Soil Moisture" units="m³/m³"><Entries>
    <ColorMapEntry rgb="255,162,0" transparent="false" sourceValue="[0.000,0.003)" value="[0.000,0.003)" ref="1"/>
    <ColorMapEntry rgb="0,0,255" transparent="false" sourceValue="[0.100,0.200)" value="[0.100,0.200)" ref="2"/>
    <ColorMapEntry rgb="10,10,10" transparent="false" sourceValue="[0.7,+INF)" value="[0.7,+INF)" ref="3"/>
  </Entries></ColorMap>
</ColorMaps>"""


def test_colormap_decodes_midpoint_and_rejects_unknown_colors() -> None:
    cmap = gibs_values.parse_colormap(_XML)
    assert cmap.units == "m³/m³"
    assert cmap.decode((0, 0, 255)) == pytest.approx(0.15)
    assert cmap.decode((1, 1, 254)) == pytest.approx(0.15)  # tolera arredondamento da cor
    assert cmap.decode((10, 10, 10)) == pytest.approx(0.7)  # faixa aberta: a ponta conhecida
    assert cmap.decode((120, 60, 200)) is None


def _layer(step: int = 1, first: date = date(2015, 1, 1), last: date = date(2026, 11, 10)) -> GibsLayer:
    return GibsLayer("L", "L", "GoogleMapsCompatible_Level6", "x", (TimeInterval(first, last, step, "D"),))


def test_soil_moisture_insight_compares_with_same_date(monkeypatch) -> None:
    def fake(layer, colormap, days, lat, lon, km, today=None):
        return {d: (0.06 if d.year == 2026 else 0.10) for d in days}

    monkeypatch.setattr(lens_insights, "values_at", fake)
    ins = lens_insights.soil_moisture_insight(_layer(), "cm", -9.0, -40.0, 9.0, date(2026, 11, 12))
    assert ins is not None and ins.numbers["diff_pct"] == -40
    assert "mais seca que o normal" in ins.text and "0,06" in ins.text and ins.page == "plantio"


def test_rain_insight_ranks_this_year() -> None:
    dates = np.arange(np.datetime64("2000-01-01"), np.datetime64("2026-03-02"), dtype="datetime64[D]")
    rain = np.full(dates.size, 2.0)
    rain[dates >= np.datetime64("2026-01-01")] = 0.1  # 2026 muito seco
    ins = lens_insights.rain_insight(RainSeries("x", dates, rain, "teste"), date(2026, 3, 1))
    assert ins is not None and ins.numbers["rank_dry"] == 1 and "entre os 5 mais secos" in ins.text


def test_relief_insight_has_runoff_risk() -> None:
    ins = lens_insights.relief_insight(12.0)
    assert ins.numbers["classe"] == "ondulado" and "enxurrada" in ins.text and ins.page == "inicio"


# --- prioridade Renda ------------------------------------------------------------------------------------------


def test_renda_priority_puts_highest_income_first() -> None:
    stats = SeasonalClimateStats("x", 450, 140, 180, 80, 0.4, 0.0, 0.4, 0.3, 0.0)
    results = MonteCarloRotationEngine(crops_catalog=crop_map()).simulate_portfolio(
        DEFAULT_STRATEGIES, stats, SimulationConfig(n_scenarios=500, horizon_years=3))
    top = rank_by_balance_priority(results, BalancePriority.RENDA)[0][0]
    assert annual_profit(top) == max(annual_profit(r) for r in results)


# --- texto do aviso ------------------------------------------------------------------------------------------


def test_water_block_text() -> None:
    from crop_optimizer.app.dashboard import _water_block

    hold = agua.HoldDays("milho_sertanejo", 6, 38.5, 70.0, 6.2, 1.0, False)
    today = agua.SoilWaterToday(date(2026, 11, 11), 0.1, 0.12, 47.0, 70.0, 38.5)
    block = _water_block("milho_sertanejo", "Milho", {"milho_sertanejo": (hold, today)}, 14, "arenosa", None)
    assert [b["days"] for b in block["bars"]] == [14, 6] and block["bars"][1]["tone"] == "curto"
    assert block["phrase"].startswith("O veranico daqui costuma passar do que o milho aguenta: 14 dias contra 6. ")
    assert "6,2 mm por dia." in block["phrase"] and "Profundidade do solo não informada" in block["phrase"]
    assert "Faltam cerca de 45 mm" in block["solo"]["text"]
    palma = agua.HoldDays("palma_forrageira", None, 0, 0, 0, 0, False)
    assert "raquete" in _water_block("palma_forrageira", "Palma forrageira",
                                     {"palma_forrageira": (palma, None)}, 14, "arenosa", None)["phrase"]
