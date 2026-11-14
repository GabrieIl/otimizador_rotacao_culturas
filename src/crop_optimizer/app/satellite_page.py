"""Página "Satélite": marcar a roça no mapa e ver as lentes de dados da NASA."""

from __future__ import annotations

from datetime import date

import folium
import streamlit as st
from streamlit_folium import st_folium

from crop_optimizer.analytics.satellite_lenses import (
    MONTHS_PT,
    LensView,
    build_lens_view,
    month_rain,
    pixel_bounds,
    pixel_label,
)
from crop_optimizer.app.state import get_roca, set_roca
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import DEFAULT_LOCATIONS
from crop_optimizer.domain.roca import Roca
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, inside_brazil_box, resolve_place
from crop_optimizer.ingestion.gibs import GibsLayer, GibsUnavailable, load_layers
from crop_optimizer.ingestion.rain_history import RainDataUnavailable, RainSeries, fetch_rain_series

_BASE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
_BASE_ATTR = "Imagem de base: Esri, Maxar, Earthstar Geographics"
_ROCA_COLOR = "#F2B01E"
_PENDING = "_ponto_pendente"


@st.cache_data(ttl=3600, show_spinner="Lendo o catálogo de imagens da NASA (GIBS)...")
def _layers(layer_ids: tuple[str, ...], today: date) -> tuple[dict[str, GibsLayer], date]:
    return load_layers(list(layer_ids), today=today)


@st.cache_data(show_spinner="Baixando a chuva do ponto (NASA POWER)...")
def _rain_series(location_json: str, today: date) -> RainSeries:
    return fetch_rain_series(LocationSpec.model_validate_json(location_json), today=today)


def _confirm_point(lat: float, lon: float) -> None:
    """Grava a roça e tenta descobrir o município (para o ZARC)."""
    if not inside_brazil_box(lat, lon):
        st.error("Essa coordenada fica fora do Brasil. Confira o sinal (no Nordeste, latitude e longitude são negativas).")
        return
    with st.spinner("Procurando o município desse ponto (OpenStreetMap + IBGE)..."):
        try:
            place = resolve_place(lat, lon)
        except GeocodeUnavailable as exc:
            set_roca(Roca(lat=lat, lon=lon, aviso_municipio=str(exc)))
        else:
            aviso = None if place.ibge_code else "Município achado, mas sem código no IBGE: o ZARC não vai aparecer."
            set_roca(Roca(lat=lat, lon=lon, municipio=place.municipio, uf=place.uf,
                          ibge_code=place.ibge_code, aviso_municipio=aviso))
    st.rerun()


def _location_picker(roca: Roca | None, default: LocationSpec) -> None:
    pending = st.session_state.pop(_PENDING, None)
    if pending is not None:
        st.session_state["lat_roca"], st.session_state["lon_roca"] = pending
    st.session_state.setdefault("lat_roca", roca.lat if roca else default.latitude)
    st.session_state.setdefault("lon_roca", roca.lon if roca else default.longitude)

    with st.expander("📍 Onde fica a sua roça?", expanded=roca is None):
        st.caption(
            "Digite a latitude e a longitude (do GPS do celular, por exemplo) ou clique no mapa. "
            "No Nordeste as duas são negativas."
        )
        c1, c2, c3 = st.columns([1, 1, 1])
        lat = c1.number_input("Latitude", min_value=-90.0, max_value=90.0, format="%.5f", key="lat_roca")
        lon = c2.number_input("Longitude", min_value=-180.0, max_value=180.0, format="%.5f", key="lon_roca")
        c3.write("")
        if c3.button("Usar este ponto", type="primary", width="stretch"):
            _confirm_point(float(lat), float(lon))

        examples = {f"{loc.name}/{loc.state}": loc for loc in DEFAULT_LOCATIONS}
        cols = st.columns(len(examples) + 1)
        cols[0].caption("Ou use um exemplo:")
        for col, (label, loc) in zip(cols[1:], examples.items(), strict=True):
            if col.button(label, width="stretch"):
                st.session_state[_PENDING] = (loc.latitude, loc.longitude)
                st.rerun()

    if roca is not None:
        st.success(f"**Sua roça:** {roca.label}. A página Plantio já usa esse ponto para a chuva e o ZARC.")
        if roca.aviso_municipio:
            st.warning(roca.aviso_municipio)


def _build_map(view: LensView | None, lat: float, lon: float, is_roca: bool) -> folium.Map:
    zoom = int(view.lens["zoom"]) if view else 8
    fmap = folium.Map(location=[lat, lon], zoom_start=zoom, tiles=None, control_scale=True, max_zoom=18)
    folium.TileLayer(_BASE_TILES, attr=_BASE_ATTR, name="Imagem de base", max_zoom=18).add_to(fmap)
    if view is not None and view.tile_url:
        folium.TileLayer(
            view.tile_url,
            attr=f"NASA GIBS · {view.lens['fonte']}",
            name=view.lens["nome"],
            overlay=True,
            opacity=0.75,
            max_native_zoom=view.layer.max_native_zoom,
            max_zoom=18,
        ).add_to(fmap)
    if view is not None:
        folium.Rectangle(
            bounds=pixel_bounds(lat, lon, float(view.lens["pixel_km"])),
            color=_ROCA_COLOR,
            weight=2,
            dash_array="6 6",
            fill=False,
            tooltip=f"Tamanho de um quadrado desta lente ({pixel_label(float(view.lens['pixel_km']))})",
        ).add_to(fmap)
    folium.CircleMarker(
        [lat, lon],
        radius=7,
        color="#0F2430",
        weight=2,
        fill=True,
        fill_color=_ROCA_COLOR,
        fill_opacity=1,
        tooltip="Sua roça" if is_roca else "Ponto ainda não confirmado",
    ).add_to(fmap)
    return fmap


def _info_column(view: LensView | None, rain: RainSeries | None, place_label: str) -> None:
    cfg = load_yaml_config("lentes")
    if view is not None:
        lens = view.lens
        with st.container(border=True):
            st.caption("ESTA LENTE")
            st.markdown(f"### {lens['nome']}")
            st.write(lens["descricao"])
            st.caption(f"Fonte: {lens['fonte']} · cada imagem junta {lens['periodo']}")
        with st.container(border=True):
            st.caption("TAMANHO DE CADA QUADRADO")
            st.markdown(f"### {pixel_label(float(lens['pixel_km']))}")
            st.write(lens["pixel_texto"])
        if view.state != "sem_dado":
            st.image(view.legend_url, caption="Escala de cores (NASA GIBS)", width="stretch")
        if lens["id"] == "chuva" and rain is not None:
            _rain_numbers(view, rain, place_label)
    with st.container(border=True):
        st.markdown("**O que o satélite não vê**")
        st.write(cfg["o_que_nao_ve"])


def _rain_numbers(view: LensView, rain: RainSeries, place_label: str) -> None:
    m = month_rain(rain, view.wanted.year, view.wanted.month)
    mes = f"{MONTHS_PT[view.wanted.month - 1]}/{view.wanted.year}"
    with st.container(border=True):
        st.caption(f"CHUVA DO MÊS NO PONTO · {place_label}")
        if m.total_mm is None:
            st.markdown(f"### {mes}: mês incompleto")
            st.write(f"{m.days_with_data} dias com dado até agora. Em média, o mês tem {m.normal_mm:.0f} mm.")
        else:
            st.markdown(f"### {m.total_mm:.0f} mm em {mes}")
            st.write(f"Em média (1991-2020), {MONTHS_PT[view.wanted.month - 1]} tem {m.normal_mm:.0f} mm.")
        st.caption("Fonte: NASA POWER (quadrado de ~50 km), a mesma do atraso da chuva.")


def satellite_page() -> None:
    st.title("🛰️ O que o satélite vê na sua roça")
    st.caption("Troque a lente e arraste o ano para ver cada dado da NASA que o app usa.")

    cfg = load_yaml_config("lentes")
    lenses = {lens["id"]: lens for lens in cfg["lentes"]}
    roca = get_roca()
    default = DEFAULT_LOCATIONS[0]
    _location_picker(roca, default)

    lat = float(st.session_state["lat_roca"])
    lon = float(st.session_state["lon_roca"])
    is_roca = roca is not None and (round(roca.lat, 5), round(roca.lon, 5)) == (round(lat, 5), round(lon, 5))

    today = date.today()
    layers: dict[str, GibsLayer] | None = None
    try:
        layers, caps_date = _layers(tuple(lens["camada"] for lens in lenses.values()), today)
    except GibsUnavailable as exc:
        st.error(f"**As lentes estão fora do ar.** {exc}")
        caps_date = None

    col_lens, col_map, col_info = st.columns([1.0, 3.0, 1.4], gap="medium")
    with col_lens:
        lens_id = st.radio(
            "LENTES",
            list(lenses),
            format_func=lambda i: lenses[i]["nome"],
            captions=[lenses[i]["fonte"] for i in lenses],
            key="lente",
        )
    lens = lenses[lens_id]

    with col_map:
        map_slot = st.container()
        c_year, c_month = st.columns([3, 2])
        year = c_year.slider("Ano", min_value=2000, max_value=today.year, value=today.year, key="ano_lente")
        month = c_month.select_slider(
            "Mês",
            options=list(range(1, 13)),
            value=today.month,
            format_func=lambda m: MONTHS_PT[m - 1][:3],
            key="mes_lente",
        )
        wanted = min(date(year, month, 15), today)

        view = None
        if layers is not None:
            layer = layers.get(lens["camada"])
            if layer is None:
                st.error(f"A camada {lens['camada']} não está mais no catálogo do GIBS.")
            else:
                view = build_lens_view(lens, layer, wanted)
                {"sem_dado": st.warning, "mais_recente": st.info}.get(view.state, st.caption)(view.status_text)

        with map_slot:
            out = st_folium(
                _build_map(view, lat, lon, is_roca),
                height=520,
                use_container_width=True,
                returned_objects=["last_clicked"],
                key="mapa_lentes",
            )
        click = (out or {}).get("last_clicked")
        if click:
            point = (round(click["lat"], 5), round(click["lng"], 5))
            if point != st.session_state.get("_ultimo_clique"):
                st.session_state["_ultimo_clique"] = point
                st.session_state[_PENDING] = point
                st.rerun()

    rain = None
    place_label = roca.label if is_roca else f"{lat:.4f}, {lon:.4f}"
    if lens_id == "chuva":
        location = roca.to_location() if is_roca else Roca(lat=lat, lon=lon).to_location()
        try:
            rain = _rain_series(location.model_dump_json(), today)
        except RainDataUnavailable as exc:
            st.warning(f"Chuva do ponto indisponível: {exc}")
    with col_info:
        _info_column(view, rain, place_label)

    caps = f" Catálogo de imagens de {caps_date:%d/%m/%Y}." if caps_date else ""
    st.caption(
        "Imagens: NASA GIBS / EOSDIS (GPM IMERG, SMAP, MODIS Terra, SRTM). Chuva do ponto: NASA POWER. "
        f"Imagem de base: Esri World Imagery. Município: © OpenStreetMap contributors (Nominatim) e IBGE.{caps}"
    )
