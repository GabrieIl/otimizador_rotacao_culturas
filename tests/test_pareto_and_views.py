"""Testes do Semáforo Agrícola, Placar em 10, Balança, Pareto e Gráficos Plotly."""

from __future__ import annotations

from crop_optimizer.analytics import (
    build_balance_tradeoff_frame,
    build_nutrient_dynamics_frame,
    build_pareto_frontier_frame,
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.app.charts import (
    plot_balance_scale_bars,
    plot_nutrient_dynamics,
    plot_pareto_frontier,
    plot_planting_window_heatmap,
    plot_survival_scoreboard,
)
from crop_optimizer.domain.crop_registry import sequeiro_ids
from crop_optimizer.domain.models import BalancePriority, SimulationConfig, TrafficLightLevel
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
    select_by_balance_priority,
)
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def test_traffic_light_thresholds() -> None:
    assert classify_traffic_light(10.0) == TrafficLightLevel.VERDE
    assert classify_traffic_light(35.0) == TrafficLightLevel.AMARELO
    assert classify_traffic_light(75.0) == TrafficLightLevel.VERMELHO
    assert TrafficLightLevel.VERDE.label == "Verde"
    assert TrafficLightLevel.VERMELHO.guidance.startswith("Guarde")


def test_pareto_scoreboard_balance_and_charts() -> None:
    stats = SeasonalClimateStats(
        location_id="quixada_ce",
        safra_rain_mean_mm=460.0,
        safra_rain_std_mm=155.0,
        safrinha_rain_mean_mm=170.0,
        safrinha_rain_std_mm=85.0,
        safrinha_water_stress_prob=0.40,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.42,
        mean_gwet_safrinha=0.26,
        veranico_prob=0.38,
        mean_smap_moisture=0.24,
        query_ms=1.0,
    )
    engine = MonteCarloRotationEngine()
    results = engine.simulate_portfolio(
        DEFAULT_STRATEGIES,
        stats,
        SimulationConfig(location_id="quixada_ce", n_scenarios=2_000, horizon_years=5, safra_delay_days=21, veranico_days=7),
    )

    frontier = compute_pareto_frontier(results, criterion="two_year_loss")
    assert len(frontier) >= 1
    assert any(r.is_pareto_optimal for r in results)
    assert len(compute_pareto_frontier(results, criterion="profit_std")) >= 1
    assert len(compute_pareto_frontier(results, criterion="soil_risk")) >= 1
    assert len(compute_pareto_frontier(results, criterion="composite")) >= 1

    ranked = rank_by_survival(results)
    assert ranked[0].prob_two_consecutive_losses <= ranked[-1].prob_two_consecutive_losses

    forage_pick = select_by_balance_priority(results, BalancePriority.FORRAGEM)
    assert forage_pick.forage_score >= 50.0
    _ = select_by_balance_priority(results, BalancePriority.COMIDA)
    _ = select_by_balance_priority(results, BalancePriority.ESCUDO)

    df_matrix = build_planting_window_risk_matrix(stats, n_samples=2_000)
    df_scoreboard = build_survival_scoreboard_frame(results)
    df_balance = build_balance_tradeoff_frame(results)
    df_nutrients = build_nutrient_dynamics_frame(results)
    df_pareto = build_pareto_frontier_frame(results)

    assert df_matrix.height == 6 * len(sequeiro_ids())
    corn = df_matrix.filter(df_matrix["crop_id"] == "milho_sertanejo").sort("delay_days")
    assert corn["failure_prob_pct"][-1] > corn["failure_prob_pct"][0]

    assert df_scoreboard.height == len(DEFAULT_STRATEGIES)
    assert df_balance.height == len(DEFAULT_STRATEGIES) * 3
    assert df_nutrients.height > 0
    assert df_pareto.height == len(DEFAULT_STRATEGIES)

    assert len(plot_planting_window_heatmap(df_matrix).data) >= 1
    assert len(plot_survival_scoreboard(df_scoreboard).data) == 2
    assert len(plot_balance_scale_bars(df_balance).data) == 3
    assert len(plot_nutrient_dynamics(df_nutrients).data) == len(DEFAULT_STRATEGIES)
    assert len(plot_pareto_frontier(df_pareto).data) >= 1
