"""Carregamentos compartilhados entre as páginas (com cache do Streamlit)."""

from __future__ import annotations

from datetime import date

import streamlit as st

from crop_optimizer.analytics.rain_delay import (
    RainDelayReport,
    ZarcStatusReport,
    build_rain_delay_report,
    fetch_location_zarc,
)
from crop_optimizer.app.state import clear_roca, get_roca, keep, store, stored, watch
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import DEFAULT_LOCATIONS
from crop_optimizer.domain.roca import Roca
from crop_optimizer.domain.soil_profile import SoilProfile, build_profile, load_field_data
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.ingestion.rain_history import RainSeries, fetch_rain_series
from crop_optimizer.ingestion.soilgrids import SoilGridsUnavailable, fetch_soilgrids_nearby
from crop_optimizer.ingestion.terrain import TerrainUnavailable, terrain_at
from crop_optimizer.lakehouse.catalog import LakehouseCatalog

EXAMPLE_KEY = "municipio_exemplo"
_EXAMPLES = {loc.location_id: loc for loc in DEFAULT_LOCATIONS}


@st.cache_resource
def lakehouse_catalog() -> LakehouseCatalog:
    settings = get_settings()
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()
    return catalog


@st.cache_data(show_spinner="Calculando a chuva da safra (NASA POWER + ZARC)...")
def rain_delay_report(
    location_json: str,
    as_of: date,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> RainDelayReport:
    defaults = [d.ibge_code for d in DEFAULT_LOCATIONS if d.ibge_code]
    return build_rain_delay_report(
        LocationSpec.model_validate_json(location_json),
        as_of,
        prefetch_ibges=defaults,
        soil_group=soil_group,
        cycle_code=cycle_code,
    )


@st.cache_data(show_spinner="Baixando a chuva do ponto (NASA POWER)...")
def rain_series(location_json: str, today: date) -> RainSeries:
    return fetch_rain_series(LocationSpec.model_validate_json(location_json), today=today)


@st.cache_data(show_spinner="Lendo o solo e o relevo do ponto (SoilGrids + SRTM)...")
def _site_layers(lat: float, lon: float):
    warnings: list[str] = []
    try:
        soil, moved = fetch_soilgrids_nearby(lat, lon)
    except SoilGridsUnavailable as exc:
        soil, moved = None, None
        warnings.append(f"Mapa de solo indisponível: {exc}")
    if moved:
        warnings.append(
            f"O mapa de solo não tem valor no ponto exato (área urbana ou água). Usamos o ponto com dado "
            f"mais próximo, {moved}. Para o solo da sua roça, marque um ponto dentro dela na página Satélite."
        )
    elif soil is not None and not soil:
        warnings.append(
            "O mapa de solo (SoilGrids) não tem valor nesse ponto nem a 3 km dele (área urbana ou água). "
            "Marque um ponto dentro da roça na página Satélite."
        )
    try:
        terrain = terrain_at(lat, lon)
    except TerrainUnavailable as exc:
        terrain = None
        warnings.append(f"Relevo indisponível: {exc}")
    return soil, terrain, warnings


def soil_profile(location: LocationSpec) -> SoilProfile:
    """Perfil do solo do local: análise de campo (arquivo) > mapa (cache) > valor típico."""
    soil, terrain, warnings = _site_layers(round(location.latitude, 4), round(location.longitude, 4))
    return build_profile(soil, terrain, load_field_data(location.location_id), warnings)


def example_selector(container=st) -> LocationSpec:
    """Seletor dos municípios de exemplo, com a mesma escolha em todas as páginas."""
    ids = list(_EXAMPLES)
    keep(EXAMPLE_KEY, ids[0])
    chosen = container.selectbox(
        "Município de exemplo",
        ids,
        format_func=lambda i: f"{_EXAMPLES[i].name} - {_EXAMPLES[i].state}",
        **watch(EXAMPLE_KEY),
    )
    return _EXAMPLES[chosen]


def select_example(location_id: str) -> None:
    """Escolhe um município de exemplo para todas as páginas (e desmarca a roça)."""
    store(EXAMPLE_KEY, location_id)
    clear_roca()


def current_location() -> tuple[LocationSpec, Roca | None]:
    """A roça marcada no mapa ou, sem roça, o município de exemplo escolhido."""
    roca = get_roca()
    if roca is not None:
        return roca.to_location(), roca
    return _EXAMPLES[stored(EXAMPLE_KEY, next(iter(_EXAMPLES)))], None


@st.cache_data(show_spinner="Comparando com o solo da região (mapas do SoilGrids)...")
def region_soil(lat: float, lon: float):
    """Valores 0-20 cm de cada pixel da região em volta do ponto, ou None se o serviço falhar."""
    from crop_optimizer.ingestion.soilgrids_wcs import RegionUnavailable, region_values

    try:
        return region_values(round(lat, 3), round(lon, 3))
    except RegionUnavailable:
        return None


@st.cache_data(show_spinner=False)
def rain_chance(location_json: str, today: date):
    """Chance de chover em cada dia do ano no ponto (marca d'água do calendário)."""
    from crop_optimizer.analytics.rain_calendar import rain_chance_by_day

    return rain_chance_by_day(rain_series(location_json, today))


def ensure_zarc_downloaded_with_progress() -> None:
    """Mostra barra de progresso real se o CSV bruto do ZARC ainda não estiver no disco."""
    from crop_optimizer.ingestion.zarc_tabua import (
        ZarcDataUnavailable,
        download_zarc_csv,
        is_zarc_csv_cached,
    )

    if is_zarc_csv_cached():
        return
    holder = st.empty()
    bar = holder.progress(0.0, text="Baixando tábua oficial de plantio ZARC (MAPA/Embrapa)...")

    def _on_progress(downloaded: int, total: int | None) -> None:
        mb = downloaded / (1024 * 1024)
        if total and total > 0:
            pct = min(1.0, downloaded / total)
            total_mb = total / (1024 * 1024)
            bar.progress(pct, text=f"Baixando tábua oficial ZARC: {mb:.1f} de {total_mb:.1f} MB...")
        else:
            bar.progress(0.5, text=f"Baixando tábua oficial ZARC: {mb:.1f} MB...")

    try:
        download_zarc_csv(progress_callback=_on_progress)
    except ZarcDataUnavailable:
        pass
    finally:
        holder.empty()


@st.cache_data(show_spinner="Carregando janelas oficiais de plantio (ZARC/MAPA)...")
def zarc_status(
    location_json: str,
    season_start: date,
    as_of: date,
    attempt: int = 0,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> ZarcStatusReport:
    """Janelas do ZARC e decêndios para `location` (cacheando também as regiões de exemplo)."""
    _ = attempt  # parte da chave do cache para permitir nova tentativa manual pela interface
    loc = LocationSpec.model_validate_json(location_json)
    defaults = [d.ibge_code for d in DEFAULT_LOCATIONS if d.ibge_code]
    return fetch_location_zarc(
        loc,
        season_start,
        as_of,
        prefetch_ibges=defaults,
        soil_group=soil_group,
        cycle_code=cycle_code,
    )


@st.cache_data(show_spinner=False)
def zarc_decendios(
    ibge_code: str | None,
    zarc_name: str,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> list[int]:
    """Menor risco do ZARC (20/30/40) em cada um dos 36 decêndios para a cultura; 0 = não indicado."""
    import polars as pl

    from crop_optimizer.ingestion.zarc_tabua import (
        ZarcDataUnavailable,
        _filter_crop_rows,
        load_zarc_table,
    )

    out = [0] * 36
    if not ibge_code:
        return out
    try:
        table = load_zarc_table([ibge_code])
    except ZarcDataUnavailable:
        return out
    local = table.filter(pl.col("geocodigo") == ibge_code)
    rows, _ = _filter_crop_rows(local, zarc_name, soil_group=soil_group, cycle_code=cycle_code)
    for dec, risk in rows.group_by("decendio").agg(pl.col("risco_pct").min()).iter_rows():
        out[int(dec) - 1] = int(risk)
    return out
