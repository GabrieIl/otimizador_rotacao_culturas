"""Ouvir e falar: transcrição do áudio recebido e voz da resposta (com cache por texto).

A API do modelo de texto não ouve nem fala; aqui ficam as duas pontas:
- `transcrever`: áudio do WhatsApp -> texto (OpenAI);
- `falar`: texto -> áudio .ogg/opus (OpenAI), com reserva em gTTS (.mp3) se a OpenAI falhar.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from crop_optimizer.accessibility.radio_tempo import GoogleTTSProvider
from crop_optimizer.agente.openai_api import OpenAIClient, OpenAIIndisponivel
from crop_optimizer.config import Settings, get_settings, load_yaml_config

logger = logging.getLogger(__name__)

# palavras que a transcrição tende a errar (ajudam o modelo de transcrição; não mudam o sentido)
VOCABULARIO = (
    "Conversa sobre roça no sertão: plantar milho, feijão-caupi, feijão de corda, macassar, sorgo, palma "
    "forrageira, capim-buffel, veranico, rebanho, bode. Quixadá, Petrolina, Sousa, Irecê."
)


class AudioInvalido(ValueError):
    """Áudio grande demais ou vazio."""


@dataclass(frozen=True, slots=True)
class Audio:
    path: Path
    mime: str
    provider: str

    @property
    def name(self) -> str:
        return self.path.name


def audio_dir(settings: Settings | None = None) -> Path:
    folder = (settings or get_settings()).paths.root / "conversa" / "audio"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def transcrever(audio: bytes, mime: str, client: OpenAIClient | None = None) -> str:
    """Levanta AudioInvalido (tamanho) ou OpenAIIndisponivel (API)."""
    max_bytes = int(load_yaml_config("conversa")["audio"]["max_bytes_recebido"])
    if not audio:
        raise AudioInvalido("áudio vazio")
    if len(audio) > max_bytes:
        raise AudioInvalido(f"áudio de {len(audio) // 1024} KB passa do limite de {max_bytes // 1024} KB")
    ext = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/amr": "amr", "audio/wav": "wav",
           "audio/x-wav": "wav", "audio/wave": "wav", "audio/webm": "webm"}
    filename = f"mensagem.{ext.get(mime.split(';')[0].strip(), 'ogg')}"
    return (client or OpenAIClient()).transcribe(audio, filename, mime.split(";")[0].strip(), VOCABULARIO)


_FORMATS = {"opus": ("ogg", "audio/ogg"), "mp3": ("mp3", "audio/mpeg")}


def _gtts(texto: str) -> bytes | None:
    result = GoogleTTSProvider().synthesize(texto)
    return result.audio_bytes if result.provider_used == "gtts" else None  # bip offline não serve


def falar(
    texto: str,
    client: OpenAIClient | None = None,
    settings: Settings | None = None,
    formato: str = "opus",
    provedor: str | None = None,
) -> Audio:
    """Áudio da resposta. Mesmo texto, provedor e formato = mesmo arquivo (cache em data/conversa/audio/).

    `provedor` (padrão em config/conversa.yaml, `voz.provedor`): "gtts" (grátis, sempre .mp3) ou "openai"
    (`formato` "opus" = .ogg dos mensageiros, "mp3" = navegador). Se o escolhido falhar, tenta o outro.
    """
    cfg = load_yaml_config("conversa")
    provedor = provedor or cfg["voz"]["provedor"]
    oa = cfg["openai"]
    key = hashlib.sha256(
        f"{provedor}|{oa['modelo_voz']}|{oa['voz']}|{oa['instrucoes_voz']}|{formato}|{texto}".encode()
    ).hexdigest()[:32]
    folder = audio_dir(settings)
    for ext, mime in (_FORMATS[formato], ("mp3", "audio/mpeg")):  # o gTTS sempre gera mp3
        cached = folder / f"{key}.{ext}"
        if cached.exists():
            return Audio(cached, mime, "cache")

    def openai() -> tuple[bytes, str, str]:
        ext, mime = _FORMATS[formato]
        return (client or OpenAIClient()).speech(texto, response_format=formato), ext, mime

    order = ["gtts", "openai"] if provedor == "gtts" else ["openai", "gtts"]
    errors = []
    for name in order:
        try:
            if name == "openai":
                data, ext, mime = openai()
            else:
                data, ext, mime = _gtts(texto), "mp3", "audio/mpeg"
                if data is None:
                    raise OpenAIIndisponivel("gTTS indisponível (sem internet?)")
        except OpenAIIndisponivel as exc:
            logger.warning("Voz %s indisponível (%s); tentando a outra.", name, exc)
            errors.append(f"{name}: {exc}")
            continue
        path = folder / f"{key}.{ext}"
        path.write_bytes(data)
        return Audio(path, mime, name)
    raise OpenAIIndisponivel("sem voz: " + "; ".join(errors))
