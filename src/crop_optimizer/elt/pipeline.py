"""Pipeline ELT assíncrono e síncrono (Bronze -> Silver -> Gold Star Schema em Parquet)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import date

import polars as pl
import pyarrow.dataset as ds

from crop_optimizer.config import Settings, get_settings
from crop_optimizer.domain.models import CropSpec, LocationSpec
from crop_optimizer.domain.presets import DEFAULT_CROPS, DEFAULT_LOCATIONS
from crop_optimizer.ingestion import (
    B3MarketDataSource,
    ClimateDataSource,
    EmbrapaZarcSource,
    MarketDataSource,
    NasaAppeearsClient,
    NasaPowerClient,
    SoilRemoteSensingSource,
    ZarcDataSource,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EltSummary:
    """Resumo de execução do pipeline ELT."""

    climate_rows: int
    zarc_rows: int
    market_rows: int
    locations_count: int
    crops_count: int
    elapsed_ms: float


class CropLakehouseEltPipeline:
    """Orquestra extração assíncrona, normalização e escrita do Star Schema em Parquet."""

    def __init__(
        self,
        settings: Settings | None = None,
        climate_source: ClimateDataSource | None = None,
        soil_source: SoilRemoteSensingSource | None = None,
        zarc_source: ZarcDataSource | None = None,
        market_source: MarketDataSource | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.climate_source = climate_source or NasaPowerClient(
            mode=self.settings.ingestion_mode,
            base_url=self.settings.nasa_power_base_url,
            seed=self.settings.random_seed,
        )
        self.soil_source = soil_source or NasaAppeearsClient(
            mode=self.settings.ingestion_mode,
            base_url=self.settings.nasa_appeears_base_url,
            token=self.settings.nasa_appeears_token,
            seed=self.settings.random_seed + 59,
        )
        self.zarc_source = zarc_source or EmbrapaZarcSource()
        self.market_source = market_source or B3MarketDataSource()

    def run(
        self,
        locations: list[LocationSpec] | None = None,
        crops: list[CropSpec] | None = None,
        start_date: date = date(2005, 1, 1),
        end_date: date = date(2025, 12, 31),
    ) -> EltSummary:
        """Executa o pipeline ELT (usa loop assíncrono internamente quando não há loop ativo)."""
        try:
            asyncio.get_running_loop()
            return self._run_sync(locations=locations, crops=crops, start_date=start_date, end_date=end_date)
        except RuntimeError:
            return asyncio.run(
                self.run_async(locations=locations, crops=crops, start_date=start_date, end_date=end_date)
            )

    async def run_async(
        self,
        locations: list[LocationSpec] | None = None,
        crops: list[CropSpec] | None = None,
        start_date: date = date(2005, 1, 1),
        end_date: date = date(2025, 12, 31),
    ) -> EltSummary:
        """Executa ingestão paralela assíncrona via asyncio.gather e materializa Star Schema."""
        t0 = time.perf_counter()
        locs = locations or DEFAULT_LOCATIONS
        crop_list = crops or DEFAULT_CROPS

        climate_tasks = [
            self.climate_source.fetch_daily_climate_async(loc, start_date, end_date)
            for loc in locs
        ]
        soil_tasks = [
            self.soil_source.fetch_soil_moisture_async(loc, start_date, end_date)
            for loc in locs
        ]
        climate_frames, soil_frames = await asyncio.gather(
            asyncio.gather(*climate_tasks),
            asyncio.gather(*soil_tasks),
        )
        return self._transform_and_load(locs, crop_list, list(climate_frames), list(soil_frames), t0)

    def _run_sync(
        self,
        locations: list[LocationSpec] | None,
        crops: list[CropSpec] | None,
        start_date: date,
        end_date: date,
    ) -> EltSummary:
        t0 = time.perf_counter()
        locs = locations or DEFAULT_LOCATIONS
        crop_list = crops or DEFAULT_CROPS
        climate_frames = [self.climate_source.fetch_daily_climate(loc, start_date, end_date) for loc in locs]
        soil_frames = [self.soil_source.fetch_soil_moisture(loc, start_date, end_date) for loc in locs]
        return self._transform_and_load(locs, crop_list, climate_frames, soil_frames, t0)

    def _transform_and_load(
        self,
        locs: list[LocationSpec],
        crop_list: list[CropSpec],
        climate_frames: list[pl.DataFrame],
        soil_frames: list[pl.DataFrame],
        t0: float,
    ) -> EltSummary:
        self.settings.paths.ensure_dirs()

        df_climate_bronze = pl.concat(climate_frames, how="vertical")
        df_soil_bronze = pl.concat(soil_frames, how="vertical")
        df_zarc_bronze = self.zarc_source.fetch_zarc_windows(locs, crop_list)
        df_market_bronze = self.market_source.fetch_market_prices(crop_list)

        df_climate_bronze.write_parquet(self.settings.paths.bronze / "nasa_power_daily.parquet")
        df_soil_bronze.write_parquet(self.settings.paths.bronze / "nasa_appeears_daily.parquet")
        df_zarc_bronze.write_parquet(self.settings.paths.bronze / "embrapa_zarc.parquet")
        df_market_bronze.write_parquet(self.settings.paths.bronze / "b3_market.parquet")

        # SILVER: limpeza, join, GDD, dias secos e janela de veranico (10d sem chuva >= 2mm)
        df_silver_climate = (
            df_climate_bronze.join(df_soil_bronze, on=["location_id", "date"], how="left")
            .sort(["location_id", "date"])
            .with_columns(
                [
                    pl.col("date").dt.year().alias("year"),
                    pl.col("date").dt.month().alias("month"),
                    pl.col("date").dt.ordinal_day().alias("doy"),
                    pl.max_horizontal(
                        pl.lit(0.0),
                        ((pl.col("t2m_max") + pl.col("t2m_min")) / 2.0) - 10.0,
                    )
                    .round(2)
                    .alias("gdd_base10"),
                    (pl.col("t2m_min") <= 2.0).alias("is_frost_day"),
                    (pl.col("gwet_root") < 0.28).alias("is_water_stress_day"),
                    (pl.col("precip_mm") < 2.0).alias("is_dry_day"),
                ]
            )
            .with_columns(
                [
                    (
                        pl.col("precip_mm")
                        .rolling_sum(window_size=10, min_samples=10)
                        .over("location_id")
                        < 5.0
                    )
                    .fill_null(False)
                    .alias("is_veranico_window")
                ]
            )
        )
        df_silver_climate.write_parquet(self.settings.paths.silver / "climate_enriched.parquet")

        # GOLD: Star Schema (Dimensões + Fato Particionado)
        df_dim_location = pl.DataFrame([loc.model_dump() for loc in locs])
        df_dim_crop = pl.DataFrame(
            [
                {
                    **crop.model_dump(exclude={"slot"}),
                    "slot": crop.slot.value,
                }
                for crop in crop_list
            ]
        )

        df_dim_location.write_parquet(self.settings.paths.dim_location)
        df_dim_crop.write_parquet(self.settings.paths.dim_crop)
        df_zarc_bronze.write_parquet(self.settings.paths.dim_zarc_window)
        df_market_bronze.write_parquet(self.settings.paths.dim_market_price)

        fact_dir = self.settings.paths.fact_climate_daily
        if fact_dir.exists():
            shutil.rmtree(fact_dir)
        fact_dir.mkdir(parents=True, exist_ok=True)

        arrow_table = df_silver_climate.to_arrow()
        ds.write_dataset(
            arrow_table,
            base_dir=str(fact_dir),
            format="parquet",
            partitioning=["location_id", "year"],
            partitioning_flavor="hive",
            existing_data_behavior="overwrite_or_ignore",
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        logger.info("ELT concluído em %.1f ms (%d linhas climáticas).", elapsed_ms, df_silver_climate.height)
        return EltSummary(
            climate_rows=df_silver_climate.height,
            zarc_rows=df_zarc_bronze.height,
            market_rows=df_market_bronze.height,
            locations_count=len(locs),
            crops_count=len(crop_list),
            elapsed_ms=elapsed_ms,
        )
