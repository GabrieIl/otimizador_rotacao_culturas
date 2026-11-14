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
from crop_optimizer.app import theme
from crop_optimizer.app.common import current_location, select_example
from crop_optimizer.app.state import arrived, get_roca, keep, set_roca, store, watch
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import DEFAULT_LOCATIONS
from crop_optimizer.domain.roca import Roca
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, inside_brazil_box, resolve_place
from crop_optimizer.ingestion.gibs import GibsLayer, GibsUnavailable, load_layers
from crop_optimizer.ingestion.rain_history import RainDataUnavailable, RainSeries, fetch_rain_series

_BASE_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
_BASE_ATTR = "Imagem de base: Esri, Maxar, Earthstar Geographics"
_ROCA_COLOR = theme.COLORS.terracota_ilustracao
_PENDING = "_ponto_pendente"
# Estado do mapa (chaves comuns de sessão: valem entre páginas).
# _ZOOM/_CENTER: última visão informada pelo mapa. _ANCHOR: visão com que a figura é criada nesta
# visita (fixa durante a visita, para o mapa não ser recriado). _REQUEST: centro pedido ao mapa
# quando o ponto muda (None = não mexer). _POINT: ponto que o mapa mostra.
_ZOOM, _CENTER, _ANCHOR, _REQUEST, _POINT = (
    "_mapa_zoom", "_mapa_centro", "_mapa_ancora", "_mapa_pedido", "_mapa_ponto"
)
_CLICKED = "_mapa_ponto_clicado"


def _map_cfg() -> dict:
    return load_yaml_config("lentes")["mapa"]


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


def _set_point(lat: float, lon: float) -> None:
    """Põe o ponto nos campos de latitude/longitude (antes de eles serem desenhados)."""
    for key, value in (("lat_roca", float(lat)), ("lon_roca", float(lon))):
        store(key, value)
        st.session_state[key] = value


def _location_picker(roca: Roca | None, current: LocationSpec) -> None:
    # O ponto acompanha a seleção feita em qualquer página (exemplo na Início, roça confirmada aqui).
    if st.session_state.get("_sat_origem") != current.location_id:
        st.session_state["_sat_origem"] = current.location_id
        st.session_state[_PENDING] = (current.latitude, current.longitude)
    keep("lat_roca", current.latitude)
    keep("lon_roca", current.longitude)
    pending = st.session_state.pop(_PENDING, None)
    if pending is not None:
        _set_point(*pending)

    with st.expander("Onde fica a sua roça?", expanded=roca is None):
        st.caption(
            "Digite a latitude e a longitude (do GPS do celular, por exemplo) ou clique no mapa. "
            "No Nordeste as duas são negativas."
        )
        c1, c2, c3 = st.columns([1, 1, 1])
        lat = c1.number_input("Latitude", min_value=-90.0, max_value=90.0, format="%.5f", **watch("lat_roca"))
        lon = c2.number_input("Longitude", min_value=-180.0, max_value=180.0, format="%.5f", **watch("lon_roca"))
        c3.write("")
        if c3.button("Usar este ponto", type="primary", width="stretch"):
            _confirm_point(float(lat), float(lon))

        cols = st.columns(len(DEFAULT_LOCATIONS) + 1)
        cols[0].caption("Ou use um exemplo:")
        for col, loc in zip(cols[1:], DEFAULT_LOCATIONS, strict=True):
            if col.button(f"{loc.name}/{loc.state}", width="stretch", key=f"exemplo_{loc.location_id}"):
                select_example(loc.location_id)  # vale para todas as páginas
                st.rerun()

    if roca is not None:
        st.success(f"**Sua roça:** {roca.label}. As páginas Início e Plantio usam esse ponto.")
        if roca.aviso_municipio:
            st.warning(roca.aviso_municipio)
    else:
        st.info(
            f"**Local em uso:** {current.name}/{current.state} (município de exemplo). "
            "Marque a sua roça para usar o ponto dela em todas as páginas."
        )


def _build_map(center: tuple[float, float], zoom: int) -> folium.Map:
    """Só a imagem de base e os limites. Fica igual durante a visita à página: se a figura muda, o
    componente recria o mapa e perde o zoom do usuário."""
    cfg = _map_cfg()
    box = cfg["limites"]
    zmin, zmax = int(cfg["zoom_minimo"]), int(cfg["zoom_maximo"])
    fmap = folium.Map(
        location=list(center),
        zoom_start=int(min(max(zoom, zmin), zmax)),
        tiles=None,
        control_scale=True,
        min_zoom=zmin,
        max_zoom=zmax,
        max_bounds=True,
        min_lat=box["sul"],
        max_lat=box["norte"],
        min_lon=box["oeste"],
        max_lon=box["leste"],
        max_bounds_viscosity=1.0,
        world_copy_jump=False,
    )
    folium.TileLayer(
        _BASE_TILES, attr=_BASE_ATTR, name="Imagem de base", min_zoom=zmin, max_zoom=zmax, no_wrap=True
    ).add_to(fmap)
    return fmap


def _dynamic_layers(view: LensView | None, lat: float, lon: float, is_roca: bool) -> folium.FeatureGroup:
    """Lente, quadrado do pixel e marcador: trocados sem recriar o mapa (zoom e posição ficam)."""
    cfg = _map_cfg()
    zmin, zmax = int(cfg["zoom_minimo"]), int(cfg["zoom_maximo"])
    group = folium.FeatureGroup(name="camadas")
    if view is not None and view.tile_url:
        folium.TileLayer(
            view.tile_url,
            attr=f"NASA GIBS · {view.lens['fonte']}",
            name=view.lens["nome"],
            opacity=0.75,
            max_native_zoom=min(view.layer.max_native_zoom, zmax),
            min_zoom=zmin,
            max_zoom=zmax,
            no_wrap=True,
        ).add_to(group)
    if view is not None:
        folium.Rectangle(
            bounds=pixel_bounds(lat, lon, float(view.lens["pixel_km"])),
            color=theme.COLORS.ocre,  # o "pixel" da marca é literalmente um pixel aqui
            weight=2,
            dash_array="6 6",
            fill=False,
            tooltip=f"Tamanho de um quadrado desta lente ({pixel_label(float(view.lens['pixel_km']))})",
        ).add_to(group)
    folium.CircleMarker(
        [lat, lon],
        radius=7,
        color=theme.COLORS.petroleo,
        weight=2,
        fill=True,
        fill_color=_ROCA_COLOR,
        fill_opacity=1,
        tooltip="Sua roça" if is_roca else "Ponto ainda não confirmado",
    ).add_to(group)
    return group


def _map_view(lat: float, lon: float, first_run: bool) -> None:
    """Decide a visão do mapa sem nunca devolver a ele a posição que ele mesmo informou."""
    point = (lat, lon)
    zoom0 = int(_map_cfg()["zoom_inicial"])
    if first_run or _ANCHOR not in st.session_state:
        # ao chegar na página: volta à última visão, se o ponto não mudou em outra página
        same_point = st.session_state.get(_POINT) == point and _CENTER in st.session_state
        center = st.session_state[_CENTER] if same_point else point
        st.session_state[_ANCHOR] = (tuple(center), st.session_state.get(_ZOOM, zoom0))
        st.session_state[_REQUEST] = None
        st.session_state[_POINT] = point
    elif st.session_state.get(_POINT) != point:
        st.session_state[_POINT] = point
        # ponto novo pelos campos ou exemplo: centraliza nele (o zoom fica); por clique, não mexe
        if st.session_state.get(_CLICKED) != point:
            st.session_state[_REQUEST] = list(point)


def _info_column(view: LensView | None, rain: RainSeries | None, place_label: str) -> None:
    cfg = load_yaml_config("lentes")
    if view is not None:
        lens = view.lens
        with st.container(border=True):
            theme.label("Esta lente")
            st.markdown(f"### {lens['nome']}")
            st.write(lens["descricao"])
            st.caption(f"Fonte: {lens['fonte']} · cada imagem junta {lens['periodo']}")
        with st.container(border=True):
            theme.label("Tamanho de cada quadrado")
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
        theme.label(f"Chuva do mês no ponto · {place_label}")
        if m.total_mm is None:
            st.markdown(f"### {mes}: mês incompleto")
            st.write(f"{m.days_with_data} dias com dado até agora. Em média, o mês tem {m.normal_mm:.0f} mm.")
        else:
            st.markdown(f"### {m.total_mm:.0f} mm em {mes}")
            st.write(f"Em média (1991-2020), {MONTHS_PT[view.wanted.month - 1]} tem {m.normal_mm:.0f} mm.")
        st.caption("Fonte: NASA POWER (quadrado de ~50 km), a mesma do atraso da chuva.")


def satellite_page() -> None:
    theme.page_header(
        "Satélite · lentes da NASA",
        "O que o satélite vê na sua roça",
        "Troque a lente e o ano para ver cada dado que o Acauã usa, e o tamanho do quadrado de cada um.",
        mascot="mascote_satelite.png",
    )

    cfg = load_yaml_config("lentes")
    lenses = {lens["id"]: lens for lens in cfg["lentes"]}
    first_run = arrived("satelite")
    roca = get_roca()
    current, _ = current_location()
    _location_picker(roca, current)

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
        keep("lente", next(iter(lenses)))
        lens_id = st.radio(
            "LENTES",
            list(lenses),
            format_func=lambda i: lenses[i]["nome"],
            captions=[lenses[i]["fonte"] for i in lenses],
            **watch("lente"),
        )
    lens = lenses[lens_id]

    with col_map:
        map_slot = st.container()
        c_year, c_month = st.columns([3, 2])
        keep("ano_lente", today.year)
        keep("mes_lente", today.month)
        year = c_year.slider("Ano", min_value=2000, max_value=today.year, **watch("ano_lente"))
        month = c_month.select_slider(
            "Mês",
            options=list(range(1, 13)),
            format_func=lambda m: MONTHS_PT[m - 1][:3],
            **watch("mes_lente"),
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

        _map_view(lat, lon, first_run)
        anchor_center, anchor_zoom = st.session_state[_ANCHOR]
        with map_slot:
            out = st_folium(
                _build_map(anchor_center, anchor_zoom),
                feature_group_to_add=_dynamic_layers(view, lat, lon, is_roca),
                center=st.session_state[_REQUEST],
                height=520,
                use_container_width=True,
                returned_objects=["last_clicked", "zoom", "center"],
                key="mapa_lentes",
            )
        out = out or {}
        # Guarda a visão só para reabrir igual ao voltar à página. NUNCA devolve ao mapa nesta
        # visita: isso fazia o mapa voltar para trás enquanto o usuário arrastava ou dava zoom.
        if out.get("center") and out.get("zoom"):
            st.session_state[_ZOOM] = int(out["zoom"])
            st.session_state[_CENTER] = (out["center"]["lat"], out["center"]["lng"])
        click = out.get("last_clicked")
        if click:
            point = (round(click["lat"], 5), round(click["lng"], 5))
            if point != st.session_state.get("_ultimo_clique"):
                st.session_state["_ultimo_clique"] = point
                st.session_state[_CLICKED] = point
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
    theme.footer(
        "Imagens: NASA GIBS / EOSDIS (GPM IMERG, SMAP, MODIS Terra, SRTM). Chuva do ponto: NASA POWER. "
        f"Imagem de base: Esri World Imagery. Município: © OpenStreetMap contributors (Nominatim) e IBGE.{caps}"
    )
