"""O agente: pergunta em texto -> modelo da OpenAI com as ferramentas -> resposta conferida.

Os canais (WhatsApp, tela Conversa, terminal) chamam só `Agente.responder(sessao, texto)`.
Sem a OpenAI (sem chave, sem crédito, sem rede) a resposta sai pelas regras, com os mesmos números.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from crop_optimizer.agente import contexto, guardas, regras
from crop_optimizer.agente.ferramentas import ESQUEMAS, Contexto, executar
from crop_optimizer.agente.openai_api import OpenAIClient, OpenAIIndisponivel, output_text
from crop_optimizer.agente.prompt import date_note, instructions
from crop_optimizer.agente.sessao import Sessao
from crop_optimizer.config import load_yaml_config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Resposta:
    texto: str
    fonte: str  # "agente" | "regras"
    ferramentas: list[str] = field(default_factory=list)
    observacoes: list[str] = field(default_factory=list)  # para log/depuração, nunca para o agricultor
    uso: dict[str, int] = field(default_factory=dict)  # tokens gastos na OpenAI (somados das rodadas)


def _tools() -> list[dict]:
    return [{"type": "function", "strict": True, **schema} for schema in ESQUEMAS]


class Agente:
    def __init__(self, client: OpenAIClient | None = None, today: date | None = None) -> None:
        self.client = client or OpenAIClient()
        self.today = today

    def responder(self, sessao: Sessao, texto: str) -> Resposta:
        ctx = Contexto(local=sessao.local, simular=sessao.simular)
        if self.today is not None:
            ctx.hoje = self.today
        self._uso: dict[str, int] = {}
        try:
            resposta = self._com_modelo(ctx, sessao, texto)
        except OpenAIIndisponivel as exc:
            logger.warning("OpenAI indisponível (%s); respondendo pelas regras.", exc)
            text, results = regras.responder(ctx, texto)
            resposta = Resposta(text, "regras", [n for n, _ in results], [f"openai: {exc}"])
        sessao.local = ctx.local
        sessao.lembrar(texto, resposta.texto)
        resposta.uso = dict(self._uso)
        return resposta

    def _com_modelo(self, ctx: Contexto, sessao: Sessao, texto: str) -> Resposta:
        cfg = load_yaml_config("conversa")["openai"]
        note = date_note(ctx.hoje, ctx.simular)
        base = contexto.dados_do_local(ctx)  # dados do local selecionado, antes da pergunta
        items: list[dict] = [
            {"role": "developer", "content": note},
            {"role": "developer", "content": contexto.mensagem(ctx, base)},
            *sessao.historico,
            {"role": "user", "content": texto},
        ]
        results: list[tuple[str, dict]] = []
        notes: list[str] = []
        text = self._loop(ctx, items, results, int(cfg["max_rodadas_ferramenta"]))

        context_numbers = f"{texto} {note}"
        for _ in range(int(cfg["tentativas_correcao"])):
            issues = guardas.problemas(text, base + results, context_numbers) if text else ["resposta vazia"]
            if not issues:
                break
            notes.append("reescrita: " + "; ".join(issues))
            items.append({"role": "developer", "content": "Reescreva a resposta. Problemas: " + "; ".join(issues)})
            text = self._loop(ctx, items, results, 1)

        issues = guardas.problemas(text, base + results, context_numbers) if text else ["resposta vazia"]
        names = [n for n, _ in results]
        if issues:
            notes.append("regras: " + "; ".join(issues))
            fallback = regras.compor(results)
            if fallback is None:
                fallback, more = regras.responder(ctx, texto)
                names += [n for n, _ in more]
            return Resposta(fallback, "regras", names, notes)
        return Resposta(guardas.ajustar(text, results, base), "agente", names, notes)

    def _somar_uso(self, usage: dict) -> None:
        parts = {
            "rodadas": 1,
            "entrada": usage.get("input_tokens", 0),
            "entrada_em_cache": (usage.get("input_tokens_details") or {}).get("cached_tokens", 0),
            "saida": usage.get("output_tokens", 0),
            "raciocinio": (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
        }
        for key, value in parts.items():
            self._uso[key] = self._uso.get(key, 0) + int(value or 0)

    def _loop(self, ctx: Contexto, items: list[dict], results: list[tuple[str, dict]], rounds: int) -> str:
        """Rodadas de function calling até o modelo responder em texto."""
        for _ in range(rounds + 1):
            response = self.client.respond(instructions=instructions(), input_items=items, tools=_tools())
            self._somar_uso(response.get("usage") or {})
            output = response.get("output", [])
            items.extend(output)
            calls = [o for o in output if o.get("type") == "function_call"]
            if not calls:
                return output_text(response)
            for call in calls:
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except json.JSONDecodeError:
                    result = {"erro": "argumentos em JSON inválido"}
                else:
                    result = executar(call["name"], args, ctx)
                results.append((call["name"], result))
                items.append({
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(result, ensure_ascii=False),
                })
        return ""  # passou do limite de rodadas sem responder
