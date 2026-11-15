"""Dados do local selecionado, entregues ao chatbot antes da pergunta.

São as mesmas ferramentas que o modelo pode chamar (mesmos números da página Plantio), rodadas de
antemão para o local e a data da conversa: aviso por cultura com chuva, janela e água; ranking das
rotações no padrão da página (5 anos, equilíbrio); e solo. Assim a maioria das perguntas é respondida
sem chamada de ferramenta, e o modelo sempre sabe de onde vêm os números.
"""

from __future__ import annotations

import json

from crop_optimizer.agente.ferramentas import Contexto, executar

# o que a página Plantio mostra ao abrir
PADRAO_PLACAR = {"horizonte_anos": 5, "prioridade": "equilibrio"}


def dados_do_local(ctx: Contexto) -> list[tuple[str, dict]]:
    """Resultados das ferramentas para o local da conversa ([] sem local)."""
    if ctx.local is None:
        return []
    return [
        ("situacao_plantio", executar("situacao_plantio", {}, ctx)),
        ("placar_rotacoes", executar("placar_rotacoes", dict(PADRAO_PLACAR), ctx)),
        ("solo_da_roca", executar("solo_da_roca", {}, ctx)),
    ]


def mensagem(ctx: Contexto, results: list[tuple[str, dict]]) -> str:
    """Mensagem de contexto (papel developer) com os dados em JSON compacto."""
    if ctx.local is None:
        return "[DADOS_DO_LOCAL] nenhum local selecionado ainda."
    data = {name: result for name, result in results}
    return (
        f"[DADOS_DO_LOCAL] local: {ctx.local.nome} ({'município de exemplo' if ctx.local.is_example else 'roça marcada no mapa'}). "
        "Calculados pelo Acauã para esta conversa; o placar está no padrão da página (5 anos, equilíbrio). "
        "Para outra cultura, horizonte, prioridade ou data, chame as ferramentas.\n"
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )
