"""Aplicação Web Interativa (Streamlit + Plotly) — Motor Estocástico de Resiliência do Sertão."""

from __future__ import annotations

import streamlit as st

from crop_optimizer.accessibility import (
    WHAT_WE_DONT_KNOW_ITEMS,
    TwilioWhatsAppClient,
    build_whatsapp_summary_message,
    compose_radio_script,
    create_tts_provider,
    generate_one_pager_pdf,
)
from crop_optimizer.analytics import (
    build_balance_tradeoff_frame,
    build_nutrient_dynamics_frame,
    build_pareto_frontier_frame,
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.app.charts import (
    plot_balance_scale_bars,
    plot_nutrient_dynamics,
    plot_pareto_frontier,
    plot_planting_window_heatmap,
    plot_survival_scoreboard,
)
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import BalancePriority, SimulationConfig, SoilHealthState
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
    select_by_balance_priority,
)
from crop_optimizer.lakehouse.catalog import LakehouseCatalog


@st.cache_resource
def _get_lakehouse_catalog() -> LakehouseCatalog:
    settings = get_settings()
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()
    return catalog


@st.cache_data(show_spinner=False)
def _run_cached_simulation(
    location_id: str,
    horizon_years: int,
    n_scenarios: int,
    initial_soil_val: int,
    safra_delay_days: int,
    veranico_days: int,
    farmer_name: str,
):
    catalog = _get_lakehouse_catalog()
    climate_stats = catalog.get_seasonal_climate_stats(location_id)
    locations = {loc.location_id: loc for loc in catalog.load_locations()}
    location = locations[location_id]
    crops = {c.crop_id: c for c in catalog.load_crops()}
    engine = MonteCarloRotationEngine(crops_catalog=crops)

    config = SimulationConfig(
        location_id=location_id,
        horizon_years=horizon_years,
        n_scenarios=n_scenarios,
        initial_soil_state=SoilHealthState(initial_soil_val),
        safra_delay_days=safra_delay_days,
        veranico_days=veranico_days,
        farmer_name=farmer_name,
    )
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, climate_stats, config)
    compute_pareto_frontier(results, criterion="two_year_loss")

    df_matrix = build_planting_window_risk_matrix(
        climate_stats,
        veranico_days=veranico_days,
        n_samples=n_scenarios,
    )
    df_scoreboard = build_survival_scoreboard_frame(results)
    df_balance = build_balance_tradeoff_frame(results)
    df_pareto = build_pareto_frontier_frame(results)
    df_nutrients = build_nutrient_dynamics_frame(results)
    df_climate_annual = catalog.get_annual_climate_summary(location_id)

    return (
        location,
        config,
        climate_stats,
        results,
        df_matrix,
        df_scoreboard,
        df_balance,
        df_pareto,
        df_nutrients,
        df_climate_annual,
    )


def main() -> None:
    st.set_page_config(
        page_title="Conselheiro do Sertão · Motor Estocástico de Resiliência",
        page_icon="🌾",
        layout="wide",
    )

    st.title("🌾 Motor Estocástico de Resiliência do Sertão")
    st.caption(
        "Conselheiro de Bolso para o Semiárido · NASA CHIRPS/SMAP + ZARC Embrapa em DuckDB/Parquet · "
        "10.000 Cenários em NumPy · Rádio do Tempo (TTS) · Ficha EMATER"
    )

    catalog = _get_lakehouse_catalog()
    locations = catalog.load_locations()
    loc_options = {f"{loc.name} - {loc.state} ({loc.biome})": loc.location_id for loc in locations}

    with st.sidebar:
        st.header("Painel do Agricultor / Técnico")
        farmer_name = st.text_input("Nome do Agricultor", value="Seu João")
        selected_loc_label = st.selectbox("Município (NASA + ZARC)", list(loc_options.keys()))
        location_id = loc_options[selected_loc_label]

        safra_delay_days = st.slider("Atraso das Chuvas (dias)", min_value=0, max_value=35, value=14, step=7)
        veranico_days = st.slider("Veranico na Quadra Chuvosa (dias secos)", min_value=0, max_value=21, value=7, step=7)
        horizon_years = st.slider("Horizonte (anos)", min_value=3, max_value=5, value=5)
        n_scenarios = st.select_slider(
            "Cenários Monte Carlo",
            options=[2_000, 5_000, 10_000, 20_000],
            value=10_000,
        )

        soil_options = {s.label: s.value for s in SoilHealthState}
        soil_label = st.selectbox("Condição Atual do Solo", list(soil_options.keys()), index=2)
        initial_soil_val = soil_options[soil_label]

    (
        location,
        config,
        climate_stats,
        results,
        df_matrix,
        df_scoreboard,
        df_balance,
        df_pareto,
        df_nutrients,
        df_climate_annual,
    ) = _run_cached_simulation(
        location_id=location_id,
        horizon_years=horizon_years,
        n_scenarios=n_scenarios,
        initial_soil_val=initial_soil_val,
        safra_delay_days=safra_delay_days,
        veranico_days=veranico_days,
        farmer_name=farmer_name,
    )

    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    ranked = rank_by_survival(results)
    resilient = ranked[0]

    corn_row = df_matrix.filter(
        (df_matrix["crop_id"] == "milho_sertanejo") & (df_matrix["delay_days"] == safra_delay_days)
    )
    corn_risk_pct = float(corn_row["failure_prob_pct"][0]) if corn_row.height > 0 else 50.0
    traffic_light = classify_traffic_light(corn_risk_pct)

    # Banner Semáforo Agrícola no topo
    if traffic_light.value == "verde":
        st.success(f"{traffic_light.emoji} **SEMÁFORO VERDE — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")
    elif traffic_light.value == "amarelo":
        st.warning(f"{traffic_light.emoji} **SEMÁFORO AMARELO — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")
    else:
        st.error(f"{traffic_light.emoji} **SEMÁFORO VERMELHO — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Só Milho (Perda em 10)", f"{traditional.loss_years_of_10} de 10 anos", delta=f"Risco 2 anos seguidos: {traditional.prob_two_consecutive_losses*100:.0f}%", delta_color="inverse")
    c2.metric(resilient.strategy.short_name, f"Sobrevive {resilient.survival_score_of_10} de 10", delta=f"Risco 2 anos seguidos: {resilient.prob_two_consecutive_losses*100:.0f}%")
    c3.metric("🌿 Forragem Garantida", f"{resilient.expected_forage_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."))
    c4.metric("⚡ Latência Total", f"{sum(r.execution_ms for r in results):.0f} ms", delta=f"DuckDB: {climate_stats.query_ms:.1f} ms")

    tab_pocket, tab_radio, tab_emater, tab_lakehouse = st.tabs(
        [
            "🚦 Conselheiro de Bolso (Semáforo & Balança)",
            "📻 O Rádio do Tempo (Áudio + WhatsApp)",
            "📄 Ficha 'O Que Não Sabemos' (EMATER / PDF)",
            "🛰️ Lakehouse NASA + ZARC (DuckDB)",
        ]
    )

    with tab_pocket:
        st.subheader("⚖️ Balança: O que pesa mais para a sua família hoje?")
        priority_choice = st.radio(
            "Clique na sua prioridade:",
            options=[
                BalancePriority.EQUILIBRADO,
                BalancePriority.COMIDA,
                BalancePriority.FORRAGEM,
                BalancePriority.ESCUDO,
            ],
            format_func=lambda p: {
                BalancePriority.EQUILIBRADO: "⚖️ Equilíbrio Geral",
                BalancePriority.COMIDA: "🌽 Comida na Mesa (Grãos)",
                BalancePriority.FORRAGEM: "🌿 Salvar o Rebanho (Forragem/Palma)",
                BalancePriority.ESCUDO: "🛡️ Escudo (Evitar 2 Anos de Perda)",
            }[p],
            horizontal=True,
        )
        chosen = select_by_balance_priority(results, priority_choice)
        st.info(
            f"**Opção recomendada pela Balança:** {chosen.strategy.name} — "
            f"🌽 {chosen.expected_food_kg_ha_year:,.0f} kg/ha·ano de grão | "
            f"🌿 {chosen.expected_forage_kg_ha_year:,.0f} kg/ha·ano de forragem | "
            f"🛡️ Sobrevive **{chosen.survival_score_of_10} de 10 anos**.".replace(",", ".")
        )

        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(plot_survival_scoreboard(df_scoreboard), width="stretch")
        with col_r:
            st.plotly_chart(plot_balance_scale_bars(df_balance), width="stretch")

        st.plotly_chart(plot_planting_window_heatmap(df_matrix), width="stretch")

    with tab_radio:
        st.subheader("📻 O Rádio do Tempo — Resumo Falado para WhatsApp")
        script = compose_radio_script(
            farmer_name=farmer_name,
            location=location,
            delay_days=safra_delay_days,
            traffic_light=traffic_light,
            traditional_result=traditional,
            resilient_result=resilient,
        )
        st.text_area("Roteiro do Áudio (Linguagem Acessível)", value=script, height=130)

        settings = get_settings()
        tts = create_tts_provider(settings.tts_provider, settings.openai_api_key)
        audio_res = tts.synthesize(script)
        st.audio(audio_res.audio_bytes, format=audio_res.mime_type)
        st.download_button(
            label=f"⬇️ Baixar Áudio ({audio_res.file_extension.upper()})",
            data=audio_res.audio_bytes,
            file_name=f"radio_do_tempo_{location.location_id}.{audio_res.file_extension}",
            mime=audio_res.mime_type,
        )

        st.divider()
        st.subheader("📲 Pré-visualização e Disparo WhatsApp (Twilio API)")
        wa_msg = build_whatsapp_summary_message(
            farmer_name=farmer_name,
            location=location,
            delay_days=safra_delay_days,
            traffic_light=traffic_light,
            traditional_result=traditional,
            resilient_result=resilient,
        )
        st.code(wa_msg, language="markdown")
        wa_number = st.text_input("Número WhatsApp do Agricultor (E.164)", value="+5587999990000")
        if st.button("Enviar Mensagem via Twilio WhatsApp"):
            client = TwilioWhatsAppClient(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_whatsapp_from,
            )
            dispatch = client.send_message(wa_number, wa_msg)
            st.success(f"Disparo processado ({dispatch.mode}) para {dispatch.to_number} | SID: {dispatch.sid}")

    with tab_emater:
        st.subheader("📄 Ficha Técnica 'O Que Não Sabemos' (1 Página A4 para EMATER/Cooperativa)")
        pdf_bytes = generate_one_pager_pdf(
            location=location,
            config=config,
            traffic_light=traffic_light,
            scoreboard=df_scoreboard,
            results=results,
        )
        st.download_button(
            label="📥 Exportar Ficha 'O Que Não Sabemos' (PDF 1 Página)",
            data=pdf_bytes,
            file_name=f"ficha_resiliencia_{location.location_id}.pdf",
            mime="application/pdf",
        )

        with st.expander("⚠️ O Que Não Sabemos — Limitações Explícitas do Algoritmo", expanded=True):
            for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
                st.markdown(f"{idx}. {item}")

        col_p, col_n = st.columns(2)
        with col_p:
            st.plotly_chart(plot_pareto_frontier(df_pareto), width="stretch")
        with col_n:
            st.plotly_chart(plot_nutrient_dynamics(df_nutrients, metric="om_mean_pct"), width="stretch")
        st.dataframe(df_pareto.to_pandas(), width="stretch", hide_index=True)

    with tab_lakehouse:
        st.subheader("🛰️ Local Data Lakehouse (CHIRPS/GPM + SMAP + ZARC em Parquet/DuckDB)")
        st.dataframe(df_climate_annual.to_pandas(), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
