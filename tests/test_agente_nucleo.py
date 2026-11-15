"""Agente: laço de ferramentas, guardas, reserva por regras e sessão (sem rede, OpenAI falsa)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import httpx
import pytest

from crop_optimizer.agente import contexto, guardas, nucleo, openai_api, regras
from crop_optimizer.agente.local import LocalConversa
from crop_optimizer.agente.nucleo import Agente
from crop_optimizer.agente.openai_api import OpenAIClient, OpenAIIndisponivel, output_text
from crop_optimizer.agente.sessao import Sessao, SessaoStore, chave_hash
from crop_optimizer.config import get_settings, load_yaml_config

CLOSING = load_yaml_config("conversa")["fechamento"]

SITUACAO = {
    "chuva": {"situacao": "firmando", "resumo": "A chuva atingiu o critério de início em 06/fev."},
    "culturas": [{
        "cultura": "Milho", "id": "milho_sertanejo",
        "aviso": {"palavra": "Arriscado", "nivel": "amarelo", "usa_clima_de_exemplo": True,
                  "motivo": "Plantando agora, com 12 dias de atraso da chuva, a roça quebra em 5 de cada 10 anos."},
        "janela_oficial": {"estado": "aberta", "abre": "11/fev", "fecha": "31/mar"},
    }],
}
PLACAR = {
    "dados_de_exemplo": True, "jeito_de_hoje": "so_milho_tradicional",
    "ranking": [
        {"id": "sorgo_caupi_palma", "nome": "Sorgo + Caupi + Palma", "quebra_de_safra": "0 de cada 10 anos",
         "descricao": "Grão e palma para o rebanho."},
        {"id": "so_milho_tradicional", "nome": "Só Milho", "quebra_de_safra": "2 de cada 10 anos", "descricao": "Só milho."},
    ],
}


def _message(text: str) -> list[dict]:
    return [{"type": "message", "content": [{"type": "output_text", "text": text}]}]


def _call(name: str, args: dict, call_id: str = "c1") -> list[dict]:
    return [{"type": "reasoning", "encrypted_content": "x"},
            {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": call_id}]


class FakeClient:
    def __init__(self, outputs: list[list[dict]]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict]] = []

    def respond(self, *, instructions: str, input_items: list[dict], tools: list[dict]) -> dict:
        self.calls.append(list(input_items))
        return {"output": self.outputs.pop(0)}


class DownClient:
    def respond(self, **_kw):
        raise OpenAIIndisponivel("sem crédito")


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Ferramentas falsas (sem motor) no agente e nas regras."""
    seen: list[tuple[str, dict]] = []

    def executar(name, args, ctx):
        seen.append((name, args))
        if name == "definir_roca":
            ctx.local = LocalConversa("quixada_ce")
            return {"ok": True}
        return {"situacao_plantio": SITUACAO, "placar_rotacoes": PLACAR}[name]

    monkeypatch.setattr(nucleo, "executar", executar)
    monkeypatch.setattr(regras, "executar", executar)
    monkeypatch.setattr(contexto, "executar", lambda name, args, ctx: {
        "situacao_plantio": SITUACAO, "placar_rotacoes": PLACAR, "solo_da_roca": {"culturas": []}}[name])
    return seen


def test_agent_runs_tools_and_adjusts_answer(fake_tools) -> None:
    client = FakeClient([
        _call("definir_roca", {"municipio": "Quixadá", "latitude": None, "longitude": None}),
        _call("situacao_plantio", {"cultura": "milho_sertanejo", "data": None}, "c2"),
        _message("**Arriscado.** Plantando agora, com 12 dias de atraso da chuva, a roça quebra em 5 de cada 10 anos."),
    ])
    sessao = Sessao(id="s")
    resp = Agente(client, today=date(2026, 3, 1)).responder(sessao, "posso plantar milho em quixadá?")

    assert resp.fonte == "agente"
    assert resp.ferramentas == ["definir_roca", "situacao_plantio"]
    assert "**" not in resp.texto and resp.texto.startswith("Arriscado.")
    assert "clima de exemplo" in resp.texto and resp.texto.endswith(CLOSING)
    assert sessao.local == LocalConversa("quixada_ce")
    assert [m["role"] for m in sessao.historico] == ["user", "assistant"]
    # a rodada seguinte recebe a saída da ferramenta e o raciocínio da anterior
    last_input = client.calls[-1]
    assert any(i.get("type") == "function_call_output" and i["call_id"] == "c2" for i in last_input)
    assert any(i.get("type") == "reasoning" for i in last_input)
    assert client.calls[0][0]["role"] == "developer" and "2026-03-01" in client.calls[0][0]["content"]


def test_greeting_has_no_closing(fake_tools) -> None:
    resp = Agente(FakeClient([_message("Oi! Mande o município ou a localização.")])).responder(Sessao("s"), "oi")
    assert resp.texto == "Oi! Mande o município ou a localização." and CLOSING not in resp.texto


def test_rule_break_asks_for_rewrite(fake_tools) -> None:
    sessao = Sessao("s", local=LocalConversa("quixada_ce"))
    client = FakeClient([
        _call("situacao_plantio", {"cultura": "milho_sertanejo", "data": None}),
        _message("Arriscado: 45% de chance de quebrar."),
        _message("Arriscado. A roça quebra em 5 de cada 10 anos."),
    ])
    resp = Agente(client).responder(sessao, "posso plantar milho?")
    assert resp.fonte == "agente" and "%" not in resp.texto
    assert "porcentagem" in resp.observacoes[0]
    assert client.calls[-1][-1]["role"] == "developer" and "Reescreva" in client.calls[-1][-1]["content"]


def test_persistent_rule_break_falls_back_to_rules(fake_tools) -> None:
    sessao = Sessao("s", local=LocalConversa("quixada_ce"))
    client = FakeClient([
        _call("situacao_plantio", {"cultura": "milho_sertanejo", "data": None}),
        _message("Pode plantar, a chuva firmou."),
        _message("Pode plantar sim."),
    ])
    resp = Agente(client).responder(sessao, "posso plantar milho?")
    assert resp.fonte == "regras"
    assert resp.texto.startswith("Milho: Arriscado.") and resp.texto.endswith(CLOSING)


def test_openai_down_answers_with_rules(fake_tools) -> None:
    sessao = Sessao("s")
    resp = Agente(DownClient()).responder(sessao, "qual roça aguenta mais em quixadá pro rebanho?")
    assert resp.fonte == "regras" and "sem crédito" in resp.observacoes[0]
    assert fake_tools[-1] == ("placar_rotacoes", {"horizonte_anos": 5, "prioridade": "forragem"})
    assert "Só Milho, dá quebra de safra em 2 de cada 10 anos" in resp.texto
    assert "Sorgo + Caupi + Palma, a quebra cai para 0 de cada 10 anos" in resp.texto
    assert "dados de exemplo" in resp.texto and sessao.local is not None


def test_rules_ask_location_and_help(fake_tools) -> None:
    resp = Agente(DownClient()).responder(Sessao("s"), "posso plantar milho?")
    assert "localização" in resp.texto and fake_tools == []
    assert "duas perguntas" in Agente(DownClient()).responder(Sessao("s"), "bom dia").texto


@pytest.mark.parametrize(("texto", "intencao", "cultura", "prioridade"), [
    ("Posso plantar mio agora?", "plantio", "milho_sertanejo", "equilibrio"),
    ("já dá pra semear feijão de corda?", "plantio", "feijao_caupi", "equilibrio"),
    ("posso plantar feijão comum?", "plantio", "feijao_comum", "equilibrio"),
    ("como está cenoura agora?", "plantio", "cenoura", "equilibrio"),
    ("e pimentão?", "plantio", "pimentao", "equilibrio"),
    ("como está o solo da roça?", "solo", None, "equilibrio"),
    ("qual roça aguenta mais pra criação", "placar", None, "forragem"),
    ("que rotação dá mais comida pra família", "placar", None, "graos"),
    ("qual plano dá mais dinheiro?", "placar", None, "renda"),
    ("bom dia", None, None, "equilibrio"),
])
def test_rules_understand(texto, intencao, cultura, prioridade) -> None:
    pedido = regras.entender(texto)
    assert (pedido.intencao, pedido.cultura, pedido.prioridade) == (intencao, cultura, prioridade)


def test_context_and_sessao_preserve_app_filters() -> None:
    sessao = Sessao(
        id="s",
        local=LocalConversa("quixada_ce"),
        soil_group="arenosa",
        cycle_code="21",
        cultura_selecionada="tomate",
        horizonte_anos=3,
        prioridade="renda",
        precisa_ter=["milho_sertanejo"],
        nao_pode_ter=["palma_forrageira"],
        culturas_atuais=["feijao_caupi"],
        fazenda_resumo={"area_total_ha": 12.0, "talhoes": []},
    )
    again = Sessao.from_dict(sessao.to_dict())
    assert again.horizonte_anos == 3 and again.prioridade == "renda" and again.cycle_code == "21"
    seen_args: list[tuple[str, dict]] = []

    def _rec(name, args, ctx):
        seen_args.append((name, dict(args)))
        return {"ok": True} if name != "placar_rotacoes" else {"ranking": [], "dados_de_exemplo": True}

    old = contexto.executar
    contexto.executar = _rec  # type: ignore[assignment]
    try:
        ctx = Agente.responder.__globals__["Contexto"](
            local=sessao.local,
            soil_group="arenosa",
            cycle_code="21",
            cultura_selecionada="tomate",
            horizonte_anos=3,
            prioridade="renda",
            precisa_ter=("milho_sertanejo",),
            nao_pode_ter=("palma_forrageira",),
            culturas_atuais=("feijao_caupi",),
            fazenda_resumo={"area_total_ha": 12.0, "talhoes": []},
        )
        res = contexto.dados_do_local(ctx)
        msg = contexto.mensagem(ctx, res)
    finally:
        contexto.executar = old
    assert ("placar_rotacoes", {"horizonte_anos": 3, "prioridade": "renda"}) in seen_args
    assert "3 anos, renda" in msg and "filtros_ativos" in msg


def test_guardas() -> None:
    results = [("situacao_plantio", SITUACAO)]
    ctx = "posso plantar? Hoje é 2026-03-01."
    assert guardas.problemas("Arriscado. Quebra em 5 de cada 10 anos, janela até 31/mar.", results, ctx) == []
    found = guardas.problemas("Pode plantar: 45% e 7 anos. A chuva já firmou.", results, ctx)
    assert len(found) == 4  # porcentagem, números 45 e 7, pode plantar, firmou
    assert guardas.problemas("A chuva não firmou ainda.", results, ctx) == []
    assert guardas.problemas("Forragem de 8.927 kg.", [("x", {"f": 8927})], "") == []
    assert guardas.limpar("# Título\n- **um** item\n2. outro") == "Título um item outro"
    closing = load_yaml_config("conversa")["fechamento"]
    doubled = guardas.ajustar(f"Arriscado. Confirme com o técnico antes de decidir. {closing}", results)
    assert doubled.count("Confirme com o técnico") == 1 and doubled.endswith(closing)


def test_sessao_store_roundtrip_and_expiry(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessaoStore(get_settings(tmp_path))
    s = store.carregar("whatsapp:+5588999990000")
    assert s.id == chave_hash("whatsapp:+5588999990000") and "5588" not in s.id
    s.local, s.simular = LocalConversa("sousa_pb"), date(2026, 3, 1)
    for i in range(6):
        s.lembrar(f"p{i}", f"r{i}")
    assert len(s.historico) == 8 and s.historico[0]["content"] == "p2"
    store.salvar(s)
    again = store.carregar("whatsapp:+5588999990000")
    assert again.local == s.local and again.simular == s.simular and again.historico == s.historico

    data = json.loads((store.folder / f"{s.id}.json").read_text(encoding="utf-8"))
    data["atualizada"] = (datetime.now() - timedelta(days=60)).isoformat()
    (store.folder / f"{s.id}.json").write_text(json.dumps(data), encoding="utf-8")
    old = store.carregar("whatsapp:+5588999990000")
    assert old.historico == [] and old.local == s.local
    store.apagar("whatsapp:+5588999990000")
    assert store.carregar("whatsapp:+5588999990000").local is None


def test_openai_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(OpenAIIndisponivel, match="não configurada"):
        OpenAIClient(api_key="").respond(instructions="", input_items=[], tools=[])

    def fake_post(url, **kw):
        assert kw["json"]["store"] is False
        return httpx.Response(429, json={"error": {"code": "insufficient_quota"}})

    monkeypatch.setattr(openai_api.httpx, "post", fake_post)
    with pytest.raises(OpenAIIndisponivel, match="insufficient_quota"):
        OpenAIClient(api_key="k").respond(instructions="", input_items=[], tools=[])

    def boom(url, **kw):
        raise httpx.ConnectError("rede fora")

    monkeypatch.setattr(openai_api.httpx, "post", boom)
    with pytest.raises(OpenAIIndisponivel, match="sem conexão"):
        OpenAIClient(api_key="k").respond(instructions="", input_items=[], tools=[])

    assert output_text({"output": [*_call("x", {}), *_message("oi"), *_message("tudo bem")]}) == "oi\ntudo bem"
