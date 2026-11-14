"""Testes das Cadeias de Markov de dinâmica do solo no Semiárido."""

from __future__ import annotations

import numpy as np

from crop_optimizer.domain.models import SoilHealthState
from crop_optimizer.domain.presets import DEFAULT_CROPS, crop_map
from crop_optimizer.engine.markov_soil import MarkovSoilModel, build_transition_matrix


def test_transition_matrices_are_row_stochastic() -> None:
    for crop in DEFAULT_CROPS:
        mat = build_transition_matrix(crop)
        assert mat.shape == (5, 5)
        assert np.all(mat >= 0.0)
        assert np.allclose(mat.sum(axis=1), 1.0, atol=1e-9)


def test_palma_and_caupi_recover_soil_better_than_continuous_corn() -> None:
    catalog = crop_map()
    model = MarkovSoilModel(fertilizer_price_brl_kg_n=6.2)
    n_scen = 2_000
    n_steps = 6
    moderate_stress = np.full((n_scen, n_steps), 0.25, dtype=np.float64)
    high_stress = np.full((n_scen, n_steps), 0.55, dtype=np.float64)

    out_regen = model.simulate(
        crops_sequence=[catalog["feijao_caupi"], catalog["palma_forrageira"]] * 3,
        n_scenarios=n_scen,
        initial_state=SoilHealthState.DEGRADADO,
        initial_nitrogen_kg_ha=42.0,
        initial_om_pct=1.8,
        climate_stress_matrix=moderate_stress,
        rng=np.random.default_rng(7),
    )
    out_corn = model.simulate(
        crops_sequence=[catalog["milho_sertanejo"]] * n_steps,
        n_scenarios=n_scen,
        initial_state=SoilHealthState.DEGRADADO,
        initial_nitrogen_kg_ha=42.0,
        initial_om_pct=1.8,
        climate_stress_matrix=high_stress,
        rng=np.random.default_rng(7),
    )

    assert np.mean(out_regen.states[:, -1]) > np.mean(out_corn.states[:, -1])
    assert np.mean(out_regen.organic_matter_pct[:, -1]) > np.mean(out_corn.organic_matter_pct[:, -1])
    assert np.mean(out_regen.nitrogen_kg_ha[:, -1]) > np.mean(out_corn.nitrogen_kg_ha[:, -1])
