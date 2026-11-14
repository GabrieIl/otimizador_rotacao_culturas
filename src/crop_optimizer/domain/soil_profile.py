"""Perfil do solo de um local: cada atributo sabe de onde veio.

Prioridade: análise de campo (informada pelo usuário) > satélite/mapa (SoilGrids, relevo) >
referência regional (solo típico do semiárido, config/aptidao.yaml). Atributo que vem da
referência é "assumido": não penaliza nem beneficia a cultura, e a tela avisa.

A análise de campo fica em data/campo/<location_id>.json (só na máquina; data/ é ignorado no git).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from crop_optimizer.config import Settings, get_settings, load_yaml_config

Source = Literal["campo", "satelite", "referencia"]

# atributo -> (rótulo, unidade, casas decimais)
ATTRIBUTES: dict[str, tuple[str, str, int]] = {
    "argila_pct": ("Argila", "%", 0),
    "areia_pct": ("Areia", "%", 0),
    "mo_pct": ("Matéria orgânica", "%", 2),
    "ph_h2o": ("pH em água", "", 1),
    "p_mehlich": ("Fósforo (Mehlich-1)", "mg/dm³", 1),
    "k_mg_dm3": ("Potássio (Mehlich-1)", "mg/dm³", 0),
    "v_pct": ("Saturação por bases (V)", "%", 0),
    "ctc_t": ("CTC a pH 7 (T)", "cmolc/dm³", 1),
    "declividade_pct": ("Declividade", "%", 1),
}
# o que nenhum satélite estima: só análise de campo
FIELD_ONLY = ("p_mehlich", "k_mg_dm3", "v_pct")


@dataclass(frozen=True, slots=True)
class SoilValue:
    value: float
    source: Source
    low: float | None = None  # faixa de incerteza (quantil 5%) quando vem do mapa
    high: float | None = None  # quantil 95%
    detail: str = ""


@dataclass(slots=True)
class SoilProfile:
    values: dict[str, SoilValue]
    elevation_m: float | None = None
    n_total_g_kg: float | None = None
    density_g_cm3: float | None = None
    warnings: list[str] = field(default_factory=list)
    field_date: str | None = None

    def get(self, attr: str) -> float:
        return self.values[attr].value

    def source_of(self, attr: str) -> Source:
        return self.values[attr].source


def reference_values() -> dict[str, float]:
    return {k: float(v) for k, v in load_yaml_config("aptidao")["solo_referencia"].items()}


def build_profile(
    satellite: dict | None,
    terrain: object | None,
    field_data: dict | None,
    warnings: list[str] | None = None,
) -> SoilProfile:
    """Junta as fontes. `satellite`: saída de fetch_soilgrids; `terrain`: TerrainInfo."""
    cfg = load_yaml_config("aptidao")
    ref = reference_values()
    values: dict[str, SoilValue] = {}
    sat = satellite or {}

    def from_sat(name: str, scale: float = 1.0) -> SoilValue | None:
        item = sat.get(name)
        if item is None:
            return None
        return SoilValue(item.mean * scale, "satelite", item.q05 * scale, item.q95 * scale, "SoilGrids 250 m")

    sat_values = {
        "argila_pct": from_sat("clay"),
        "areia_pct": from_sat("sand"),
        # SoilGrids soc em g/kg -> C.O. dag/kg (/10) -> M.O. (x 1,724)
        "mo_pct": from_sat("soc", float(cfg["fator_carbono_para_mo"]) / 10.0),
        "ph_h2o": from_sat("phh2o"),
        # cmol(c)/kg ~ cmolc/dm3 (aproximação: densidade ~1)  # REVISAR AGRÔNOMO
        "ctc_t": from_sat("cec"),
    }
    if terrain is not None:
        sat_values["declividade_pct"] = SoilValue(
            terrain.slope_pct, "satelite", detail=f"relevo SRTM (Terrain Tiles), pixel ~{terrain.pixel_m:.0f} m"
        )

    field_values = (field_data or {}).get("valores", {})
    for attr in ATTRIBUTES:
        raw = field_values.get(attr)
        if raw is not None:
            values[attr] = SoilValue(float(raw), "campo", detail="análise de campo")
        elif sat_values.get(attr) is not None:
            values[attr] = sat_values[attr]
        else:
            detail = "só análise de solo mede" if attr in FIELD_ONLY else "sem dado no mapa"
            values[attr] = SoilValue(ref[attr], "referencia", detail=f"valor típico do semiárido ({detail})")

    n_total = sat["nitrogen"].mean if "nitrogen" in sat else None
    density = sat["bdod"].mean if "bdod" in sat else None
    return SoilProfile(
        values=values,
        elevation_m=getattr(terrain, "elevation_m", None),
        n_total_g_kg=n_total,
        density_g_cm3=density,
        warnings=list(warnings or []),
        field_date=(field_data or {}).get("data"),
    )


# --- análise de campo -------------------------------------------------------

def _field_path(location_id: str, settings: Settings) -> Path:
    folder = settings.paths.root / "campo"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in location_id)
    return folder / f"{safe}.json"


def load_field_data(location_id: str, settings: Settings | None = None) -> dict | None:
    path = _field_path(location_id, settings or get_settings())
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_field_data(
    location_id: str, valores: dict[str, float | None], nota: str = "", settings: Settings | None = None
) -> dict:
    clean = {k: float(v) for k, v in valores.items() if k in ATTRIBUTES and v is not None}
    data = {"valores": clean, "data": date.today().isoformat(), "nota": nota}
    _field_path(location_id, settings or get_settings()).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def clear_field_data(location_id: str, settings: Settings | None = None) -> None:
    path = _field_path(location_id, settings or get_settings())
    if path.exists():
        path.unlink()
