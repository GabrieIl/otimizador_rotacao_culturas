"""Otimizador da Fronteira de Pareto, Ranqueamento de Sobrevivência e Balança de Prioridades."""

from __future__ import annotations

from typing import Literal

from crop_optimizer.domain.models import BalancePriority, StrategySimulationResult

RiskCriterion = Literal["profit_std", "soil_risk", "composite", "two_year_loss"]


def _risk_value(result: StrategySimulationResult, criterion: RiskCriterion) -> float:
    if criterion == "profit_std":
        return result.profit_std_brl_ha
    if criterion == "soil_risk":
        return (4.0 - result.final_soil_score_mean) + result.final_soil_score_std
    if criterion == "two_year_loss":
        return result.prob_two_consecutive_losses
    soil_penalty = max(0.0, 2.8 - result.final_soil_score_mean) * 650.0
    survival_penalty = result.prob_two_consecutive_losses * 4_000.0
    return result.profit_std_brl_ha + soil_penalty + survival_penalty


def _return_value(result: StrategySimulationResult, criterion: RiskCriterion) -> float:
    if criterion == "two_year_loss":
        return result.expected_food_kg_ha_year + 0.35 * result.expected_forage_kg_ha_year
    return result.expected_npv_brl_ha


def compute_pareto_frontier(
    results: list[StrategySimulationResult],
    criterion: RiskCriterion = "two_year_loss",
) -> list[StrategySimulationResult]:
    """Identifica estratégias não-dominadas e atualiza `is_pareto_optimal`."""
    for res in results:
        res.is_pareto_optimal = False

    risks = [_risk_value(r, criterion) for r in results]
    returns = [_return_value(r, criterion) for r in results]

    frontier: list[StrategySimulationResult] = []
    for i, cand in enumerate(results):
        dominated = False
        for j in range(len(results)):
            if i == j:
                continue
            better_or_eq_return = returns[j] >= returns[i]
            better_or_eq_risk = risks[j] <= risks[i]
            strictly_better = (returns[j] > returns[i]) or (risks[j] < risks[i])
            if better_or_eq_return and better_or_eq_risk and strictly_better:
                dominated = True
                break
        if not dominated:
            cand.is_pareto_optimal = True
            frontier.append(cand)

    frontier.sort(key=lambda r: _risk_value(r, criterion))
    return frontier


def rank_by_survival(results: list[StrategySimulationResult]) -> list[StrategySimulationResult]:
    """Ranqueia rotações minimizando a probabilidade de 2 quebras de safra seguidas."""
    return sorted(
        results,
        key=lambda r: (
            r.prob_two_consecutive_losses,
            r.prob_herd_collapse,
            -r.survival_score_of_10,
            -(r.expected_food_kg_ha_year + 0.25 * r.expected_forage_kg_ha_year),
        ),
    )


# pesos de (grãos, forragem, estabilidade, renda) por prioridade
_PRIORITY_WEIGHTS = {
    BalancePriority.EQUILIBRADO: (0.25, 0.25, 0.25, 0.25),
    BalancePriority.COMIDA: (0.55, 0.10, 0.20, 0.15),
    BalancePriority.FORRAGEM: (0.10, 0.55, 0.20, 0.15),
    BalancePriority.ESCUDO: (0.15, 0.15, 0.55, 0.15),
    BalancePriority.RENDA: (0.15, 0.10, 0.20, 0.55),
}


def annual_profit(result: StrategySimulationResult) -> float:
    """Renda líquida média por ano (R$/ha), com os preços e custos de referência do motor."""
    return float(result.metadata.get("annual_profit_mean", 0.0))


def income_scores(results: list[StrategySimulationResult]) -> dict[int, float]:
    """Nota 0-100 da renda, relativa às rotações comparadas (a melhor = 100, a pior = 0)."""
    values = {id(r): annual_profit(r) for r in results}
    low, high = min(values.values(), default=0.0), max(values.values(), default=0.0)
    if high - low < 1e-9:
        return {k: 50.0 for k in values}
    return {k: 100.0 * (v - low) / (high - low) for k, v in values.items()}


def balance_score(result: StrategySimulationResult, priority: BalancePriority, income_score: float = 50.0) -> float:
    """Nota 0-100 da rotação com os pesos da prioridade (grãos, forragem, estabilidade, renda)."""
    w_food, w_forage, w_shield, w_income = _PRIORITY_WEIGHTS[priority]
    return (w_food * result.food_score + w_forage * result.forage_score + w_shield * result.shield_score
            + w_income * income_score)


def rank_by_balance_priority(
    results: list[StrategySimulationResult],
    priority: BalancePriority = BalancePriority.EQUILIBRADO,
) -> list[tuple[StrategySimulationResult, float]]:
    """Todas as rotações, da melhor para a pior, com a nota da prioridade escolhida."""
    income = income_scores(results)
    scored = [(r, balance_score(r, priority, income[id(r)])) for r in results]
    return sorted(scored, key=lambda item: item[1], reverse=True)


def select_by_balance_priority(
    results: list[StrategySimulationResult],
    priority: BalancePriority = BalancePriority.EQUILIBRADO,
) -> StrategySimulationResult:
    """Seleciona a rotação ideal conforme o que pesa mais (grãos, forragem, estabilidade, renda)."""
    return rank_by_balance_priority(results, priority)[0][0]
