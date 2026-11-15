"""Ferramentas do agente: consultam o motor e devolvem JSON pequeno, já em linguagem de conversa.

Regras (CLAUDE.md): toda probabilidade sai como "X de cada 10", nunca percentual; o que vem do
clima sintético sai marcado com `dados_de_exemplo: true`; o modelo de linguagem só repassa os
números daqui, não calcula nada.

Cada ferramenta recebe um `Contexto` (local da conversa e data) e argumentos já validados.
`ESQUEMAS` descreve os argumentos em JSON Schema (formato aceito pelo function calling).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from crop_optimizer.agente import consultas
from crop_optimizer.agente.local import (
    LocalConversa,
    local_por_coordenada,
    local_por_municipio,
    municipios_aceitos,
)
from crop_optimizer.agente.recomendacao import FINALIDADES, Opcao, recomendar, serve_para
from crop_optimizer.analytics.crop_advice import WORDS as RISK_WORDS
from crop_optimizer.analytics.crop_advice import failure_rule_text
from crop_optimizer.analytics.rain_delay import (
    CropWindowStatus,
    RainDelayReport,
    describe_status,
    fmt_date,
    fmt_date_year,
)
from crop_optimizer.analytics.soil_suitability import TEXTURE_LABELS, texture_class
from crop_optimizer.analytics.views import loss_risk_label
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.crop_registry import is_irrigated
from crop_optimizer.domain.fazenda import load_fazenda
from crop_optimizer.domain.models import BalancePriority, StrategySimulationResult
from crop_optimizer.engine import rank_by_survival
from crop_optimizer.engine.candidates import CURRENT_ID
from crop_optimizer.engine.pareto import annual_profit, rank_by_balance_priority

CROP_IDS = consultas.CROP_IDS  # as mesmas culturas da página Plantio, na mesma ordem
HORIZONTES = consultas.HORIZONS
# as mesmas prioridades da página ("O que pesa mais")
PRIORIDADES = {
    "equilibrio": BalancePriority.EQUILIBRADO,
    "graos": BalancePriority.COMIDA,
    "forragem": BalancePriority.FORRAGEM,
    "estabilidade": BalancePriority.ESCUDO,
    "renda": BalancePriority.RENDA,
}


@dataclass(slots=True)
class Contexto:
    """Estado da conversa e filtros do app que as ferramentas leem e (só `definir_roca`) alteram."""

    local: LocalConversa | None = None
    hoje: date = field(default_factory=date.today)
    simular: date | None = None  # data usada quando a ferramenta não recebe `data` (demonstração)
    soil_group: str | None = None
    cycle_code: str | None = None
    cultura_selecionada: str | None = None
    horizonte_anos: int = 5
    prioridade: str = "equilibrio"
    precisa_ter: tuple[str, ...] = ()
    nao_pode_ter: tuple[str, ...] = ()
    culturas_atuais: tuple[str, ...] = ()
    fazenda_resumo: dict[str, Any] | None = None


class ErroFerramenta(ValueError):
    """Argumento inválido: vira {"erro": ...} para o modelo corrigir a chamada ou perguntar."""


def _cfg() -> dict:
    return load_yaml_config("conversa")


def de_10(prob: float) -> int:
    """Probabilidade (0 a 1) como "X de cada 10"."""
    return int(round(10 * max(0.0, min(1.0, prob))))


def de_10_texto(prob: float) -> str:
    n = de_10(prob)
    if n == 0 and prob > 0:
        return "menos de 1 de cada 10"
    return f"{n} de cada 10"


def _crop_name(crop_id: str) -> str:
    return load_yaml_config("aptidao")["culturas"][crop_id]["nome"]


def _local_info(ctx: Contexto) -> dict:
    local = ctx.local
    assert local is not None
    info: dict[str, Any] = {"nome": local.nome, "tipo": "município de exemplo" if local.is_example else "roça marcada"}
    if not local.is_example:
        info["exemplo_mais_perto"] = f"{local.exemplo.name}/{local.exemplo.state}"
        info["distancia_exemplo_km"] = round(local.distancia_exemplo_km)
        if local.aviso:
            info["aviso"] = local.aviso
    return info


def _as_of(ctx: Contexto, data: str | None) -> date:
    if not data:
        return ctx.simular or ctx.hoje
    try:
        day = date.fromisoformat(data)
    except ValueError as exc:
        raise ErroFerramenta(f"data inválida '{data}': use AAAA-MM-DD") from exc
    if day > ctx.hoje:
        raise ErroFerramenta("a data não pode ser no futuro: o Acauã só olha a chuva que já caiu")
    return day


def _exemplo_txt(ctx: Contexto) -> str:
    ex = ctx.local.exemplo
    return f"{ex.name}/{ex.state}"


# --- definir_roca ------------------------------------------------------------

def definir_roca(
    ctx: Contexto, municipio: str | None = None, latitude: float | None = None, longitude: float | None = None
) -> dict:
    if latitude is not None and longitude is not None:
        ctx.local = local_por_coordenada(latitude, longitude)
    elif municipio:
        local = local_por_municipio(municipio)
        if local is None:
            return {
                "erro": "municipio_fora_da_lista",
                "explicacao": (
                    f"Por nome, o Acauã conhece só {', '.join(municipios_aceitos())}. Para outro lugar, peça "
                    "para mandar a localização da roça pelo WhatsApp (clipe, depois Localização)."
                ),
            }
        ctx.local = local
    else:
        raise ErroFerramenta("informe o município ou a latitude e a longitude")
    out = {"ok": True, "local": _local_info(ctx)}
    if not ctx.local.is_example:
        out["aviso"] = _cfg()["avisos"]["roca_longe"].format(
            km=round(ctx.local.distancia_exemplo_km), exemplo=_exemplo_txt(ctx)
        )
    return out


# --- situacao_plantio -------------------------------------------------------

def _rain_block(report: RainDelayReport) -> dict:
    s = report.status
    title, body, _level = describe_status(s)
    block: dict[str, Any] = {
        "dados_de_exemplo": False,
        "fonte": f"{report.source}, cada ponto cobre uns 50 km",
        "dados_ate": fmt_date(s.data_until),
        "safra": s.season_label,
        "situacao": s.state,
        "resumo": f"{title}. {body}",
        "firmou_em": fmt_date(s.onset_date) if s.onset_date else None,
        "data_normal": fmt_date(s.reference_date) if s.reference_date else None,
        "atraso_dias": s.delay_days if s.state not in ("antes_da_epoca", "sem_referencia") else None,
        "chuva_desde_inicio_mm": round(s.rain_season_mm),
    }
    if s.still_came_of_10 is not None:
        block["nos_anos_com_atraso_assim_ainda_firmou"] = f"{s.still_came_of_10} de cada 10"
    v = report.veranico
    if v is not None and v.seasons_with_onset:
        block["veranico"] = {
            "o_que_e": f"{v.min_days} dias ou mais sem chuva depois que a chuva firma",
            "acontece": f"{v.of_10} de cada 10 anos",
            "maior_seca_tipica_dias": v.typical_longest,
        }
    if report.veranico_alert:
        block["alerta_agora"] = report.veranico_alert
    return block


def _window_block(report: RainDelayReport | None, cw: CropWindowStatus | None) -> dict | None:
    if report is None:
        return None
    if report.zarc_error:
        return {"erro": report.zarc_error}
    if cw is None:
        return None  # cultura que não consta no ZARC (palma, capim, irrigadas)
    words = _cfg()["janela_zarc"]
    out: dict[str, Any] = {"estado": words[cw.state], "fonte": f"ZARC {report.zarc_safra} (MAPA/Embrapa)"}
    if cw.window is None:
        out["explicacao"] = "o ZARC não indica plantio de sequeiro aqui (risco alto ou não zoneado)"
        return out
    out["abre"] = fmt_date(cw.opens)
    out["fecha"] = fmt_date(cw.closes)
    out["abre_ano"] = fmt_date_year(cw.opens)
    out["fecha_ano"] = fmt_date_year(cw.closes)
    if cw.days_left is not None:
        out["faltam_dias"] = cw.days_left
    out["menor_risco_oficial"] = (
        f"perda em até {de_10_texto(cw.window.best_risk_pct / 100)} anos, conforme o solo e o ciclo"
    )
    return out


def _water_block(water: dict | None, crop_id: str, pano: consultas.Panorama) -> dict | None:
    """Quantos dias a lavoura aguenta sem chuva (ou intervalo de rega) e água no solo hoje."""
    if water is None or crop_id not in water:
        return None
    hold, today, plan = water[crop_id]
    v = pano.report.veranico if pano.report is not None else None
    out: dict[str, Any] = {"fonte": "chuva e temperatura do NASA POWER, balanço de água FAO-56, textura do solo"}
    if plan is not None:
        out["rega"] = {
            "intervalo_maximo_dias": plan.interval_days,
            "litros_por_m2_cada_rega": round(plan.liters_per_m2),
            "total_litros_por_m2": round(plan.total_liters_m2),
            "periodo": "por ano" if plan.per_year else "no ciclo todo",
            "pico_mm_dia": round(plan.peak_mm_day, 1),
            "profundidade_raiz_m": round(plan.zr_m, 2),
        }
    elif hold.days is None:
        out["aguenta_sem_chuva"] = "guarda água na própria planta e atravessa veranicos longos"
    else:
        out["aguenta_sem_chuva_na_floracao_dias"] = hold.days
    if plan is None and v is not None and v.seasons_with_onset:
        out["veranico_tipico_daqui_dias"] = v.typical_longest
    if today is not None:
        solo_today: dict[str, Any] = {
            "em": fmt_date(today.day),
            "hoje": f"{round(today.fraction * 10)} de 10 partes do que a camada da raiz segura",
            "normal_da_data": None if today.normal_fraction is None else f"{round(today.normal_fraction * 10)} de 10",
        }
        if plan is None:
            solo_today["chuva_que_falta_para_plantar_mm"] = (
                5 * round(today.missing_mm / 5) if today.missing_mm > 0 else 0
            )
        elif today.fraction < 0.9:
            solo_today["primeira_rega_litros_por_m2"] = max(5, 5 * round(today.taw_mm * (1 - today.fraction) / 5))
        out["agua_no_solo"] = solo_today
    return out


def _opcao(pano: consultas.Panorama, crop_id: str, water: dict | None) -> Opcao:
    """Os dados de uma cultura que entram na recomendação "o que plantar hoje"."""
    verdict = pano.verdict(crop_id, water=water)
    window = pano.window(crop_id)
    hold = water[crop_id][0].days if water and crop_id in water else None
    v = pano.report.veranico if pano.report is not None else None
    soil = next((c for c in pano.suitability if c.crop_id == crop_id), None)
    return Opcao(
        crop_id=crop_id,
        nome=_crop_name(crop_id),
        nivel=verdict.level,
        palavra=verdict.word,
        motivo=verdict.reason,
        quebra_de_10=verdict.risk_of_10,
        quebra_pct=pano.risk_pct(crop_id),
        janela_estado=window.state if window is not None else None,
        janela_abre=window.opens if window is not None else None,
        janela_fecha=window.closes if window is not None else None,
        aguenta_dias=hold,
        veranico_tipico=v.typical_longest if v is not None and v.seasons_with_onset else None,
        nota_solo=soil.index if soil else 0.0,
        aptidao_solo=soil.label if soil else "sem dado",
    )


def _fazenda_do_local(ctx: Contexto) -> dict[str, Any] | None:
    if ctx.fazenda_resumo is not None:
        return ctx.fazenda_resumo
    if ctx.local is None:
        return None
    faz = load_fazenda(ctx.local.location().location_id)
    if faz is None:
        return None
    return {
        "area_total_ha": faz.area_total_ha,
        "talhoes": [
            {
                "nome": t.nome,
                "area_ha": t.area_ha,
                "cultura": _crop_name(t.cultura) if t.cultura and t.cultura in CROP_IDS else t.cultura,
                "plantio": t.plantio.isoformat() if t.plantio else None,
            }
            for t in faz.talhoes
        ],
    }


def _default_current_crops(ctx: Contexto) -> tuple[str, ...]:
    if ctx.culturas_atuais:
        return ctx.culturas_atuais
    if ctx.local is None:
        return ()
    faz = load_fazenda(ctx.local.location().location_id)
    return tuple(t.cultura for t in faz.talhoes if t.cultura) if faz else ()


def situacao_plantio(
    ctx: Contexto, cultura: str | None = None, data: str | None = None, finalidade: str | None = None
) -> dict:
    """Posso plantar agora? O que plantar hoje? Aviso por cultura e a recomendação do dia.

    Chuva da safra, janela oficial e água são reais; o risco por cultura usa clima de exemplo.
    """
    if cultura is not None and cultura not in CROP_IDS:
        raise ErroFerramenta(f"cultura desconhecida '{cultura}'; use uma de {CROP_IDS}")
    if finalidade is not None and finalidade not in FINALIDADES:
        raise ErroFerramenta(f"finalidade deve ser uma de {list(FINALIDADES)}")
    as_of = _as_of(ctx, data)
    pano = consultas.panorama(
        ctx.local.location(),
        ctx.local.exemplo_id,
        as_of,
        soil_group=ctx.soil_group,
        cycle_code=ctx.cycle_code,
    )

    water = pano.water()
    crops = []
    for crop_id in [cultura] if cultura else CROP_IDS:
        irrigated = is_irrigated(crop_id)
        verdict = pano.verdict(crop_id, water=water)
        item: dict[str, Any] = {
            "cultura": _crop_name(crop_id),
            "id": crop_id,
            "manejo": "irrigado" if irrigated else "sequeiro",
            "serve_para": serve_para(crop_id),
            # o aviso da página: ZARC e chuva primeiro; só com a janela aberta entra o risco simulado
            "aviso": {
                "palavra": verdict.word,
                "nivel": verdict.level,
                "motivo": verdict.reason,
                "usa_clima_de_exemplo": False if irrigated else (verdict.word in RISK_WORDS.values()),
            },
        }
        if not irrigated:
            item["quebra_de_safra_com_o_atraso_de_hoje"] = {
                "chance": f"{verdict.risk_of_10} de cada 10 anos",
                "o_que_e": failure_rule_text(),
                "dados_de_exemplo": True,
            }
        water_block = _water_block(water, crop_id, pano)
        if water_block is not None:
            item["agua"] = water_block
        window = _window_block(pano.zarc, pano.window(crop_id))
        if window is not None:
            item["janela_oficial"] = window
        crops.append(item)

    out: dict[str, Any] = {
        "local": _local_info(ctx),
        "data_consultada": as_of.isoformat(),
        "chuva": _rain_block(pano.report) if pano.report else {"erro": f"chuva real indisponível: {pano.rain_error}"},
        "atraso_usado_no_risco_dias": pano.safra_delay_days,
        "calibrado_nasa_power": pano.rain_override is not None,
        "filtros_zarc": {
            "solo": TEXTURE_LABELS.get(pano.soil_group, pano.soil_group),
            "ciclo": ctx.cycle_code or "todos",
        },
    }
    if ctx.cultura_selecionada:
        out["cultura_em_foco_no_app"] = _crop_name(ctx.cultura_selecionada)
    if cultura is None:  # "o que plantar hoje?": a ação do dia vem antes da lista
        out["recomendacao"] = recomendar([_opcao(pano, c, water) for c in CROP_IDS], as_of, finalidade)
    out["culturas"] = crops
    out["aviso"] = _cfg()["avisos"]["risco_exemplo"].format(exemplo=_exemplo_txt(ctx))
    return out


# --- placar_rotacoes ---------------------------------------------------------

def _rotation_block(r: StrategySimulationResult, horizon: int, nota: float) -> dict:
    s = r.strategy
    return {
        "id": s.strategy_id,
        "nome": s.short_name or s.name,
        "descricao": s.description,
        "nota_na_prioridade": round(nota),
        "colhe": f"{r.survival_score_of_10} de cada 10 anos",
        "quebra_de_safra": f"{r.loss_years_of_10} de cada 10 anos",
        "risco_grave": {"o_que_e": loss_risk_label(horizon), "chance": f"{de_10_texto(r.prob_two_consecutive_losses)} cenários"},
        "falta_forragem_para_o_rebanho": f"{de_10_texto(r.prob_herd_collapse)} cenários",
        "graos_kg_por_ha_ano": round(r.expected_food_kg_ha_year),
        "forragem_kg_por_ha_ano": round(r.expected_forage_kg_ha_year),
        "renda_reais_por_ha_ano": round(annual_profit(r)),
    }


def placar_rotacoes(
    ctx: Contexto, horizonte_anos: int | None = None, prioridade: str | None = None, data: str | None = None
) -> dict:
    """Ranking das rotações conforme a prioridade e filtros do app, como na página Plantio."""
    eff_horizon = ctx.horizonte_anos if horizonte_anos is None else horizonte_anos
    eff_priority = ctx.prioridade if prioridade is None else prioridade
    if eff_horizon not in HORIZONTES:
        raise ErroFerramenta(f"horizonte deve ser um de {HORIZONTES}")
    if eff_priority not in PRIORIDADES:
        raise ErroFerramenta(f"prioridade deve ser uma de {list(PRIORIDADES)}")
    as_of = _as_of(ctx, data)
    pano = consultas.panorama(
        ctx.local.location(),
        ctx.local.exemplo_id,
        as_of,
        soil_group=ctx.soil_group,
        cycle_code=ctx.cycle_code,
    )
    current_crops = _default_current_crops(ctx)
    results = pano.rotations(
        eff_horizon,
        required=ctx.precisa_ter,
        excluded=ctx.nao_pode_ter,
        current_crops=current_crops,
    )
    by_id = {r.strategy.strategy_id: r for r in results}
    atual = by_id.get(CURRENT_ID) or by_id.get(_cfg()["rotacao_atual"], results[0])
    ranked_all = rank_by_balance_priority(results, PRIORIDADES[eff_priority])
    has_current = any(r.strategy.strategy_id == CURRENT_ID for r, _ in ranked_all)
    if has_current:
        top = [(r, sc) for r, sc in ranked_all if r.strategy.strategy_id != CURRENT_ID][:consultas.TOP_ROTATIONS]
        current_pos = next(i for i, (r, _) in enumerate(ranked_all) if r.strategy.strategy_id == CURRENT_ID)
        ranked = sorted([*top, ranked_all[current_pos]], key=lambda item: -item[1])
    else:
        current_pos = next(
            (i for i, (r, _) in enumerate(ranked_all) if r.strategy.strategy_id == atual.strategy.strategy_id), 0
        )
        ranked = ranked_all
    n_candidates = max(0, len(results) - 1) if has_current else len(results)
    out: dict[str, Any] = {
        "local": _local_info(ctx),
        "dados_de_exemplo": True,
        "calibrado_nasa_power": pano.rain_override is not None,
        "aviso": _cfg()["avisos"]["placar_exemplo"].format(exemplo=_exemplo_txt(ctx)),
        "horizonte_anos": eff_horizon,
        "prioridade": eff_priority,
        "cenarios": consultas.N_SCENARIOS,
        "atraso_da_chuva_usado_dias": pano.safra_delay_days,
        "jeito_de_hoje": atual.strategy.strategy_id,
        "posicao_jeito_de_hoje": current_pos + 1,
        "total_combinacoes": len(results),
        "combinacoes_que_cumprem": n_candidates,
        "menor_risco_de_perda": rank_by_survival(results)[0].strategy.strategy_id,
        "filtros_aplicados": {
            "precisa_ter": [_crop_name(c) for c in ctx.precisa_ter if c in CROP_IDS],
            "nao_pode_ter": [_crop_name(c) for c in ctx.nao_pode_ter if c in CROP_IDS],
            "culturas_atuais": [_crop_name(c) for c in current_crops if c in CROP_IDS],
        },
        "ranking": [_rotation_block(r, eff_horizon, nota) for r, nota in ranked],
    }
    if set(ctx.precisa_ter) & set(ctx.nao_pode_ter):
        out["aviso_restricoes"] = 'A mesma cultura está em "precisa ter" e em "não pode ter".'
    elif n_candidates == 0:
        out["aviso_restricoes"] = "Nenhuma rotação alternativa de 1 a 3 culturas cumpre essas restrições."
    return out


# --- solo_da_roca -------------------------------------------------------------

def solo_da_roca(ctx: Contexto) -> dict:
    """Como o solo do local limita cada cultura (mapa SoilGrids/SRTM ou análise de campo)."""
    location = ctx.local.location()
    profile = consultas.soil_profile(location)
    sources = {v.source for v in profile.values.values()}
    order = {cid: i for i, cid in enumerate(CROP_IDS)}
    crops = []
    for c in sorted(consultas.evaluate(profile), key=lambda s: order.get(s.crop_id, 999)):
        lim = c.limiting
        crops.append({
            "cultura": c.name,
            "id": c.crop_id,
            "aptidao": c.label,
            "o_que_mais_limita": None if lim.degree == "nula" else {"fator": lim.label, "grau": lim.degree, "motivo": lim.reason},
            "tem_valor_assumido": c.any_assumed,
        })
    tex = ctx.soil_group or texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    out: dict[str, Any] = {
        "local": _local_info(ctx),
        "fonte": "análise de campo" if "campo" in sources else "mapa de solo ISRIC SoilGrids (250 m) e relevo SRTM",
        "textura": TEXTURE_LABELS.get(tex, tex),
        "profundidade_cm": profile.depth_cm,
        "dados_de_exemplo": False,
        "culturas": crops,
        "avisos": profile.warnings,
        "limite": "fósforo, potássio e saturação por bases só uma análise de solo mede",
    }
    fazenda = _fazenda_do_local(ctx)
    if fazenda is not None:
        out["fazenda"] = fazenda
    return out


# --- registro e execução ------------------------------------------------------

_NULLABLE_DATE = {
    "type": ["string", "null"],
    "description": "Data AAAA-MM-DD para simular outro dia (só para demonstração). null = hoje.",
}

ESQUEMAS: list[dict] = [
    {
        "name": "definir_roca",
        "description": (
            "Guarda onde fica a roça. Use quando a pessoa disser o município ou mandar a localização. "
            "Por nome só valem os municípios de exemplo; para outro lugar, peça a localização."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "municipio": {"type": ["string", "null"], "description": "Nome do município falado pela pessoa."},
                "latitude": {"type": ["number", "null"]},
                "longitude": {"type": ["number", "null"]},
            },
            "required": ["municipio", "latitude", "longitude"],
            "additionalProperties": False,
        },
    },
    {
        "name": "situacao_plantio",
        "description": (
            "Responde 'posso plantar agora?' e 'o que plantar hoje?': o aviso de cada cultura (o mesmo da página "
            "Plantio), a chuva desta safra (real), a janela oficial do ZARC (real), a água da roça (real) e o risco "
            "de quebra (clima de exemplo). Sem cultura, traz também a recomendação do dia, já ordenada."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cultura": {
                    "type": ["string", "null"],
                    "enum": [*CROP_IDS, None],
                    "description": "Cultura perguntada; null = todas. Feijão de corda/macassar = feijao_caupi.",
                },
                "data": _NULLABLE_DATE,
                "finalidade": {
                    "type": ["string", "null"],
                    "enum": [*FINALIDADES, None],
                    "description": "Para que a pessoa quer plantar: graos (comida, vender grão) ou forragem "
                                   "(gado, bode, criação). null = qualquer.",
                },
            },
            "required": ["cultura", "data", "finalidade"],
            "additionalProperties": False,
        },
    },
    {
        "name": "placar_rotacoes",
        "description": (
            "Responde 'qual plano rende mais estável?': ranking das rotações (jeito de hoje e alternativas) pela "
            "prioridade, com em quantos de cada 10 anos colhe, grãos, forragem e renda. Usa clima de exemplo: sempre avisar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "horizonte_anos": {"type": "integer", "enum": HORIZONTES, "description": "Anos à frente; padrão 5."},
                "prioridade": {
                    "type": "string",
                    "enum": list(PRIORIDADES),
                    "description": (
                        "O que pesa mais no plano; padrão equilibrio. Comida/grão = graos; rebanho/criação = "
                        "forragem; não perder/colher todo ano = estabilidade; dinheiro = renda."
                    ),
                },
                "data": _NULLABLE_DATE,
            },
            "required": ["horizonte_anos", "prioridade", "data"],
            "additionalProperties": False,
        },
    },
    {
        "name": "solo_da_roca",
        "description": "Diz como o solo do local limita cada cultura (mapa de solo ou análise de campo).",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]

_FUNCOES = {
    "definir_roca": definir_roca,
    "situacao_plantio": situacao_plantio,
    "placar_rotacoes": placar_rotacoes,
    "solo_da_roca": solo_da_roca,
}
_PRECISA_LOCAL = {"situacao_plantio", "placar_rotacoes", "solo_da_roca"}


def executar(nome: str, argumentos: dict, ctx: Contexto) -> dict:
    """Roda uma ferramenta pelo nome. Erros esperados voltam como {"erro": ...}, nunca como exceção."""
    func = _FUNCOES.get(nome)
    if func is None:
        return {"erro": f"ferramenta desconhecida '{nome}'"}
    if nome in _PRECISA_LOCAL and ctx.local is None:
        return {
            "erro": "local_desconhecido",
            "explicacao": (
                "Ainda não sei onde fica a roça. Peça a localização pelo WhatsApp (clipe, depois Localização) "
                f"ou o nome do município ({', '.join(municipios_aceitos())})."
            ),
        }
    args = {k: v for k, v in (argumentos or {}).items() if v is not None}
    try:
        return func(ctx, **args)
    except ErroFerramenta as exc:
        return {"erro": str(exc)}
    except TypeError as exc:
        return {"erro": f"argumentos inválidos para {nome}: {exc}"}
