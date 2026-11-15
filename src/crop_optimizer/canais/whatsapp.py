"""Canal WhatsApp (Twilio): recebe texto, áudio ou localização e responde com texto e áudio.

Fluxo (o webhook responde na hora e o resto roda em segundo plano, porque o Twilio espera no
máximo 15 s e áudio + agente + voz pode passar disso):

    webhook -> valida assinatura -> descarta MessageSid repetido -> TwiML imediato
            -> processar(): áudio? baixa e transcreve | localização? guarda a roça | texto
                            -> agente -> manda o texto -> manda o áudio (/media/<arquivo>)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from html import escape

import httpx

from crop_optimizer.accessibility.whatsapp import TwilioWhatsAppClient
from crop_optimizer.agente.ferramentas import Contexto, definir_roca
from crop_optimizer.agente.nucleo import Agente
from crop_optimizer.agente.openai_api import OpenAIIndisponivel
from crop_optimizer.agente.sessao import SessaoStore, chave_hash
from crop_optimizer.agente.voz import Audio, AudioInvalido, falar, transcrever
from crop_optimizer.config import Settings, load_yaml_config

logger = logging.getLogger(__name__)

Sender = Callable[[str, str, str | None], object]  # (para, texto, url da mídia)


def twiml(text: str | None = None) -> str:
    body = f"<Message>{escape(text)}</Message>" if text else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def calcular_assinatura(url: str, params: dict[str, str], auth_token: str) -> str:
    """X-Twilio-Signature: base64(HMAC-SHA1(token, url + cada chave e valor do form em ordem alfabética))."""
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def assinatura_valida(url: str, params: dict[str, str], signature: str, auth_token: str) -> bool:
    return hmac.compare_digest(calcular_assinatura(url, params, auth_token), signature or "")


@dataclass(frozen=True, slots=True)
class MensagemWhatsApp:
    de: str  # "whatsapp:+55..."
    sid: str
    texto: str = ""
    media_url: str | None = None
    media_tipo: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @classmethod
    def from_form(cls, form: dict[str, str]) -> MensagemWhatsApp:
        lat, lon = form.get("Latitude"), form.get("Longitude")
        has_media = int(form.get("NumMedia") or 0) > 0
        return cls(
            de=form.get("From", ""),
            sid=form.get("MessageSid", ""),
            texto=(form.get("Body") or "").strip(),
            media_url=form.get("MediaUrl0") if has_media else None,
            media_tipo=form.get("MediaContentType0") if has_media else None,
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
        )

    @property
    def is_audio(self) -> bool:
        return bool(self.media_tipo and self.media_tipo.startswith("audio/"))

    @property
    def is_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class WhatsAppService:
    def __init__(
        self,
        settings: Settings,
        agente: Agente | None = None,
        sender: Sender | None = None,
        downloader: Callable[[str], bytes] | None = None,
        transcriber: Callable[[bytes, str], str] = transcrever,
        speaker: Callable[[str], Audio] = falar,
        store: SessaoStore | None = None,
    ) -> None:
        self.settings = settings
        self.agente = agente or Agente()
        twilio = TwilioWhatsAppClient(settings.twilio_account_sid, settings.twilio_auth_token,
                                      settings.twilio_whatsapp_from)
        self.sender = sender or (lambda to, body, media: twilio.send_message(to, body, media))
        self.downloader = downloader or self._download
        self.transcriber = transcriber
        self.speaker = speaker
        self.store = store or SessaoStore(settings)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    # --- webhook (rápido) ---------------------------------------------------------

    def assinatura_ok(self, path_and_query: str, params: dict[str, str], signature: str | None) -> bool:
        """Sem URL pública ou sem token não dá para conferir (teste local): aceita e avisa no log."""
        token, base = self.settings.twilio_auth_token, self.settings.public_url
        if not token or not base:
            logger.warning("Assinatura do Twilio não conferida (falta TWILIO_AUTH_TOKEN ou ACAUA_PUBLIC_URL).")
            return True
        return assinatura_valida(base + path_and_query, params, signature or "", token)

    def nova(self, sid: str) -> bool:
        """False se o Twilio reenviou uma mensagem que já está sendo atendida."""
        with self._seen_lock:
            if not sid or sid in self._seen:
                return not sid
            self._seen[sid] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
            return True

    def resposta_imediata(self, msg: MensagemWhatsApp) -> str:
        cfg = load_yaml_config("conversa")["whatsapp"]
        return twiml(cfg["aviso_processando_audio"] if msg.is_audio else None)

    # --- atendimento (em segundo plano) ---------------------------------------------

    def processar(self, msg: MensagemWhatsApp) -> None:
        lock = self._locks.setdefault(chave_hash(msg.de), threading.Lock())
        with lock:  # uma mensagem por vez de cada pessoa, na ordem em que chegaram
            try:
                self._processar(msg)
            except Exception:
                logger.exception("Erro ao atender a mensagem %s", msg.sid)
                self._send(msg.de, load_yaml_config("conversa")["whatsapp"]["erro"], None)

    def _processar(self, msg: MensagemWhatsApp) -> None:
        cfg = load_yaml_config("conversa")["whatsapp"]
        sessao = self.store.carregar(msg.de)
        intro = [] if sessao.apresentado else [cfg["boas_vindas"]]
        sessao.apresentado = True

        if msg.is_location:
            ctx = Contexto(local=sessao.local)
            out = definir_roca(ctx, latitude=msg.latitude, longitude=msg.longitude)
            sessao.local = ctx.local
            self.store.salvar(sessao)
            reply = " ".join([cfg["roca_anotada"].format(nome=ctx.local.nome), out.get("aviso", "")]).strip()
            self._reply(msg.de, intro, reply)
            return

        texto, heard = msg.texto, None
        if msg.is_audio:
            try:
                texto = self.transcriber(self.downloader(msg.media_url), msg.media_tipo or "audio/ogg")
            except (AudioInvalido, OpenAIIndisponivel, httpx.HTTPError) as exc:
                logger.warning("Áudio %s sem transcrição: %s", msg.sid, exc)
                texto = ""
            if not texto:
                self.store.salvar(sessao)
                self._reply(msg.de, intro, cfg["nao_ouvi"])
                return
            heard = f'Ouvi: "{texto}"' if cfg["mostrar_transcricao"] else None
        elif msg.media_url:
            self.store.salvar(sessao)
            self._reply(msg.de, intro, cfg["midia_nao_suportada"])
            return

        resposta = self.agente.responder(sessao, texto or "oi")
        self.store.salvar(sessao)
        logger.info("Mensagem %s respondida por %s (%s)", msg.sid, resposta.fonte, ", ".join(resposta.ferramentas))
        self._reply(msg.de, [*intro, *([heard] if heard else [])], resposta.texto)

    def _reply(self, to: str, before: list[str], answer: str) -> None:
        """Texto (com boas-vindas e transcrição, se houver) e depois o áudio só da resposta."""
        self._send(to, "\n\n".join([*before, answer]), None)
        cfg = load_yaml_config("conversa")["whatsapp"]
        if not cfg["responder_com_audio"]:
            return
        if not self.settings.public_url:
            logger.warning("Sem ACAUA_PUBLIC_URL: o Twilio não tem de onde baixar o áudio; vai só o texto.")
            return
        try:
            audio = self.speaker(answer)
        except OpenAIIndisponivel as exc:
            logger.warning("Resposta sem áudio: %s", exc)
            return
        self._send(to, "", f"{self.settings.public_url}/media/{audio.name}")

    def _send(self, to: str, body: str, media_url: str | None) -> None:
        self.sender(to, body, media_url)

    def _download(self, url: str) -> bytes:
        """A mídia do Twilio pede a autenticação da conta e redireciona para o arquivo."""
        auth = (self.settings.twilio_account_sid or "", self.settings.twilio_auth_token or "")
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url, auth=auth)
            resp.raise_for_status()
            return resp.content
