"""Modelagem vetorizada de saúde e nutrientes do solo via Cadeias de Markov."""

from __future__ import annotations

import numpy as np

from crop_optimizer.domain.models import CropSpec, MarkovSoilOutput, SoilHealthState

# Fatores agronômicos associados a cada estado discreto do solo (0=Crítico .. 4=Regenerativo)
STATE_NITROGEN_EQUIV_KG_HA = np.array([25.0, 42.0, 65.0, 88.0, 112.0], dtype=np.float64)
STATE_ORGANIC_MATTER_PCT = np.array([1.2, 1.8, 2.5, 3.3, 4.1], dtype=np.float64)
STATE_YIELD_MULTIPLIER = np.array([0.72, 0.86, 1.00, 1.08, 1.15], dtype=np.float64)


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    row_sums = matrix.sum(axis=1, keepdims=True)
    return matrix / np.where(row_sums == 0.0, 1.0, row_sums)


def build_transition_matrix(crop: CropSpec) -> np.ndarray:
    """Constrói matriz estocástica 5x5 P(s_{t+1} | s_t, cultura) com soma das linhas = 1."""
    if crop.crop_id in ("palma_forrageira", "capim_buffel", "braquiaria"):
        # Coberturas vivas e palma protegem o solo contra erosão eólica/hídrica e elevam matéria orgânica
        base = np.array(
            [
                [0.18, 0.56, 0.26, 0.00, 0.00],
                [0.02, 0.24, 0.54, 0.20, 0.00],
                [0.00, 0.04, 0.34, 0.48, 0.14],
                [0.00, 0.00, 0.07, 0.51, 0.42],
                [0.00, 0.00, 0.02, 0.16, 0.82],
            ],
            dtype=np.float64,
        )
    elif crop.crop_id in ("feijao_caupi", "crotalaria"):
        # Leguminosas fixadoras de nitrogênio
        base = np.array(
            [
                [0.24, 0.52, 0.24, 0.00, 0.00],
                [0.04, 0.30, 0.50, 0.16, 0.00],
                [0.00, 0.06, 0.42, 0.42, 0.10],
                [0.00, 0.00, 0.10, 0.54, 0.36],
                [0.00, 0.00, 0.03, 0.20, 0.77],
            ],
            dtype=np.float64,
        )
    elif crop.crop_id in ("milho_sertanejo", "milho_safrinha", "algodao"):
        # Monocultivo/cereal exigente em água e N tende a degradar solo exposto na seca
        base = np.array(
            [
                [0.82, 0.18, 0.00, 0.00, 0.00],
                [0.34, 0.52, 0.14, 0.00, 0.00],
                [0.06, 0.34, 0.52, 0.08, 0.00],
                [0.00, 0.09, 0.36, 0.48, 0.07],
                [0.00, 0.00, 0.14, 0.42, 0.44],
            ],
            dtype=np.float64,
        )
    elif crop.crop_id in ("sorgo_forrageiro", "sorgo"):
        # Sorgo deixa boa palhada radicular e mantém equilíbrio relativo
        base = np.array(
            [
                [0.58, 0.36, 0.06, 0.00, 0.00],
                [0.14, 0.54, 0.28, 0.04, 0.00],
                [0.02, 0.16, 0.60, 0.19, 0.03],
                [0.00, 0.03, 0.22, 0.58, 0.17],
                [0.00, 0.00, 0.06, 0.28, 0.66],
            ],
            dtype=np.float64,
        )
    else:
        base = np.array(
            [
                [0.65, 0.30, 0.05, 0.00, 0.00],
                [0.18, 0.58, 0.22, 0.02, 0.00],
                [0.02, 0.18, 0.62, 0.16, 0.02],
                [0.00, 0.04, 0.24, 0.58, 0.14],
                [0.00, 0.00, 0.06, 0.28, 0.66],
            ],
            dtype=np.float64,
        )
    return _normalize_rows(base)


class MarkovSoilModel:
    """Simulador vetorizado em NumPy para evolução estocástica do solo."""

    def __init__(self, fertilizer_price_brl_kg_n: float = 6.20) -> None:
        self.fertilizer_price_brl_kg_n = fertilizer_price_brl_kg_n
        self._matrix_cache: dict[str, np.ndarray] = {}

    def get_matrix(self, crop: CropSpec) -> np.ndarray:
        if crop.crop_id not in self._matrix_cache:
            self._matrix_cache[crop.crop_id] = build_transition_matrix(crop)
        return self._matrix_cache[crop.crop_id]

    def simulate(
        self,
        crops_sequence: list[CropSpec],
        n_scenarios: int,
        initial_state: SoilHealthState,
        initial_nitrogen_kg_ha: float,
        initial_om_pct: float,
        climate_stress_matrix: np.ndarray,
        rng: np.random.Generator,
    ) -> MarkovSoilOutput:
        """Executa simulação vetorizada da Cadeia de Markov para todos os cenários simultaneamente."""
        n_steps = len(crops_sequence)
        states = np.empty((n_scenarios, n_steps + 1), dtype=np.int8)
        nitrogen = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        om = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        fert_savings = np.zeros((n_scenarios, n_steps), dtype=np.float64)
        yield_mult = np.empty((n_scenarios, n_steps), dtype=np.float64)

        states[:, 0] = int(initial_state.value)
        nitrogen[:, 0] = initial_nitrogen_kg_ha
        om[:, 0] = initial_om_pct

        u_draws = rng.random((n_scenarios, n_steps))

        for t, crop in enumerate(crops_sequence):
            cur_states = states[:, t]
            yield_mult[:, t] = STATE_YIELD_MULTIPLIER[cur_states]

            usable_residual_n = np.maximum(0.0, nitrogen[:, t] - 38.0) * 0.45
            n_offset = np.minimum(crop.nitrogen_demand_kg_ha, usable_residual_n)
            fert_savings[:, t] = n_offset * self.fertilizer_price_brl_kg_n

            base_mat = self.get_matrix(crop)
            severe_mask = climate_stress_matrix[:, t] > 0.38
            next_states = np.empty(n_scenarios, dtype=np.int8)

            if np.any(~severe_mask):
                idx_normal = np.flatnonzero(~severe_mask)
                cdf_normal = np.cumsum(base_mat[cur_states[idx_normal]], axis=1)
                cdf_normal[:, -1] = 1.0
                next_states[idx_normal] = np.sum(
                    u_draws[idx_normal, t : t + 1] > cdf_normal,
                    axis=1,
                ).astype(np.int8)

            if np.any(severe_mask):
                idx_stress = np.flatnonzero(severe_mask)
                stressed_mat = base_mat.copy()
                for s in range(1, 5):
                    stressed_mat[s] *= 0.86
                    stressed_mat[s, s - 1] += 0.14
                stressed_mat = _normalize_rows(stressed_mat)
                cdf_stress = np.cumsum(stressed_mat[cur_states[idx_stress]], axis=1)
                cdf_stress[:, -1] = 1.0
                next_states[idx_stress] = np.sum(
                    u_draws[idx_stress, t : t + 1] > cdf_stress,
                    axis=1,
                ).astype(np.int8)

            states[:, t + 1] = next_states

            target_n = STATE_NITROGEN_EQUIV_KG_HA[next_states]
            n_balance = crop.nitrogen_fixation_kg_ha - 0.35 * crop.nitrogen_demand_kg_ha
            nitrogen[:, t + 1] = np.clip(
                0.55 * nitrogen[:, t] + 0.45 * target_n + 0.25 * n_balance,
                16.0,
                145.0,
            )

            target_om = STATE_ORGANIC_MATTER_PCT[next_states]
            om[:, t + 1] = np.clip(
                0.70 * om[:, t] + 0.30 * target_om + crop.organic_matter_delta_pct,
                1.0,
                5.0,
            )

        return MarkovSoilOutput(
            states=states,
            nitrogen_kg_ha=nitrogen,
            organic_matter_pct=om,
            fertilizer_savings_brl_ha=fert_savings,
            yield_multiplier=yield_mult,
        )
