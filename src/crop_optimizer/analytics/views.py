"""Tradutores das simulações matemáticas para as visões inclusivas e técnicas do Sertão."""

from __future__ import annotations

import numpy as np
import polars as pl

from crop_optimizer.domain.models import (
    CropSpec,
    SimulationConfig,
    StrategySimulationResult,
    TrafficLightLevel,
)
from crop_optimizer.domain.presets import crop_map
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def loss_risk_label(horizon_years: int) -> str:
    """Rótulo do risco que o motor calcula: 2 quebras de safra seguidas; com 1 ano, a quebra no ano."""
    return "risco de 2 quebras de safra seguidas" if horizon_years >= 2 else "risco de quebra de safra no ano"


def classify_traffic_light(failure_prob_pct: float) -> TrafficLightLevel:
    """Converte probabilidade de quebra em Semáforo Agrícola (Verde / Amarelo / Vermelho)."""
    if failure_prob_pct < 25.0:
        return TrafficLightLevel.VERDE
    if failure_prob_pct < 55.0:
        return TrafficLightLevel.AMARELO
    return TrafficLightLevel.VERMELHO


def build_planting_window_risk_matrix(
    climate_stats: SeasonalClimateStats,
    target_crops: list[CropSpec] | None = None,
    delay_days_grid: list[int] | None = None,
    n_samples: int = 10_000,
    seed: int = 42,
    config: SimulationConfig | None = None,
) -> pl.DataFrame:
    """
    Visão 1 (Semáforo Agrícola): Matriz de Atraso das Chuvas x Culturas.

    Usa o MESMO motor do ranking das rotações (cada cultura plantada sozinha, 1 ano), com o veranico
    sorteado do histórico real e a mesma régua de quebra de safra (config/colheita.yaml).
    `config` traz o solo de hoje (estado, matéria orgânica, nitrogênio, fator por cultura); o
    `veranico_days` dele é um veranico FIXO somado ao sorteado (o app usa 0).
    """
    catalog = crop_map()
    targets = target_crops or [
        catalog["milho_sertanejo"],
        catalog["feijao_caupi"],
        catalog["sorgo_forrageiro"],
        catalog["palma_forrageira"],
        catalog["capim_buffel"],
    ]
    delays = delay_days_grid or [0, 7, 14, 21, 28, 35]
    base = (config or SimulationConfig()).model_copy(
        update={"n_scenarios": n_samples, "seed": seed}
    )
    engine = MonteCarloRotationEngine(crops_catalog=catalog)

    rows: list[dict[str, object]] = []
    for delay in delays:
        cfg = base.model_copy(update={"safra_delay_days": delay})
        for crop in targets:
            failure_pct = engine.harvest_failure_prob(crop.crop_id, climate_stats, cfg) * 100.0
            light = classify_traffic_light(failure_pct)
            rows.append(
                {
                    "delay_days": delay,
                    "delay_label": f"+{delay} dias" if delay > 0 else "No Tempo (0d)",
                    "crop_id": crop.crop_id,
                    "crop_name": crop.name,
                    "failure_prob_pct": round(failure_pct, 1),
                    "traffic_light": light.value,
                    "traffic_guidance": light.guidance,
                    "cell_display": f"{light.label}: {light.guidance}",
                }
            )
    return pl.DataFrame(rows)


def build_survival_scoreboard_frame(results: list[StrategySimulationResult]) -> pl.DataFrame:
    """Visão 2: Placar de Sobrevivência das Rotações ('Em quantos de 10 anos você sobrevive')."""
    rows: list[dict[str, object]] = []
    for res in results:
        rows.append(
            {
                "strategy_id": res.strategy.strategy_id,
                "strategy_name": res.strategy.name,
                "short_name": res.strategy.short_name or res.strategy.name,
                "survival_score_of_10": res.survival_score_of_10,
                "loss_years_of_10": res.loss_years_of_10,
                "survival_phrase": f"Sobrevive {res.survival_score_of_10} de 10 anos",
                "loss_phrase": f"Perde a roça em {res.loss_years_of_10} de 10",
                "prob_two_consecutive_losses_pct": round(res.prob_two_consecutive_losses * 100.0, 1),
                "prob_herd_collapse_pct": round(res.prob_herd_collapse * 100.0, 1),
                "expected_food_kg_ha_year": round(res.expected_food_kg_ha_year, 1),
                "expected_forage_kg_ha_year": round(res.expected_forage_kg_ha_year, 1),
                "food_score": res.food_score,
                "forage_score": res.forage_score,
                "shield_score": res.shield_score,
            }
        )
    return pl.DataFrame(rows).sort("prob_two_consecutive_losses_pct")


def build_balance_tradeoff_frame(results: list[StrategySimulationResult]) -> pl.DataFrame:
    """Visão 3: Dados para a Balança Comida x Forragem x Escudo."""
    rows: list[dict[str, object]] = []
    for res in results:
        short = res.strategy.short_name or res.strategy.name
        rows.extend(
            [
                {
                    "strategy_id": res.strategy.strategy_id,
                    "strategy_name": short,
                    "pillar": "Comida (Grão)",
                    "score": res.food_score,
                    "raw_label": f"{res.expected_food_kg_ha_year:,.0f} kg/ha·ano",
                },
                {
                    "strategy_id": res.strategy.strategy_id,
                    "strategy_name": short,
                    "pillar": "Forragem (Rebanho)",
                    "score": res.forage_score,
                    "raw_label": f"{res.expected_forage_kg_ha_year:,.0f} kg/ha·ano",
                },
                {
                    "strategy_id": res.strategy.strategy_id,
                    "strategy_name": short,
                    "pillar": "Escudo (Anti-Colapso)",
                    "score": res.shield_score,
                    "raw_label": f"{100.0 - res.prob_two_consecutive_losses * 100.0:.1f}% seguro",
                },
            ]
        )
    return pl.DataFrame(rows)


def build_nutrient_dynamics_frame(results: list[StrategySimulationResult]) -> pl.DataFrame:
    """Dinâmica de Nutrientes do solo (N, Matéria Orgânica e economia com insumos)."""
    rows: list[dict[str, object]] = []
    for res in results:
        n_traj = res.soil_output.nitrogen_kg_ha
        om_traj = res.soil_output.organic_matter_pct
        cum_savings = np.zeros_like(n_traj)
        cum_savings[:, 1:] = np.cumsum(res.soil_output.fertilizer_savings_brl_ha, axis=1)

        labels = ["Início", *res.step_labels]
        for idx, label in enumerate(labels):
            rows.append(
                {
                    "strategy_id": res.strategy.strategy_id,
                    "strategy_name": res.strategy.short_name or res.strategy.name,
                    "step_index": idx,
                    "step_label": label,
                    "nitrogen_mean_kg_ha": round(float(np.mean(n_traj[:, idx])), 2),
                    "nitrogen_p10_kg_ha": round(float(np.percentile(n_traj[:, idx], 10)), 2),
                    "nitrogen_p90_kg_ha": round(float(np.percentile(n_traj[:, idx], 90)), 2),
                    "om_mean_pct": round(float(np.mean(om_traj[:, idx])), 3),
                    "om_p10_pct": round(float(np.percentile(om_traj[:, idx], 10)), 3),
                    "om_p90_pct": round(float(np.percentile(om_traj[:, idx], 90)), 3),
                    "cum_fertilizer_savings_brl_ha": round(float(np.mean(cum_savings[:, idx])), 2),
                }
            )
    return pl.DataFrame(rows)


def build_pareto_frontier_frame(results: list[StrategySimulationResult]) -> pl.DataFrame:
    """Consolida métricas de sobrevivência, biomassa, solo e finanças para a visão técnica."""
    rows: list[dict[str, object]] = []
    for res in results:
        rows.append(
            {
                "strategy_id": res.strategy.strategy_id,
                "strategy_name": res.strategy.name,
                "short_name": res.strategy.short_name or res.strategy.name,
                "sequence": " → ".join(res.strategy.annual_sequence),
                "survival_score_of_10": res.survival_score_of_10,
                "loss_years_of_10": res.loss_years_of_10,
                "prob_two_consecutive_losses_pct": round(res.prob_two_consecutive_losses * 100.0, 2),
                "prob_herd_collapse_pct": round(res.prob_herd_collapse * 100.0, 2),
                "expected_food_kg_ha_year": round(res.expected_food_kg_ha_year, 1),
                "expected_forage_kg_ha_year": round(res.expected_forage_kg_ha_year, 1),
                "expected_npv_brl_ha": round(res.expected_npv_brl_ha, 2),
                "profit_std_brl_ha": round(res.profit_std_brl_ha, 2),
                "cvar_95_brl_ha": round(res.cvar_95_brl_ha, 2),
                "prob_loss_pct": round(res.prob_loss * 100.0, 2),
                "final_soil_score": round(res.final_soil_score_mean, 3),
                "soil_risk_index": round((4.0 - res.final_soil_score_mean) + res.final_soil_score_std, 3),
                "fertilizer_savings_brl_ha": round(res.total_fertilizer_savings_mean, 2),
                "final_nitrogen_kg_ha": round(res.metadata.get("final_nitrogen_mean", 0.0), 2),
                "final_om_pct": round(res.metadata.get("final_om_mean", 0.0), 3),
                "is_pareto_optimal": res.is_pareto_optimal,
                "execution_ms": round(res.execution_ms, 2),
            }
        )
    return pl.DataFrame(rows).sort("prob_two_consecutive_losses_pct")
