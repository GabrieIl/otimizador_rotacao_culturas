"""O aviso por cultura e o ranking das rotações usam o mesmo motor e a mesma régua de quebra de safra."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from crop_optimizer.analytics.crop_advice import failure_rule_text
from crop_optimizer.analytics.views import build_planting_window_risk_matrix
from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, crop_map
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats

STATS = SeasonalClimateStats("x", 330, 105, 160, 80, 0.9, 0.0, 0.24, 0.12, 0.0, veranico_prob=0.79,
                             veranico_lengths=(10, 33, 14, 15, 17, 11, 19, 11, 13, 18, 12, 31, 21, 20, 20))


def _so_milho(horizon: int, delay: int = 0):
    strategy = next(s for s in DEFAULT_STRATEGIES if s.strategy_id == "so_milho_tradicional")
    cfg = SimulationConfig(n_scenarios=4_000, horizon_years=horizon, safra_delay_days=delay)
    return MonteCarloRotationEngine(crops_catalog=crop_map()).simulate_strategy(strategy, STATS, cfg)


@pytest.mark.parametrize("delay", [0, 14])
def test_milho_no_aviso_e_so_milho_no_ranking_contam_igual(delay: int) -> None:
    matrix = build_planting_window_risk_matrix(STATS, delay_days_grid=[delay], n_samples=4_000,
                                               config=SimulationConfig(n_scenarios=4_000))
    aviso = matrix.filter(matrix["crop_id"] == "milho_sertanejo")["failure_prob_pct"][0]
    ranking = _so_milho(1, delay)
    # mesmo motor, mesma semente, mesma régua: o mesmo número
    assert aviso == pytest.approx(ranking.metadata["annual_loss_prob"] * 100, abs=0.05)
    assert round(aviso / 10) == ranking.loss_years_of_10
    assert ranking.survival_score_of_10 + ranking.loss_years_of_10 == 10


def test_quebra_e_colheita_relativa_abaixo_da_regua() -> None:
    res = _so_milho(5)
    cfg = SimulationConfig()
    assert res.relative_harvest.shape == (4_000, 5)
    assert np.all(res.relative_harvest >= 0)
    assert res.metadata["annual_loss_prob"] == pytest.approx(
        float(np.mean(res.relative_harvest < cfg.harvest_failure_threshold)))


def test_veranico_sorteado_nao_fixo() -> None:
    """Sem veranico no histórico o risco cai; com veranico em todo ano (fixo) ele sobe."""
    sem = replace(STATS, veranico_prob=0.0)
    sempre = replace(STATS, veranico_prob=1.0)
    eng = MonteCarloRotationEngine(crops_catalog=crop_map())
    cfg = SimulationConfig(n_scenarios=4_000)
    p_sem = eng.harvest_failure_prob("milho_sertanejo", sem, cfg)
    p_real = eng.harvest_failure_prob("milho_sertanejo", STATS, cfg)
    p_sempre = eng.harvest_failure_prob("milho_sertanejo", sempre, cfg)
    assert p_sem < p_real < p_sempre


def test_texto_da_regua_vem_do_config() -> None:
    assert failure_rule_text() == "colhe menos da metade do normal"
