"""Camada de interface interativa (Streamlit + Plotly)."""

from crop_optimizer.app.charts import (
    plot_balance_scale_bars,
    plot_nutrient_dynamics,
    plot_pareto_frontier,
    plot_planting_window_heatmap,
    plot_survival_scoreboard,
)

__all__ = [
    "plot_balance_scale_bars",
    "plot_nutrient_dynamics",
    "plot_pareto_frontier",
    "plot_planting_window_heatmap",
    "plot_survival_scoreboard",
]
