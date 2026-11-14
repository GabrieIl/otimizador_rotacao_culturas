"""O Rádio do Tempo: geração de roteiro regionalizado e Text-to-Speech (TTS) Audio-First."""

from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
import numpy as np
from gtts import gTTS

from crop_optimizer.domain.models import (
    LocationSpec,
    StrategySimulationResult,
    TrafficLightLevel,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioSynthesisResult:
    """Resultado da síntese de áudio do Rádio do Tempo."""

    script: str
    audio_bytes: bytes
    mime_type: str
    provider_used: str
    file_extension: str


class TTSProvider(Protocol):
    """Contrato para provedores de Text-to-Speech."""

    def synthesize(self, text: str) -> AudioSynthesisResult: ...


def compose_radio_script(
    farmer_name: str,
    location: LocationSpec,
    delay_days: int,
    traffic_light: TrafficLightLevel,
    traditional_result: StrategySimulationResult,
    resilient_result: StrategySimulationResult,
    horizon_years: int = 5,
) -> str:
    """Compila o Placar de Sobrevivência e o Semáforo em linguagem falada, simples e direta."""
    if traffic_light == TrafficLightLevel.VERDE:
        clima_frase = (
            f"A chuva em {location.name} está dentro da janela boa. "
            "O sinal está verde para plantar com cuidado."
        )
    elif traffic_light == TrafficLightLevel.AMARELO:
        motivo = (
            f"com {delay_days} dias de atraso na chuva em {location.name}"
            if delay_days > 0
            else f"pelo histórico de chuva de {location.name}"
        )
        clima_frase = f"Atenção: {motivo}, o sinal ficou amarelo. Insistir só no milho já traz perigo."
    else:
        motivo = f"a chuva atrasou {delay_days} dias" if delay_days > 0 else "o histórico de chuva é de muito risco"
        clima_frase = (
            f"Alerta vermelho em {location.name}: {motivo}. "
            "Guarde a semente do milho porque o risco de perder a roça é extremo."
        )

    trad_name = traditional_result.strategy.short_name or traditional_result.strategy.name
    res_name = resilient_result.strategy.short_name or resilient_result.strategy.name
    forage_fmt = f"{round(resilient_result.expected_forage_kg_ha_year):,}".replace(",", ".")
    herd_risk_pct = round(traditional_result.prob_herd_collapse * 100)

    saudacao = f"Alô, {farmer_name}!" if farmer_name else "Alô, agricultora e agricultor!"
    periodo = "para o próximo ano" if horizon_years == 1 else f"para os próximos {horizon_years} anos"
    rebanho = "no ano" if horizon_years == 1 else "em dois anos seguidos"
    return (
        f"{saudacao} Aqui é o Rádio do Tempo do seu conselheiro de bolso. "
        f"{clima_frase} "
        f"O aplicativo rodou dez mil cálculos {periodo}. "
        f"Se o senhor apostar apenas em {trad_name}, "
        f"em cada dez anos o senhor perde a lavoura em {traditional_result.loss_years_of_10}, "
        f"com chance de {herd_risk_pct}% de faltar comida para o rebanho {rebanho}. "
        f"Já se o senhor adotar {res_name}, "
        f"a perda cai para {resilient_result.loss_years_of_10} anos em dez, "
        f"garantindo cerca de {forage_fmt} quilos de forragem por hectare todo ano "
        "para proteger a sua criação."
    )


class OfflineWavTTSProvider:
    """Sintetizador offline em Python puro (WAV PCM 16 kHz) para testes e operação sem internet."""

    def synthesize(self, text: str) -> AudioSynthesisResult:
        sample_rate = 16_000
        # Duração proporcional curta e previsível (0.6s a 2.5s) para feedback rápido
        duration_s = float(np.clip(len(text) * 0.008, 0.8, 2.5))
        t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
        # Tom amigável de "chamada do Rádio do Tempo" modulado por envelope suave
        envelope = np.sin(np.pi * t / duration_s) ** 0.5
        signal = 0.25 * envelope * (np.sin(2 * np.pi * 440.0 * t) + 0.5 * np.sin(2 * np.pi * 660.0 * t))
        pcm = (np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())

        return AudioSynthesisResult(
            script=text,
            audio_bytes=buf.getvalue(),
            mime_type="audio/wav",
            provider_used="offline_wav",
            file_extension="wav",
        )


class GoogleTTSProvider:
    """Provedor Google TTS (gTTS PT-BR) com fallback automático para áudio offline."""

    def __init__(self, fallback: TTSProvider | None = None) -> None:
        self.fallback = fallback or OfflineWavTTSProvider()

    def synthesize(self, text: str) -> AudioSynthesisResult:
        try:
            buf = io.BytesIO()
            tts = gTTS(text=text, lang="pt", tld="com.br", slow=False)
            tts.write_to_fp(buf)
            return AudioSynthesisResult(
                script=text,
                audio_bytes=buf.getvalue(),
                mime_type="audio/mp3",
                provider_used="gtts",
                file_extension="mp3",
            )
        except Exception as exc:
            logger.warning("Falha no Google TTS (%s). Usando fallback offline.", exc)
            return self.fallback.synthesize(text)


class OpenAITTSProvider:
    """Provedor OpenAI Audio Speech API (tts-1) com fallback automático para offline."""

    def __init__(
        self,
        api_key: str | None,
        voice: str = "onyx",
        model: str = "tts-1",
        fallback: TTSProvider | None = None,
    ) -> None:
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.fallback = fallback or OfflineWavTTSProvider()

    def synthesize(self, text: str) -> AudioSynthesisResult:
        if not self.api_key:
            return self.fallback.synthesize(text)
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": text, "voice": self.voice},
                )
                resp.raise_for_status()
            return AudioSynthesisResult(
                script=text,
                audio_bytes=resp.content,
                mime_type="audio/mpeg",
                provider_used="openai_tts",
                file_extension="mp3",
            )
        except Exception as exc:
            logger.warning("Falha no OpenAI TTS (%s). Usando fallback offline.", exc)
            return self.fallback.synthesize(text)


def create_tts_provider(
    provider: Literal["offline", "gtts", "openai"] = "offline",
    openai_api_key: str | None = None,
) -> TTSProvider:
    """Instancia o provedor de TTS configurado."""
    if provider == "gtts":
        return GoogleTTSProvider()
    if provider == "openai":
        return OpenAITTSProvider(api_key=openai_api_key)
    return OfflineWavTTSProvider()
