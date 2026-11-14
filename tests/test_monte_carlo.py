"""Testes do motor Monte Carlo vetorizado (Sobrevivência, 2 anos seguidos e SLA < 5s)."""

from __future__ import annotations

import time

from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _sertao_stats() -> SeasonalClimateStats:
    return SeasonalClimateStats(
        location_id="petrolina_pe",
        safra_rain_mean_mm=430.0,
        safra_rain_std_mm=150.0,
        safrinha_rain_mean_mm=165.0,
        safrinha_rain_std_mm=80.0,
        safrinha_water_stress_prob=0.45,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.40,
        mean_gwet_safrinha=0.25,
        veranico_prob=0.35,
        mean_smap_moisture=0.23,
        query_ms=1.5,
    )


def test_monte_carlo_reproducibility_and_resilience_advantage() -> None:
    engine = MonteCarloRotationEngine()
    stats = _sertao_stats()
    by_id = {s.strategy_id: s for s in DEFAULT_STRATEGIES}

    cfg = SimulationConfig(
        location_id="petrolina_pe",
        n_scenarios=5_000,
        horizon_years=5,
        safra_delay_days=21,
        veranico_days=10,
        seed=123,
    )
    res_corn = engine.simulate_strategy(by_id["so_milho_tradicional"], stats, cfg)
    res_corn_2 = engine.simulate_strategy(by_id["so_milho_tradicional"], stats, cfg)
    res_resilient = engine.simulate_strategy(by_id["sorgo_caupi_palma"], stats, cfg)

    assert res_corn.expected_npv_brl_ha == res_corn_2.expected_npv_brl_ha
    assert res_resilient.prob_two_consecutive_losses < res_corn.prob_two_consecutive_losses
    assert res_resilient.expected_forage_kg_ha_year > res_corn.expected_forage_kg_ha_year
    assert res_resilient.survival_score_of_10 >= res_corn.survival_score_of_10


def test_monte_carlo_10k_scenarios_under_5_seconds() -> None:
    engine = MonteCarloRotationEngine()
    stats = _sertao_stats()
    cfg = SimulationConfig(
        location_id="petrolina_pe",
        n_scenarios=10_000,
        horizon_years=5,
        safra_delay_days=14,
        veranico_days=7,
        seed=42,
    )

    t0 = time.perf_counter()
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, stats, cfg)
    elapsed_s = time.perf_counter() - t0

    assert len(results) == len(DEFAULT_STRATEGIES)
    assert elapsed_s < 5.0, f"Simulação excedeu SLA de 5s: {elapsed_s:.2f}s"
