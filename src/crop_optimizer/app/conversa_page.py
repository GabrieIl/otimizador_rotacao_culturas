"""Página Conversa: o chatbot do Acauã, por texto ou áudio, com os dados e filtros do app.

O local é o mesmo das outras páginas (a roça marcada no mapa ou o município de exemplo) e os filtros
seguem as escolhas da Início e da Plantio (data simulada, solo/ciclo ZARC, cultura em foco, horizonte,
prioridade, restrições das rotações e talhões da fazenda). O agente recebe a descrição do app e os dados
desse local antes de cada pergunta (agente/prompt.py e agente/contexto.py).
"""

from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from crop_optimizer.agente.consultas import HORIZONS
from crop_optimizer.agente.ferramentas import PRIORIDADES
from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.agente.nucleo import Agente
from crop_optimizer.agente.openai_api import OpenAIIndisponivel
from crop_optimizer.agente.sessao import Sessao
from crop_optimizer.agente.voz import AudioInvalido, falar, transcrever
from crop_optimizer.analytics.soil_suitability import TEXTURE_LABELS, texture_class
from crop_optimizer.app import navigation, theme
from crop_optimizer.app.common import current_location, soil_profile
from crop_optimizer.app.home_page import crop_names
from crop_optimizer.app.state import arrived, keep, stored, watch
from crop_optimizer.domain.fazenda import load_fazenda
from crop_optimizer.domain.models import BalancePriority, LocationSpec
from crop_optimizer.domain.roca import Roca, nearest_preset
from crop_optimizer.ingestion.zarc_tabua import cycle_label

_SESSION = "conversa_sessao"
_MESSAGES = "conversa_mensagens"
_USER_AVATAR_BG = "#2C4A52"  # petróleo claro da paleta (blueColor em .streamlit/config.toml)

_PRIORITY_TO_AGENTE = {
    **{str(bp): key for key, bp in PRIORIDADES.items()},
    **{bp.value: key for key, bp in PRIORIDADES.items()},
    **{key: key for key in PRIORIDADES},
}
_PRIORITY_LABEL = {
    "equilibrio": "Equilíbrio",
    "graos": "Produção de grãos",
    "forragem": "Forragem",
    "estabilidade": "Estabilidade",
    "renda": "Renda",
}
_SOURCE_LABEL = {
    "campo": "análise de campo",
    "mapa": "SoilGrids + SRTM",
    "estimado": "valor típico",
}


def local_da_conversa(location: LocationSpec, roca: Roca | None) -> LocalConversa:
    """O local das outras páginas no formato do agente (a roça usa o exemplo mais perto no Monte Carlo)."""
    if roca is None:
        return LocalConversa(exemplo_id=location.location_id)
    nearest, _km = nearest_preset(roca.lat, roca.lon)
    return LocalConversa(nearest.location_id, roca.lat, roca.lon, roca.municipio, roca.uf, roca.ibge_code,
                         roca.aviso_municipio)


def _normalize_priority(raw: object) -> str:
    if isinstance(raw, BalancePriority):
        return _PRIORITY_TO_AGENTE.get(raw.value, "equilibrio")
    return _PRIORITY_TO_AGENTE.get(str(raw or "equilibrio"), "equilibrio")


def _filter_crops(raw: object, names: dict[str, str]) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(c) for c in raw if str(c) in names]


def _sync_sessao_filters(sessao: Sessao, location: LocationSpec, local: LocalConversa, as_of: date) -> list[tuple[str, str]]:
    """Sincroniza os filtros escolhidos no app com a sessão do agente e retorna os itens de resumo."""
    names = crop_names()
    profile = soil_profile(location)
    soil_group = texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    soil_sources = {v.source for v in profile.values.values() if v.source != "estimado"}
    soil_src_txt = ", ".join(_SOURCE_LABEL.get(s, s) for s in sorted(soil_sources)) or _SOURCE_LABEL["estimado"]

    raw_cycle = stored("ciclo_zarc", "todos")
    cycle_code = None if not raw_cycle or str(raw_cycle) == "todos" else str(raw_cycle)

    raw_crop = stored("cultura")
    cultura_sel = str(raw_crop) if raw_crop and str(raw_crop) in names else None

    raw_horizon = stored("horizonte", 5)
    horizonte = int(raw_horizon) if raw_horizon in HORIZONS else 5
    prioridade = _normalize_priority(stored("prioridade", BalancePriority.EQUILIBRADO))

    precisa_ter = _filter_crops(stored("rot_precisa", []), names)
    nao_pode_ter = _filter_crops(stored("rot_sem", []), names)

    fazenda = load_fazenda(location.location_id)
    culturas_atuais = [t.cultura for t in fazenda.talhoes if t.cultura] if fazenda else []
    fazenda_resumo = None
    if fazenda is not None:
        fazenda_resumo = {
            "area_total_ha": fazenda.area_total_ha,
            "talhoes": [
                {
                    "nome": t.nome,
                    "area_ha": t.area_ha,
                    "cultura": names.get(t.cultura, t.cultura) if t.cultura else None,
                    "plantio": t.plantio.isoformat() if t.plantio else None,
                }
                for t in fazenda.talhoes
            ],
        }

    sessao.local = local
    sessao.simular = as_of if as_of != date.today() else None
    sessao.soil_group = soil_group
    sessao.cycle_code = cycle_code
    sessao.cultura_selecionada = cultura_sel
    sessao.horizonte_anos = horizonte
    sessao.prioridade = prioridade
    sessao.precisa_ter = precisa_ter
    sessao.nao_pode_ter = nao_pode_ter
    sessao.culturas_atuais = culturas_atuais
    sessao.fazenda_resumo = fazenda_resumo

    # itens legíveis para o painel "Resumo dos filtros escolhidos"
    local_kind = "Município de exemplo" if local.is_example else f"Roça no mapa (exemplo: {local.exemplo.name}/{local.exemplo.state})"
    data_txt = f"{as_of:%d/%m/%Y} (simulada)" if as_of != date.today() else f"{as_of:%d/%m/%Y} (hoje)"
    ciclo_txt = "Todos os ciclos" if cycle_code is None else cycle_label(cycle_code)
    cultura_txt = names[cultura_sel] if cultura_sel else "Todas as culturas"
    horiz_txt = "1 ano" if horizonte == 1 else f"{horizonte} anos"
    prio_txt = _PRIORITY_LABEL.get(prioridade, prioridade)

    restr_parts = []
    if precisa_ter:
        restr_parts.append("Precisa ter: " + ", ".join(names[c] for c in precisa_ter))
    if nao_pode_ter:
        restr_parts.append("Sem: " + ", ".join(names[c] for c in nao_pode_ter))
    restr_txt = " · ".join(restr_parts) if restr_parts else "Sem restrições"

    if fazenda and fazenda.talhoes:
        hoje_lbl = ", ".join(dict.fromkeys(names.get(c, c) for c in culturas_atuais))
        faz_txt = (
            f"{len(fazenda.talhoes)} {'talhão' if len(fazenda.talhoes) == 1 else 'talhões'} · "
            f"{fazenda.area_total_ha:.1f} ha" + (f" ({hoje_lbl})" if hoje_lbl else "")
        ).replace(".", ",")
    else:
        faz_txt = "Nenhum talhão cadastrado"

    return [
        ("Local", f"{local.nome} ({local_kind})"),
        ("Data", data_txt),
        ("Solo e ZARC", f"{TEXTURE_LABELS.get(soil_group, soil_group)} ({soil_src_txt}) · Ciclo: {ciclo_txt}"),
        ("Cultura em foco", cultura_txt),
        ("Ranking", f"{horiz_txt} · {prio_txt}"),
        ("Restrições", restr_txt),
        ("Sua roça", faz_txt),
    ]


def _render_filter_summary(summary_items: list[tuple[str, str]]) -> None:
    cells = "".join(
        f'<div class="acaua-filtro-item"><span class="k">{escape(label)}</span>'
        f'<span class="v">{escape(value)}</span></div>'
        for label, value in summary_items
    )
    st.html(
        """
        <style>
          .acaua-filtros-card {
            background: var(--acaua-creme, #F2EFEA);
            border: 1px solid var(--acaua-linha, #D9D0BF);
            border-radius: 0.75rem;
            padding: 0.9rem 1.15rem;
            margin: 0.5rem 0 0.85rem 0;
          }
          .acaua-filtros-head {
            font-family: var(--acaua-fonte-rotulo, monospace);
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--acaua-texto-suave, #56676B);
            margin: 0 0 0.55rem 0;
          }
          .acaua-filtros-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 0.45rem 1.1rem;
          }
          .acaua-filtro-item {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
          }
          .acaua-filtro-item .k {
            font-family: var(--acaua-fonte-rotulo, monospace);
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--acaua-texto-suave, #56676B);
          }
          .acaua-filtro-item .v {
            font-size: 0.88rem;
            font-weight: 600;
            color: var(--acaua-petroleo, #163037);
            line-height: 1.3;
          }
        </style>
        <section class="acaua-filtros-card" aria-label="Resumo dos filtros escolhidos">
          <div class="acaua-filtros-head">Resumo dos filtros escolhidos</div>
          <div class="acaua-filtros-grid">"""
        + cells
        + "</div></section>"
    )


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

    # o agente sempre usa o local, a data e todos os filtros escolhidos agora no app
    summary_items = _sync_sessao_filters(sessao, location, local, as_of)
    _render_filter_summary(summary_items)
    c_plantio, c_inicio = st.columns(2)
    with c_plantio:
        navigation.link("plantio", "Ajustar filtros na página Plantio")
    with c_inicio:
        navigation.link("inicio", "Editar solo e talhões na Início")

    messages: list[dict] = st.session_state[_MESSAGES]
    if not messages:
        st.markdown(
            "Pergunte, por escrito ou pelo microfone, se já dá para plantar e qual plano rende mais estável "
            f"em **{local.nome}**. As respostas usam os filtros acima e os dados deste local: chuva e temperatura do "
            "NASA POWER, janela oficial do ZARC, solo do SoilGrids e as contas do Acauã."
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
