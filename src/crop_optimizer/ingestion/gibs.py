"""NASA GIBS (Global Imagery Browse Services): camadas WMTS para as lentes do mapa.

O GetCapabilities (~6 MB) é guardado em data/bronze/gibs/, um arquivo por dia. Dele saem,
para cada camada, o formato, a grade de tiles e os períodos com imagem. Com isso:
- a data pedida é encaixada na imagem que existe (ex.: composição de 16 dias que a contém);
- antes do início da série, a lente diz "sem imagem neste ano" em vez de mostrar tile vazio.
"""

from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "gibs"
_NS = {"w": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1"}
_PERIOD = re.compile(r"^P(\d+)([DMY])$")


class GibsUnavailable(RuntimeError):
    """Sem GetCapabilities do GIBS (rede fora e nenhum cache)."""


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: date
    end: date
    step: int
    unit: str  # D, M ou Y


@dataclass(frozen=True, slots=True)
class GibsLayer:
    identifier: str
    title: str
    matrix_set: str
    url_template: str  # ResourceURL do GetCapabilities
    intervals: tuple[TimeInterval, ...]  # vazio = camada fixa, sem data

    @property
    def max_native_zoom(self) -> int:
        return int(self.matrix_set.rsplit("Level", 1)[-1])

    @property
    def first_date(self) -> date | None:
        return self.intervals[0].start if self.intervals else None

    @property
    def last_date(self) -> date | None:
        return self.intervals[-1].end if self.intervals else None


@dataclass(frozen=True, slots=True)
class SnappedImage:
    """Imagem que de fato será mostrada para a data pedida."""

    start: date
    end: date  # igual a start em produto diário; fim da composição em 8/16 dias
    is_latest: bool  # a data pedida era posterior ao último dado: mostramos o mais recente


def _parse_date(text: str) -> date:
    return date.fromisoformat(text[:10])


def _add(d: date, n: int, unit: str) -> date:
    if unit == "D":
        return d + timedelta(days=n)
    months = n if unit == "M" else 12 * n
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _steps_between(start: date, d: date, step: int, unit: str) -> int:
    if unit == "D":
        return (d - start).days // step
    months = (d.year - start.year) * 12 + (d.month - start.month) - (d.day < start.day)
    return months // (step if unit == "M" else 12 * step)


def parse_capabilities(xml_bytes: bytes, layer_ids: list[str]) -> dict[str, GibsLayer]:
    root = ET.fromstring(xml_bytes)
    wanted = set(layer_ids)
    out: dict[str, GibsLayer] = {}
    for node in root.find("w:Contents", _NS).findall("w:Layer", _NS):
        ident = node.find("ows:Identifier", _NS).text
        if ident not in wanted:
            continue
        intervals: list[TimeInterval] = []
        dim = node.find("w:Dimension", _NS)
        if dim is not None:
            for value in dim.findall("w:Value", _NS):
                start, end, period = value.text.split("/")
                match = _PERIOD.match(period)
                if match is None:  # sub-diário (PT30M): fora do escopo das lentes
                    continue
                intervals.append(
                    TimeInterval(_parse_date(start), _parse_date(end), int(match[1]), match[2])
                )
        intervals.sort(key=lambda iv: iv.start)
        out[ident] = GibsLayer(
            identifier=ident,
            title=node.find("ows:Title", _NS).text,
            matrix_set=node.find("w:TileMatrixSetLink/w:TileMatrixSet", _NS).text,
            url_template=node.find("w:ResourceURL", _NS).get("template"),
            intervals=tuple(intervals),
        )
    return out


def snap_date(layer: GibsLayer, wanted: date) -> SnappedImage | None:
    """Imagem que cobre `wanted`; None se a série ainda não existia nessa data."""
    if not layer.intervals:
        return None
    if wanted < layer.intervals[0].start:
        return None
    is_latest = wanted > layer.intervals[-1].end
    target = min(wanted, layer.intervals[-1].end)
    chosen = [iv for iv in layer.intervals if iv.start <= target][-1]
    if target > chosen.end:
        # buraco na série: aceita a última imagem só se ela ainda cobre a data pedida
        last_end = _add(chosen.end, chosen.step, chosen.unit) - timedelta(days=1)
        if target > last_end:
            return None
        target = chosen.end
    steps = _steps_between(chosen.start, target, chosen.step, chosen.unit)
    start = _add(chosen.start, steps * chosen.step, chosen.unit)
    end = _add(start, chosen.step, chosen.unit) - timedelta(days=1)
    # No GIBS o fim do intervalo é o INÍCIO da última composição; a composição segue por `step`.
    if chosen.step == 1 and chosen.unit == "D":
        end = start
    return SnappedImage(start=start, end=end, is_latest=is_latest)


def tile_url(layer: GibsLayer, image: SnappedImage | None) -> str:
    """URL de tiles no formato do Leaflet ({z}/{y}/{x})."""
    url = (
        layer.url_template.replace("{TileMatrixSet}", layer.matrix_set)
        .replace("{TileMatrix}", "{z}")
        .replace("{TileRow}", "{y}")
        .replace("{TileCol}", "{x}")
    )
    if "{Time}" in url:
        if image is None:
            raise ValueError(f"{layer.identifier} sem imagem para a data pedida")
        url = url.replace("{Time}", image.start.isoformat())
    return url


def legend_url(colormap: str) -> str:
    return load_yaml_config("lentes")["gibs"]["legenda_url"].format(colormap=colormap)


def _latest_cached(folder: Path) -> Path | None:
    files = sorted(folder.glob("wmts_epsg3857_best_*.xml"))
    return files[-1] if files else None


def load_layers(
    layer_ids: list[str], today: date | None = None, settings: Settings | None = None
) -> tuple[dict[str, GibsLayer], date]:
    """Camadas pedidas + data do GetCapabilities usado (pode ser de um dia anterior se a rede falhar)."""
    cfg = load_yaml_config("lentes")["gibs"]
    settings = settings or get_settings()
    today = today or date.today()
    folder = settings.paths.bronze_source(SOURCE_DIR)
    path = folder / f"wmts_epsg3857_best_{today:%Y%m%d}.xml"
    if not path.exists():
        try:
            with httpx.Client(timeout=float(cfg["timeout_segundos"])) as client:
                response = client.get(cfg["capabilities_url"])
                response.raise_for_status()
            path.write_bytes(response.content)
        except Exception as exc:  # noqa: BLE001
            fallback = _latest_cached(folder)
            if fallback is None:
                raise GibsUnavailable(f"NASA GIBS indisponível e sem cache local: {exc}") from exc
            path = fallback
    caps_date = date.fromisoformat(
        f"{path.stem[-8:-4]}-{path.stem[-4:-2]}-{path.stem[-2:]}"
    )
    return parse_capabilities(path.read_bytes(), layer_ids), caps_date
