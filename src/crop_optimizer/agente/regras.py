"""Respostas sem a OpenAI: palavras-chave para entender e frases-modelo para responder.

Usado quando a API cai e quando a resposta do modelo quebra uma regra mesmo depois de reescrita.
As frases seguem o CLAUDE.md (seção 7) e usam só o que as ferramentas devolveram.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from crop_optimizer.agente.ferramentas import HORIZONTES, Contexto, executar
from crop_optimizer.agente.local import local_por_municipio, municipios_aceitos
from crop_optimizer.config import load_yaml_config


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _has(text: str, words: list[str]) -> bool:
    return any(_plain(w) in text for w in words)


def _match_crop(text: str, crop_keywords: dict[str, list[str]]) -> str | None:
    """Encontra a cultura pelo termo mais específico primeiro (ex.: feijão comum > feijão; pimentão > pimenta)."""
    pairs = [
        (_plain(word), cid)
        for cid, words in crop_keywords.items()
        for word in words
    ]
    pairs.sort(key=lambda item: -len(item[0]))
    for word, cid in pairs:
        if re.search(rf"\b{re.escape(word)}", text):
            return cid
    return None


def _match_horizon(text: str) -> int | None:
    m = re.search(r"\b(10|[1235])\s*anos?\b", text)
    if m:
        val = int(m.group(1))
        if val in HORIZONTES:
            return val
    return None


@dataclass(frozen=True, slots=True)
class Pedido:
    intencao: str | None  # "plantio" | "placar" | "solo" | None
    cultura: str | None
    prioridade: str
    municipio: str | None
    prioridade_explicita: str | None = None
    horizonte: int | None = None


def entender(texto: str) -> Pedido:
    cfg = load_yaml_config("conversa")["regras"]
    text = _plain(texto)
    crop = _match_crop(text, cfg["culturas"])
    if _has(text, cfg["placar"]):
        intent = "placar"
    elif _has(text, cfg["plantio"]) or crop is not None:
        intent = "plantio"
    elif _has(text, cfg.get("solo", [])):
        intent = "solo"
    else:
        intent = None
    explicit_priority = next((p for p, words in cfg["prioridades"].items() if _has(text, words)), None)
    priority = explicit_priority or "equilibrio"
    horizon = _match_horizon(text)
    local = local_por_municipio(texto)
    return Pedido(intent, crop, priority, local.exemplo.name if local else None, explicit_priority, horizon)


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
    ranking_list = result.get("ranking", [])
    ranking = {r["id"]: r for r in ranking_list}
    if not ranking_list:
        aviso = result.get("aviso_restricoes") or "Nenhuma rotação cumpre os filtros escolhidos."
        return f"{aviso} {_closing()}"
    hoje = ranking.get(result.get("jeito_de_hoje")) or ranking_list[0]
    melhor = ranking_list[0]
    parts = [f"Do jeito que planta hoje, {hoje['nome']}, dá quebra de safra em {hoje['quebra_de_safra']}."]
    if melhor["id"] == hoje["id"]:
        if result.get("aviso_restricoes"):
            parts.append(result["aviso_restricoes"])
        else:
            parts.append("Nesta conta, o jeito de hoje já é o primeiro do ranking.")
    else:
        parts.append(f"Com {melhor['nome']}, a quebra cai para {melhor['quebra_de_safra']}. {melhor['descricao']}")
    parts.append("É uma conta com dados de exemplo.")
    return " ".join([*parts, _closing()])


def compor_solo(result: dict) -> str:
    textura = result.get("textura", "sem textura")
    prof = result.get("profundidade_cm")
    prof_txt = f" e profundidade de cerca de {round(prof)} cm" if prof is not None else ""
    parts = [f"O solo em {result['local']['nome']} tem textura {textura}{prof_txt} (fonte: {result['fonte']})."]
    crops = result.get("culturas", [])
    boas = [c["cultura"] for c in crops if c["aptidao"] in ("Boa", "Boa / Ótima", "Ótima", "Forte")][:4]
    if boas:
        parts.append(f"Têm melhor aptidão neste solo: {', '.join(boas)}.")
    faz = result.get("fazenda")
    if faz and faz.get("talhoes"):
        nomes = ", ".join(f"{t['nome']} ({t['area_ha']} ha)" for t in faz["talhoes"])
        parts.append(f"Talhões cadastrados: {nomes}.")
    if result.get("limite"):
        parts.append(f"Importante: {result['limite']}.")
    return " ".join(parts)


def compor(results: list[tuple[str, dict]]) -> str | None:
    """Resposta a partir do último resultado útil das ferramentas (None se nenhum serve)."""
    for name, result in reversed(results):
        if "erro" in result:
            continue
        if name == "situacao_plantio":
            return compor_plantio(result)
        if name == "placar_rotacoes":
            return compor_placar(result)
        if name == "solo_da_roca":
            return compor_solo(result)
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
    if pedido.intencao == "solo":
        name, args = "solo_da_roca", {}
    elif pedido.intencao == "plantio":
        priority_for_purpose = pedido.prioridade_explicita or ctx.prioridade
        finalidade = priority_for_purpose if priority_for_purpose in ("graos", "forragem") else None
        name, args = "situacao_plantio", {"cultura": pedido.cultura, "finalidade": finalidade}
    else:
        name, args = "placar_rotacoes", {
            "horizonte_anos": pedido.horizonte if pedido.horizonte is not None else ctx.horizonte_anos,
            "prioridade": pedido.prioridade_explicita or ctx.prioridade,
        }
    result = executar(name, args, ctx)
    results.append((name, result))
    if "erro" in result:
        return f"Não consegui fazer a conta agora: {result.get('explicacao') or result['erro']}. {_closing()}", results
    return compor(results) or help_text(), results
