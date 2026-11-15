"""Gerador de PDF de 1 página (One-Pager): Ficha Técnica 'O Que Não Sabemos' para EMATER/Cooperativas."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from fpdf import FPDF

from crop_optimizer.analytics.soil_suitability import TEXTURE_LABELS, texture_class
from crop_optimizer.analytics.views import loss_risk_label
from crop_optimizer.domain.models import (
    LocationSpec,
    SimulationConfig,
    StrategySimulationResult,
    TrafficLightLevel,
)
from crop_optimizer.domain.presets import crop_map

if TYPE_CHECKING:
    from crop_optimizer.analytics.rain_delay import CropWindowStatus
    from crop_optimizer.domain.soil_profile import SoilProfile

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
    }
    out = text
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out.encode("latin-1", errors="replace").decode("latin-1")


def _format_soil_summary(soil_profile: SoilProfile | None) -> str:
    if soil_profile is None:
        return "Solo: referencia regional do semiarido."
    tex = TEXTURE_LABELS.get(
        texture_class(soil_profile.get("areia_pct"), soil_profile.get("argila_pct")),
        "media",
    )
    mo = soil_profile.get("mo_pct")
    ph = soil_profile.get("ph_h2o")
    slope = soil_profile.get("declividade_pct")
    field_count = sum(1 for v in soil_profile.values.values() if v.source == "campo")
    ref_count = sum(1 for v in soil_profile.values.values() if v.source == "referencia")
    src = (
        f"com {field_count} dado(s) de analise de campo"
        if field_count
        else f"satelite/mapa ({ref_count} assumido(s) por referencia)"
    )
    return (
        f"Solo do ponto: textura {tex}, argila {soil_profile.get('argila_pct'):.0f}%, "
        f"MO {mo:.2f}%, pH {ph:.1f}, decliv. {slope:.1f}% ({src})."
    )


def _format_zarc_summary(
    crop_windows: list[CropWindowStatus] | None,
    zarc_safra: str | None,
    zarc_error: str | None,
) -> str:
    if zarc_error:
        return f"ZARC ({zarc_safra or 'MAPA'}): indisponivel ({zarc_error[:75]})."
    if not crop_windows:
        return "ZARC: consulte a janela municipal atualizada antes do plantio."
    crops = crop_map()
    parts: list[str] = []
    for cw in crop_windows[:3]:
        cname = crops[cw.crop_id].name if cw.crop_id in crops else cw.crop_id
        if cw.window is None:
            parts.append(f"{cname}: sem indicacao")
        else:
            parts.append(f"{cname}: {cw.phrase.lower()}")
    prefix = f"ZARC {zarc_safra}" if zarc_safra else "ZARC"
    return f"{prefix}: " + " | ".join(parts) + "."


def generate_one_pager_pdf(
    location: LocationSpec,
    config: SimulationConfig,
    traffic_light: TrafficLightLevel,
    scoreboard: pl.DataFrame,
    results: list[StrategySimulationResult],
    reference_date: date | None = None,
    *,
    soil_profile: SoilProfile | None = None,
    crop_windows: list[CropWindowStatus] | None = None,
    zarc_safra: str | None = None,
    zarc_error: str | None = None,
    rain_source_note: str | None = None,
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
    pdf.set_xy(10, 5)
    pdf.cell(190, 7, _latin1_safe("FICHA TECNICA - MOTOR ESTOCASTICO DE RESILIENCIA DO SERTAO"))
    pdf.set_font("Helvetica", "", 9.0)
    pdf.set_xy(10, 13)
    place_txt = f"{location.name}-{location.state}" if location.state else location.name
    pdf.cell(
        190,
        5,
        _latin1_safe(
            f"Local: {place_txt} ({location.latitude:.4f}, {location.longitude:.4f}) | "
            + (f"Agricultor: {config.farmer_name} | " if config.farmer_name else "")
            + f"Horizonte: {config.horizon_years} ano(s) | Data: {ref_day.isoformat()}"
        ),
    )
    if location.ibge_code:
        pdf.set_xy(10, 18.5)
        pdf.set_font("Helvetica", "", 8.0)
        pdf.cell(190, 5, _latin1_safe(f"Codigo IBGE: {location.ibge_code} | Bioma: {location.biome}"))

    # Bloco 1: Contexto e Semáforo
    pdf.set_text_color(20, 20, 20)
    pdf.set_xy(10, 29)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(190, 6, _latin1_safe("1. Cenario Climatico & Semaforo Agricola (NASA POWER + ZARC)"))

    pdf.set_font("Helvetica", "", 9.0)
    pdf.set_xy(10, 35.5)
    extra_rain = f" {rain_source_note}" if rain_source_note else ""
    pdf.multi_cell(
        190,
        4.6,
        _latin1_safe(
            f"Simulacao de {config.n_scenarios:,} futuros possiveis em {config.horizon_years} anos "
            f"(atraso das chuvas: {config.safra_delay_days} dias | veranico: {config.veranico_days} dias)."
            f"{extra_rain} Status do Semaforo: [{traffic_light.value.upper()}] - {traffic_light.guidance}."
        ).replace(",", "."),
    )

    # Bloco 2: Placar de Sobrevivência & Biomassa
    y_block2 = max(49.0, pdf.get_y() + 2.5)
    pdf.set_xy(10, y_block2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(190, 6, _latin1_safe("2. Placar de Sobrevivencia & Balanco de Biomassa (Comida x Forragem x Risco)"))

    # Cabeçalho da tabela
    pdf.set_xy(10, y_block2 + 6.5)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font("Helvetica", "B", 8.5)
    col_widths = [58, 28, 30, 26, 26, 22]
    risk_header = "2 Anos Perda" if config.horizon_years >= 2 else "Perda no ano"
    headers = ["Rotacao", "Sobrevive/10", risk_header, "Comida (kg/ha)", "Forragem (kg)", "VPL (R$/ha)"]
    for w, h in zip(col_widths, headers, strict=True):
        pdf.cell(w, 6, _latin1_safe(h), border=1, fill=True, align="C")
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
            pdf.cell(w, 6, _latin1_safe(val), border=1, align="L" if idx == 0 else "C")
        pdf.ln()

    # Bloco 3: Saúde do Solo, Ponto & Janela Oficial ZARC
    y_after_table = pdf.get_y() + 3.5
    pdf.set_xy(10, y_after_table)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(190, 6, _latin1_safe("3. Solo da Roca, Saude (Markov) & Janela Oficial ZARC"))

    pdf.set_xy(10, y_after_table + 6.5)
    pdf.set_font("Helvetica", "", 8.8)
    best = min(results, key=lambda r: r.prob_two_consecutive_losses)
    worst = max(results, key=lambda r: r.prob_two_consecutive_losses)
    soil_line = _format_soil_summary(soil_profile)
    zarc_line = _format_zarc_summary(crop_windows, zarc_safra, zarc_error)
    pdf.multi_cell(
        190,
        4.5,
        _latin1_safe(
            f"- Melhor escudo ({best.strategy.short_name or best.strategy.name}): "
            f"{loss_risk_label(config.horizon_years)} cai de {worst.prob_two_consecutive_losses*100:.1f}% "
            f"para {best.prob_two_consecutive_losses*100:.1f}%; score do solo {best.final_soil_score_mean:.2f}/4.0, "
            f"economia de R$ {best.total_fertilizer_savings_mean:,.0f}/ha.\n"
            f"- {soil_line}\n"
            f"- {zarc_line}"
        ).replace(",", "."),
    )

    # Bloco 4: Ficha O QUE NÃO SABEMOS (Honestidade Algorítmica)
    y_unknown = max(145.0, pdf.get_y() + 4.0)
    box_h = min(90.0, 274.0 - y_unknown)
    pdf.set_fill_color(254, 243, 199)
    pdf.set_draw_color(217, 119, 6)
    pdf.rect(10, y_unknown, 190, box_h, style="DF")

    pdf.set_xy(14, y_unknown + 3.5)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(146, 64, 14)
    pdf.cell(182, 5.5, _latin1_safe("4. O QUE NAO SABEMOS (Validacao Obrigatoria com Tecnico EMATER/ONG)"))

    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", "", 8.6)
    cur_y = y_unknown + 10.5
    for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
        pdf.set_xy(14, cur_y)
        pdf.multi_cell(182, 4.4, _latin1_safe(f"{idx}. {item}"))
        cur_y = pdf.get_y() + 1.5

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
