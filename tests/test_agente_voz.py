"""Voz do agente: transcrição com limite de tamanho, áudio da resposta com cache e reserva em gTTS."""

from __future__ import annotations

import pytest

from crop_optimizer.accessibility import radio_tempo
from crop_optimizer.accessibility.radio_tempo import AudioSynthesisResult
from crop_optimizer.agente import voz
from crop_optimizer.agente.openai_api import OpenAIIndisponivel
from crop_optimizer.agente.voz import AudioInvalido, falar, transcrever
from crop_optimizer.config import get_settings


class FakeClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.spoken, self.heard = fail, [], []

    def speech(self, text: str, response_format: str = "opus") -> bytes:
        if self.fail:
            raise OpenAIIndisponivel("sem crédito")
        self.spoken.append(text)
        return b"OggS" + text.encode()

    def transcribe(self, audio: bytes, filename: str, mime: str, prompt: str = "") -> str:
        self.heard.append((filename, mime, prompt))
        return "posso plantar?"


def test_falar_caches_by_text(tmp_path) -> None:
    settings, client = get_settings(tmp_path), FakeClient()
    first = falar("Pode plantar.", client, settings, provedor="openai")
    again = falar("Pode plantar.", client, settings, provedor="openai")
    assert first.mime == "audio/ogg" and first.provider == "openai" and again.provider == "cache"
    assert again.path == first.path and client.spoken == ["Pode plantar."]
    assert falar("Arriscado.", client, settings, provedor="openai").path != first.path
    web = falar("Pode plantar.", client, settings, formato="mp3", provedor="openai")
    assert web.mime == "audio/mpeg" and web.path.suffix == ".mp3" and web.path != first.path


def test_falar_falls_back_to_gtts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_gtts(self, text):
        return AudioSynthesisResult(text, b"ID3mp3", "audio/mp3", "gtts", "mp3")

    monkeypatch.setattr(radio_tempo.GoogleTTSProvider, "synthesize", fake_gtts)
    audio = falar("Espere a chuva firmar.", FakeClient(fail=True), get_settings(tmp_path), provedor="openai")
    assert audio.mime == "audio/mpeg" and audio.path.suffix == ".mp3" and audio.path.read_bytes() == b"ID3mp3"

    def offline(self, text):
        return AudioSynthesisResult(text, b"RIFF", "audio/wav", "offline_wav", "wav")

    monkeypatch.setattr(radio_tempo.GoogleTTSProvider, "synthesize", offline)
    with pytest.raises(OpenAIIndisponivel, match="sem voz"):  # bip offline não serve como resposta
        falar("Outro texto.", FakeClient(fail=True), get_settings(tmp_path), provedor="openai")


def test_transcrever_limits_and_mime() -> None:
    client = FakeClient()
    assert transcrever(b"OggS", "audio/ogg; codecs=opus", client) == "posso plantar?"
    filename, mime, prompt = client.heard[0]
    assert (filename, mime) == ("mensagem.ogg", "audio/ogg") and "Quixadá" in prompt
    with pytest.raises(AudioInvalido, match="vazio"):
        transcrever(b"", "audio/ogg", client)
    limit = voz.load_yaml_config("conversa")["audio"]["max_bytes_recebido"]
    with pytest.raises(AudioInvalido, match="limite"):
        transcrever(b"x" * (limit + 1), "audio/ogg", client)


def test_default_voice_is_free_gtts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(radio_tempo.GoogleTTSProvider, "synthesize",
                        lambda self, text: AudioSynthesisResult(text, b"ID3", "audio/mp3", "gtts", "mp3"))
    client = FakeClient()
    audio = falar("Pode plantar.", client, get_settings(tmp_path))  # padrão: config/conversa.yaml
    assert audio.provider == "gtts" and audio.mime == "audio/mpeg" and client.spoken == []
