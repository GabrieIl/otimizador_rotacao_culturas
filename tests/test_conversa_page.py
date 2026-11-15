"""Página Conversa: usa o local e a data do app, responde no chat (sem OpenAI: pelas regras)."""

from __future__ import annotations

import textwrap
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.app.conversa_page import local_da_conversa
from crop_optimizer.domain.presets import location_map
from crop_optimizer.domain.roca import Roca

_APP = textwrap.dedent(
    """
    from crop_optimizer.app.conversa_page import conversa_page
    conversa_page()
    """
)


@pytest.fixture
def page(tmp_path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # sem OpenAI: o agente responde pelas regras
    path = tmp_path / "conversa.py"
    path.write_text(_APP, encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=180)
    at.session_state["_guardado_municipio_exemplo"] = "quixada_ce"
    at.session_state["_guardado_data_simulada"] = date(2026, 3, 1)
    return at.run()


def _chat(at: AppTest) -> list[str]:
    return [" ".join(m.value for m in msg.markdown) for msg in at.chat_message]


def test_chat_answers_with_selected_location(page: AppTest) -> None:
    assert not page.exception
    assert "Quixadá/CE" in page.markdown[0].value  # texto de abertura cita o local do app
    page.chat_input[0].set_value("posso plantar milho?").run()
    assert not page.exception
    question, answer = _chat(page)
    assert question == "posso plantar milho?"
    assert answer.startswith("Milho: Arriscado.") and "de cada 10" in answer
    sessao = page.session_state["conversa_sessao"]
    assert sessao.local == LocalConversa("quixada_ce") and sessao.simular == date(2026, 3, 1)

    page.chat_input[0].set_value("qual plano rende mais pro rebanho?").run()
    assert len(_chat(page)) == 4 and "quebra" in _chat(page)[-1]

    page.button[0].click().run()  # nova conversa
    assert _chat(page) == []


def test_local_da_conversa_matches_app_location() -> None:
    quixada = location_map()["quixada_ce"]
    assert local_da_conversa(quixada, None) == LocalConversa("quixada_ce")
    roca = Roca(-5.1991, -39.2927, "Quixeramobim", "CE", "2311405")
    local = local_da_conversa(roca.to_location(), roca)
    assert local.exemplo_id == "quixada_ce" and local.location() == roca.to_location()
