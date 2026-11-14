"""Limitação do solo POR CULTURA (o mesmo solo pode ser bom para o caupi e crítico para o milho).

Para cada cultura, cada fator vira um grau de limitação (nula, ligeira, moderada, forte, muito
forte) comparando o atributo do solo com a exigência da cultura (config/aptidao.yaml):

    nitrogênio  <- classe de matéria orgânica  x  exigência de N
    fósforo     <- classe de P por argila      x  exigência de P
    potássio    <- classe de K                 x  exigência de K
    bases       <- classe de V%                x  exigência de Ca/Mg
    acidez      <- pH contra a faixa ótima/absoluta da cultura (FAO Ecocrop)
    água        <- textura (retenção)          x  sensibilidade à seca
    erosão      <- classe de relevo            -  proteção das perenes

Grau -> nota (Sys et al., 1991). Índice = nota mínima x raiz(produto das demais) x 100
(método da raiz quadrada). O fator para o Monte Carlo é relativo ao solo típico do semiárido,
porque a produtividade base das culturas já representa a roça típica da região.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import SoilHealthState
from crop_optimizer.domain.soil_profile import SoilProfile, reference_values
from crop_optimizer.engine.markov_soil import STATE_ORGANIC_MATTER_PCT

NUTRIENT_CLASSES = ["muito_baixo", "baixo", "medio", "bom", "muito_bom"]
CLASS_LABELS = {"muito_baixo": "muito baixo", "baixo": "baixo", "medio": "médio", "bom": "bom", "muito_bom": "muito bom"}
DEGREES = ["nula", "ligeira", "moderada", "forte", "muito_forte"]
DEGREE_LABELS = {"nula": "nenhuma", "ligeira": "ligeira", "moderada": "moderada", "forte": "forte", "muito_forte": "muito forte"}
FACTOR_LABELS = {
    "nitrogenio": "Nitrogênio",
    "fosforo": "Fósforo",
    "potassio": "Potássio",
    "bases": "Cálcio e magnésio (V%)",
    "acidez": "Acidez (pH)",
    "agua": "Água retida (textura)",
    "erosao": "Erosão (declividade)",
}
# atributo que alimenta cada fator (para saber se foi medido, mapeado ou assumido)
FACTOR_ATTR = {
    "nitrogenio": "mo_pct",
    "fosforo": "p_mehlich",
    "potassio": "k_mg_dm3",
    "bases": "v_pct",
    "acidez": "ph_h2o",
    "agua": "areia_pct",
    "erosao": "declividade_pct",
}


def classify(value: float, upper_limits: list[float]) -> str:
    """Classe pelos limites superiores de muito_baixo, baixo, medio e bom."""
    for name, limit in zip(NUTRIENT_CLASSES, upper_limits, strict=False):
        if value <= limit:
            return name
    return NUTRIENT_CLASSES[-1]


def phosphorus_class(p: float, clay_pct: float) -> str:
    for row in load_yaml_config("aptidao")["classes_analise"]["p_mehlich_por_argila"]:
        if clay_pct <= row["argila_max"]:
            return classify(p, row["limites"])
    return classify(p, load_yaml_config("aptidao")["classes_analise"]["p_mehlich_por_argila"][-1]["limites"])


def texture_class(sand_pct: float, clay_pct: float) -> str:
    cfg = load_yaml_config("aptidao")["textura"]
    if clay_pct >= cfg["muito_argilosa_argila_min"]:
        return "muito_argilosa"
    if clay_pct >= cfg["argilosa_argila_min"]:
        return "argilosa"
    if sand_pct - clay_pct >= cfg["arenosa_areia_menos_argila_min"]:
        return "arenosa"
    return "media"


TEXTURE_LABELS = {"arenosa": "arenosa", "media": "média", "argilosa": "argilosa", "muito_argilosa": "muito argilosa"}


def relief_class(slope_pct: float) -> dict:
    for row in load_yaml_config("aptidao")["relevo_classes"]:
        if slope_pct <= row["max"]:
            return row
    return load_yaml_config("aptidao")["relevo_classes"][-1]


def _shift(degree: str, steps: int) -> str:
    return DEGREES[max(0, min(len(DEGREES) - 1, DEGREES.index(degree) + steps))]


def _ph_degree(ph: float, optimum: list[float], absolute: list[float]) -> str:
    cfg = load_yaml_config("aptidao")
    if optimum[0] <= ph <= optimum[1]:
        return "nula"
    if not absolute[0] <= ph <= absolute[1]:
        return cfg["ph_grau_fora_absoluto"]
    distance = optimum[0] - ph if ph < optimum[0] else ph - optimum[1]
    for row in cfg["ph_graus_fora_otimo"]:
        if distance <= row["ate_unidades"]:
            return row["grau"]
    return "forte"


@dataclass(frozen=True, slots=True)
class FactorResult:
    factor: str
    degree: str
    rating: float
    reason: str
    assumed: bool  # o atributo veio do solo de referência (sem dado local)

    @property
    def label(self) -> str:
        return FACTOR_LABELS[self.factor]


@dataclass(frozen=True, slots=True)
class CropSuitability:
    crop_id: str
    name: str
    index: float
    suit_class: str
    label: str
    factors: tuple[FactorResult, ...]
    yield_factor: float  # relativo ao solo típico do semiárido (vai para o Monte Carlo)

    @property
    def limiting(self) -> FactorResult:
        return min(self.factors, key=lambda f: f.rating)

    @property
    def any_assumed(self) -> bool:
        return any(f.assumed and f.degree != "nula" for f in self.factors)


def _factors(values: dict[str, float], sources: dict[str, str], crop_id: str) -> list[FactorResult]:
    cfg = load_yaml_config("aptidao")
    req = cfg["culturas"][crop_id]
    notes = cfg["notas_grau"]
    nut = cfg["grau_por_classe_nutriente"]
    classes = cfg["classes_analise"]
    out: list[FactorResult] = []

    def add(factor: str, degree: str, reason: str) -> None:
        out.append(
            FactorResult(factor, degree, float(notes[degree]), reason, sources.get(FACTOR_ATTR[factor]) == "referencia")
        )

    mo_cls = classify(values["mo_pct"], classes["mo_pct"])
    add("nitrogenio", nut[req["nitrogenio"]][mo_cls],
        f"matéria orgânica {CLASS_LABELS[mo_cls]} ({values['mo_pct']:.1f}%); exigência de N {req['nitrogenio']}")
    p_cls = phosphorus_class(values["p_mehlich"], values["argila_pct"])
    add("fosforo", nut[req["fosforo"]][p_cls],
        f"fósforo {CLASS_LABELS[p_cls]} ({values['p_mehlich']:.1f} mg/dm³ com {values['argila_pct']:.0f}% de argila); "
        f"exigência {req['fosforo']}")
    k_cls = classify(values["k_mg_dm3"], classes["k_mg_dm3"])
    add("potassio", nut[req["potassio"]][k_cls],
        f"potássio {CLASS_LABELS[k_cls]} ({values['k_mg_dm3']:.0f} mg/dm³); exigência {req['potassio']}")
    v_cls = classify(values["v_pct"], classes["v_pct"])
    bases_req = cfg["bases_por_cultura"][crop_id]
    add("bases", nut[bases_req][v_cls], f"V% {CLASS_LABELS[v_cls]} ({values['v_pct']:.0f}%); exigência {bases_req}")
    add("acidez", _ph_degree(values["ph_h2o"], req["ph_otimo"], req["ph_absoluto"]),
        f"pH {values['ph_h2o']:.1f}; faixa boa para a cultura {req['ph_otimo'][0]}-{req['ph_otimo'][1]}")
    tex = texture_class(values["areia_pct"], values["argila_pct"])
    add("agua", cfg["grau_por_textura"][req["agua"]][tex],
        f"solo de textura {TEXTURE_LABELS[tex]}; sensibilidade à seca {req['agua']}")
    relief = relief_class(values["declividade_pct"])
    add("erosao", _shift(relief["grau"], -int(req["erosao_reduz_graus"])),
        f"relevo {relief['nome']} ({values['declividade_pct']:.0f}%)"
        + ("; cultura perene protege o solo" if req["erosao_reduz_graus"] else ""))
    return out


def land_index(ratings: list[float]) -> float:
    """Método da raiz quadrada: nota mínima x raiz(produto das demais) x 100."""
    if not ratings:
        return 100.0
    ordered = sorted(ratings)
    return 100.0 * ordered[0] * math.sqrt(math.prod(ordered[1:]))


def _index_class(index: float) -> dict:
    for row in load_yaml_config("aptidao")["classes_indice"]:
        if index >= row["min"]:
            return row
    return load_yaml_config("aptidao")["classes_indice"][-1]


def evaluate(profile: SoilProfile) -> list[CropSuitability]:
    cfg = load_yaml_config("aptidao")
    values = {k: v.value for k, v in profile.values.items()}
    sources = {k: v.source for k, v in profile.values.items()}
    ref = reference_values()
    low, high = cfg["fator_solo_limites"]
    out: list[CropSuitability] = []
    for crop_id, req in cfg["culturas"].items():
        ref_factors = {f.factor: f for f in _factors(ref, {}, crop_id)}
        # Fator cujo atributo não tem dado local usa o grau do solo de referência: fica neutro
        # (não penaliza nem beneficia) mesmo que outro atributo (ex.: argila) mude a classe.
        factors = [
            FactorResult(f.factor, ref_factors[f.factor].degree, ref_factors[f.factor].rating,
                         "sem dado local: assumido o valor típico do semiárido", True)
            if f.assumed else f
            for f in _factors(values, sources, crop_id)
        ]
        index = land_index([f.rating for f in factors])
        ref_index = land_index([f.rating for f in ref_factors.values()])
        row = _index_class(index)
        out.append(
            CropSuitability(
                crop_id=crop_id,
                name=req["nome"],
                index=index,
                suit_class=row["classe"],
                label=row["rotulo"],
                factors=tuple(factors),
                yield_factor=float(np.clip(index / ref_index, low, high)),
            )
        )
    return out


def initial_markov_state(om_pct: float) -> SoilHealthState:
    """Estado da cadeia de Markov cuja meta de M.O. é a mais próxima da M.O. do local.

    Mantém a dinâmica coerente (a M.O. simulada não "pula" para a meta do estado logo no
    primeiro ano). O estado não é rótulo de qualidade para o usuário: a qualidade é por cultura.
    """
    return SoilHealthState(int(np.argmin(np.abs(STATE_ORGANIC_MATTER_PCT - om_pct))))


def available_nitrogen_kg_ha(profile: SoilProfile) -> float:
    """N disponível no ano (kg/ha) ~ N total na camada x taxa de mineralização.

    N total vem da M.O. (x fração de N) quando há análise de campo de M.O.; senão, do N total do
    SoilGrids; senão, da M.O. assumida. Parâmetros em config/aptidao.yaml (REVISAR AGRÔNOMO).
    """
    cfg = load_yaml_config("aptidao")["nitrogenio_disponivel"]
    density = profile.density_g_cm3 or float(cfg["densidade_solo_g_cm3"])
    soil_mass_kg_ha = density * 1000.0 * (float(cfg["profundidade_cm"]) / 100.0) * 10_000.0
    mo = profile.values["mo_pct"]
    if mo.source != "campo" and profile.n_total_g_kg is not None:
        n_total = profile.n_total_g_kg / 1000.0 * soil_mass_kg_ha
    else:
        n_total = mo.value / 100.0 * float(cfg["fracao_n_na_mo"]) * soil_mass_kg_ha
    return float(np.clip(n_total * float(cfg["taxa_mineralizacao_ano"]), 16.0, 145.0))
