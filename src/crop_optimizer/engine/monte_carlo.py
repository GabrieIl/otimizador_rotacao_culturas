"""Motor vetorizado de Simulação de Monte Carlo (Sobrevivência, Biomassa e Secas Plurianuais)."""

from __future__ import annotations

import time

import numpy as np

from crop_optimizer.domain.models import (
    CropSpec,
    RotationStrategy,
    SeasonSlot,
    SimulationConfig,
    StrategySimulationResult,
)
from crop_optimizer.domain.presets import crop_map
from crop_optimizer.engine.markov_soil import MarkovSoilModel
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _delay_and_veranico_penalty(
    delay_days: int,
    veranico_days: int,
    slot: SeasonSlot,
    crop: CropSpec,
) -> tuple[float, float]:
    """
    Calcula (estresse_adicional, teto_produtivo) para atraso das águas + veranico.
    Milho sequeiro sofre quebra severa se atrasar > 15 dias ou houver veranico na floração;
    sorgo, caupi e palma mantêm elevada estabilidade.
    """
    if crop.crop_id in ("palma_forrageira", "capim_buffel"):
        extra = min(0.14, 0.0015 * delay_days + 0.002 * veranico_days)
        return (extra, 1.0)

    sens = crop.drought_sensitivity
    delay_eff = max(0, delay_days - 5)
    delay_stress = min(0.55, (0.011 * delay_eff + 0.00022 * (delay_eff**2)) * sens)
    veranico_stress = min(0.45, 0.016 * veranico_days * sens)

    if slot == SeasonSlot.SAFRINHA and delay_days > 14:
        delay_stress = min(0.60, delay_stress * 1.15)

    yield_cap = max(0.40, 1.0 - 0.0065 * delay_eff * min(1.3, sens))
    return (min(0.75, delay_stress + veranico_stress), yield_cap)


class MonteCarloRotationEngine:
    """Simula 10.000+ cenários de 5 anos focando em biomassa (Comida + Forragem) e sobrevivência."""

    def __init__(self, crops_catalog: dict[str, CropSpec] | None = None) -> None:
        self.crops_catalog = crops_catalog or crop_map()

    def simulate_strategy(
        self,
        strategy: RotationStrategy,
        climate_stats: SeasonalClimateStats,
        config: SimulationConfig,
    ) -> StrategySimulationResult:
        t0 = time.perf_counter()
        n_scen = config.n_scenarios
        horizon = config.horizon_years

        annual_crops = [self.crops_catalog[cid] for cid in strategy.annual_sequence]
        full_sequence: list[CropSpec] = []
        step_labels: list[str] = []
        step_years: list[int] = []
        for yr in range(1, horizon + 1):
            for crop in annual_crops:
                full_sequence.append(crop)
                step_labels.append(f"Ano {yr} · {crop.name}")
                step_years.append(yr)

        n_steps = len(full_sequence)
        rng = np.random.default_rng(config.seed)

        # 1. Ciclos plurianuais El Niño / La Niña com persistência AR(1) (risco de 2+ secas seguidas)
        annual_enso = np.empty((n_scen, horizon), dtype=np.float64)
        cur_enso = np.clip(rng.normal(1.0, 0.24, size=n_scen), 0.45, 1.55)
        annual_enso[:, 0] = cur_enso
        for yr in range(1, horizon):
            cur_enso = np.clip(
                1.0 + 0.48 * (cur_enso - 1.0) + rng.normal(0.0, 0.22, size=n_scen),
                0.42,
                1.60,
            )
            annual_enso[:, yr] = cur_enso

        # Ocorrência estocástica de veranico em cada ano (somado ao veranico simulado pelo usuário)
        veranico_annual_days = np.where(
            rng.random((n_scen, horizon)) < climate_stats.veranico_prob,
            rng.integers(8, 19, size=(n_scen, horizon)),
            0,
        )

        # 2. Estresse hídrico vetorizado por safra/cultura
        climate_stress = np.zeros((n_scen, n_steps), dtype=np.float64)
        delay_yield_cap = np.ones(n_steps, dtype=np.float64)

        for t, crop in enumerate(full_sequence):
            yr_idx = step_years[t] - 1
            enso_factor = annual_enso[:, yr_idx]
            eff_veranico = config.veranico_days + veranico_annual_days[:, yr_idx]

            # Penalidade base para o atraso informado
            base_delay_stress, cap = _delay_and_veranico_penalty(
                config.safra_delay_days,
                0,
                crop.slot,
                crop,
            )
            delay_yield_cap[t] = cap

            # Chuva acumulada na janela útil (quadra chuvosa)
            rain_mean = climate_stats.safra_rain_mean_mm
            rain_std = climate_stats.safra_rain_std_mm
            rain_req = 430.0 if crop.crop_id == "milho_sertanejo" else (270.0 if not crop.is_cover_crop else 160.0)

            rain_draw = np.maximum(
                55.0,
                rng.normal(rain_mean, rain_std, size=n_scen) * enso_factor,
            )
            deficit_ratio = np.clip((rain_req - rain_draw) / rain_req, 0.0, 0.90)

            veranico_factor = (
                0.002 if crop.crop_id in ("palma_forrageira", "capim_buffel") else 0.015 * crop.drought_sensitivity
            )
            veranico_stress = np.clip(eff_veranico * veranico_factor, 0.0, 0.50)

            stress = np.clip(
                deficit_ratio * crop.drought_sensitivity
                + base_delay_stress * rng.uniform(0.7, 1.25, size=n_scen)
                + veranico_stress,
                0.0,
                0.95,
            )
            climate_stress[:, t] = stress

        # 3. Cadeia de Markov do solo acoplada ao estresse climático
        markov_model = MarkovSoilModel(fertilizer_price_brl_kg_n=config.fertilizer_price_brl_kg_n)
        soil_out = markov_model.simulate(
            crops_sequence=full_sequence,
            n_scenarios=n_scen,
            initial_state=config.initial_soil_state,
            initial_nitrogen_kg_ha=config.initial_nitrogen_kg_ha,
            initial_om_pct=config.initial_organic_matter_pct,
            climate_stress_matrix=climate_stress,
            rng=rng,
        )

        # 4. Balanço de Biomassa (Comida + Forragem) e Fluxo Financeiro Auxiliar
        # Na agricultura familiar do Semiárido (1 ha), múltiplas culturas no mesmo ano dividem área/água
        # com ganho de sinergia (LER ~ 1.15 para 2 culturas e ~ 1.25 para 3 culturas).
        n_annual = len(annual_crops)
        ler_factor = 1.0 if n_annual == 1 else (1.15 if n_annual == 2 else 1.25)
        area_share = ler_factor / n_annual

        annual_food = np.zeros((n_scen, horizon), dtype=np.float64)
        annual_forage = np.zeros((n_scen, horizon), dtype=np.float64)
        annual_profit = np.zeros((n_scen, horizon), dtype=np.float64)
        npv_profit = np.zeros(n_scen, dtype=np.float64)

        for t, crop in enumerate(full_sequence):
            yr_idx = step_years[t] - 1
            discount_factor = 1.0 / ((1.0 + config.discount_rate) ** yr_idx)

            # Matéria orgânica protege umidade do solo no Semiárido
            soil_buffer = np.clip((soil_out.organic_matter_pct[:, t] - 1.8) * 0.09, 0.0, 0.22)
            effective_stress = np.maximum(0.0, climate_stress[:, t] * (1.0 - soil_buffer))

            grain_yield_factor = np.clip(1.0 - 0.92 * effective_stress, 0.08, 1.15)
            realized_grain_ton = (
                crop.base_yield_ton_ha
                * area_share
                * delay_yield_cap[t]
                * soil_out.yield_multiplier[:, t]
                * grain_yield_factor
            )
            food_kg = realized_grain_ton * 1000.0 * crop.food_fraction

            # Forragem (palhada + palma + buffel) tem maior resiliência à seca
            forage_stress = effective_stress * (1.0 - 0.55 * crop.forage_drought_resilience)
            forage_factor = np.clip(1.0 - 0.72 * forage_stress, 0.25, 1.15)
            forage_kg = (
                crop.forage_yield_ton_ha
                * area_share
                * 1000.0
                * (0.5 + 0.5 * soil_out.yield_multiplier[:, t])
                * forage_factor
            )

            annual_food[:, yr_idx] += food_kg
            annual_forage[:, yr_idx] += forage_kg

            scaled_cost = crop.direct_cost_brl_ha * area_share
            scaled_fert_savings = soil_out.fertilizer_savings_brl_ha[:, t] * area_share

            if crop.is_cover_crop:
                forage_replacement_value = forage_kg * 0.18
                step_profit = forage_replacement_value + scaled_fert_savings - scaled_cost
            else:
                vol = crop.price_volatility
                price_shock = np.exp(rng.normal(-0.5 * (vol**2), vol, size=n_scen))
                realized_price = crop.base_price_brl_ton * price_shock
                revenue = realized_grain_ton * realized_price + (forage_kg * 0.08)
                net_cost = scaled_cost - scaled_fert_savings
                step_profit = revenue - net_cost

            annual_profit[:, yr_idx] += step_profit
            npv_profit += step_profit * discount_factor

        # 5. Métricas de Sobrevivência (Foco Sertão)
        food_deficit = annual_food < (0.65 * config.family_food_target_kg_year)
        forage_deficit = annual_forage < (0.75 * config.herd_forage_target_kg_year)
        # Perda severa anual: colapso da comida OU falta crítica de forragem para o rebanho
        severe_year_loss = (food_deficit & forage_deficit) | (
            annual_food < (0.45 * config.family_food_target_kg_year)
        )

        if horizon >= 2:
            two_consec_loss = np.any(severe_year_loss[:, :-1] & severe_year_loss[:, 1:], axis=1)
            prob_two_consec = float(np.mean(two_consec_loss))
            two_consec_forage = np.any(forage_deficit[:, :-1] & forage_deficit[:, 1:], axis=1)
            prob_herd_collapse = float(np.mean(two_consec_forage))
        else:
            prob_two_consec = float(np.mean(severe_year_loss))
            prob_herd_collapse = float(np.mean(forage_deficit))

        mean_annual_loss_rate = float(np.mean(severe_year_loss))
        loss_years_of_10 = int(np.clip(round(mean_annual_loss_rate * 10.0), 0, 10))
        survival_score_of_10 = 10 - loss_years_of_10

        expected_food = float(np.mean(annual_food))
        expected_forage = float(np.mean(annual_forage))

        # Escores normalizados (0..100) para a Balança Comida x Forragem x Escudo
        food_score = float(np.clip((expected_food / (config.family_food_target_kg_year * 1.45)) * 100.0, 0.0, 100.0))
        forage_score = float(np.clip((expected_forage / (config.herd_forage_target_kg_year * 3.0)) * 100.0, 0.0, 100.0))
        shield_score = float(np.clip((1.0 - prob_two_consec) * 100.0, 0.0, 100.0))

        expected_npv = float(np.mean(npv_profit))
        profit_std = float(np.std(npv_profit))
        var_5 = float(np.percentile(npv_profit, 5.0))
        tail = npv_profit[npv_profit <= var_5]
        cvar_95 = float(np.mean(tail)) if tail.size > 0 else var_5
        prob_loss = float(np.mean(npv_profit < 0.0))

        final_states = soil_out.states[:, -1].astype(np.float64)
        final_soil_mean = float(np.mean(final_states))
        final_soil_std = float(np.std(final_states))
        total_fert_savings = float(np.mean(np.sum(soil_out.fertilizer_savings_brl_ha, axis=1)))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return StrategySimulationResult(
            strategy=strategy,
            npv_profit_brl_ha=npv_profit,
            annual_profit_brl_ha=annual_profit,
            annual_food_kg_ha=annual_food,
            annual_forage_kg_ha=annual_forage,
            soil_output=soil_out,
            step_labels=step_labels,
            expected_npv_brl_ha=expected_npv,
            profit_std_brl_ha=profit_std,
            cvar_95_brl_ha=cvar_95,
            prob_loss=prob_loss,
            expected_food_kg_ha_year=expected_food,
            expected_forage_kg_ha_year=expected_forage,
            prob_two_consecutive_losses=prob_two_consec,
            prob_herd_collapse=prob_herd_collapse,
            survival_score_of_10=survival_score_of_10,
            loss_years_of_10=loss_years_of_10,
            food_score=round(food_score, 1),
            forage_score=round(forage_score, 1),
            shield_score=round(shield_score, 1),
            final_soil_score_mean=final_soil_mean,
            final_soil_score_std=final_soil_std,
            total_fertilizer_savings_mean=total_fert_savings,
            execution_ms=elapsed_ms,
            metadata={
                "var_95_brl_ha": var_5,
                "final_nitrogen_mean": float(np.mean(soil_out.nitrogen_kg_ha[:, -1])),
                "final_om_mean": float(np.mean(soil_out.organic_matter_pct[:, -1])),
                "annual_loss_prob": mean_annual_loss_rate,
            },
        )

    def simulate_portfolio(
        self,
        strategies: list[RotationStrategy],
        climate_stats: SeasonalClimateStats,
        config: SimulationConfig,
    ) -> list[StrategySimulationResult]:
        return [self.simulate_strategy(strat, climate_stats, config) for strat in strategies]
