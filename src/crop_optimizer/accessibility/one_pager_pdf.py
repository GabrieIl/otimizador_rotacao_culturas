"""Gerador de PDF de 1 página (One-Pager): Ficha Técnica 'O Que Não Sabemos' para EMATER/Cooperativas."""

from __future__ import annotations

from datetime import date

import polars as pl
from fpdf import FPDF

from crop_optimizer.domain.models import (
    LocationSpec,
    SimulationConfig,
    StrategySimulationResult,
    TrafficLightLevel,
)

WHAT_WE_DONT_KNOW_ITEMS: list[str] = [
    "Microvariabilidade do solo na propriedade (manchas de salinidade, compactacao ou profundidade efetiva).",
    "Disponibilidade real de reserva hidrica local (cisterna-calçadao, barreiro trincheira ou poço artesiano).",
    "Pressao biologica pontual (lagarta-do-cartucho, cochonilha-do-carmim na palma ou qualidade da semente crioula).",
    "Tamanho exato do rebanho (UA/cabecas) e estoque atual de feno/silagem ja armazenado na fazenda.",
    "Custos logisticos e precos praticados na feira livre ou compra institucional (PAA/PNAE) da semana.",
]


def _latin1_safe(text: str) -> str:
    replacements = {
        "→": "->",
        "×": "x",
        "·": "-",
        "—": "-",
        "🟢": "[VERDE]",
        "🟡": "[AMARELO]",
        "🔴": "[VERMELHO]",
        "🌽": "[COMIDA]",
        "🌿": "[FORRAGEM]",
        "🛡️": "[ESCUDO]",
    }
    out = text
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out.encode("latin-1", errors="replace").decode("latin-1")


def generate_one_pager_pdf(
    location: LocationSpec,
    config: SimulationConfig,
    traffic_light: TrafficLightLevel,
    scoreboard: pl.DataFrame,
    results: list[StrategySimulationResult],
    reference_date: date | None = None,
) -> bytes:
    """
    Gera PDF A4 estritamente em 1 página (One-Pager) pronto para compartilhamento via WhatsApp
    entre agricultor, técnico da EMATER, ONG ou cooperativa.
    """
    ref_day = reference_date or date.today()
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # Faixa de cabeçalho
    pdf.set_fill_color(22, 101, 52)
    pdf.rect(0, 0, 210, 26, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_xy(10, 6)
    pdf.cell(190, 7, _latin1_safe("FICHA TECNICA - MOTOR ESTOCASTICO DE RESILIENCIA DO SERTAO"))
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_xy(10, 14)
    pdf.cell(
        190,
        6,
        _latin1_safe(
            f"Municipio: {location.name}-{location.state} ({location.biome}) | "
            f"Agricultor: {config.farmer_name} | Data: {ref_day.isoformat()}"
        ),
    )

    # Bloco 1: Contexto e Semáforo
    pdf.set_text_color(20, 20, 20)
    pdf.set_xy(10, 31)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(190, 6, _latin1_safe("1. Cenario Climatico & Semaforo Agricola (NASA CHIRPS/SMAP + ZARC)"))

    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_xy(10, 38)
    pdf.multi_cell(
        190,
        5,
        _latin1_safe(
            f"Simulacao de {config.n_scenarios:,} futuros possiveis em {config.horizon_years} anos "
            f"(atraso das chuvas: {config.safra_delay_days} dias | veranico simulado: {config.veranico_days} dias). "
            f"Status do Semaforo: [{traffic_light.value.upper()}] - {traffic_light.guidance}."
        ).replace(",", "."),
    )

    # Bloco 2: Placar de Sobrevivência & Biomassa
    pdf.set_xy(10, 54)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(190, 6, _latin1_safe("2. Placar de Sobrevivencia & Balanco de Biomassa (Comida x Forragem x Risco)"))

    # Cabeçalho da tabela
    pdf.set_xy(10, 62)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font("Helvetica", "B", 8.5)
    col_widths = [58, 28, 30, 26, 26, 22]
    headers = ["Rotacao", "Sobrevive/10", "2 Anos Perda", "Comida (kg/ha)", "Forragem (kg)", "VPL (R$/ha)"]
    for w, h in zip(col_widths, headers, strict=True):
        pdf.cell(w, 7, _latin1_safe(h), border=1, fill=True, align="C")
    pdf.ln()

    by_id = {r.strategy.strategy_id: r for r in results}
    pdf.set_font("Helvetica", "", 8.5)
    for row in scoreboard.to_dicts()[:4]:
        res = by_id[row["strategy_id"]]
        vals = [
            row["short_name"][:32],
            f"{row['survival_score_of_10']} / 10",
            f"{row['prob_two_consecutive_losses_pct']:.1f}%",
            f"{row['expected_food_kg_ha_year']:,.0f}".replace(",", "."),
            f"{row['expected_forage_kg_ha_year']:,.0f}".replace(",", "."),
            f"{res.expected_npv_brl_ha:,.0f}".replace(",", "."),
        ]
        pdf.set_x(10)
        for idx, (w, val) in enumerate(zip(col_widths, vals, strict=True)):
            pdf.cell(w, 7, _latin1_safe(val), border=1, align="L" if idx == 0 else "C")
        pdf.ln()

    # Bloco 3: Cadeia de Markov do Solo
    y_after_table = pdf.get_y() + 5
    pdf.set_xy(10, y_after_table)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(190, 6, _latin1_safe("3. Saude do Solo (Cadeia de Markov) & Economia com Insumos"))

    pdf.set_xy(10, y_after_table + 7)
    pdf.set_font("Helvetica", "", 9.0)
    best = min(results, key=lambda r: r.prob_two_consecutive_losses)
    worst = max(results, key=lambda r: r.prob_two_consecutive_losses)
    pdf.multi_cell(
        190,
        5,
        _latin1_safe(
            f"- Melhor escudo ({best.strategy.short_name or best.strategy.name}): "
            f"risco de 2 anos seguidos de perda total cai de {worst.prob_two_consecutive_losses*100:.1f}% "
            f"para {best.prob_two_consecutive_losses*100:.1f}%; "
            f"score final do solo {best.final_soil_score_mean:.2f}/4.0 e economia de R$ {best.total_fertilizer_savings_mean:,.0f}/ha."
        ).replace(",", "."),
    )

    # Bloco 4: Ficha O QUE NÃO SABEMOS (Honestidade Algorítmica)
    y_unknown = max(145.0, pdf.get_y() + 6)
    pdf.set_fill_color(254, 243, 199)
    pdf.set_draw_color(217, 119, 6)
    pdf.rect(10, y_unknown, 190, 92, style="DF")

    pdf.set_xy(14, y_unknown + 4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(146, 64, 14)
    pdf.cell(182, 6, _latin1_safe("4. O QUE NAO SABEMOS (Validacao Obrigatoria com Tecnico EMATER/ONG)"))

    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 9.0)
    cur_y = y_unknown + 12
    for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
        pdf.set_xy(14, cur_y)
        pdf.multi_cell(182, 5, _latin1_safe(f"{idx}. {item}"))
        cur_y = pdf.get_y() + 2

    # Rodapé
    pdf.set_xy(10, 278)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(
        190,
        5,
        _latin1_safe(
            "Documento de apoio a decisao (1 pagina) - Local Data Lakehouse DuckDB + Parquet | "
            "Validar com ZARC oficial e assistencia tecnica local."
        ),
        align="C",
    )

    return bytes(pdf.output())
