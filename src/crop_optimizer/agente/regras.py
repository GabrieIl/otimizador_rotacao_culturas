"""Respostas sem a OpenAI: palavras-chave para entender e frases-modelo para responder.

Usado quando a API cai e quando a resposta do modelo quebra uma regra mesmo depois de reescrita.
As frases seguem o CLAUDE.md (seção 7) e usam só o que as ferramentas devolveram.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from crop_optimizer.agente.ferramentas import Contexto, executar
from crop_optimizer.agente.local import local_por_municipio, municipios_aceitos
from crop_optimizer.config import load_yaml_config


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _has(text: str, words: list[str]) -> bool:
    return any(_plain(w) in text for w in words)


@dataclass(frozen=True, slots=True)
class Pedido:
    intencao: str | None  # "plantio" | "placar" | None
    cultura: str | None
    prioridade: str
    municipio: str | None


def entender(texto: str) -> Pedido:
    cfg = load_yaml_config("conversa")["regras"]
    text = _plain(texto)
    intent = "placar" if _has(text, cfg["placar"]) else "plantio" if _has(text, cfg["plantio"]) else None
    crop = next((cid for cid, words in cfg["culturas"].items() if _has(text, words)), None)
    priority = next((p for p, words in cfg["prioridades"].items() if _has(text, words)), "equilibrio")
    local = local_por_municipio(texto)
    return Pedido(intent, crop, priority, local.exemplo.name if local else None)


def _closing() -> str:
    return load_yaml_config("conversa")["fechamento"]


def _ask_location() -> str:
    return (
        "Para responder, preciso saber onde fica a roça. Mande a localização pelo WhatsApp (clipe, depois "
        f"Localização) ou diga o município: {', '.join(municipios_aceitos())}."
    )


def help_text() -> str:
    return (
        "O Acauã responde duas perguntas: posso plantar agora, por exemplo \"posso plantar milho?\", e qual roça "
        "aguenta mais, por exemplo \"qual roça aguenta mais seca?\"."
    )


def compor_plantio(result: dict) -> str:
    crops = result["culturas"]
    if len(crops) == 1:
        c = crops[0]
        parts = [f"{c['cultura']}: {c['aviso']['palavra']}.", c["aviso"]["motivo"]]
        win = c.get("janela_oficial")
        if win and win.get("abre"):
            parts.append(f"A janela oficial de plantio vai de {win['abre']} a {win['fecha']}.")
    elif result.get("recomendacao"):  # "o que plantar hoje?": a ação do dia, não a lista
        parts = [result["recomendacao"]["o_que_fazer_hoje"]]
        chuva = result.get("chuva", {})
        if chuva.get("resumo"):
            parts.append(chuva["resumo"])
    else:
        parts = ["; ".join(f"{c['cultura']}: {c['aviso']['palavra']}" for c in crops) + "."]
    if any(c["aviso"]["usa_clima_de_exemplo"] for c in crops):
        parts.append("A conta do risco usa clima de exemplo.")
    return " ".join([*parts, _closing()])


def compor_placar(result: dict) -> str:
    ranking = {r["id"]: r for r in result["ranking"]}
    hoje = ranking[result["jeito_de_hoje"]]
    melhor = result["ranking"][0]
    parts = [f"Do jeito que planta hoje, {hoje['nome']}, dá quebra de safra em {hoje['quebra_de_safra']}."]
    if melhor["id"] == hoje["id"]:
        parts.append("Nesta conta, o jeito de hoje já é o primeiro do ranking.")
    else:
        parts.append(f"Com {melhor['nome']}, a quebra cai para {melhor['quebra_de_safra']}. {melhor['descricao']}")
    parts.append("É uma conta com dados de exemplo.")
    return " ".join([*parts, _closing()])


def compor(results: list[tuple[str, dict]]) -> str | None:
    """Resposta a partir do último resultado útil das ferramentas (None se nenhum serve)."""
    for name, result in reversed(results):
        if "erro" in result:
            continue
        if name == "situacao_plantio":
            return compor_plantio(result)
        if name == "placar_rotacoes":
            return compor_placar(result)
    return None


def responder(ctx: Contexto, texto: str) -> tuple[str, list[tuple[str, dict]]]:
    """Responde só com regras. Devolve o texto e as ferramentas usadas."""
    pedido = entender(texto)
    results: list[tuple[str, dict]] = []
    if pedido.municipio:
        results.append(("definir_roca", executar("definir_roca", {"municipio": pedido.municipio}, ctx)))
    if pedido.intencao is None:
        if pedido.municipio:
            return f"Certo, anotei a roça em {ctx.local.nome}. " + help_text(), results
        return help_text(), results
    if ctx.local is None:
        return _ask_location(), results
    if pedido.intencao == "plantio":
        finalidade = pedido.prioridade if pedido.prioridade in ("graos", "forragem") else None
        name, args = "situacao_plantio", {"cultura": pedido.cultura, "finalidade": finalidade}
    else:
        name, args = "placar_rotacoes", {"horizonte_anos": 5, "prioridade": pedido.prioridade}
    result = executar(name, args, ctx)
    results.append((name, result))
    if "erro" in result:
        return f"Não consegui fazer a conta agora: {result.get('explicacao') or result['erro']}. {_closing()}", results
    return compor(results), results
