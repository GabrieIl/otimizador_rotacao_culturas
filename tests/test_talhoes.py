"""Talhões: cadastro da fazenda, rotações com restrições e calendário de cada talhão (Feature 9)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from crop_optimizer.analytics import talhoes as tl
from crop_optimizer.domain.crop_registry import sequeiro_ids
from crop_optimizer.domain.fazenda import Fazenda, Talhao, clear_fazenda, load_fazenda, save_fazenda
from crop_optimizer.engine.candidates import (
    CURRENT_ID,
    candidate_strategies,
    current_strategy,
    satisfies,
)
from crop_optimizer.engine.rain_onset import OnsetReference

# chuva firma, em mediana, 163 dias depois de 1º/set = 11/fev
REF = OnsetReference(9, 1991, 2020, [1991], [163], 163, 140, 180)
HOJE = date(2026, 11, 15)


def _fazenda() -> Fazenda:
    return Fazenda(10.0, [
        Talhao("t1", "Talhão 1", 4.0, "milho_sertanejo", date(2026, 3, 1)),
        Talhao("t2", "Talhão 2", 3.0),
        Talhao("t3", "Talhão 3", 2.0, "tomate", date(2026, 10, 20)),
        Talhao("t4", "Beira do rio", 1.0, "banana", date(2025, 6, 1)),
    ])


# --- cadastro ----------------------------------------------------------------------------------------------


def test_fazenda_salva_e_le_de_volta(tmp_path) -> None:
    from crop_optimizer.config import get_settings

    settings = get_settings(tmp_path)
    faz = _fazenda()
    save_fazenda("roca_x", faz, settings)
    back = load_fazenda("roca_x", settings)
    assert back is not None and back.talhoes == faz.talhoes and back.area_total_ha == 10.0
    clear_fazenda("roca_x", settings)
    assert load_fazenda("roca_x", settings) is None


def test_problemas_do_cadastro() -> None:
    assert _fazenda().problems() == []
    ruim = Fazenda(5.0, [Talhao("t1", "A", 4.0, "milho_sertanejo", None), Talhao("t2", "B", 2.0)])
    probs = " ".join(ruim.problems())
    assert "passa da área da fazenda" in probs and "precisa da data do plantio" in probs


# --- rotações com restrições ----------------------------------------------------------------------------------


def test_restricoes_montam_as_candidatas() -> None:
    todas = candidate_strategies()
    n = len(sequeiro_ids())
    assert len(todas) == n + n * (n - 1) // 2 + n * (n - 1) * (n - 2) // 6
    com_milho_sem_sorgo = candidate_strategies(["milho_sertanejo"], ["sorgo_forrageiro"])
    assert com_milho_sem_sorgo and all(satisfies(s, ["milho_sertanejo"], ["sorgo_forrageiro"])
                                       for s in com_milho_sem_sorgo)
    assert candidate_strategies(["milho_sertanejo"], ["milho_sertanejo"]) == []
    # combinação igual a uma rotação de exemplo mantém o nome dela
    assert any(s.short_name == "Milho + Caupi" for s in candidate_strategies(["milho_sertanejo", "feijao_caupi"]))


def test_rotacao_de_hoje_vem_dos_talhoes() -> None:
    hoje = current_strategy(["milho_sertanejo", "tomate", "banana"])
    assert hoje.strategy_id == CURRENT_ID and hoje.annual_sequence == ["milho_sertanejo"]  # só sequeiro
    assert current_strategy([]).annual_sequence == ["milho_sertanejo"]


# --- calendário --------------------------------------------------------------------------------------------


def test_safras_na_data_em_que_a_chuva_firma() -> None:
    assert tl.season_starts(REF, HOJE, 2)[:2] == [date(2027, 2, 11), date(2028, 2, 11)]


def test_modo_hoje_repete_a_cultura_de_cada_talhao() -> None:
    plan = tl.plan_farm(_fazenda(), "hoje", [], REF, HOJE, 2)
    milho = [c for c in plan["t1"] if c.inicio > HOJE]
    assert milho and all(c.crop_id == "milho_sertanejo" and c.inicio.month == 2 for c in milho)
    assert plan["t2"] == []  # sem cultura: nada a repetir
    tomate = plan["t3"]
    assert tomate[0].inicio == date(2026, 10, 20) and len(tomate) > 2  # com rega: replanta depois da colheita
    assert plan["t4"] == [tl.Cultivo("banana", date(2025, 6, 1), None, "perene")]


def test_modo_ranking_gira_as_anuais_e_fixa_as_perenes() -> None:
    plan = tl.plan_farm(_fazenda(), "ranking", ["feijao_caupi", "sorgo_forrageiro", "palma_forrageira"], REF, HOJE, 3)
    t1 = [c.crop_id for c in plan["t1"] if c.origem == "plano"]
    t2 = [c.crop_id for c in plan["t2"] if c.origem == "plano"]
    assert t1[:2] == ["feijao_caupi", "sorgo_forrageiro"] and t2[:2] == ["sorgo_forrageiro", "feijao_caupi"]
    # palma (perene) vai para o menor talhão livre; a banana plantada fica onde está
    assert [c.crop_id for c in plan["t3"]] == ["tomate", "palma_forrageira"]
    assert plan["t3"][0].origem == "hoje" and plan["t3"][1].fim is None
    assert [c.crop_id for c in plan["t4"]] == ["banana"]


def test_rotacao_so_de_perenes_reparte_os_talhoes() -> None:
    places, annuals = tl.layout(Fazenda(4, [Talhao(f"t{i}", str(i), 1.0) for i in range(4)]),
                                ["palma_forrageira", "capim_buffel"])
    assert annuals == [] and sorted(p[1] for p in places.values()) == ["capim_buffel"] * 2 + ["palma_forrageira"] * 2


def test_calendario_marca_plantio_e_colheita() -> None:
    plan = tl.plan_farm(_fazenda(), "ranking", ["feijao_caupi", "sorgo_forrageiro"], REF, HOJE, 2)
    grid = tl.month_grid(plan["t2"], HOJE, 2)
    assert [r["ano"] for r in grid] == [2026, 2027, 2028]
    fev27 = grid[1]["meses"][1]["itens"]
    assert fev27 == [{"id": "sorgo_forrageiro", "estado": "plantio", "origem": "plano"}]
    states = [m["itens"][0]["estado"] for m in grid[1]["meses"] if m["itens"]]
    assert states[0] == "plantio" and states[-1] == "colheita" and "cresce" in states
    assert grid[0]["meses"][10]["hoje"] and grid[0]["meses"][9]["passado"]


def test_cultura_de_hoje_ja_colhida_aparece_no_ano() -> None:
    plan = tl.plan_farm(_fazenda(), "ranking", ["feijao_caupi"], REF, HOJE, 1)
    assert plan["t1"][0] == tl.Cultivo("milho_sertanejo", date(2026, 3, 1),
                                        date(2026, 3, 1) + timedelta(days=125), "hoje")
    assert tl.crop_now(plan["t1"], HOJE) == ("feijao_caupi", "próxima")


@pytest.mark.parametrize("areas", [[4, 3, 2, 1], [1], [5, 5], [10, 1, 1, 1, 1, 1, 1]])
def test_treemap_proporcional(areas: list[float]) -> None:
    rects = tl.treemap(areas)
    total = sum(areas)
    for a, (x, y, w, h) in zip(areas, rects, strict=True):
        assert w * h == pytest.approx(100 * 56 * a / total, rel=1e-6)
        assert 0 <= x <= 100 and 0 <= y <= 56 and x + w <= 100.0001 and y + h <= 56.0001
