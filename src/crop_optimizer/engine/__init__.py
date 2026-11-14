"""Motor matemático: Cadeias de Markov, Monte Carlo de Sobrevivência e Otimização."""

from crop_optimizer.engine.markov_soil import MarkovSoilModel, build_transition_matrix
from crop_optimizer.engine.monte_carlo import MonteCarloRotationEngine
from crop_optimizer.engine.pareto import (
    RiskCriterion,
    compute_pareto_frontier,
    rank_by_survival,
    select_by_balance_priority,
)

__all__ = [
    "MarkovSoilModel",
    "MonteCarloRotationEngine",
    "RiskCriterion",
    "build_transition_matrix",
    "compute_pareto_frontier",
    "rank_by_survival",
    "select_by_balance_priority",
]
