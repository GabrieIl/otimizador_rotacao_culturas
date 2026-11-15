"""Dados do local selecionado, entregues ao chatbot antes da pergunta.

São as mesmas ferramentas que o modelo pode chamar (mesmos números da página Plantio), rodadas de
antemão para o local e a data da conversa: aviso por cultura com chuva, janela e água; ranking das
rotações no padrão da página (5 anos, equilíbrio); e solo. Assim a maioria das perguntas é respondida
sem chamada de ferramenta, e o modelo sempre sabe de onde vêm os números.
"""

from __future__ import annotations

import json

from crop_optimizer.agente.ferramentas import Contexto, executar

# o que a página Plantio mostra ao abrir (padrão quando o app não definiu outro filtro)
PADRAO_PLACAR = {"horizonte_anos": 5, "prioridade": "equilibrio"}


def filtros_ativos(ctx: Contexto) -> dict:
    """Resumo dos filtros selecionados no app para o contexto da conversa."""
    return {
        "data_simulada": ctx.simular.isoformat() if ctx.simular else None,
        "solo_zarc": ctx.soil_group,
        "ciclo_zarc": ctx.cycle_code or "todos",
        "cultura_em_foco": ctx.cultura_selecionada,
        "horizonte_anos": ctx.horizonte_anos,
        "prioridade": ctx.prioridade,
        "precisa_ter": list(ctx.precisa_ter),
        "nao_pode_ter": list(ctx.nao_pode_ter),
        "culturas_atuais": list(ctx.culturas_atuais),
        "tem_fazenda": ctx.fazenda_resumo is not None,
    }


def dados_do_local(ctx: Contexto) -> list[tuple[str, dict]]:
    """Resultados das ferramentas para o local e filtros da conversa ([] sem local)."""
    if ctx.local is None:
        return []
    placar_args = {
        "horizonte_anos": ctx.horizonte_anos or PADRAO_PLACAR["horizonte_anos"],
        "prioridade": ctx.prioridade or PADRAO_PLACAR["prioridade"],
    }
    return [
        ("situacao_plantio", executar("situacao_plantio", {}, ctx)),
        ("placar_rotacoes", executar("placar_rotacoes", placar_args, ctx)),
        ("solo_da_roca", executar("solo_da_roca", {}, ctx)),
    ]


def mensagem(ctx: Contexto, results: list[tuple[str, dict]]) -> str:
    """Mensagem de contexto (papel developer) com os dados e filtros em JSON compacto."""
    if ctx.local is None:
        return "[DADOS_DO_LOCAL] nenhum local selecionado ainda."
    data = {"filtros_ativos": filtros_ativos(ctx), **{name: result for name, result in results}}
    placar_desc = f"{ctx.horizonte_anos} {'ano' if ctx.horizonte_anos == 1 else 'anos'}, {ctx.prioridade}"
    return (
        f"[DADOS_DO_LOCAL] local: {ctx.local.nome} ({'município de exemplo' if ctx.local.is_example else 'roça marcada no mapa'}). "
        f"Calculados pelo Acauã com os filtros escolhidos no app (placar em {placar_desc}). "
        "Para outra cultura, horizonte, prioridade ou data, chame as ferramentas.\n"
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )
