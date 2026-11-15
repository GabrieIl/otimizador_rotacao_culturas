"""CLI unificada para ELT assíncrono, simulação de sobrevivência, API WhatsApp e Dashboard."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn

from crop_optimizer.accessibility import compose_radio_script
from crop_optimizer.analytics import (
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.api import create_app
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, location_map
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
)
from crop_optimizer.lakehouse.catalog import LakehouseCatalog


def cmd_elt(data_dir: str | None = None, mode: str | None = None) -> None:
    settings = get_settings(data_dir)
    if mode in ("offline", "online"):
        settings.ingestion_mode = mode  # type: ignore[assignment]
    summary = CropLakehouseEltPipeline(settings).run()
    print(
        f"[ELT] Concluído em {summary.elapsed_ms:.1f} ms | "
        f"Clima: {summary.climate_rows} linhas | "
        f"ZARC: {summary.zarc_rows} | Mercado: {summary.market_rows}"
    )


def cmd_simulate(
    location_id: str = "petrolina_pe",
    n_scenarios: int = 10_000,
    horizon_years: int = 5,
    delay_days: int = 14,
    veranico_days: int = 7,
    data_dir: str | None = None,
) -> None:
    settings = get_settings(data_dir)
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()

    stats = catalog.get_seasonal_climate_stats(location_id)
    locs = {loc.location_id: loc for loc in catalog.load_locations()}
    location = locs.get(location_id) or location_map()["petrolina_pe"]
    crops = {c.crop_id: c for c in catalog.load_crops()}
    catalog.close()

    engine = MonteCarloRotationEngine(crops_catalog=crops)
    config = SimulationConfig(
        location_id=location_id,
        n_scenarios=n_scenarios,
        horizon_years=horizon_years,
        safra_delay_days=delay_days,
        veranico_days=veranico_days,
    )
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, stats, config)
    compute_pareto_frontier(results, criterion="two_year_loss")
    ranked = rank_by_survival(results)
    scoreboard = build_survival_scoreboard_frame(results)

    matrix = build_planting_window_risk_matrix(
        stats,
        delay_days_grid=[delay_days],
        n_samples=min(2_000, n_scenarios),
        config=config,
    )
    corn_row = matrix.filter(matrix["crop_id"] == "milho_sertanejo")
    light = classify_traffic_light(float(corn_row["failure_prob_pct"][0]))

    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    resilient = ranked[0]

    total_ms = sum(r.execution_ms for r in results)
    print(f"[DuckDB] Consulta climática ({location_id}): {stats.query_ms:.2f} ms")
    print(
        f"[Monte Carlo] {len(results)} estratégias x {n_scenarios:,} cenários "
        f"em {total_ms:.1f} ms ({total_ms / 1000.0:.3f} s) | Semáforo: {light.label} - {light.guidance}"
    )
    print(
        scoreboard.select(
            [
                "short_name",
                "survival_score_of_10",
                "prob_two_consecutive_losses_pct",
                "expected_food_kg_ha_year",
                "expected_forage_kg_ha_year",
                "food_score",
                "forage_score",
                "shield_score",
            ]
        )
    )
    print("\n[Rádio do Tempo]")
    print(compose_radio_script(config.farmer_name, location, delay_days, light, traditional, resilient))


def cmd_app() -> None:
    dashboard_path = Path(__file__).resolve().parent / "app" / "dashboard.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)], check=True)


def cmd_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(create_app(), host=host, port=port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="crop-opt",
        description="Motor Estocástico de Resiliência do Sertão",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_elt = subparsers.add_parser("elt", help="Executa pipeline ELT assíncrono (Bronze -> Silver -> Gold Parquet)")
    p_elt.add_argument("--data-dir", default=None)
    p_elt.add_argument("--mode", choices=["offline", "online"], default=None)

    p_sim = subparsers.add_parser("simulate", help="Roda benchmark DuckDB + Monte Carlo (10k cenários)")
    p_sim.add_argument("--location", default="petrolina_pe")
    p_sim.add_argument("--scenarios", type=int, default=10_000)
    p_sim.add_argument("--years", type=int, default=5)
    p_sim.add_argument("--delay-days", type=int, default=14)
    p_sim.add_argument("--veranico-days", type=int, default=7)
    p_sim.add_argument("--data-dir", default=None)

    subparsers.add_parser("app", help="Inicia o dashboard interativo Streamlit")

    p_api = subparsers.add_parser("api", help="Inicia API HTTP para Rádio do Tempo, PDF e Webhook Twilio")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "elt":
        cmd_elt(data_dir=args.data_dir, mode=args.mode)
    elif args.command == "simulate":
        cmd_simulate(
            location_id=args.location,
            n_scenarios=args.scenarios,
            horizon_years=args.years,
            delay_days=args.delay_days,
            veranico_days=args.veranico_days,
            data_dir=args.data_dir,
        )
    elif args.command == "app":
        cmd_app()
    elif args.command == "api":
        cmd_api(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
