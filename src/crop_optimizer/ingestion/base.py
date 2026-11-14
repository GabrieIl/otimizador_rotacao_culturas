"""Interfaces base (síncronas e assíncronas) para conectores climáticos, fenológicos e de mercado."""

from __future__ import annotations

from datetime import date
from typing import Protocol

import polars as pl

from crop_optimizer.domain.models import CropSpec, LocationSpec


class ClimateDataSource(Protocol):
    """Contrato para fontes de séries temporais climáticas diárias (NASA POWER / CHIRPS / GPM)."""

    def fetch_daily_climate(
        self,
        location: LocationSpec,
        start_date: date,
        end_date: date,
    ) -> pl.DataFrame: ...

    async def fetch_daily_climate_async(
        self,
        location: LocationSpec,
        start_date: date,
        end_date: date,
    ) -> pl.DataFrame: ...


class SoilRemoteSensingSource(Protocol):
    """Contrato para séries de umidade do solo / NDVI via satélite (NASA AppEEARS / SMAP / MODIS)."""

    def fetch_soil_moisture(
        self,
        location: LocationSpec,
        start_date: date,
        end_date: date,
    ) -> pl.DataFrame: ...

    async def fetch_soil_moisture_async(
        self,
        location: LocationSpec,
        start_date: date,
        end_date: date,
    ) -> pl.DataFrame: ...


class ZarcDataSource(Protocol):
    """Contrato para metadados de zoneamento agrícola de risco climático (ZARC Embrapa)."""

    def fetch_zarc_windows(
        self,
        locations: list[LocationSpec],
        crops: list[CropSpec],
    ) -> pl.DataFrame: ...


class MarketDataSource(Protocol):
    """Contrato para séries e parâmetros de preço de mercado (B3 / CEPEA)."""

    def fetch_market_prices(self, crops: list[CropSpec]) -> pl.DataFrame: ...
