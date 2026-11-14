"""Teste ponta a ponta: CLI ELT + Lakehouse + Simulação do Sertão."""

from __future__ import annotations

from pathlib import Path

from crop_optimizer.cli import main as cli_main


def test_cli_elt_and_simulate_end_to_end(tmp_path: Path) -> None:
    cli_main(["elt", "--data-dir", str(tmp_path), "--mode", "offline"])
    cli_main([
        "simulate",
        "--location",
        "petrolina_pe",
        "--scenarios",
        "2000",
        "--years",
        "5",
        "--delay-days",
        "14",
        "--veranico-days",
        "7",
        "--data-dir",
        str(tmp_path),
    ])
