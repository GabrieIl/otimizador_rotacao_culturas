"""Página Conversa: o chatbot do Acauã, por texto ou áudio, com os dados do local selecionado.

O local é o mesmo das outras páginas (a roça marcada no mapa ou o município de exemplo) e a data é a
mesma do "Simular outra data" da Plantio. O agente recebe a descrição do app e os dados desse local
antes de cada pergunta (agente/prompt.py e agente/contexto.py).
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.agente.nucleo import Agente
from crop_optimizer.agente.openai_api import OpenAIIndisponivel
from crop_optimizer.agente.sessao import Sessao
from crop_optimizer.agente.voz import AudioInvalido, falar, transcrever
from crop_optimizer.app import navigation, theme
from crop_optimizer.app.common import current_location
from crop_optimizer.app.state import arrived, keep, stored, watch
from crop_optimizer.domain.roca import nearest_preset

_SESSION = "conversa_sessao"
_MESSAGES = "conversa_mensagens"
_USER_AVATAR_BG = "#2C4A52"  # petróleo claro da paleta (blueColor em .streamlit/config.toml)


def local_da_conversa(location, roca) -> LocalConversa:
    """O local das outras páginas no formato do agente (a roça usa o exemplo mais perto no Monte Carlo)."""
    if roca is None:
        return LocalConversa(exemplo_id=location.location_id)
    nearest, _km = nearest_preset(roca.lat, roca.lon)
    return LocalConversa(nearest.location_id, roca.lat, roca.lon, roca.municipio, roca.uf, roca.ibge_code,
                         roca.aviso_municipio)


def _sessao() -> Sessao:
    if _SESSION not in st.session_state:
        st.session_state[_SESSION] = Sessao(id="app")
        st.session_state[_MESSAGES] = []
    return st.session_state[_SESSION]


def _show(message: dict) -> None:
    avatar = theme.asset("icone.png") if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        if message.get("por_audio"):
            st.caption("Pergunta por áudio (o que o Acauã entendeu)")
        st.markdown(message["text"])
        if message.get("audio"):
            st.audio(message["audio"], format="audio/mpeg", autoplay=message.get("autoplay", False))


def conversa_page() -> None:
    arrived("conversa")
    location, roca = current_location()
    local = local_da_conversa(location, roca)
    as_of = stored("data_simulada", date.today())
    where = f"Sua roça: {roca.label}" if roca is not None else f"{location.name}/{location.state} · município de exemplo"

    theme.page_header("Conversa", "Pergunte ao Acauã", where)
    # o fundo do avatar do usuário vem do redColor do tema (o vermelho do "Não plante"): troca pelo petróleo claro
    st.html(f"<style>[data-testid='stChatMessageAvatarUser']{{background-color:{_USER_AVATAR_BG};}}</style>")
    c_link, c_audio, c_clear = st.columns([1.6, 1.4, 1], vertical_alignment="center")
    with c_link:
        navigation.link("satelite", "Marcar ou trocar a roça no mapa")
    with c_audio:
        keep("conversa_audio", False)
        st.toggle("Responder também em áudio", **watch("conversa_audio"),
                  help="Pergunta feita por áudio sempre recebe a resposta em áudio.")
    sessao = _sessao()
    with c_clear:
        if st.button("Nova conversa"):
            st.session_state.pop(_SESSION, None)
            sessao = _sessao()
    if as_of != date.today():
        st.caption(f"Simulando o dia **{as_of:%d/%m/%Y}** (mude no rodapé da página Plantio).")

    # o agente sempre usa o local e a data escolhidos agora no app
    sessao.local = local
    sessao.simular = as_of if as_of != date.today() else None

    messages: list[dict] = st.session_state[_MESSAGES]
    if not messages:
        st.markdown(
            "Pergunte, por escrito ou pelo microfone, se já dá para plantar e qual plano rende mais estável "
            f"em **{local.nome}**. As respostas usam os dados deste local: chuva e temperatura do NASA POWER, "
            "janela oficial do ZARC, solo do SoilGrids e as contas do Acauã."
        )
    for message in messages:
        _show(message)

    value = st.chat_input("Escreva ou grave a sua pergunta", accept_audio=True, key="conversa_entrada")
    st.caption("A pergunta e o áudio passam pela OpenAI para serem entendidos. O Acauã apoia a decisão; "
               "confirme com o técnico local.")
    if not value:
        return

    text, heard = (value.text or "").strip(), None
    audio_in = getattr(value, "audio", None)
    if audio_in is not None:
        try:
            with st.spinner("Ouvindo..."):
                heard = transcrever(audio_in.getvalue(), audio_in.type or "audio/wav")
        except (AudioInvalido, OpenAIIndisponivel) as exc:
            st.error(f"Não consegui ouvir o áudio: {exc}. Pode escrever a pergunta?")
            return
        text = heard or text
    if not text:
        return

    question = {"role": "user", "text": text, "por_audio": heard is not None}
    messages.append(question)
    _show(question)
    with st.spinner("O Acauã está consultando os dados do local..."):
        resposta = Agente().responder(sessao, text)
    answer = {"role": "assistant", "text": resposta.texto, "audio": None}
    if heard is not None or stored("conversa_audio", False):
        try:
            with st.spinner("Gravando a resposta..."):
                answer["audio"] = str(falar(resposta.texto, formato="mp3").path)
            answer["autoplay"] = True
        except OpenAIIndisponivel as exc:
            st.warning(f"Resposta sem áudio: {exc}")
    messages.append(answer)
    _show(answer)
    answer["autoplay"] = False  # só toca sozinho uma vez
