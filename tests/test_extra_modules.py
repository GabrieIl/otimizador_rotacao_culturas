"""Testes adicionais para módulos de atraso da chuva, terreno, geocodificação, gráficos e UI."""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

from crop_optimizer.analytics import build_nutrient_dynamics_frame
from crop_optimizer.analytics.rain_delay import (
    CropWindowStatus,
    RainDelayReport,
    crop_window_status,
    describe_status,
    fmt_date,
)
from crop_optimizer.app.charts import plot_rotation_soil, plot_rotation_years
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, location_map
from crop_optimizer.engine import MonteCarloRotationEngine
from crop_optimizer.engine.rain_onset import OnsetReference, RainSeasonStatus, VeranicoClimatology
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, inside_brazil_box, resolve_place
from crop_optimizer.ingestion.rain_history import RainDataUnavailable, fetch_rain_series
from crop_optimizer.ingestion.terrain import (
    decode_terrarium,
    horn_slope_pct,
    pixel_size_m,
    terrain_at,
)
from crop_optimizer.ingestion.zarc_tabua import ZarcWindow
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def test_rain_delay_helpers_and_status_descriptions() -> None:
    assert fmt_date(None) == "—"
    assert fmt_date(date(2026, 2, 5)) == "05/fev"

    win = ZarcWindow(
        crop_id="milho_sertanejo",
        zarc_name="MILHO",
        decendios=[4, 5, 6, 7, 8, 9],
        start_dec=4,
        end_dec=9,
        best_risk_pct=20,
        combos=3,
        portaria="Portaria ZARC 2025",
    )
    assert crop_window_status(None, "milho_sertanejo", date(2026, 1, 1), date(2026, 2, 1)).state == "sem_indicacao"
    st_before = crop_window_status(win, "milho_sertanejo", date(2026, 1, 1), date(2026, 1, 5))
    assert st_before.state == "ainda_nao_abriu"
    assert "abre" in st_before.phrase
    st_open = crop_window_status(win, "milho_sertanejo", date(2026, 1, 1), date(2026, 2, 15))
    assert st_open.state == "aberta"
    assert "faltam" in st_open.phrase
    st_closed = crop_window_status(win, "milho_sertanejo", date(2026, 1, 1), date(2026, 4, 15))
    assert st_closed.state == "fechou"
    assert "fechou" in st_closed.phrase
    assert CropWindowStatus("x", None, "sem_indicacao").phrase.startswith("Sem indicação")

    loc = location_map()["petrolina_pe"]
    ref = OnsetReference(
        hydro_start_month=1,
        first_year=1991,
        last_year=2020,
        season_years=[2019, 2020],
        offsets=[10, 25],
        median_offset=24,
        p25_offset=9,
        p75_offset=40,
    )
    for state_name in ("sem_referencia", "antes_da_epoca", "atrasada", "firmando", "firmou"):
        status = RainSeasonStatus(
            as_of=date(2026, 3, 1),
            season_start=date(2026, 1, 1),
            data_until=date(2026, 3, 1),
            season_label="2026",
            reference_date=date(2026, 1, 25),
            reference_early=date(2026, 1, 10),
            reference_late=None if state_name == "sem_referencia" else date(2026, 2, 10),
            onset_date=date(2026, 2, 15) if state_name in ("firmando", "firmou") else None,
            delay_days=21,
            state=state_name,  # type: ignore[arg-type]
            rain_season_mm=180.0,
            still_came_of_10=6 if state_name == "atrasada" else None,
            reference=ref,
        )
        title, expl, level = describe_status(status)
        assert title and expl and level in ("info", "success", "warning", "error")

    rep = RainDelayReport(
        location=loc,
        status=RainSeasonStatus(
            as_of=date(2026, 3, 1),
            season_start=date(2026, 1, 1),
            data_until=date(2026, 3, 1),
            season_label="2026",
            reference_date=date(2026, 1, 25),
            reference_early=date(2026, 1, 10),
            reference_late=date(2026, 2, 10),
            onset_date=date(2026, 2, 1),
            delay_days=7,
            state="firmou",
            rain_season_mm=220.0,
            still_came_of_10=None,
            reference=ref,
        ),
        source="NASA",
        veranico=VeranicoClimatology(
            min_days=10,
            window_days=90,
            seasons_with_onset=10,
            longest_spells=(5, 12, 14, 8, 10, 4, 6, 15, 7, 9),
        ),
        dry_days_now=12,
    )
    assert rep.veranico_alert is not None
    assert "Veranico" in rep.veranico_alert
    assert rep.motor_delay_days >= 0


def test_rain_history_cache_and_failure(tmp_path: Path) -> None:
    settings = get_settings(data_dir=tmp_path)
    loc = location_map()["petrolina_pe"]

    with (
        patch("crop_optimizer.ingestion.rain_history.httpx.Client", side_effect=RuntimeError("offline")),
        pytest.raises(RainDataUnavailable),
    ):
        fetch_rain_series(loc, today=date(2026, 3, 1), settings=settings)

    payload = {
        "properties": {
            "parameter": {
                "PRECTOTCORR": {"20250101": 12.0, "20250102": -999.0}
            }
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None
    with patch("crop_optimizer.ingestion.rain_history.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        series = fetch_rain_series(loc, today=date(2026, 3, 1), settings=settings)
        assert series.last_valid_date == date(2025, 1, 1)


def test_terrain_and_geocode_with_mocked_cache(tmp_path: Path) -> None:
    settings = get_settings(data_dir=tmp_path)
    rgb = np.array([[[128, 100, 0]]], dtype=np.uint8)
    assert decode_terrarium(rgb)[0, 0] == pytest.approx(100.0)
    grid = np.full((3, 3), 100.0)
    assert horn_slope_pct(grid, 30.0) == 0.0
    assert pixel_size_m(-9.38, 12) > 0.0

    # Mock PNG tile download
    img = Image.new("RGB", (256, 256), color=(129, 100, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    mock_resp = MagicMock()
    mock_resp.content = buf.getvalue()
    mock_resp.raise_for_status.return_value = None
    with patch("crop_optimizer.ingestion.terrain.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        info = terrain_at(-9.3891, -40.5030, settings=settings)
        assert info.elevation_m == pytest.approx(356.0)
        assert info.slope_pct == pytest.approx(0.0)

    assert inside_brazil_box(-9.38, -40.50)
    assert not inside_brazil_box(40.0, -70.0)
    with pytest.raises(GeocodeUnavailable):
        resolve_place(40.0, -70.0, settings=settings)

    # Pre-seed nominatim & ibge bronze cache to test resolve_place offline
    nom_dir = settings.paths.bronze_source("nominatim")
    ibge_dir = settings.paths.bronze_source("ibge")
    (nom_dir / "reverse_-9.3891_-40.5030_z10.json").write_text(
        json.dumps({"address": {"country_code": "br", "city": "Petrolina", "ISO3166-2-lvl4": "BR-PE"}}),
        encoding="utf-8",
    )
    (ibge_dir / "municipios_PE.json").write_text(
        json.dumps([{"id": 2611101, "nome": "Petrolina"}]),
        encoding="utf-8",
    )
    place = resolve_place(-9.3891, -40.5030, settings=settings)
    assert place.ibge_code == "2611101"

    from crop_optimizer.ingestion.geocode import place_from_address

    rural = place_from_address(
        {"village": "Izacolândia", "municipality": "Petrolina", "ISO3166-2-lvl4": "BR-PE", "country_code": "br"},
        [{"id": 2611101, "nome": "Petrolina"}],
    )
    assert (rural.municipio, rural.ibge_code) == ("Petrolina", "2611101")


def test_dashboard_zarc_data_handles_errors_and_windows() -> None:
    from crop_optimizer.analytics.rain_delay import ZarcStatusReport
    from crop_optimizer.app.dashboard import _zarc_data

    err_res = ZarcStatusReport(zarc_safra="2026/2027", zarc_error="Portal fora do ar")
    out_err = _zarc_data("milho_sertanejo", None, date(2026, 2, 10), err_res, "Petrolina/PE")
    assert out_err["has_window"] is False
    assert out_err["state_txt"] == "ZARC indisponível"
    assert "Portal fora do ar" in out_err["detail"]

    win = ZarcWindow(
        crop_id="feijao_caupi",
        zarc_name="Feijão Caupi",
        decendios=[4, 5, 6],
        start_dec=4,
        end_dec=6,
        best_risk_pct=20,
        combos=2,
        portaria="Port. 123",
    )
    cw = crop_window_status(win, "feijao_caupi", date(2026, 1, 1), date(2026, 2, 15))
    decs = [20 if i in (4, 5, 6) else 0 for i in range(1, 37)]
    ok_res = ZarcStatusReport(
        crop_windows=[cw],
        zarc_safra="2026/2027",
        zarc_error=None,
        decendios_by_crop={"feijao_caupi": decs},
    )
    out_ok = _zarc_data("feijao_caupi", cw, date(2026, 2, 15), ok_res, "Petrolina/PE")
    assert out_ok["has_window"] is True
    assert out_ok["decendios"][3] == 20
    assert "Petrolina/PE" in out_ok["source"]
    assert "Port. 123" in out_ok["source"]


def test_rotation_detail_charts_and_streamlit_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats = SeasonalClimateStats(
        location_id="petrolina_pe",
        safra_rain_mean_mm=430.0,
        safra_rain_std_mm=150.0,
        safrinha_rain_mean_mm=165.0,
        safrinha_rain_std_mm=80.0,
        safrinha_water_stress_prob=0.45,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.40,
        mean_gwet_safrinha=0.25,
        veranico_prob=0.35,
        mean_smap_moisture=0.23,
        query_ms=1.0,
    )
    cfg = SimulationConfig(location_id="petrolina_pe", n_scenarios=500)
    results = MonteCarloRotationEngine().simulate_portfolio(DEFAULT_STRATEGIES, stats, cfg)
    fig_years = plot_rotation_years(results[0], cfg.family_food_target_kg_year, cfg.herd_forage_target_kg_year)
    assert len(fig_years.data) >= 4
    df_nutrients = build_nutrient_dynamics_frame(results)
    fig_soil = plot_rotation_soil(df_nutrients, results[0].strategy.short_name)
    assert len(fig_soil.data) == 1

    monkeypatch.setenv("CROP_OPT_DATA_DIR", str(tmp_path))
    dash_path = Path(__file__).resolve().parents[1] / "src" / "crop_optimizer" / "app" / "dashboard.py"
    at = AppTest.from_file(str(dash_path), default_timeout=20)
    at.run()
    assert not at.exception
