"""Ferramentas do agente: mesmo aviso e mesmo ranking da página Plantio, sempre em "X de cada 10"."""

from __future__ import annotations

import json
import textwrap
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from crop_optimizer.agente import local as local_mod
from crop_optimizer.agente.ferramentas import ESQUEMAS, PRIORIDADES, Contexto, de_10_texto, executar
from crop_optimizer.agente.local import LocalConversa, local_por_coordenada, local_por_municipio
from crop_optimizer.domain.roca import Roca
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, Place

_APP = textwrap.dedent(
    """
    from crop_optimizer.app.dashboard import plantio_page
    plantio_page()
    """
)


def _page_data(tmp_path, location_id: str, as_of: date, horizon: int, priority: str) -> dict:
    """Dados que a página Plantio entrega aos componentes (aviso por cultura e ranking)."""
    path = tmp_path / "plantio.py"
    path.write_text(_APP, encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=180)
    at.session_state["_guardado_municipio_exemplo"] = location_id
    at.session_state["_guardado_data_simulada"] = as_of
    at.session_state["_guardado_horizonte"] = horizon
    at.session_state["_guardado_prioridade"] = priority
    at.run()
    assert not at.exception
    comps = {c.proto.component_name: json.loads(c.proto.json) for c in at.get("bidi_component")}
    return {"culturas": comps["acaua_combo_cultura"]["items"], "ranking": comps["acaua_ranking_rotacoes"]["items"]}


def _of_10(text: str) -> int:
    return 0 if text.startswith("menos de 1") else int(text.split()[0])


@pytest.mark.parametrize(("location_id", "nome", "as_of", "horizon", "priority"), [
    ("quixada_ce", "Quixadá", date(2026, 3, 1), 5, "equilibrio"),
    ("petrolina_pe", "Petrolina", date(2026, 2, 10), 10, "graos"),
    ("irece_ba", "Irecê", date(2025, 12, 5), 1, "estabilidade"),
    ("sousa_pb", "Sousa", date(2026, 3, 10), 3, "renda"),
])
def test_tools_match_plantio_page(tmp_path, location_id: str, nome: str, as_of: date, horizon: int,
                                  priority: str) -> None:
    page = _page_data(tmp_path, location_id, as_of, horizon, PRIORIDADES[priority])

    ctx = Contexto(hoje=date.today())
    assert executar("definir_roca", {"municipio": nome}, ctx)["ok"]
    sit = executar("situacao_plantio", {"cultura": None, "data": as_of.isoformat()}, ctx)
    placar = executar("placar_rotacoes", {"horizonte_anos": horizon, "prioridade": priority,
                                          "data": as_of.isoformat()}, ctx)

    # aviso por cultura: mesma cultura, mesmo nível (na UI, "rega" usa badge "neutro")
    tool = {c["id"]: c["aviso"] for c in sit["culturas"]}
    assert [c["id"] for c in page["culturas"]] == list(tool)
    for item in page["culturas"]:
        tool_tone = "neutro" if tool[item["id"]]["nivel"] == "rega" else tool[item["id"]]["nivel"]
        assert tool_tone == item["tone"], item["id"]

    # ranking: mesma ordem e mesmos números
    assert [r["id"] for r in placar["ranking"]] == [r["id"] for r in page["ranking"]]
    for tool_r, page_r in zip(placar["ranking"], page["ranking"], strict=True):
        assert _of_10(tool_r["colhe"]) == page_r["aguenta"]
        assert page_r["risco"].endswith(f"em {_of_10(tool_r['risco_grave']['chance'])} de 10 cenários")
        assert page_r["graos"] == f"{tool_r['graos_kg_por_ha_ano']:,} kg/ha·ano".replace(",", ".")
        assert page_r["forragem"] == f"{tool_r['forragem_kg_por_ha_ano']:,} kg/ha·ano".replace(",", ".")
        assert page_r["renda"] == f"R$ {tool_r['renda_reais_por_ha_ano']:,}/ha·ano".replace(",", ".")


def test_tool_outputs_never_use_percent_for_chances() -> None:
    ctx = Contexto(hoje=date(2026, 3, 1))
    executar("definir_roca", {"municipio": "quixada"}, ctx)
    for name, args in [("situacao_plantio", {}), ("placar_rotacoes", {"horizonte_anos": 1})]:
        text = json.dumps(executar(name, args, ctx), ensure_ascii=False)
        assert "%" not in text, name
        assert "de cada 10" in text
    placar = executar("placar_rotacoes", {"horizonte_anos": 1}, ctx)
    assert placar["dados_de_exemplo"] is True and placar["aviso"].startswith("DADOS DE EXEMPLO")
    assert "quebra de safra no ano" in placar["ranking"][0]["risco_grave"]["o_que_e"]


def test_tools_need_location_and_validate_arguments() -> None:
    ctx = Contexto(hoje=date(2026, 3, 1))
    assert executar("situacao_plantio", {}, ctx)["erro"] == "local_desconhecido"
    assert executar("nao_existe", {}, ctx)["erro"].startswith("ferramenta desconhecida")
    assert executar("definir_roca", {"municipio": "Recife"}, ctx)["erro"] == "municipio_fora_da_lista"
    assert "erro" in executar("definir_roca", {}, ctx)
    executar("definir_roca", {"municipio": "Irecê"}, ctx)
    assert "cultura desconhecida" in executar("situacao_plantio", {"cultura": "soja"}, ctx)["erro"]
    assert "futuro" in executar("situacao_plantio", {"data": "2026-03-02"}, ctx)["erro"]
    assert "inválida" in executar("situacao_plantio", {"data": "01/03/2026"}, ctx)["erro"]
    assert "horizonte" in executar("placar_rotacoes", {"horizonte_anos": 4}, ctx)["erro"]
    assert "prioridade" in executar("placar_rotacoes", {"prioridade": "lucro"}, ctx)["erro"]
    assert "argumentos inválidos" in executar("solo_da_roca", {"x": 1}, ctx)["erro"]


def test_schemas_match_functions() -> None:
    names = {s["name"] for s in ESQUEMAS}
    assert names == {"definir_roca", "situacao_plantio", "placar_rotacoes", "solo_da_roca"}
    for schema in ESQUEMAS:
        params = schema["parameters"]
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"])  # formato estrito


def test_de_10_texto() -> None:
    assert de_10_texto(0.0) == "0 de cada 10"
    assert de_10_texto(0.03) == "menos de 1 de cada 10"
    assert de_10_texto(0.26) == "3 de cada 10"
    assert de_10_texto(1.4) == "10 de cada 10"


def test_local_por_municipio_accepts_spoken_names() -> None:
    assert local_por_municipio("quixada").exemplo_id == "quixada_ce"
    assert local_por_municipio("Irecê-BA").exemplo_id == "irece_ba"
    assert local_por_municipio("moro em sousa").exemplo_id == "sousa_pb"
    assert local_por_municipio("Recife") is None


def test_local_por_coordenada_uses_same_location_as_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_mod, "resolve_place", lambda lat, lon, s=None: Place("Quixeramobim", "CE", "2311405"))
    local = local_por_coordenada(-5.19912, -39.29271)
    assert local.exemplo_id == "quixada_ce" and not local.is_example
    assert local.nome == "Quixeramobim/CE" and 30 < local.distancia_exemplo_km < 50
    roca = Roca(-5.1991, -39.2927, "Quixeramobim", "CE", "2311405")
    assert local.location() == roca.to_location()
    assert LocalConversa.from_dict(local.to_dict()) == local

    def _fail(lat, lon, s=None):
        raise GeocodeUnavailable("rede fora")

    monkeypatch.setattr(local_mod, "resolve_place", _fail)
    unknown = local_por_coordenada(-5.2, -39.3)
    assert unknown.aviso == "rede fora" and "não identificado" in unknown.nome


def test_placar_rotacoes_respects_filters_and_current_crops() -> None:
    ctx = Contexto(
        local=LocalConversa("quixada_ce"),
        hoje=date(2026, 3, 1),
        horizonte_anos=3,
        prioridade="renda",
        precisa_ter=("milho_sertanejo",),
        nao_pode_ter=("palma_forrageira",),
        culturas_atuais=("feijao_caupi",),
    )
    placar = executar("placar_rotacoes", {}, ctx)
    assert placar["horizonte_anos"] == 3
    assert placar["prioridade"] == "renda"
    assert placar["filtros_aplicados"]["precisa_ter"] == ["Milho"]
    assert placar["filtros_aplicados"]["nao_pode_ter"] == ["Palma forrageira"]
    assert placar["filtros_aplicados"]["culturas_atuais"] == ["Feijão-caupi"]
    assert placar["jeito_de_hoje"] == "como_planta_hoje"
    assert len(placar["ranking"]) <= 6
    assert any(r["id"] == "como_planta_hoje" for r in placar["ranking"])

    conflict_ctx = Contexto(
        local=LocalConversa("quixada_ce"),
        hoje=date(2026, 3, 1),
        precisa_ter=("milho_sertanejo",),
        nao_pode_ter=("milho_sertanejo",),
    )
    conflict = executar("placar_rotacoes", {}, conflict_ctx)
    assert "aviso_restricoes" in conflict and conflict["combinacoes_que_cumprem"] == 0


def test_situacao_plantio_irrigated_and_zarc_filters() -> None:
    ctx = Contexto(
        local=LocalConversa("petrolina_pe"),
        hoje=date(2026, 3, 1),
        soil_group="arenosa",
        cycle_code="21",
        cultura_selecionada="tomate",
    )
    res = executar("situacao_plantio", {"cultura": "tomate"}, ctx)
    c = res["culturas"][0]
    assert c["manejo"] == "irrigado"
    assert c["aviso"]["nivel"] == "rega"
    assert c["aviso"]["palavra"] == "Só com rega"
    assert c["aviso"]["usa_clima_de_exemplo"] is False
    assert "quebra_de_safra_com_o_atraso_de_hoje" not in c
    assert "rega" in c["agua"]
    assert res["cultura_em_foco_no_app"] == "Tomate"
    assert res["filtros_zarc"]["ciclo"] == "21"


def test_solo_da_roca_includes_texture_and_fazenda() -> None:
    ctx = Contexto(
        local=LocalConversa("quixada_ce"),
        hoje=date(2026, 3, 1),
        fazenda_resumo={"area_total_ha": 10.0, "talhoes": [{"nome": "Talhão 1", "area_ha": 5.0}]},
    )
    solo = executar("solo_da_roca", {}, ctx)
    assert solo["textura"]
    assert solo["fazenda"]["area_total_ha"] == 10.0
