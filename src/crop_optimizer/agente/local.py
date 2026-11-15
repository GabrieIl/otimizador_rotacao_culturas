"""Onde fica a roça de quem está conversando: município de exemplo ou ponto (pin do WhatsApp)."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass

from crop_optimizer.config import Settings
from crop_optimizer.domain.models import LocationSpec
from crop_optimizer.domain.presets import DEFAULT_LOCATIONS, location_map
from crop_optimizer.domain.roca import Roca, nearest_preset
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, resolve_place


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in plain).split())


@dataclass(frozen=True, slots=True)
class LocalConversa:
    """Local guardado na sessão. `exemplo_id` é o município de exemplo usado pelo Monte Carlo."""

    exemplo_id: str
    lat: float | None = None  # None = é o próprio município de exemplo
    lon: float | None = None
    municipio: str | None = None
    uf: str | None = None
    ibge_code: str | None = None
    aviso: str | None = None  # por que o município do ponto não foi identificado

    @property
    def is_example(self) -> bool:
        return self.lat is None

    @property
    def exemplo(self) -> LocationSpec:
        return location_map()[self.exemplo_id]

    @property
    def distancia_exemplo_km(self) -> float:
        if self.is_example:
            return 0.0
        return nearest_preset(self.lat, self.lon)[1]

    @property
    def nome(self) -> str:
        if self.is_example:
            return f"{self.exemplo.name}/{self.exemplo.state}"
        return f"{self.municipio}/{self.uf}" if self.municipio else "sua roça (município não identificado)"

    def location(self) -> LocationSpec:
        """Local da chuva, do ZARC e do solo (o mesmo que a página Plantio usa)."""
        if self.is_example:
            return self.exemplo
        roca = Roca(self.lat, self.lon, self.municipio, self.uf, self.ibge_code, self.aviso)
        return roca.to_location()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LocalConversa:
        return cls(**data)


def municipios_aceitos() -> list[str]:
    return [f"{loc.name}/{loc.state}" for loc in DEFAULT_LOCATIONS]


def local_por_municipio(nome: str) -> LocalConversa | None:
    """Município de exemplo pelo nome falado ("quixada", "Quixadá-CE"...). None se não for um deles."""
    wanted = _normalize(nome)
    for loc in DEFAULT_LOCATIONS:
        name = _normalize(loc.name)
        if wanted in (name, f"{name} {loc.state.lower()}") or name in wanted.split() or wanted.startswith(name):
            return LocalConversa(exemplo_id=loc.location_id)
    return None


def local_por_coordenada(lat: float, lon: float, settings: Settings | None = None) -> LocalConversa:
    """Ponto marcado (pin): descobre o município (OpenStreetMap + IBGE) e o exemplo mais perto."""
    exemplo, _km = nearest_preset(lat, lon)
    try:
        place = resolve_place(lat, lon, settings)
    except GeocodeUnavailable as exc:
        return LocalConversa(exemplo.location_id, round(lat, 4), round(lon, 4), aviso=str(exc))
    return LocalConversa(
        exemplo.location_id, round(lat, 4), round(lon, 4), place.municipio, place.uf, place.ibge_code
    )
