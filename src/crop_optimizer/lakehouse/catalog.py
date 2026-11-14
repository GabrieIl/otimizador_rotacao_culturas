"""Camada analítica do Local Data Lakehouse sobre Parquet + DuckDB."""

from __future__ import annotations

import time
from dataclasses import dataclass

import duckdb
import polars as pl

from crop_optimizer.config import LakehousePaths, Settings, get_settings
from crop_optimizer.domain.models import CropSpec, LocationSpec, SeasonSlot


@dataclass(slots=True)
class SeasonalClimateStats:
    """Distribuições climáticas extraídas do Lakehouse para calibrar o motor estocástico."""

    location_id: str
    safra_rain_mean_mm: float
    safra_rain_std_mm: float
    safrinha_rain_mean_mm: float
    safrinha_rain_std_mm: float
    safrinha_water_stress_prob: float
    frost_prob_safrinha: float
    mean_gwet_safra: float
    mean_gwet_safrinha: float
    query_ms: float
    veranico_prob: float = 0.30
    mean_smap_moisture: float = 0.24


class LakehouseCatalog:
    """Catálogo DuckDB conectado diretamente às tabelas Star Schema em Parquet."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.paths: LakehousePaths = self.settings.paths
        self._conn: duckdb.DuckDBPyConnection | None = None

    def is_ready(self) -> bool:
        required = (
            self.paths.dim_location,
            self.paths.dim_crop,
            self.paths.dim_zarc_window,
            self.paths.dim_market_price,
        )
        has_dims = all(path.exists() for path in required)
        has_facts = any(self.paths.fact_climate_daily.rglob("*.parquet"))
        return has_dims and has_facts

    def connect(self) -> duckdb.DuckDBPyConnection:
        if not self.is_ready():
            raise FileNotFoundError(
                f"Lakehouse não inicializado em {self.paths.gold}. Execute o pipeline ELT primeiro."
            )
        if self._conn is None:
            conn = duckdb.connect(database=":memory:")
            fact_glob = (self.paths.fact_climate_daily / "**" / "*.parquet").as_posix()
            conn.execute(
                f"CREATE OR REPLACE VIEW fact_climate_daily AS "
                f"SELECT * FROM read_parquet('{fact_glob}', hive_partitioning=true)"
            )
            conn.execute(
                f"CREATE OR REPLACE VIEW dim_location AS "
                f"SELECT * FROM read_parquet('{self.paths.dim_location.as_posix()}')"
            )
            conn.execute(
                f"CREATE OR REPLACE VIEW dim_crop AS "
                f"SELECT * FROM read_parquet('{self.paths.dim_crop.as_posix()}')"
            )
            conn.execute(
                f"CREATE OR REPLACE VIEW dim_zarc_window AS "
                f"SELECT * FROM read_parquet('{self.paths.dim_zarc_window.as_posix()}')"
            )
            conn.execute(
                f"CREATE OR REPLACE VIEW dim_market_price AS "
                f"SELECT * FROM read_parquet('{self.paths.dim_market_price.as_posix()}')"
            )
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def query_pl(self, sql: str, params: list[object] | None = None) -> pl.DataFrame:
        conn = self.connect()
        relation = conn.sql(sql, params=params) if params else conn.sql(sql)
        return pl.from_arrow(relation.to_arrow_table())

    def load_locations(self) -> list[LocationSpec]:
        df = self.query_pl("SELECT * FROM dim_location ORDER BY name")
        return [LocationSpec(**row) for row in df.to_dicts()]

    def load_crops(self) -> list[CropSpec]:
        df = self.query_pl("SELECT * FROM dim_crop ORDER BY crop_id")
        return [
            CropSpec(**{**row, "slot": SeasonSlot(row["slot"])})
            for row in df.to_dicts()
        ]

    def get_zarc_windows(self, location_id: str) -> pl.DataFrame:
        return self.query_pl(
            """
            SELECT z.*, c.name AS crop_name
            FROM dim_zarc_window z
            JOIN dim_crop c ON c.crop_id = z.crop_id
            WHERE z.location_id = ?
            ORDER BY c.slot, c.name
            """,
            [location_id],
        )

    def get_market_prices(self) -> pl.DataFrame:
        return self.query_pl(
            """
            SELECT m.*, c.name AS crop_name, c.slot
            FROM dim_market_price m
            JOIN dim_crop c ON c.crop_id = m.crop_id
            ORDER BY c.slot, c.name
            """
        )

    def get_annual_climate_summary(self, location_id: str) -> pl.DataFrame:
        return self.query_pl(
            """
            SELECT
                year,
                ROUND(SUM(precip_mm), 1) AS total_precip_mm,
                ROUND(AVG(t2m), 2) AS avg_temp_c,
                ROUND(AVG(smap_soil_moisture), 3) AS avg_smap_moisture,
                ROUND(AVG(gwet_root), 3) AS avg_soil_wetness,
                SUM(CASE WHEN is_veranico_window THEN 1 ELSE 0 END) AS veranico_days,
                SUM(CASE WHEN is_water_stress_day THEN 1 ELSE 0 END) AS water_stress_days
            FROM fact_climate_daily
            WHERE location_id = ?
            GROUP BY year
            ORDER BY year
            """,
            [location_id],
        )

    def get_seasonal_climate_stats(self, location_id: str) -> SeasonalClimateStats:
        """Agrega estatísticas da quadra chuvosa (Jan-Mai) e transição (Jun-Dez) via DuckDB."""
        t0 = time.perf_counter()
        df = self.query_pl(
            """
            WITH seasonal AS (
                SELECT
                    year,
                    CASE
                        WHEN month IN (1, 2, 3, 4, 5) THEN 'safra'
                        ELSE 'safrinha'
                    END AS season_bucket,
                    precip_mm,
                    gwet_root,
                    smap_soil_moisture,
                    is_frost_day,
                    is_water_stress_day,
                    is_veranico_window
                FROM fact_climate_daily
                WHERE location_id = ?
            ),
            yearly_bucket AS (
                SELECT
                    year,
                    season_bucket,
                    SUM(precip_mm) AS season_rain_mm,
                    AVG(gwet_root) AS mean_gwet,
                    AVG(smap_soil_moisture) AS mean_smap,
                    MAX(CASE WHEN is_frost_day THEN 1 ELSE 0 END) AS had_frost,
                    MAX(CASE WHEN is_veranico_window THEN 1 ELSE 0 END) AS had_veranico,
                    AVG(CASE WHEN is_water_stress_day THEN 1.0 ELSE 0.0 END) AS stress_rate
                FROM seasonal
                GROUP BY year, season_bucket
            )
            SELECT
                season_bucket,
                AVG(season_rain_mm) AS rain_mean,
                COALESCE(STDDEV_SAMP(season_rain_mm), 95.0) AS rain_std,
                AVG(mean_gwet) AS gwet_mean,
                AVG(mean_smap) AS smap_mean,
                AVG(had_frost) AS frost_prob,
                AVG(had_veranico) AS veranico_prob,
                AVG(stress_rate) AS stress_prob
            FROM yearly_bucket
            GROUP BY season_bucket
            """,
            [location_id],
        )
        query_ms = (time.perf_counter() - t0) * 1000.0
        by_bucket = {row["season_bucket"]: row for row in df.to_dicts()}
        safra = by_bucket.get("safra", {})
        safrinha = by_bucket.get("safrinha", {})

        return SeasonalClimateStats(
            location_id=location_id,
            safra_rain_mean_mm=float(safra.get("rain_mean", 440.0)),
            safra_rain_std_mm=float(safra.get("rain_std", 145.0)),
            safrinha_rain_mean_mm=float(safrinha.get("rain_mean", 180.0)),
            safrinha_rain_std_mm=float(safrinha.get("rain_std", 85.0)),
            safrinha_water_stress_prob=float(safrinha.get("stress_prob", 0.42)),
            frost_prob_safrinha=float(safrinha.get("frost_prob", 0.0)),
            mean_gwet_safra=float(safra.get("gwet_mean", 0.42)),
            mean_gwet_safrinha=float(safrinha.get("gwet_mean", 0.28)),
            veranico_prob=float(safra.get("veranico_prob", 0.34)),
            mean_smap_moisture=float(safra.get("smap_mean", 0.25)),
            query_ms=query_ms,
        )
