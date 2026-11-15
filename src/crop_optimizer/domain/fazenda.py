"""A fazenda do usuário: área total e talhões (área, cultura plantada hoje e data do plantio).

Informada na página Início e guardada só neste computador, em data/fazenda/<location_id>.json (data/ é
ignorado no git), como a análise de campo.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from crop_optimizer.config import Settings, get_settings


@dataclass(slots=True)
class Talhao:
    id: str
    nome: str
    area_ha: float
    cultura: str | None = None  # crop_id plantado hoje (None = sem cultura)
    plantio: date | None = None  # data do plantio da cultura de hoje


@dataclass(slots=True)
class Fazenda:
    area_total_ha: float
    talhoes: list[Talhao] = field(default_factory=list)

    @property
    def area_talhoes_ha(self) -> float:
        return sum(t.area_ha for t in self.talhoes)

    def problems(self) -> list[str]:
        """O que não fecha nos dados informados (a tela mostra; não impede de salvar)."""
        out = []
        if not self.talhoes:
            out.append("Nenhum talhão informado.")
        if any(t.area_ha <= 0 for t in self.talhoes):
            out.append("Todo talhão precisa de área maior que zero.")
        if self.area_total_ha > 0 and self.area_talhoes_ha > self.area_total_ha * 1.001:
            out.append(f"A soma dos talhões ({self.area_talhoes_ha:.1f} ha) passa da área da fazenda "
                       f"({self.area_total_ha:.1f} ha).")
        if any(t.cultura and t.plantio is None for t in self.talhoes):
            out.append("Talhão com cultura plantada precisa da data do plantio.")
        if any(t.plantio and t.plantio > date.today() for t in self.talhoes):
            out.append("A data do plantio não pode estar no futuro.")
        return out


def _path(location_id: str, settings: Settings) -> Path:
    folder = settings.paths.root / "fazenda"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in location_id)
    return folder / f"{safe}.json"


def to_dict(f: Fazenda) -> dict:
    data = asdict(f)
    for t in data["talhoes"]:
        t["plantio"] = t["plantio"].isoformat() if t["plantio"] else None
    return data


def from_dict(data: dict) -> Fazenda:
    talhoes = [
        Talhao(t["id"], t["nome"], float(t["area_ha"]), t.get("cultura") or None,
               date.fromisoformat(t["plantio"]) if t.get("plantio") else None)
        for t in data.get("talhoes", [])
    ]
    return Fazenda(float(data.get("area_total_ha", 0.0)), talhoes)


def load_fazenda(location_id: str, settings: Settings | None = None) -> Fazenda | None:
    path = _path(location_id, settings or get_settings())
    return from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


def save_fazenda(location_id: str, fazenda: Fazenda, settings: Settings | None = None) -> None:
    _path(location_id, settings or get_settings()).write_text(
        json.dumps(to_dict(fazenda), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clear_fazenda(location_id: str, settings: Settings | None = None) -> None:
    path = _path(location_id, settings or get_settings())
    if path.exists():
        path.unlink()
