"""A roça escolhida pelo usuário (latitude/longitude livres) e a ponte com o resto do app."""

from __future__ import annotations

import math
from dataclasses import dataclass

from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import DEFAULT_LOCATIONS


@dataclass(frozen=True, slots=True)
class Roca:
    lat: float
    lon: float
    municipio: str | None = None
    uf: str | None = None
    ibge_code: str | None = None
    aviso_municipio: str | None = None  # por que o município não foi encontrado

    @property
    def label(self) -> str:
        where = f"{self.municipio}/{self.uf}" if self.municipio else "município não identificado"
        return f"{where} ({self.lat:.4f}, {self.lon:.4f})"

    def to_location(self) -> LocationSpec:
        """LocationSpec para o cálculo da chuva e do ZARC (o id identifica o cache por ponto)."""
        return LocationSpec(
            location_id=f"roca_{self.lat:.4f}_{self.lon:.4f}",
            name=self.municipio or "Sua roça",
            state=self.uf or "",
            ibge_code=self.ibge_code,
            biome="",
            latitude=self.lat,
            longitude=self.lon,
        )


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em linha reta (haversine), em km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_preset(lat: float, lon: float) -> tuple[LocationSpec, float]:
    """Município de exemplo mais próximo (o Monte Carlo só tem clima desses)."""
    best = min(DEFAULT_LOCATIONS, key=lambda loc: distance_km(lat, lon, loc.latitude, loc.longitude))
    return best, distance_km(lat, lon, best.latitude, best.longitude)
