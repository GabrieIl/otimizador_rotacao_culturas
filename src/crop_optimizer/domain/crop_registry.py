"""Registro das culturas (config/culturas.yaml) e checagem de que cada uma está ligada a todos os dados.

Uma cultura só funciona de ponta a ponta se estiver em todas as fontes que as telas usam. Esta é a lista
de pontos que `check_connections()` confere, um por um:

| Ponto              | Onde                                   | Para quê                                   | Obrigatório para |
|--------------------|----------------------------------------|--------------------------------------------|------------------|
| registro           | config/culturas.yaml                   | grupo e manejo (sequeiro/irrigado)          | todas            |
| nome               | config/aptidao.yaml (culturas.nome)    | nome na tela                                | todas            |
| solo               | config/aptidao.yaml (culturas)         | aptidão do solo (Início)                    | todas            |
| bases              | config/aptidao.yaml (bases_por_cultura)| fator V% da aptidão                         | todas            |
| descricao          | config/aptidao.yaml (descricao_...)    | texto do card em destaque                   | todas            |
| agua               | config/agua.yaml                       | dias que aguenta / intervalo de rega        | todas            |
| icone              | app/icons.py                           | ícone no seletor e nos cards                | todas            |
| motor              | domain/presets.py (CropSpec)           | risco de quebra pela chuva (Monte Carlo)    | sequeiro         |
| chuva_ciclo        | config/culturas.yaml (chuva_ciclo_mm)  | régua de falta de água do motor             | sequeiro         |
| zarc               | config/zarc.yaml                       | janela oficial (só se a tábua tiver)        | opcional         |
"""

from __future__ import annotations

from dataclasses import dataclass

from crop_optimizer.config import load_yaml_config


def registry() -> dict[str, dict]:
    return load_yaml_config("culturas")["culturas"]


def group_names() -> dict[str, str]:
    return load_yaml_config("culturas")["grupos"]


def crop_info(crop_id: str) -> dict:
    return registry().get(crop_id, {})


def is_irrigated(crop_id: str) -> bool:
    return crop_info(crop_id).get("manejo") == "irrigado"


def is_perennial(crop_id: str) -> bool:
    return bool(crop_info(crop_id).get("perene"))


def sequeiro_ids() -> list[str]:
    return [c for c, info in registry().items() if info.get("manejo") == "sequeiro"]


def ordered_ids() -> list[str]:
    """Culturas na ordem dos grupos (para seletor e cards)."""
    reg = registry()
    out: list[str] = []
    for group in group_names():
        out += [c for c, info in reg.items() if info.get("grupo") == group]
    return out + [c for c in reg if c not in out]


@dataclass(frozen=True, slots=True)
class Connection:
    crop_id: str
    point: str
    ok: bool
    required: bool
    detail: str = ""


def check_connections() -> list[Connection]:
    """Cada cultura x cada ponto de dado: está ligada? (veja a tabela no topo do módulo)."""
    from crop_optimizer.app.icons import CROP_ICONS
    from crop_optimizer.domain.presets import crop_map

    apt = load_yaml_config("aptidao")
    agua = load_yaml_config("agua")["culturas"]
    zarc = load_yaml_config("zarc")["culturas"]
    engine = crop_map()
    reg = registry()
    all_ids = set(reg) | set(apt["culturas"]) | set(agua) | set(CROP_ICONS) | set(zarc)
    out: list[Connection] = []
    for crop_id in sorted(all_ids):
        info = reg.get(crop_id, {})
        sequeiro = info.get("manejo") == "sequeiro"
        soil = apt["culturas"].get(crop_id, {})
        soil_keys = {"ph_otimo", "ph_absoluto", "nitrogenio", "fosforo", "potassio", "agua", "erosao_reduz_graus"}
        water = agua.get(crop_id, {})
        water_ok = bool(water.get("reserva_na_planta")) or {"fases_dias", "kc", "zr_m", "p"} <= set(water)
        checks = [
            ("registro", crop_id in reg and info.get("grupo") in group_names()
             and info.get("manejo") in ("sequeiro", "irrigado"), True, "grupo e manejo"),
            ("nome", bool(soil.get("nome")), True, ""),
            ("solo", soil_keys <= set(soil), True, ", ".join(sorted(soil_keys - set(soil)))),
            ("bases", crop_id in apt["bases_por_cultura"], True, ""),
            ("descricao", crop_id in apt["descricao_culturas"], True, ""),
            ("agua", water_ok, True, ""),
            ("icone", crop_id in CROP_ICONS, True, ""),
            ("motor", crop_id in engine, sequeiro, "CropSpec em domain/presets.py"),
            ("chuva_ciclo", "chuva_ciclo_mm" in info, sequeiro, "config/culturas.yaml"),
            ("zarc", crop_id in zarc, False, zarc.get(crop_id, "fora da tábua anual do ZARC")),
        ]
        out += [Connection(crop_id, point, ok, req, detail) for point, ok, req, detail in checks]
    return out


def missing_connections() -> list[Connection]:
    return [c for c in check_connections() if c.required and not c.ok]
