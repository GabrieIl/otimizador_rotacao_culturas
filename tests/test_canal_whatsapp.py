"""Canal WhatsApp: webhook do Twilio, assinatura, áudio, localização e resposta em texto + voz (sem rede)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from crop_optimizer.agente import local as local_mod
from crop_optimizer.agente.nucleo import Resposta
from crop_optimizer.agente.openai_api import OpenAIIndisponivel
from crop_optimizer.agente.voz import Audio, audio_dir
from crop_optimizer.api import create_app
from crop_optimizer.canais.whatsapp import WhatsAppService, assinatura_valida, calcular_assinatura
from crop_optimizer.config import get_settings, load_yaml_config
from crop_optimizer.ingestion.geocode import Place

CFG = load_yaml_config("conversa")["whatsapp"]
PUBLIC = "https://acaua.trycloudflare.com"
TOKEN = "token-de-teste"
PATH = "/api/v1/whatsapp/webhook"
FROM = "whatsapp:+5588999990000"


class FakeAgent:
    def __init__(self) -> None:
        self.perguntas: list[str] = []

    def responder(self, sessao, texto):
        self.perguntas.append(texto)
        return Resposta(f"Resposta para: {texto}", "agente", ["situacao_plantio"])


@pytest.fixture
def env(tmp_path):
    settings = get_settings(tmp_path)
    settings.public_url, settings.twilio_auth_token, settings.twilio_account_sid = PUBLIC, TOKEN, "AC1"
    sent: list[tuple[str, str, str | None]] = []
    agent = FakeAgent()
    reply_audio = audio_dir(settings) / ("a" * 32 + ".ogg")
    reply_audio.write_bytes(b"OggS-fake")
    state = {"transcricao": "posso plantar milho?", "download": b"OggS-recebido"}

    def transcriber(audio: bytes, mime: str) -> str:
        assert audio == state["download"] and mime == "audio/ogg"
        if state["transcricao"] is None:
            raise OpenAIIndisponivel("fora")
        return state["transcricao"]

    svc = WhatsAppService(
        settings,
        agente=agent,
        sender=lambda to, body, media: sent.append((to, body, media)),
        downloader=lambda url: state["download"],
        transcriber=transcriber,
        speaker=lambda text: Audio(reply_audio, "audio/ogg", "fake"),
    )
    client = TestClient(create_app(settings, whatsapp=svc))

    def post(params: dict, signed: bool = True):
        headers = {"X-Twilio-Signature": calcular_assinatura(PUBLIC + PATH, params, TOKEN) if signed else "x"}
        return client.post(PATH, data=params, headers=headers)

    return {"post": post, "sent": sent, "agent": agent, "state": state, "svc": svc, "client": client,
            "audio": reply_audio}


def _text(sid: str, body: str) -> dict:
    return {"MessageSid": sid, "From": FROM, "Body": body, "NumMedia": "0"}


def test_text_message_gets_text_and_audio(env) -> None:
    r = env["post"](_text("SM1", "posso plantar milho?"))
    assert r.status_code == 200 and r.text.endswith("<Response></Response>")
    (to, body, media), (to2, body2, media2) = env["sent"]
    assert to == to2 == FROM
    assert body.startswith(CFG["boas_vindas"]) and body.endswith("Resposta para: posso plantar milho?")
    assert media is None and body2 == "" and media2 == f"{PUBLIC}/media/{env['audio'].name}"

    env["post"](_text("SM2", "e o feijão?"))
    assert env["sent"][2][1] == "Resposta para: e o feijão?"  # boas-vindas só na primeira vez


def test_duplicate_and_unsigned_messages(env) -> None:
    env["post"](_text("SM1", "oi"))
    env["post"](_text("SM1", "oi"))  # o Twilio reenviou
    assert env["agent"].perguntas == ["oi"]
    r = env["post"](_text("SM9", "oi"), signed=False)
    assert r.status_code == 403 and env["agent"].perguntas == ["oi"]


def test_audio_message_is_transcribed(env) -> None:
    params = {"MessageSid": "SM3", "From": FROM, "Body": "", "NumMedia": "1",
              "MediaUrl0": "https://api.twilio.com/media/1", "MediaContentType0": "audio/ogg"}
    r = env["post"](params)
    assert CFG["aviso_processando_audio"] in r.text
    assert env["agent"].perguntas == ["posso plantar milho?"]
    assert 'Ouvi: "posso plantar milho?"' in env["sent"][0][1]

    env["state"]["transcricao"] = None
    env["post"]({**params, "MessageSid": "SM4"})
    assert env["sent"][-2][1] == CFG["nao_ouvi"] and len(env["agent"].perguntas) == 1


def test_location_sets_the_farm(env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_mod, "resolve_place", lambda lat, lon, s=None: Place("Quixeramobim", "CE", "2311405"))
    env["post"]({"MessageSid": "SM5", "From": FROM, "Body": "", "NumMedia": "0",
                 "Latitude": "-5.19912", "Longitude": "-39.29271"})
    body = env["sent"][0][1]
    assert "Anotei a roça em Quixeramobim/CE" in body and "Quixadá/CE" in body
    sessao = env["svc"].store.carregar(FROM)
    assert sessao.local.municipio == "Quixeramobim" and sessao.local.exemplo_id == "quixada_ce"
    assert env["agent"].perguntas == []


def test_image_is_not_supported(env) -> None:
    env["post"]({"MessageSid": "SM6", "From": FROM, "Body": "", "NumMedia": "1",
                 "MediaUrl0": "https://api.twilio.com/media/2", "MediaContentType0": "image/jpeg"})
    assert env["sent"][0][1].endswith(CFG["midia_nao_suportada"]) and env["agent"].perguntas == []


def test_without_public_url_only_text_is_sent(env) -> None:
    env["svc"].settings.public_url = None  # sem túnel: não confere assinatura e não manda áudio
    env["post"](_text("SM7", "oi"), signed=False)
    assert len(env["sent"]) == 1


def test_agent_crash_sends_apology(env, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(sessao, texto):
        raise RuntimeError("falhou")

    monkeypatch.setattr(env["agent"], "responder", boom)
    env["post"](_text("SM8", "oi"))
    assert env["sent"][-1][1] == CFG["erro"]


def test_media_route(env) -> None:
    client = env["client"]
    ok = client.get(f"/media/{env['audio'].name}")
    assert ok.status_code == 200 and ok.content == b"OggS-fake" and ok.headers["content-type"] == "audio/ogg"
    assert client.get("/media/" + "b" * 32 + ".ogg").status_code == 404
    assert client.get("/media/..%2F..%2F.env").status_code == 404


def test_signature() -> None:
    params = {"Body": "oi", "From": FROM}
    sig = calcular_assinatura(PUBLIC + PATH, params, TOKEN)
    assert assinatura_valida(PUBLIC + PATH, params, sig, TOKEN)
    assert not assinatura_valida(PUBLIC + PATH, {**params, "Body": "tchau"}, sig, TOKEN)
    assert not assinatura_valida(PUBLIC + PATH, params, sig, "outro-token")


def test_whatsapp_only_app_hides_other_routes(tmp_path) -> None:
    client = TestClient(create_app(get_settings(tmp_path), somente_whatsapp=True))
    assert client.get("/health").status_code == 200
    for path in ("/api/v1/radio-do-tempo", "/api/v1/simulate", "/api/v1/ficha-tecnica.pdf"):
        assert client.post(path, json={}).status_code == 404
