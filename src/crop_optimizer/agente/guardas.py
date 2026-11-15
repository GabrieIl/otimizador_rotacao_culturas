"""Conferência da resposta do modelo antes de ela virar áudio.

Duas categorias:
- problemas que pedem reescrita (`problemas`): porcentagem, número que não veio das ferramentas,
  "pode plantar" quando nenhum aviso diz isso;
- ajustes que o código faz sozinho (`ajustar`): tira markdown, avisa dado de exemplo, garante o fecho.
"""

from __future__ import annotations

import json
import re

from crop_optimizer.config import load_yaml_config

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_PERCENT = re.compile(r"\d\s*%|por\s*cento", re.IGNORECASE)
_CAN_PLANT = re.compile(r"(?<!não )\bpode(?:m)? plantar\b", re.IGNORECASE)
_RAIN_SET = re.compile(r"(?<!não )\b(?:já )?firmou\b", re.IGNORECASE)
DATA_TOOLS = ("situacao_plantio", "placar_rotacoes")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        out.add(raw.replace(".", "").replace(",", "."))  # 8.927 -> 8927; 1,5 -> 1.5
    return out


def tool_payload(results: list[tuple[str, dict]]) -> str:
    return " ".join(json.dumps(r, ensure_ascii=False) for _name, r in results)


def problemas(texto: str, results: list[tuple[str, dict]], contexto: str) -> list[str]:
    """Regras quebradas pela resposta. `contexto` = pergunta + nota da data (números que podem aparecer)."""
    found = []
    if _PERCENT.search(texto):
        found.append('usou porcentagem; escreva a chance como "X de cada 10"')
    allowed = _numbers(tool_payload(results)) | _numbers(contexto) | {"10"}
    loose = sorted(n for n in _numbers(texto) - allowed)
    if loose:
        found.append(f"usou números que não vieram das ferramentas: {', '.join(loose)}")
    words = [c["aviso"]["palavra"] for name, r in results if name == "situacao_plantio" for c in r.get("culturas", [])]
    if words and "Pode plantar" not in words and _CAN_PLANT.search(texto):
        found.append("disse que pode plantar, mas nenhum aviso diz \"Pode plantar\"")
    rain = [r["chuva"].get("situacao") for name, r in results if name == "situacao_plantio" and "chuva" in r]
    if rain and rain[-1] == "firmando" and _RAIN_SET.search(texto):
        found.append("disse que a chuva firmou, mas ela só atingiu o critério de início (falta confirmar)")
    return found


def usou_dado_de_exemplo(results: list[tuple[str, dict]]) -> bool:
    for name, r in results:
        if name == "placar_rotacoes" and r.get("dados_de_exemplo"):
            return True
        if name == "situacao_plantio" and any(c["aviso"].get("usa_clima_de_exemplo") for c in r.get("culturas", [])):
            return True
    return False


def limpar(texto: str) -> str:
    """Tira markdown e listas: o texto vai para o WhatsApp e para a voz."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), texto)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(#+|[-*•]|\d+[.)])\s+", "", line).strip()
        if line:
            lines.append(line)
    return re.sub(r"[ \t]+", " ", " ".join(lines)).strip()


def usou_dados(results: list[tuple[str, dict]]) -> bool:
    return any(name in DATA_TOOLS and "erro" not in r for name, r in results)


def _context_markers(context: list[tuple[str, dict]]) -> tuple[list[str], list[str]]:
    """Palavras dos avisos e nomes das rotações que aparecem nos dados do local."""
    words, rotations = [], []
    for name, r in context:
        if name == "situacao_plantio":
            words += [c["aviso"]["palavra"] for c in r.get("culturas", [])]
        if name == "placar_rotacoes":
            rotations += [x["nome"] for x in r.get("ranking", [])]
    return words, rotations


def ajustar(texto: str, results: list[tuple[str, dict]], context: list[tuple[str, dict]] | None = None) -> str:
    """Tira markdown; avisa dado de exemplo; fecho só quando a resposta traz plantio ou rotação.

    `results` são as ferramentas chamadas nesta resposta; `context`, os dados do local entregues antes da
    pergunta (contam como "dados usados" quando a resposta cita um aviso, uma rotação ou um número).
    """
    closing = load_yaml_config("conversa")["fechamento"]
    text = limpar(texto)
    for sentence in [closing, *(f"{p.strip()}." for p in closing.split(".") if p.strip())]:
        text = text.replace(sentence, "")  # o modelo às vezes repete o fecho ou parte dele
    text = re.sub(r"\s+", " ", text).strip()
    words, rotations = _context_markers(context or [])
    cites_rotation = any(n.lower() in text.lower() for n in rotations)
    cites_context = bool(context) and (cites_rotation or any(w.lower() in text.lower() for w in words)
                                       or bool(_NUMBER.search(text)))
    if not (usou_dados(results) or cites_context):
        return text
    risk_talk = cites_rotation or "quebra" in text.lower()
    if (usou_dado_de_exemplo(results) or risk_talk) and "exemplo" not in text.lower():
        text += " A conta do risco usa clima de exemplo."
    return f"{text} {closing}"
