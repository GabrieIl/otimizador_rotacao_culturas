"""Lentes do mapa: qual imagem do GIBS mostrar, com que aviso, e números do ponto da roça.

Segue o padrão de "estado visível" do God's Eye View: cada lente diz se mostra a imagem da
data pedida, a mais recente (quando a data pedida ainda não tem imagem), um dado fixo, ou
nada (antes do início da série). Nunca mostra uma camada vazia sem explicar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from crop_optimizer.ingestion.gibs import GibsLayer, SnappedImage, legend_url, snap_date, tile_url
from crop_optimizer.ingestion.rain_history import RainSeries

LensState = Literal["fixo", "ok", "mais_recente", "sem_dado"]
MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]


@dataclass(slots=True)
class LensView:
    lens: dict
    layer: GibsLayer
    wanted: date
    image: SnappedImage | None
    state: LensState
    tile_url: str | None
    legend_url: str

    @property
    def status_text(self) -> str:
        nome = self.lens["nome"]
        if self.state == "fixo":
            return f"{nome}: dado fixo, não muda com o ano."
        if self.state == "sem_dado":
            first = self.layer.first_date
            mes = f"{MONTHS_PT[self.wanted.month - 1]} de {self.wanted.year}"
            if first is not None and self.wanted >= first:
                return f"Sem imagem de {nome} em {mes}: falha na série do satélite nesse período."
            return f"Sem imagem de {nome} em {mes}: essa série começa em {first:%d/%m/%Y}."
        img = self.image
        assert img is not None
        quando = (
            f"do dia {img.start:%d/%m/%Y}"
            if img.start == img.end
            else f"de {img.start:%d/%m} a {img.end:%d/%m/%Y} ({self.lens['periodo']} juntos)"
        )
        if self.state == "mais_recente":
            return f"Ainda não há imagem para essa data. Mostrando a mais recente, {quando}."
        return f"Imagem {quando}."


def build_lens_view(lens: dict, layer: GibsLayer, wanted: date) -> LensView:
    legend = legend_url(lens["colormap"])
    if not layer.intervals:
        return LensView(lens, layer, wanted, None, "fixo", tile_url(layer, None), legend)
    image = snap_date(layer, wanted)
    if image is None:
        return LensView(lens, layer, wanted, None, "sem_dado", None, legend)
    state: LensState = "mais_recente" if image.is_latest else "ok"
    return LensView(lens, layer, wanted, image, state, tile_url(layer, image), legend)


def pixel_label(km: float) -> str:
    if km >= 1:
        return f"cerca de {km:g} km"
    return f"cerca de {km * 1000:.0f} m"


def pixel_bounds(lat: float, lon: float, km: float) -> list[list[float]]:
    """Quadrado de `km` de lado centrado no ponto ([[sul, oeste], [norte, leste]]), para o Leaflet."""
    half_lat = (km / 2) / 111.32
    half_lon = (km / 2) / (111.32 * max(0.01, math.cos(math.radians(lat))))
    return [[lat - half_lat, lon - half_lon], [lat + half_lat, lon + half_lon]]


@dataclass(frozen=True, slots=True)
class MonthRain:
    total_mm: float | None  # None = mês incompleto ou sem dado
    normal_mm: float
    days_with_data: int
    days_in_month: int


def month_rain(series: RainSeries, year: int, month: int, first_year: int = 1991, last_year: int = 2020) -> MonthRain:
    """Chuva do mês no ponto (NASA POWER) e a média do mesmo mês na normal."""
    years = series.dates.astype("datetime64[Y]").astype(int) + 1970
    months = series.dates.astype("datetime64[M]").astype(int) % 12 + 1
    in_month = (years == year) & (months == month)
    values = series.precip_mm[in_month]
    valid = int(np.sum(~np.isnan(values)))
    total = float(np.nansum(values)) if values.size and valid == values.size else None
    normal_mask = (months == month) & (years >= first_year) & (years <= last_year)
    n_years = last_year - first_year + 1
    normal = float(np.nansum(series.precip_mm[normal_mask])) / n_years
    return MonthRain(total, normal, valid, int(values.size))
