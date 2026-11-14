"""Coordenada da roça -> município, UF e código IBGE.

1. Nominatim (OpenStreetMap) devolve o nome do município e a UF da coordenada.
2. A API de localidades do IBGE devolve a lista oficial de municípios da UF; o código
   vem do município com o mesmo nome (sem acento/maiúscula).

Respostas guardadas sem alteração em data/bronze/nominatim/ e data/bronze/ibge/.
"""

from __future__ import annotations

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
    name = address.get("city") or address.get("municipality") or address.get("town") or address.get("village")
    iso = address.get("ISO3166-2-lvl4", "")
    if not name or not iso.startswith("BR-"):
        raise GeocodeUnavailable("Não achamos um município nesse ponto (está no mar ou em área sem cadastro?).")
    uf = iso[3:]
    code = None
    if municipalities:
        wanted = _normalize(name)
        for mun in municipalities:
            if _normalize(mun["nome"]) == wanted:
                code = str(mun["id"])
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
