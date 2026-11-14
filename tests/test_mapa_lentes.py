"""Testes da Feature 2: GIBS (catálogo e datas), lentes, roça e município."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from crop_optimizer.analytics.satellite_lenses import (
    build_lens_view,
    month_rain,
    pixel_bounds,
    pixel_label,
)
from crop_optimizer.domain.roca import Roca, distance_km, nearest_preset
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, place_from_address
from crop_optimizer.ingestion.gibs import parse_capabilities, snap_date, tile_url
from crop_optimizer.ingestion.rain_history import RainSeries

_CAPS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1">
 <Contents>
  <Layer>
   <ows:Title>Vegetation Index (16-Day)</ows:Title>
   <ows:Identifier>NDVI_16</ows:Identifier>
   <Format>image/png</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier><Default>2026-10-16</Default>
    <Value>2000-03-05/2000-12-18/P16D</Value>
    <Value>2026-01-01/2026-10-16/P16D</Value>
   </Dimension>
   <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible_Level9</TileMatrixSet></TileMatrixSetLink>
   <ResourceURL format="image/png" resourceType="tile"
    template="https://gibs.example/NDVI_16/default/{Time}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png"/>
  </Layer>
  <Layer>
   <ows:Title>Rain daily</ows:Title>
   <ows:Identifier>RAIN</ows:Identifier>
   <Format>image/png</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier>
    <Value>2000-06-01/2026-11-13/P1D</Value>
    <Value>2026-01-01T00:00:00Z/2026-11-13T00:00:00Z/PT30M</Value>
   </Dimension>
   <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible_Level6</TileMatrixSet></TileMatrixSetLink>
   <ResourceURL format="image/png" resourceType="tile"
    template="https://gibs.example/RAIN/default/{Time}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png"/>
  </Layer>
  <Layer>
   <ows:Title>Relief</ows:Title>
   <ows:Identifier>DEM</ows:Identifier>
   <Format>image/png</Format>
   <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible_Level12</TileMatrixSet></TileMatrixSetLink>
   <ResourceURL format="image/png" resourceType="tile"
    template="https://gibs.example/DEM/default/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png"/>
  </Layer>
  <Layer>
   <ows:Title>Ignored</ows:Title>
   <ows:Identifier>OTHER</ows:Identifier>
   <Format>image/png</Format>
   <TileMatrixSetLink><TileMatrixSet>X_Level1</TileMatrixSet></TileMatrixSetLink>
   <ResourceURL format="image/png" resourceType="tile" template="x"/>
  </Layer>
 </Contents>
</Capabilities>"""

LAYERS = parse_capabilities(_CAPS, ["NDVI_16", "RAIN", "DEM"])
LENS = {"id": "verde", "nome": "Verde", "fonte": "MODIS", "colormap": "MODIS_L3_NDVI", "periodo": "16 dias"}


def test_parse_capabilities_reads_only_wanted_layers() -> None:
    assert set(LAYERS) == {"NDVI_16", "RAIN", "DEM"}
    ndvi = LAYERS["NDVI_16"]
    assert ndvi.max_native_zoom == 9
    assert ndvi.first_date == date(2000, 3, 5) and ndvi.last_date == date(2026, 10, 16)
    assert len(LAYERS["RAIN"].intervals) == 1  # PT30M (sub-diário) é ignorado
    assert LAYERS["DEM"].intervals == ()


def test_snap_16_day_composite_inside_and_latest() -> None:
    ndvi = LAYERS["NDVI_16"]
    inside = snap_date(ndvi, date(2026, 3, 15))
    assert (inside.start, inside.end, inside.is_latest) == (date(2026, 3, 6), date(2026, 3, 21), False)
    latest = snap_date(ndvi, date(2026, 11, 15))
    # o fim do intervalo (16/10) é o início da última composição, que vai até 31/10
    assert (latest.start, latest.end, latest.is_latest) == (date(2026, 10, 16), date(2026, 10, 31), True)


def test_snap_gap_between_intervals() -> None:
    # logo depois do fim do intervalo, a última composição ainda cobre a data
    assert snap_date(LAYERS["NDVI_16"], date(2000, 12, 25)).start == date(2000, 12, 18)
    # anos depois, dentro do buraco: sem imagem (não mostrar 2000 como se fosse 2015)
    assert snap_date(LAYERS["NDVI_16"], date(2015, 6, 1)) is None
    view = build_lens_view(LENS, LAYERS["NDVI_16"], date(2015, 6, 1))
    assert view.state == "sem_dado" and "falha na série" in view.status_text


def test_snap_before_series_start_is_none() -> None:
    assert snap_date(LAYERS["NDVI_16"], date(1999, 1, 1)) is None


def test_snap_daily() -> None:
    img = snap_date(LAYERS["RAIN"], date(2025, 3, 15))
    assert img.start == img.end == date(2025, 3, 15)


def test_tile_url_uses_resource_template() -> None:
    img = snap_date(LAYERS["RAIN"], date(2025, 3, 15))
    assert tile_url(LAYERS["RAIN"], img) == "https://gibs.example/RAIN/default/2025-03-15/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png"
    assert tile_url(LAYERS["DEM"], None).endswith("/GoogleMapsCompatible_Level12/{z}/{y}/{x}.png")
    with pytest.raises(ValueError):
        tile_url(LAYERS["RAIN"], None)


def test_lens_view_states() -> None:
    assert build_lens_view(LENS, LAYERS["NDVI_16"], date(1999, 5, 1)).state == "sem_dado"
    assert build_lens_view(LENS, LAYERS["NDVI_16"], date(2026, 3, 15)).state == "ok"
    latest = build_lens_view(LENS, LAYERS["NDVI_16"], date(2026, 11, 15))
    assert latest.state == "mais_recente"
    assert "16/10 a 31/10/2026" in latest.status_text
    assert build_lens_view(LENS, LAYERS["DEM"], date(2026, 1, 1)).state == "fixo"


def test_pixel_helpers() -> None:
    assert pixel_label(10) == "cerca de 10 km"
    assert pixel_label(0.25) == "cerca de 250 m"
    (s, w), (n, e) = pixel_bounds(-9.0, -40.0, 10)
    assert distance_km(s, -40.0, n, -40.0) == pytest.approx(10, rel=0.01)
    assert distance_km(-9.0, w, -9.0, e) == pytest.approx(10, rel=0.01)


def test_month_rain_total_normal_and_incomplete() -> None:
    dates = np.arange(np.datetime64("1991-01-01"), np.datetime64("2026-03-11"), dtype="datetime64[D]")
    precip = np.where((dates.astype("datetime64[M]").astype(int) % 12) == 2, 2.0, 0.0)  # 2 mm/dia em março
    series = RainSeries("x", dates, precip, "teste")
    full = month_rain(series, 2025, 3)
    assert full.total_mm == pytest.approx(62.0) and full.normal_mm == pytest.approx(62.0)
    series.precip_mm[-1] = np.nan
    partial = month_rain(series, 2026, 3)
    assert partial.total_mm is None and partial.days_with_data == 9


def test_roca_location_and_nearest_preset() -> None:
    roca = Roca(lat=-9.05, lon=-40.9, municipio="Casa Nova", uf="BA", ibge_code="2907202")
    loc = roca.to_location()
    assert loc.location_id == "roca_-9.0500_-40.9000"
    assert loc.ibge_code == "2907202" and loc.state == "BA"
    preset, km = nearest_preset(-9.05, -40.9)
    assert preset.location_id == "petrolina_pe" and 50 < km < 60
    assert Roca(lat=-9.0, lon=-40.0).label.startswith("município não identificado")


def test_place_from_address_matches_ibge_name_without_accents() -> None:
    address = {"municipality": "João Dourado", "ISO3166-2-lvl4": "BR-BA", "country_code": "br"}
    ibge = [{"id": 2918357, "nome": "Joao Dourado"}, {"id": 2914604, "nome": "Irecê"}]
    place = place_from_address(address, ibge)
    assert (place.municipio, place.uf, place.ibge_code) == ("João Dourado", "BA", "2918357")
    assert place_from_address({"city": "X", "ISO3166-2-lvl4": "BR-PE", "country_code": "br"}, ibge).ibge_code is None


def test_place_from_address_rejects_abroad_and_sea() -> None:
    with pytest.raises(GeocodeUnavailable):
        place_from_address({"city": "Lima", "country_code": "pe"}, [])
    with pytest.raises(GeocodeUnavailable):
        place_from_address({}, [])
