"""Script de benchmark: valida leitura DuckDB (<50ms) e 10.000 cenários Monte Carlo (<5s)."""

from _bootstrap import ensure_venv

ensure_venv()

from crop_optimizer.cli import cmd_simulate  # noqa: E402

if __name__ == "__main__":
    cmd_simulate(location_id="petrolina_pe", n_scenarios=10_000, horizon_years=5, delay_days=14, veranico_days=7)
