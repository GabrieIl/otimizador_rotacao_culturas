"""Gráficos Plotly do Acauã, com as cores e fontes da marca (app/theme.py)."""

from __future__ import annotations

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import polars as pl

from crop_optimizer.app.theme import COLORS, plotly_layout


def plot_planting_window_heatmap(df_matrix: pl.DataFrame) -> go.Figure:
    """Visão 1: Matriz de Atraso das Chuvas convertida em Semáforo Agrícola (Verde/Amarelo/Vermelho)."""
    pdf = df_matrix.to_pandas()
    order = (
        df_matrix.select(["delay_days", "delay_label"])
        .unique()
        .sort("delay_days")["delay_label"]
        .to_list()
    )
    pivot_val = pdf.pivot(index="delay_label", columns="crop_name", values="failure_prob_pct").reindex(order)
    pivot_txt = pdf.pivot(index="delay_label", columns="crop_name", values="cell_display").reindex(order)

    # Escala discreta alinhada ao Semáforo: <25% Verde, 25-55% Amarelo, >=55% Vermelho
    # tons claros das cores do semáforo (texto em petróleo legível em todas as células)
    verde, amarelo, vermelho = "#BFD6C7", "#F1DDB0", "#E6BDB8"
    colorscale = [
        [0.0, verde],
        [0.249, verde],
        [0.25, amarelo],
        [0.549, amarelo],
        [0.55, vermelho],
        [1.0, vermelho],
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot_val.values,
            x=list(pivot_val.columns),
            y=list(pivot_val.index),
            text=pivot_txt.values,
            texttemplate="%{text}",
            textfont=dict(color=COLORS.petroleo, size=12),
            xgap=3,
            ygap=3,
            colorscale=colorscale,
            zmin=0,
            zmax=100,
            colorbar=dict(title="Risco (%)", tickvals=[12, 40, 78], ticktext=["Verde", "Amarelo", "Vermelho"]),
            hovertemplate="Atraso: %{y}<br>Cultura: %{x}<br>Risco de quebra: %{z:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Se a chuva atrasar, quanto arrisca cada cultura",
        xaxis_title="",
        yaxis_title="Atraso da chuva",
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return plotly_layout(fig, height=430)


def plot_survival_scoreboard(df_scoreboard: pl.DataFrame) -> go.Figure:
    """Visão 2: Placar de Sobrevivência ('Em quantos de 10 anos você sobrevive')."""
    pdf = df_scoreboard.to_pandas()
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=pdf["short_name"],
            x=pdf["survival_score_of_10"],
            name="Anos com Lavoura & Rebanho Salvos (em 10)",
            orientation="h",
            marker_color=COLORS.verde,
            text=[f"{v}/10 salvos" for v in pdf["survival_score_of_10"]],
            textposition="inside",
        )
    )
    fig.add_trace(
        go.Bar(
            y=pdf["short_name"],
            x=pdf["loss_years_of_10"],
            name="Anos de Perda Severa (em 10)",
            orientation="h",
            marker_color=COLORS.vermelho,
            text=[f"{v}/10 perda" if v > 0 else "" for v in pdf["loss_years_of_10"]],
            textposition="inside",
        )
    )
    fig.update_layout(
        barmode="stack",
        title="Em quantos de cada 10 anos a roça aguenta",
        xaxis=dict(title="Anos em 10", range=[0, 10], dtick=1),
        yaxis_title="",
        legend=dict(orientation="h", y=-0.22),
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return plotly_layout(fig, height=340)


def plot_balance_scale_bars(df_balance: pl.DataFrame) -> go.Figure:
    """Visão 3: Balança Comida x Forragem x Escudo."""
    pdf = df_balance.to_pandas()
    fig = px.bar(
        pdf,
        x="score",
        y="strategy_name",
        color="pillar",
        barmode="group",
        orientation="h",
        text="raw_label",
        color_discrete_map={
            "Comida (Grão)": COLORS.ocre,
            "Forragem (Rebanho)": COLORS.verde,
            "Escudo (Anti-Colapso)": COLORS.petroleo,
        },
        labels={"score": "Índice da Balança (0 a 100)", "strategy_name": "Rotação", "pillar": "Pilar"},
        title="Comida, forragem e escudo de cada rotação",
    )
    fig.update_layout(xaxis=dict(range=[0, 115]), legend=dict(orientation="h", y=-0.22), margin=dict(l=20, r=20, t=55, b=20))
    return plotly_layout(fig, height=400)


def plot_nutrient_dynamics(
    df_nutrients: pl.DataFrame,
    metric: str = "nitrogen_mean_kg_ha",
) -> go.Figure:
    """Curva de Dinâmica de Nutrientes do solo (Cadeia de Markov)."""
    pdf = df_nutrients.to_pandas()
    titles = {
        "nitrogen_mean_kg_ha": ("Dinâmica de Nitrogênio Disponível no Solo (kg N/ha)", "Nitrogênio (kg/ha)"),
        "om_mean_pct": ("Evolução da Matéria Orgânica do Solo (%)", "Matéria Orgânica (%)"),
        "cum_fertilizer_savings_brl_ha": ("Economia Acumulada com Insumos Nitrogenados (R$/ha)", "Economia Acumulada (R$/ha)"),
    }
    title, y_label = titles.get(metric, ("Dinâmica do Solo", metric))

    fig = px.line(
        pdf,
        x="step_index",
        y=metric,
        color="strategy_name",
        markers=True,
        hover_data=["step_label", "nitrogen_mean_kg_ha", "om_mean_pct", "cum_fertilizer_savings_brl_ha"],
        labels={"step_index": "Ciclo Sazonal", metric: y_label, "strategy_name": "Estratégia"},
        title=title,
    )
    fig.update_layout(legend=dict(orientation="h", y=-0.22), margin=dict(l=20, r=20, t=55, b=20))
    return plotly_layout(fig, height=410)


def plot_pareto_frontier(
    df_pareto: pl.DataFrame, risk_col: str = "prob_two_consecutive_losses_pct", horizon_years: int = 5
) -> go.Figure:
    """Gráfico técnico: Risco de 2 Anos Seguidos de Perda vs Produção/VPL."""
    pdf = df_pareto.to_pandas()
    y_col = "expected_food_kg_ha_year" if risk_col == "prob_two_consecutive_losses_pct" else "expected_npv_brl_ha"
    y_title = "Comida Esperada (kg grão/ha·ano)" if y_col == "expected_food_kg_ha_year" else "VPL Esperado (R$/ha)"
    x_title = (
        ("Probabilidade de 2 Anos Seguidos de Perda Total (%)" if horizon_years >= 2 else "Probabilidade de Perder a Safra no Ano (%)")
        if risk_col == "prob_two_consecutive_losses_pct"
        else "Risco Financeiro — Desvio Padrão (R$/ha)"
    )

    fig = go.Figure()
    non_pareto = pdf[~pdf["is_pareto_optimal"]]
    pareto = pdf[pdf["is_pareto_optimal"]].sort_values(risk_col)

    if not non_pareto.empty:
        fig.add_trace(
            go.Scatter(
                x=non_pareto[risk_col],
                y=non_pareto[y_col],
                mode="markers+text",
                text=non_pareto["short_name"],
                textposition="bottom center",
                marker=dict(size=13, color=COLORS.linha, line=dict(width=1, color=COLORS.texto_suave)),
                name="Estratégias Dominadas",
            )
        )

    if not pareto.empty:
        fig.add_trace(
            go.Scatter(
                x=pareto[risk_col],
                y=pareto[y_col],
                mode="lines+markers+text",
                text=pareto["short_name"],
                textposition="top center",
                line=dict(color=COLORS.terracota, width=2.5, dash="dash"),
                marker=dict(size=16, color=COLORS.terracota, symbol="square", line=dict(width=2, color="#ffffff")),
                name="Fronteira Ótima (Pareto)",
            )
        )

    fig.update_layout(
        title="Fronteira técnica: risco x comida (para o técnico)",
        xaxis_title=x_title,
        yaxis_title=y_title,
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return plotly_layout(fig, height=430)


def plot_rotation_years(result, family_target: float, herd_target: float) -> go.Figure:
    """Comida e forragem por ano de UMA rotação: mediana e faixa (10% piores a 10% melhores cenários)."""
    from plotly.subplots import make_subplots

    years = list(range(1, result.annual_food_kg_ha.shape[1] + 1))
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Comida (kg de grão por ha)", "Forragem (kg por ha)"))
    for col, arr, target, color, name in (
        (1, result.annual_food_kg_ha, family_target, COLORS.ocre, "comida"),
        (2, result.annual_forage_kg_ha, herd_target, COLORS.verde, "forragem"),
    ):
        p10, p50, p90 = (np.percentile(arr, q, axis=0) for q in (10, 50, 90))
        fig.add_trace(go.Scatter(x=years + years[::-1], y=list(p90) + list(p10[::-1]), fill="toself", mode="lines",
                                 fillcolor="rgba(22,48,55,0.10)", line=dict(width=0), hoverinfo="skip",
                                 showlegend=False), row=1, col=col)
        fig.add_trace(go.Scatter(x=years, y=p50, mode="lines+markers", line=dict(color=color, width=3),
                                 name=f"{name} (cenário do meio)", showlegend=False), row=1, col=col)
        fig.add_hline(y=target, line=dict(color=COLORS.vermelho, dash="dash", width=1.5), row=1, col=col,
                      annotation_text="o que a família precisa" if col == 1 else "o que o rebanho precisa",
                      annotation_font_size=11, annotation_font_color=COLORS.vermelho)
    fig.update_xaxes(title_text="ano", dtick=1)
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return plotly_layout(fig, height=340)


def plot_rotation_soil(df_nutrients: pl.DataFrame, strategy_name: str) -> go.Figure:
    """Matéria orgânica do solo ao longo dos ciclos, para uma rotação."""
    pdf = df_nutrients.filter(pl.col("strategy_name") == strategy_name).to_pandas()
    fig = go.Figure(go.Scatter(x=pdf["step_index"], y=pdf["om_mean_pct"], mode="lines+markers",
                               line=dict(color=COLORS.terracota, width=3), text=pdf["step_label"],
                               hovertemplate="%{text}<br>matéria orgânica: %{y:.2f}%<extra></extra>"))
    fig.update_layout(title="Matéria orgânica do solo com esta rotação", xaxis_title="ciclo",
                      yaxis_title="matéria orgânica (%)", margin=dict(l=20, r=20, t=55, b=20))
    return plotly_layout(fig, height=320)
