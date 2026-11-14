"""Gráficos Plotly reutilizáveis para o Conselheiro do Sertão e Back-office EMATER."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import polars as pl


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
    colorscale = [
        [0.0, "#16a34a"],
        [0.249, "#22c55e"],
        [0.25, "#eab308"],
        [0.549, "#facc15"],
        [0.55, "#dc2626"],
        [1.0, "#991b1b"],
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot_val.values,
            x=list(pivot_val.columns),
            y=list(pivot_val.index),
            text=pivot_txt.values,
            texttemplate="%{text}",
            colorscale=colorscale,
            zmin=0,
            zmax=100,
            colorbar=dict(title="Risco (%)", tickvals=[12, 40, 78], ticktext=["Verde", "Amarelo", "Vermelho"]),
            hovertemplate="Atraso: %{y}<br>Cultura: %{x}<br>Risco de quebra: %{z:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Semáforo Agrícola — Impacto do Atraso das Chuvas e Veranicos",
        xaxis_title="Cultura / Opção de Plantio",
        yaxis_title="Atraso no Início das Águas",
        height=430,
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return fig


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
            marker_color="#16a34a",
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
            marker_color="#dc2626",
            text=[f"{v}/10 perda" if v > 0 else "" for v in pdf["loss_years_of_10"]],
            textposition="inside",
        )
    )
    fig.update_layout(
        barmode="stack",
        title="Placar de Sobrevivência em 10 Anos (Simulação de 10.000 Futuros)",
        xaxis=dict(title="Anos em 10", range=[0, 10], dtick=1),
        yaxis_title="",
        height=340,
        legend=dict(orientation="h", y=-0.22),
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return fig


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
            "Comida (Grão)": "#f59e0b",
            "Forragem (Rebanho)": "#16a34a",
            "Escudo (Anti-Colapso)": "#2563eb",
        },
        labels={"score": "Índice da Balança (0 a 100)", "strategy_name": "Rotação", "pillar": "Pilar"},
        title="Balança: Comida × Forragem do Rebanho × Escudo Climático",
    )
    fig.update_layout(height=400, xaxis=dict(range=[0, 115]), legend=dict(orientation="h", y=-0.22), margin=dict(l=20, r=20, t=55, b=20))
    return fig


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
    fig.update_layout(height=410, legend=dict(orientation="h", y=-0.22), margin=dict(l=20, r=20, t=55, b=20))
    return fig


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
                marker=dict(size=13, color="#94a3b8", line=dict(width=1, color="#475569")),
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
                line=dict(color="#16a34a", width=2.5, dash="dash"),
                marker=dict(size=16, color="#15803d", symbol="diamond", line=dict(width=2, color="#ffffff")),
                name="Fronteira Ótima (Pareto)",
            )
        )

    fig.update_layout(
        title="Fronteira Técnica de Resiliência (EMATER / Cooperativas)",
        xaxis_title=x_title,
        yaxis_title=y_title,
        height=430,
        margin=dict(l=20, r=20, t=55, b=20),
    )
    return fig
