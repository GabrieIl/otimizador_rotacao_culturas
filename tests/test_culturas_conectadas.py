"""Toda cultura está ligada a todos os dados que as telas usam (Feature 8: novas culturas)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from crop_optimizer.analytics import agua
from crop_optimizer.analytics.crop_advice import irrigated_verdict
from crop_optimizer.analytics.soil_suitability import evaluate
from crop_optimizer.analytics.views import build_planting_window_risk_matrix
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.domain.crop_registry import (
    check_connections,
    is_irrigated,
    missing_connections,
    ordered_ids,
    registry,
    sequeiro_ids,
)
from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import crop_map
from crop_optimizer.domain.soil_profile import build_profile
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine, rain_requirement_mm
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats

NOVAS = ["alface", "rucula", "coentro", "cebolinha", "espinafre", "rabanete", "tomate", "pimentao", "morango",
         "pimenta", "mandioca", "batata_doce", "cenoura", "maracuja", "mamao", "banana", "limao", "feijao_comum",
         "fava", "milho_sertanejo"]
STATS = SeasonalClimateStats("x", 330, 105, 160, 80, 0.9, 0.0, 0.24, 0.12, 0.0, veranico_prob=0.79,
                             veranico_lengths=(10, 33, 14, 15, 17, 11))


def test_todas_as_culturas_pedidas_estao_no_registro() -> None:
    assert set(NOVAS) <= set(registry())
    assert len(registry()) == 24


def test_nenhuma_ligacao_obrigatoria_faltando() -> None:
    faltando = [(c.crop_id, c.point, c.detail) for c in missing_connections()]
    assert faltando == []


def test_cada_cultura_passa_por_todos_os_pontos() -> None:
    points = {c.point for c in check_connections()}
    assert points == {"registro", "nome", "solo", "bases", "descricao", "agua", "icone", "motor", "chuva_ciclo", "zarc"}
    by_crop = {}
    for c in check_connections():
        by_crop.setdefault(c.crop_id, set()).add(c.point)
    assert all(v == points for v in by_crop.values())
    assert set(by_crop) == set(registry()) == set(CROP_ICONS)


def test_ordem_por_grupo_cobre_todas() -> None:
    order = ordered_ids()
    assert sorted(order) == sorted(registry()) and len(order) == len(set(order))


def test_sequeiro_entra_no_motor_e_irrigada_nao() -> None:
    seq = sequeiro_ids()
    assert {"feijao_comum", "fava", "mandioca", "batata_doce"} <= set(seq)
    assert not any(is_irrigated(c) for c in seq)
    matrix = build_planting_window_risk_matrix(STATS, delay_days_grid=[0], n_samples=1_000,
                                               config=SimulationConfig(n_scenarios=1_000))
    assert set(matrix["crop_id"]) == set(seq)
    assert ((matrix["failure_prob_pct"] >= 0) & (matrix["failure_prob_pct"] <= 100)).all()
    # mandioca (rústica) quebra menos que o feijão comum
    risk = dict(zip(matrix["crop_id"], matrix["failure_prob_pct"], strict=True))
    assert risk["mandioca"] < risk["feijao_comum"]


def test_regua_de_chuva_antiga_preservada() -> None:
    catalog = crop_map()
    assert rain_requirement_mm(catalog["milho_sertanejo"]) == 430
    assert rain_requirement_mm(catalog["feijao_caupi"]) == 270
    assert rain_requirement_mm(catalog["palma_forrageira"]) == 160


def test_leguminosas_novas_melhoram_o_solo_como_o_caupi() -> None:
    from crop_optimizer.engine.markov_soil import build_transition_matrix

    caupi = build_transition_matrix(crop_map()["feijao_caupi"])
    assert np.allclose(build_transition_matrix(crop_map()["fava"]), caupi)
    assert np.allclose(build_transition_matrix(crop_map()["feijao_comum"]), caupi)


def test_aptidao_do_solo_avalia_todas() -> None:
    results = evaluate(build_profile(None, None, None))
    assert {r.crop_id for r in results} == set(registry())
    assert all(0 <= r.index <= 100 for r in results)


# --- rega ---------------------------------------------------------------------------------------------------


def test_kc_curve_follows_fao56_phases() -> None:
    crop = agua.crop_water("tomate")
    kc = agua.kc_curve(crop)
    assert kc.size == sum(crop.phases)
    assert kc[0] == pytest.approx(crop.kc[0]) and kc.max() == pytest.approx(crop.kc[1])
    assert kc[-1] == pytest.approx(crop.kc[2])


def test_et0_climatology_has_every_day() -> None:
    dates = np.arange(np.datetime64("1991-01-01"), np.datetime64("2021-01-01"), dtype="datetime64[D]")
    doy = (dates - dates.astype("datetime64[Y]")).astype(int)
    et0 = 4 + 2 * np.sin(2 * np.pi * doy / 365)
    clim = agua.et0_climatology(dates, et0)
    assert clim.shape == (366,) and np.all(np.isfinite(clim))
    assert clim[91] > clim[273]  # abril (seno alto) > outubro


@pytest.mark.parametrize("crop_id", [c for c in registry() if is_irrigated(c)])
def test_plano_de_rega_de_cada_irrigada(crop_id: str) -> None:
    from crop_optimizer.domain.crop_registry import is_perennial

    clim = np.full(366, 6.0)
    plan = agua.irrigation_plan(crop_id, 70.0, clim, date(2026, 11, 15), is_perennial(crop_id))
    assert plan is not None and plan.interval_days >= 1
    assert plan.liters_per_m2 > 0 and plan.total_liters_m2 > plan.liters_per_m2
    verdict = irrigated_verdict(crop_id, "X", plan)
    assert verdict.level == "rega" and "maior intervalo entre regas" in verdict.reason


def test_concordancia_do_aviso_de_rega() -> None:
    clim = np.full(366, 6.0)
    plan = agua.irrigation_plan("tomate", 70.0, clim, date(2026, 11, 15), False)
    assert irrigated_verdict("tomate", "Tomate", plan).reason.startswith("No semiárido, o tomate é cultivado")
    assert irrigated_verdict("alface", "Alface", plan).reason.startswith("No semiárido, a alface é cultivada")


def test_solo_que_segura_mais_agua_rega_menos_vezes() -> None:
    clim = np.full(366, 6.0)
    areia = agua.irrigation_plan("tomate", 70.0, clim, date(2026, 11, 15), False)
    media = agua.irrigation_plan("tomate", 140.0, clim, date(2026, 11, 15), False)
    raso = agua.irrigation_plan("tomate", 140.0, clim, date(2026, 11, 15), False, depth_m=0.3)
    assert media.interval_days > areia.interval_days
    assert raso.limited_by_depth and raso.interval_days < media.interval_days


def test_motor_roda_cada_cultura_de_sequeiro() -> None:
    eng = MonteCarloRotationEngine(crops_catalog=crop_map())
    for crop_id in sequeiro_ids():
        p = eng.harvest_failure_prob(crop_id, STATS, SimulationConfig(n_scenarios=500))
        assert 0.0 <= p <= 1.0
