"""Testes da Feature 3: perfil do solo, limitação por cultura e efeito no Monte Carlo."""

from __future__ import annotations

import numpy as np
import pytest

from crop_optimizer.analytics.soil_suitability import (
    available_nitrogen_kg_ha,
    classify,
    evaluate,
    initial_markov_state,
    land_index,
    phosphorus_class,
    relief_class,
    texture_class,
)
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig, SoilHealthState
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, crop_map
from crop_optimizer.domain.soil_profile import (
    build_profile,
    clear_field_data,
    load_field_data,
    reference_values,
    save_field_data,
)
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.ingestion import soilgrids
from crop_optimizer.ingestion.soilgrids import SoilGridsValue, parse_soilgrids
from crop_optimizer.ingestion.terrain import decode_terrarium, horn_slope_pct
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _by_crop(results):
    return {c.crop_id: c for c in results}


# --- classes oficiais (Alvarez V. et al., 1999) -----------------------------

def test_official_classes() -> None:
    assert classify(0.5, [0.70, 2.00, 4.00, 7.00]) == "muito_baixo"
    assert classify(1.3, [0.70, 2.00, 4.00, 7.00]) == "baixo"
    assert classify(8.0, [0.70, 2.00, 4.00, 7.00]) == "muito_bom"
    # o mesmo P muda de classe com a argila (capacidade tampão)
    assert phosphorus_class(8.0, 10) == "muito_baixo"
    assert phosphorus_class(8.0, 25) == "baixo"
    assert phosphorus_class(8.0, 50) == "baixo"  # 35-60% de argila: baixo vai de 4,1 a 8,0
    assert phosphorus_class(10.0, 50) == "medio"
    assert phosphorus_class(8.0, 70) == "medio"


def test_texture_and_relief() -> None:
    assert texture_class(85, 8) == "arenosa"
    assert texture_class(58, 22) == "media"
    assert texture_class(30, 40) == "argilosa"
    assert texture_class(10, 65) == "muito_argilosa"
    assert relief_class(2)["nome"] == "plano"
    assert relief_class(12)["nome"] == "ondulado"
    assert relief_class(50)["grau"] == "muito_forte"


def test_land_index_square_root_method() -> None:
    assert land_index([1.0, 1.0]) == pytest.approx(100.0)
    # mínimo 0,5 e demais 0,9 x 0,9: 0,5 x raiz(0,81) = 0,45
    assert land_index([0.9, 0.5, 0.9]) == pytest.approx(45.0)


# --- limitação por cultura ----------------------------------------------------

def _profile(**field) -> object:
    return build_profile(None, None, {"valores": field} if field else None)


def test_same_soil_different_crops_nitrogen() -> None:
    """Pouca matéria orgânica (pouco N) pesa no milho, não no feijão-caupi."""
    res = _by_crop(evaluate(_profile(mo_pct=0.5)))
    n_milho = next(f for f in res["milho_sertanejo"].factors if f.factor == "nitrogenio")
    n_caupi = next(f for f in res["feijao_caupi"].factors if f.factor == "nitrogenio")
    assert n_milho.degree == "forte"
    assert n_caupi.degree == "nula"


def test_reference_soil_has_factor_one() -> None:
    for c in evaluate(_profile()):
        assert c.yield_factor == pytest.approx(1.0)


def test_low_phosphorus_from_field_lowers_factor() -> None:
    res = _by_crop(evaluate(_profile(p_mehlich=3.0, argila_pct=20.0)))
    assert res["milho_sertanejo"].yield_factor < 1.0
    assert res["milho_sertanejo"].limiting.factor == "fosforo"
    assert res["milho_sertanejo"].yield_factor < res["capim_buffel"].yield_factor


def test_assumed_attribute_is_neutral_even_if_clay_changes_its_class() -> None:
    """P sem análise não pode mudar de classe só porque a argila do mapa mudou."""
    res = _by_crop(evaluate(_profile(argila_pct=8.0, areia_pct=60.0)))
    fosforo = next(f for f in res["milho_sertanejo"].factors if f.factor == "fosforo")
    ref = _by_crop(evaluate(_profile()))
    fosforo_ref = next(f for f in ref["milho_sertanejo"].factors if f.factor == "fosforo")
    assert fosforo.assumed and fosforo.degree == fosforo_ref.degree


def test_slope_hurts_annual_crops_more_than_perennials() -> None:
    res = _by_crop(evaluate(_profile(declividade_pct=15.0)))
    e_milho = next(f for f in res["milho_sertanejo"].factors if f.factor == "erosao")
    e_palma = next(f for f in res["palma_forrageira"].factors if f.factor == "erosao")
    assert e_milho.degree == "moderada" and e_palma.degree == "ligeira"


def test_ph_outside_absolute_range_is_very_strong() -> None:
    res = _by_crop(evaluate(_profile(ph_h2o=4.0)))
    acidez = next(f for f in res["milho_sertanejo"].factors if f.factor == "acidez")
    assert acidez.degree == "muito_forte"
    assert res["milho_sertanejo"].suit_class in ("S3", "N")


# --- perfil: fontes e prioridade --------------------------------------------

def _sg_payload() -> dict:
    def layer(name, unit, d_factor, mean, q05, q95):
        depths = [
            {"label": d, "values": {"mean": mean, "Q0.05": q05, "Q0.95": q95}}
            for d in ("0-5cm", "5-15cm", "15-30cm")
        ]
        return {"name": name, "unit_measure": {"d_factor": d_factor, "target_units": unit}, "depths": depths}

    return {
        "properties": {
            "layers": [
                layer("clay", "%", 10, 200, 50, 400),
                layer("sand", "%", 10, 600, 300, 850),
                layer("soc", "g/kg", 10, 80, 10, 200),
                layer("phh2o", "pH", 10, 62, 50, 75),
                layer("nitrogen", "g/kg", 100, 80, 30, 150),
            ]
        }
    }


def test_parse_soilgrids_units_and_mo_conversion() -> None:
    parsed = parse_soilgrids(_sg_payload(), {"0-5cm": 5, "5-15cm": 10, "15-30cm": 5})
    assert parsed["clay"].mean == pytest.approx(20.0)
    assert parsed["nitrogen"].mean == pytest.approx(0.8)
    profile = build_profile(parsed, None, None)
    # soc 8 g/kg -> C.O. 0,8 dag/kg -> M.O. 0,8 x 1,724
    assert profile.get("mo_pct") == pytest.approx(0.8 * 1.724)
    assert profile.source_of("mo_pct") == "satelite"
    assert profile.values["mo_pct"].low < profile.get("mo_pct") < profile.values["mo_pct"].high
    assert profile.source_of("p_mehlich") == "referencia"  # satélite não mede P


def test_field_value_wins_over_satellite() -> None:
    parsed = parse_soilgrids(_sg_payload(), {"0-5cm": 5, "5-15cm": 10, "15-30cm": 5})
    profile = build_profile(parsed, None, {"valores": {"mo_pct": 2.5}, "data": "2026-11-14"})
    assert profile.get("mo_pct") == 2.5 and profile.source_of("mo_pct") == "campo"
    assert profile.field_date == "2026-11-14"


def test_field_data_round_trip(tmp_path) -> None:
    settings = get_settings(tmp_path)
    assert load_field_data("roca_x", settings) is None
    save_field_data("roca_x", {"p_mehlich": 4.0, "k_mg_dm3": None, "inexistente": 1.0}, "lab", settings)
    data = load_field_data("roca_x", settings)
    assert data["valores"] == {"p_mehlich": 4.0} and data["nota"] == "lab"
    clear_field_data("roca_x", settings)
    assert load_field_data("roca_x", settings) is None


def test_soilgrids_nearby_fallback(monkeypatch) -> None:
    calls = []

    def fake(lat, lon, settings=None):
        calls.append((lat, lon))
        return {} if len(calls) < 3 else {"clay": SoilGridsValue(20, 10, 30, "%")}

    monkeypatch.setattr(soilgrids, "fetch_soilgrids", fake)
    values, moved = soilgrids.fetch_soilgrids_nearby(-9.0, -40.0)
    assert values and moved == "a 3 km ao sul"
    assert calls[1][0] > -9.0 > calls[2][0]  # tentou norte, depois sul


# --- motor --------------------------------------------------------------------

def test_markov_initial_state_and_nitrogen() -> None:
    assert initial_markov_state(1.2) == SoilHealthState.CRITICO
    assert initial_markov_state(2.4) == SoilHealthState.EQUILIBRADO
    n = available_nitrogen_kg_ha(_profile(mo_pct=1.0))
    # 1% M.O. x 5% N x 2.800 t/ha x 2% ao ano = 28 kg/ha
    assert n == pytest.approx(28.0)


def test_terrain_decoding_and_slope() -> None:
    rgb = np.array([[[128, 0, 0], [128, 100, 128]]], dtype=np.uint8)
    assert decode_terrarium(rgb).tolist() == [[0.0, 100.5]]
    # plano inclinado: sobe 3 m por pixel de 30 m no eixo x -> 10%
    window = np.array([[0, 3, 6], [0, 3, 6], [0, 3, 6]], dtype=float)
    assert horn_slope_pct(window, 30.0) == pytest.approx(10.0)


def _stats() -> SeasonalClimateStats:
    return SeasonalClimateStats(
        location_id="x", safra_rain_mean_mm=450, safra_rain_std_mm=140, safrinha_rain_mean_mm=180,
        safrinha_rain_std_mm=80, safrinha_water_stress_prob=0.4, frost_prob_safrinha=0.0,
        mean_gwet_safra=0.4, mean_gwet_safrinha=0.3, query_ms=0.0,
    )


def test_monte_carlo_soil_factor_per_crop() -> None:
    engine = MonteCarloRotationEngine(crops_catalog=crop_map())
    so_milho = [s for s in DEFAULT_STRATEGIES if s.strategy_id == "so_milho_tradicional"]
    base = SimulationConfig(n_scenarios=500)
    same = SimulationConfig(n_scenarios=500, soil_crop_factors={"milho_sertanejo": 1.0})
    worse = SimulationConfig(n_scenarios=500, soil_crop_factors={"milho_sertanejo": 0.6})
    only_caupi = SimulationConfig(n_scenarios=500, soil_crop_factors={"feijao_caupi": 0.6})
    food = {
        name: engine.simulate_portfolio(so_milho, _stats(), cfg)[0].expected_food_kg_ha_year
        for name, cfg in [("base", base), ("same", same), ("worse", worse), ("only_caupi", only_caupi)]
    }
    assert food["same"] == pytest.approx(food["base"])
    assert food["worse"] < 0.7 * food["base"]
    assert food["only_caupi"] == pytest.approx(food["base"])  # fator do caupi não afeta só milho


def test_reference_values_complete() -> None:
    assert set(reference_values()) >= {"argila_pct", "areia_pct", "mo_pct", "ph_h2o", "p_mehlich", "declividade_pct"}
