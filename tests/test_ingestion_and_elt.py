"""Testes da camada de ingestão assíncrona/síncrona, ELT Star Schema Parquet e consultas DuckDB."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crop_optimizer.config import get_settings
from crop_optimizer.domain.presets import DEFAULT_CROPS, DEFAULT_LOCATIONS, location_map
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.ingestion import NasaAppeearsClient, NasaPowerClient
from crop_optimizer.lakehouse.catalog import LakehouseCatalog


def test_elt_builds_partitioned_star_schema_and_duckdb_queries(tmp_path: Path) -> None:
    settings = get_settings(data_dir=tmp_path)
    pipeline = CropLakehouseEltPipeline(settings=settings)
    summary = pipeline.run(start_date=date(2020, 1, 1), end_date=date(2022, 12, 31))

    assert summary.locations_count == 4
    assert summary.crops_count == len(DEFAULT_CROPS)
    assert summary.climate_rows > 4000

    assert settings.paths.dim_location.exists()
    assert settings.paths.dim_crop.exists()
    assert settings.paths.dim_zarc_window.exists()
    assert settings.paths.dim_market_price.exists()
    assert any(settings.paths.fact_climate_daily.rglob("*.parquet"))

    catalog = LakehouseCatalog(settings)
    assert catalog.is_ready()

    stats = catalog.get_seasonal_climate_stats("petrolina_pe")
    assert stats.safra_rain_mean_mm > 100.0
    assert 0.0 <= stats.veranico_prob <= 1.0
    assert stats.query_ms < 1000.0

    zarc = catalog.get_zarc_windows("quixada_ce")
    assert zarc.height == summary.crops_count
    prices = catalog.get_market_prices()
    assert prices.height == summary.crops_count
    annual = catalog.get_annual_climate_summary("petrolina_pe")
    assert annual.height == 3
    assert "veranico_days" in annual.columns
    catalog.close()


def test_async_elt_and_lakehouse_error_when_uninitialized(tmp_path: Path) -> None:
    settings = get_settings(data_dir=tmp_path)
    catalog = LakehouseCatalog(settings)
    assert not catalog.is_ready()
    with pytest.raises(FileNotFoundError):
        catalog.connect()

    pipeline = CropLakehouseEltPipeline(settings=settings)
    summary = asyncio.run(
        pipeline.run_async(
            locations=DEFAULT_LOCATIONS[:2],
            start_date=date(2021, 1, 1),
            end_date=date(2021, 12, 31),
        )
    )
    assert summary.locations_count == 2
    assert summary.climate_rows == 365 * 2


def test_online_nasa_clients_parse_and_fallback() -> None:
    loc = location_map()["petrolina_pe"]
    sample_payload = {
        "properties": {
            "parameter": {
                "T2M": {"20240101": 28.0, "20240102": 29.0},
                "T2M_MIN": {"20240101": 21.0, "20240102": 22.0},
                "T2M_MAX": {"20240101": 35.0, "20240102": 36.0},
                "PRECTOTCORR": {"20240101": 12.5, "20240102": 0.0},
                "ALLSKY_SFC_SW_DWN": {"20240101": 20.0, "20240102": 22.0},
                "GWETROOT": {"20240101": 0.45, "20240102": 0.42},
            }
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = sample_payload
    mock_resp.raise_for_status.return_value = None

    power_online = NasaPowerClient(mode="online")
    with patch("crop_optimizer.ingestion.nasa_power.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value = mock_resp
        df_sync = power_online.fetch_daily_climate(loc, date(2024, 1, 1), date(2024, 1, 2))
        assert df_sync.height == 2
        assert df_sync["source"][0] == "nasa_power_chirps_api"

    with patch("crop_optimizer.ingestion.nasa_power.httpx.AsyncClient") as mock_async:
        async_inst = mock_async.return_value.__aenter__.return_value
        async_inst.get = AsyncMock(return_value=mock_resp)
        df_async = asyncio.run(
            power_online.fetch_daily_climate_async(loc, date(2024, 1, 1), date(2024, 1, 2))
        )
        assert df_async.height == 2

    # Fallback quando rede falha
    with patch("crop_optimizer.ingestion.nasa_power.httpx.Client", side_effect=RuntimeError("offline")):
        df_fb = power_online.fetch_daily_climate(loc, date(2024, 1, 1), date(2024, 1, 5))
        assert df_fb.height == 5
        assert df_fb["source"][0] == "chirps_nasa_power_calibrated"

    appeears = NasaAppeearsClient(mode="online", token="fake-token")
    with patch("crop_optimizer.ingestion.nasa_appeears.httpx.Client", side_effect=RuntimeError("offline")):
        df_soil = appeears.fetch_soil_moisture(loc, date(2024, 1, 1), date(2024, 1, 4))
        assert df_soil.height == 4
