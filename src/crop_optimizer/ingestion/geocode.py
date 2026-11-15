"""Coordenada da roça -> município, UF e código IBGE.

1. Nominatim (OpenStreetMap) devolve o nome do município e a UF da coordenada.
2. A API de localidades do IBGE devolve a lista oficial de municípios da UF; o código
   vem do município com o mesmo nome (sem acento/maiúscula).

Respostas guardadas sem alteração em data/bronze/nominatim/ e data/bronze/ibge/.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import httpx

from crop_optimizer.config import Settings, get_settings, load_yaml_config


class GeocodeUnavailable(RuntimeError):
    """Não deu para descobrir o município (rede fora, ponto no mar, fora do Brasil...)."""


@dataclass(frozen=True, slots=True)
class Place:
    municipio: str
    uf: str
    ibge_code: str | None


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    municipio: str
    uf: str
    ibge_code: str | None
    lat: float
    lon: float
    display_name: str = ""

    @property
    def label(self) -> str:
        return f"{self.municipio}/{self.uf}" if self.uf else self.municipio


BRAZIL_UFS: tuple[str, ...] = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)


def inside_brazil_box(lat: float, lon: float) -> bool:
    box = load_yaml_config("localizacao")["limites_brasil"]
    return box["lat_min"] <= lat <= box["lat_max"] and box["lon_min"] <= lon <= box["lon_max"]


def _normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(text.lower().replace("-", " ").replace("'", " ").split())


def _get_json(url: str, params: dict | None, cache: Path, timeout: float, headers: dict | None = None):
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        with httpx.Client(timeout=timeout, headers=headers or {}) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise GeocodeUnavailable(f"Falha ao consultar {url.split('/')[2]}: {exc}") from exc
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _reverse(lat: float, lon: float, settings: Settings) -> dict:
    cfg = load_yaml_config("localizacao")["nominatim"]
    cache = settings.paths.bronze_source("nominatim") / f"reverse_{lat:.4f}_{lon:.4f}_z{cfg['zoom']}.json"
    return _get_json(
        cfg["url"],
        {
            "format": "jsonv2",
            "lat": f"{lat:.4f}",
            "lon": f"{lon:.4f}",
            "zoom": cfg["zoom"],
            "addressdetails": 1,
            "accept-language": "pt-BR",
        },
        cache,
        float(cfg["timeout_segundos"]),
        headers={"User-Agent": cfg["user_agent"]},
    )


def _municipalities(uf: str, settings: Settings) -> list[dict]:
    cfg = load_yaml_config("localizacao")["ibge"]
    cache = settings.paths.bronze_source("ibge") / f"municipios_{uf}.json"
    return _get_json(cfg["url_municipios"].format(uf=uf), None, cache, float(cfg["timeout_segundos"]))


def place_from_address(address: dict, municipalities: list[dict] | None) -> Place:
    """Separado da rede para poder testar: endereço do Nominatim + lista do IBGE -> Place."""
    if address.get("country_code") not in (None, "br"):
        raise GeocodeUnavailable("O ponto não fica no Brasil.")
    candidates = [
        str(address[k]).strip()
        for k in ("city", "municipality", "town", "village", "county")
        if address.get(k)
    ]
    iso = address.get("ISO3166-2-lvl4", "")
    if not candidates or not iso.startswith("BR-"):
        raise GeocodeUnavailable("Não achamos um município nesse ponto (está no mar ou em área sem cadastro?).")
    name = candidates[0]
    uf = iso[3:]
    code = None
    if municipalities:
        by_norm = {_normalize(mun["nome"]): mun for mun in municipalities}
        for candidate in candidates:
            mun = by_norm.get(_normalize(candidate))
            if mun is not None:
                code = str(mun["id"])
                name = str(mun["nome"]) if candidate != name else name
                break
    return Place(municipio=name, uf=uf, ibge_code=code)


def resolve_place(lat: float, lon: float, settings: Settings | None = None) -> Place:
    settings = settings or get_settings()
    if not inside_brazil_box(lat, lon):
        raise GeocodeUnavailable("A coordenada está fora do Brasil.")
    payload = _reverse(lat, lon, settings)
    if "error" in payload:
        raise GeocodeUnavailable(f"OpenStreetMap não achou endereço nesse ponto: {payload['error']}")
    address = payload.get("address", {})
    uf = address.get("ISO3166-2-lvl4", "BR-")[3:]
    municipalities = _municipalities(uf, settings) if uf else None
    return place_from_address(address, municipalities)


def _search_nominatim(query: str, uf: str | None, settings: Settings) -> list[dict]:
    cfg = load_yaml_config("localizacao")["nominatim"]
    search_url = cfg.get("search_url", "https://nominatim.openstreetmap.org/search")
    cleaned = query.strip()
    full_query = f"{cleaned}, {uf}, Brasil" if uf else f"{cleaned}, Brasil"
    key = hashlib.sha1(full_query.lower().encode("utf-8")).hexdigest()[:16]
    cache = settings.paths.bronze_source("nominatim") / f"search_{key}.json"
    return _get_json(
        search_url,
        {
            "format": "jsonv2",
            "q": full_query,
            "countrycodes": "br",
            "addressdetails": 1,
            "limit": 6,
            "accept-language": "pt-BR",
        },
        cache,
        float(cfg["timeout_segundos"]),
        headers={"User-Agent": cfg["user_agent"]},
    )


def candidates_from_hits(
    hits: list[dict],
    municipalities_by_uf: dict[str, list[dict] | None] | None = None,
) -> list[PlaceCandidate]:
    """Converte resultados do Nominatim Search em `PlaceCandidate` únicos no Brasil."""
    found: list[PlaceCandidate] = []
    seen: set[tuple[str, str]] = set()
    by_uf = municipalities_by_uf or {}
    for hit in hits:
        try:
            lat = float(hit["lat"])
            lon = float(hit["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not inside_brazil_box(lat, lon):
            continue
        address = hit.get("address", {})
        uf = str(address.get("ISO3166-2-lvl4", "BR-"))[3:]
        try:
            place = place_from_address(address, by_uf.get(uf))
        except GeocodeUnavailable:
            continue
        dedup_key = (_normalize(place.municipio), place.uf)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        found.append(
            PlaceCandidate(
                municipio=place.municipio,
                uf=place.uf,
                ibge_code=place.ibge_code,
                lat=round(lat, 5),
                lon=round(lon, 5),
                display_name=str(hit.get("display_name", place.municipio)),
            )
        )
    return found


def search_places(
    query: str,
    uf: str | None = None,
    settings: Settings | None = None,
) -> list[PlaceCandidate]:
    """Busca município, povoado ou CEP pelo nome e resolve coordenadas + código IBGE."""
    cleaned = query.strip()
    if not cleaned:
        raise GeocodeUnavailable("Digite o nome do município, povoado ou CEP para buscar.")
    settings = settings or get_settings()
    uf_norm = uf.strip().upper() if uf and uf.strip() else None
    hits = _search_nominatim(cleaned, uf_norm, settings)
    if not isinstance(hits, list):
        return []
    muns_by_uf: dict[str, list[dict] | None] = {}
    for hit in hits:
        hit_uf = str(hit.get("address", {}).get("ISO3166-2-lvl4", "BR-"))[3:]
        if hit_uf and hit_uf not in muns_by_uf:
            try:
                muns_by_uf[hit_uf] = _municipalities(hit_uf, settings)
            except GeocodeUnavailable:
                muns_by_uf[hit_uf] = None
    return candidates_from_hits(hits, muns_by_uf)
