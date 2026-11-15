"""Cliente mínimo da API da OpenAI (httpx, sem SDK): respostas com function calling, transcrição e voz."""

from __future__ import annotations

from typing import Any

import httpx

from crop_optimizer.config import get_settings, load_yaml_config

BASE_URL = "https://api.openai.com/v1"


class OpenAIIndisponivel(RuntimeError):
    """Sem chave, sem rede, sem crédito ou erro da API. O agente cai nas regras."""


def _cfg() -> dict:
    return load_yaml_config("conversa")["openai"]


class OpenAIClient:
    def __init__(self, api_key: str | None = None, timeout_s: float | None = None) -> None:
        self.api_key = api_key if api_key is not None else get_settings().openai_api_key
        self.timeout_s = timeout_s or float(_cfg()["timeout_segundos"])

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        if not self.api_key:
            raise OpenAIIndisponivel("OPENAI_API_KEY não configurada")
        try:
            resp = httpx.post(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_s,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise OpenAIIndisponivel(f"sem conexão com a OpenAI: {exc}") from exc
        if resp.status_code != 200:
            try:
                err = resp.json().get("error", {})
                detail = err.get("code") or err.get("message") or resp.text[:200]
            except ValueError:
                detail = resp.text[:200]
            raise OpenAIIndisponivel(f"OpenAI respondeu {resp.status_code}: {detail}")
        return resp

    def respond(self, *, instructions: str, input_items: list[dict], tools: list[dict]) -> dict:
        """Uma rodada da Responses API. `store: false`: nada fica guardado na OpenAI."""
        cfg = _cfg()
        return self._post(
            "/responses",
            json={
                "model": cfg["modelo_agente"],
                "reasoning": {"effort": cfg["esforco_agente"]},
                "text": {"verbosity": cfg.get("verbosidade", "medium")},
                "max_output_tokens": int(cfg["max_tokens_resposta"]),
                "store": False,
                "instructions": instructions,
                "input": input_items,
                "tools": tools,
            },
        ).json()


    def transcribe(self, audio: bytes, filename: str, mime: str, prompt: str = "") -> str:
        """Áudio -> texto em português (aceita o .ogg/opus do WhatsApp direto)."""
        cfg = _cfg()
        data = {"model": cfg["modelo_transcricao"], "language": "pt"}
        if prompt:
            data["prompt"] = prompt
        resp = self._post("/audio/transcriptions", files={"file": (filename, audio, mime)}, data=data)
        return str(resp.json().get("text", "")).strip()

    def speech(self, text: str, response_format: str = "opus") -> bytes:
        """Texto -> voz. `opus` sai em .ogg, o formato das mensagens de voz do WhatsApp."""
        cfg = _cfg()
        return self._post(
            "/audio/speech",
            json={
                "model": cfg["modelo_voz"],
                "voice": cfg["voz"],
                "instructions": cfg["instrucoes_voz"],
                "input": text,
                "response_format": response_format,
            },
        ).content


def output_text(response: dict) -> str:
    """Junta o texto das mensagens de uma resposta da Responses API."""
    parts = []
    for item in response.get("output", []):
        if item.get("type") == "message":
            parts.extend(c.get("text", "") for c in item.get("content", []) if c.get("type") == "output_text")
    return "\n".join(p for p in parts if p).strip()
