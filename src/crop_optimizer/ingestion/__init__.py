"""Conectores de ingestão de dados (NASA, Embrapa ZARC e B3)."""

from crop_optimizer.ingestion.b3_market import B3MarketDataSource
from crop_optimizer.ingestion.base import (
    ClimateDataSource,
    MarketDataSource,
    SoilRemoteSensingSource,
    ZarcDataSource,
)
from crop_optimizer.ingestion.embrapa_zarc import EmbrapaZarcSource
from crop_optimizer.ingestion.nasa_appeears import NasaAppeearsClient
from crop_optimizer.ingestion.nasa_power import NasaPowerClient

__all__ = [
    "B3MarketDataSource",
    "ClimateDataSource",
    "EmbrapaZarcSource",
    "MarketDataSource",
    "NasaAppeearsClient",
    "NasaPowerClient",
    "SoilRemoteSensingSource",
    "ZarcDataSource",
]
