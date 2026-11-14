"""Camada de consultas do Local Data Lakehouse (Parquet + DuckDB)."""

from crop_optimizer.lakehouse.catalog import LakehouseCatalog, SeasonalClimateStats

__all__ = ["LakehouseCatalog", "SeasonalClimateStats"]
