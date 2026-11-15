"""Recomendação "o que plantar hoje": ordem explícita, por finalidade, sem culturas a evitar na ordem."""

from __future__ import annotations

from datetime import date

from crop_optimizer.agente.ferramentas import Contexto, executar
from crop_optimizer.agente.recomendacao import Opcao, recomendar, serve_para

HOJE = date(2026, 1, 5)


def _op(crop_id: str, nivel: str, palavra: str, quebra: float, janela: str | None = "aberta",
        abre: date | None = None, aguenta: int | None = 10, solo: float = 60.0) -> Opcao:
    return Opcao(crop_id, crop_id.split("_")[0].capitalize(), nivel, palavra, f"motivo de {crop_id}",
                 round(quebra / 10), quebra, janela, abre, date(2026, 3, 31), aguenta, 12, solo, "Bom")


def test_serve_para() -> None:
    assert serve_para("milho_sertanejo") == ["graos"]
    assert serve_para("feijao_caupi") == ["graos"]
    assert serve_para("sorgo_forrageiro") == ["graos", "forragem"]
    assert serve_para("palma_forrageira") == ["forragem"]
    assert serve_para("capim_buffel") == ["forragem"]


def test_order_follows_the_criterion() -> None:
    opcoes = [
        _op("milho_sertanejo", "amarelo", "Arriscado", 42.0),
        _op("feijao_caupi", "verde", "Pode plantar", 12.0),
        _op("sorgo_forrageiro", "verde", "Pode plantar", 3.0),
        _op("palma_forrageira", "verde", "Pode plantar", 0.0, janela=None, aguenta=None),
        _op("capim_buffel", "vermelho", "Não plante", 0.0),
    ]
    rec = recomendar(opcoes, HOJE)
    graos = [o["id"] for o in rec["por_finalidade"]["graos"]["ordem"]]
    assert graos == ["sorgo_forrageiro", "feijao_caupi", "milho_sertanejo"]  # pode plantar e menor quebra primeiro
    assert rec["por_finalidade"]["graos"]["o_que_fazer_hoje"] == "pode plantar sorgo hoje"
    forragem = [o["id"] for o in rec["por_finalidade"]["forragem"]["ordem"]]
    assert forragem == ["palma_forrageira", "sorgo_forrageiro"]  # capim (Não plante) fica fora da ordem
    assert rec["evitar"] == [{"cultura": "Capim", "aviso": "Não plante", "motivo": "motivo de capim_buffel"}]
    assert rec["o_que_fazer_hoje"].startswith("Para grãos, pode plantar sorgo hoje; para forragem do rebanho")
    assert rec["criterio"].startswith("aviso de hoje")


def test_waiting_prefers_the_window_that_opens_first() -> None:
    opcoes = [
        _op("milho_sertanejo", "espera", "Espere a chuva firmar", 20.0, "ainda_nao_abriu", date(2026, 2, 11)),
        _op("feijao_caupi", "espera", "Espere a chuva firmar", 25.0, "ainda_nao_abriu", date(2026, 1, 21)),
    ]
    rec = recomendar(opcoes, HOJE, finalidade="graos")
    assert list(rec["por_finalidade"]) == ["graos"]
    assert [o["id"] for o in rec["por_finalidade"]["graos"]["ordem"]] == ["feijao_caupi", "milho_sertanejo"]
    assert rec["o_que_fazer_hoje"] == "Para grãos, espere a chuva firmar; quando firmar, a primeira opção é feijao."
    window = [_op("feijao_caupi", "espera", "Espere a janela abrir", 5.0, "ainda_nao_abriu", date(2026, 1, 21))]
    assert "a primeira janela oficial a abrir é a de feijao, em 21/jan" in recomendar(window, HOJE, "graos")["o_que_fazer_hoje"]


def test_water_and_soil_break_ties() -> None:
    curta = _op("feijao_caupi", "verde", "Pode plantar", 0.0, aguenta=5)
    longa = _op("milho_sertanejo", "verde", "Pode plantar", 0.0, aguenta=15)
    assert recomendar([curta, longa], HOJE, "graos")["por_finalidade"]["graos"]["ordem"][0]["id"] == "milho_sertanejo"
    solo_bom = _op("feijao_caupi", "verde", "Pode plantar", 0.0, solo=80.0)
    solo_ruim = _op("milho_sertanejo", "verde", "Pode plantar", 0.0, solo=40.0)
    assert recomendar([solo_ruim, solo_bom], HOJE, "graos")["por_finalidade"]["graos"]["ordem"][0]["id"] == "feijao_caupi"


def test_tool_adds_recommendation_only_without_crop() -> None:
    ctx = Contexto(hoje=date(2026, 3, 1))
    executar("definir_roca", {"municipio": "quixada"}, ctx)
    todas = executar("situacao_plantio", {}, ctx)
    assert set(todas["recomendacao"]["por_finalidade"]) == {"graos", "forragem"}
    assert all("serve_para" in c for c in todas["culturas"])
    uma = executar("situacao_plantio", {"cultura": "milho_sertanejo"}, ctx)
    assert "recomendacao" not in uma
    gado = executar("situacao_plantio", {"finalidade": "forragem"}, ctx)
    assert list(gado["recomendacao"]["por_finalidade"]) == ["forragem"]
    assert "finalidade" in executar("situacao_plantio", {"finalidade": "lucro"}, ctx)["erro"]
