"""Página Conversa: usa o local e a data do app, responde no chat (sem OpenAI: pelas regras)."""

from __future__ import annotations

import textwrap
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.app.conversa_page import local_da_conversa
from crop_optimizer.domain.models import BalancePriority
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


def test_conversa_syncs_filters_and_renders_summary(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "conversa_filtros.py"
    path.write_text(_APP, encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=180)
    at.session_state["_guardado_municipio_exemplo"] = "quixada_ce"
    at.session_state["_guardado_data_simulada"] = date(2026, 3, 1)
    at.session_state["_guardado_cultura"] = "cenoura"
    at.session_state["_guardado_ciclo_zarc"] = "21"
    at.session_state["_guardado_horizonte"] = 3
    at.session_state["_guardado_prioridade"] = BalancePriority.RENDA
    at.session_state["_guardado_rot_precisa"] = ["milho_sertanejo"]
    at.session_state["_guardado_rot_sem"] = ["palma_forrageira"]
    at.run()

    assert not at.exception
    html_text = " ".join(str(h.proto) for h in at.get("html"))
    assert "Resumo dos filtros escolhidos" in html_text
    assert "Cenoura" in html_text
    assert "3 anos" in html_text
    assert "Renda" in html_text
    assert "Precisa ter: Milho" in html_text
    assert "Sem: Palma" in html_text

    sessao = at.session_state["conversa_sessao"]
    assert sessao.cultura_selecionada == "cenoura"
    assert sessao.cycle_code == "21"
    assert sessao.horizonte_anos == 3
    assert sessao.prioridade == "renda"
    assert sessao.precisa_ter == ["milho_sertanejo"]
    assert sessao.nao_pode_ter == ["palma_forrageira"]
    assert sessao.soil_group

    at.chat_input[0].set_value("posso plantar cenoura?").run()
    assert not at.exception
    answer = _chat(at)[-1]
    assert answer.startswith("Cenoura: Só com rega.") and "%" not in answer
