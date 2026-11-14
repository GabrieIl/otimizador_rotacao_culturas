"""Aplicação Web Interativa (Streamlit + Plotly) — Motor Estocástico de Resiliência do Sertão."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

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
from crop_optimizer.analytics.rain_delay import (
    RainDelayReport,
    describe_status,
    fmt_date,
)
from crop_optimizer.analytics.soil_suitability import (
    available_nitrogen_kg_ha,
    evaluate,
    initial_markov_state,
)
from crop_optimizer.analytics.views import loss_risk_label
from crop_optimizer.app import navigation
from crop_optimizer.app.charts import (
    plot_balance_scale_bars,
    plot_nutrient_dynamics,
    plot_pareto_frontier,
    plot_planting_window_heatmap,
    plot_survival_scoreboard,
)
from crop_optimizer.app.common import current_location, soil_profile
from crop_optimizer.app.common import lakehouse_catalog as _get_lakehouse_catalog
from crop_optimizer.app.common import rain_delay_report as _rain_delay_report
from crop_optimizer.app.home_page import home_page
from crop_optimizer.app.satellite_page import satellite_page
from crop_optimizer.app.state import arrived, clear_roca, keep, watch
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import (
    BalancePriority,
    SimulationConfig,
    SoilHealthState,
)
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.domain.roca import nearest_preset
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
    select_by_balance_priority,
)
from crop_optimizer.engine.rain_onset import OnsetCriteria
from crop_optimizer.ingestion.rain_history import RainDataUnavailable

DELAY_GRID = [0, 7, 14, 21, 28, 35]
N_SCENARIOS = 10_000  # fixo: cenários do Monte Carlo
HORIZONS = [1, 2, 3, 5]  # anos; escolhido como filtro dos painéis que usam a simulação
DEFAULT_HORIZON = 5
_CROP_LABELS = {
    "milho_sertanejo": "Milho",
    "feijao_caupi": "Feijão-caupi",
    "sorgo_forrageiro": "Sorgo forrageiro",
}


def _render_rain_section(report: RainDelayReport) -> None:
    s = report.status
    loc = report.location
    st.subheader(f"Chuva da safra {s.season_label} em {loc.name}/{loc.state}")
    title, body, level = describe_status(s)
    getattr(st, level)(f"**{title}.** {body}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("A chuva firmou em", fmt_date(s.onset_date) if s.onset_date else "Ainda não")
    c2.metric("Em ano normal", fmt_date(s.reference_date))
    if s.state in ("antes_da_epoca", "sem_referencia"):
        c3.metric("Atraso", "—")
    elif s.delay_days < 0:
        c3.metric("Atraso", f"{s.delay_days} dias", delta="adiantada")
    else:
        c3.metric("Atraso", f"{s.delay_days} dias")
    c4.metric("Atraso usado na simulação", f"{report.motor_delay_days} dias")
    if report.veranico_alert:
        st.warning(f"**{report.veranico_alert}**")
    if report.veranico is not None and report.veranico.seasons_with_onset:
        v = report.veranico
        st.markdown(
            f"**Veranico** ({v.min_days} dias ou mais sem chuva depois que a chuva firma): aconteceu em "
            f"**{v.of_10} de cada 10 anos** de {s.reference.first_year} a {s.reference.last_year}. "
            f"A maior seca dentro da safra costuma durar **{v.typical_longest} dias**."
        )

    crit = OnsetCriteria.from_config()
    ref = s.reference
    st.caption(
        f"Chuva diária: {report.source}, com dados até {s.data_until:%d/%m/%Y} "
        "(a fonte tem uns 3 dias de atraso e cada ponto cobre uns 50 km). "
        f"A chuva \"firma\" quando caem {crit.rain_3d_mm:.0f} mm em 3 dias e não vem veranico de mais de "
        f"{crit.max_dry_spell_days} dias nos {crit.check_window_days} dias seguintes (Sivakumar, 1988). "
        f"Normal = mediana de {ref.first_year} a {ref.last_year}; em {ref.years_without_onset} desses "
        f"{ref.n_years} anos a chuva não firmou."
    )

    if report.zarc_error:
        st.warning(f"Janelas oficiais do ZARC indisponíveis: {report.zarc_error}")
    elif report.crop_windows:
        lines = [
            f"- **{_CROP_LABELS.get(cw.crop_id, cw.crop_id)}**: {cw.phrase}"
            for cw in report.crop_windows
        ]
        st.markdown(
            f"**Janela oficial de plantio em sequeiro (ZARC {report.zarc_safra}, MAPA/Embrapa)**, "
            f"em {fmt_date(s.data_until)}:\n" + "\n".join(lines)
        )


def _climate_stats(location_id: str, veranico_prob: float | None, veranico_lengths: tuple[int, ...]):
    """Estatísticas do lakehouse com o veranico trocado pelo observado na chuva real (NASA POWER)."""
    stats = _get_lakehouse_catalog().get_seasonal_climate_stats(location_id)
    if veranico_prob is None:
        return stats
    return replace(stats, veranico_prob=veranico_prob, veranico_lengths=veranico_lengths)


@st.cache_data(show_spinner=False)
def _risk_matrix(location_id: str, safra_delay_days: int, typical_veranico_days: int,
                 veranico_prob: float | None, veranico_lengths: tuple[int, ...]):
    """Matriz atraso x cultura do semáforo (não depende do horizonte)."""
    return build_planting_window_risk_matrix(
        _climate_stats(location_id, veranico_prob, veranico_lengths),
        delay_days_grid=sorted({*DELAY_GRID, safra_delay_days}),
        veranico_days=typical_veranico_days,
        n_samples=N_SCENARIOS,
    )


@st.cache_data(show_spinner="Rodando 10.000 cenários...")
def _run_cached_simulation(
    location_id: str,
    horizon_years: int,
    initial_soil_val: int,
    safra_delay_days: int,
    veranico_prob: float | None = None,
    veranico_lengths: tuple[int, ...] = (),
    initial_om_pct: float = 2.2,
    initial_n_kg_ha: float = 55.0,
    soil_factors: tuple[tuple[str, float], ...] = (),
):
    catalog = _get_lakehouse_catalog()
    climate_stats = _climate_stats(location_id, veranico_prob, veranico_lengths)
    locations = {loc.location_id: loc for loc in catalog.load_locations()}
    location = locations[location_id]
    crops = {c.crop_id: c for c in catalog.load_crops()}
    engine = MonteCarloRotationEngine(crops_catalog=crops)

    config = SimulationConfig(
        location_id=location_id,
        horizon_years=horizon_years,
        n_scenarios=N_SCENARIOS,
        initial_soil_state=SoilHealthState(initial_soil_val),
        initial_organic_matter_pct=initial_om_pct,
        initial_nitrogen_kg_ha=initial_n_kg_ha,
        soil_crop_factors=dict(soil_factors),
        safra_delay_days=safra_delay_days,
        veranico_days=0,  # o veranico vem do sorteio com o histórico real, não de um valor fixo
    )
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, climate_stats, config)
    compute_pareto_frontier(results, criterion="two_year_loss")

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
        df_scoreboard,
        df_balance,
        df_pareto,
        df_nutrients,
        df_climate_annual,
    )


def plantio_page() -> None:
    arrived("plantio")
    st.title("Motor Estocástico de Resiliência do Sertão")
    st.caption(
        "Conselheiro de Bolso para o Semiárido · NASA CHIRPS/SMAP + ZARC Embrapa em DuckDB/Parquet · "
        "10.000 Cenários em NumPy · Rádio do Tempo (TTS) · Ficha EMATER"
    )

    location_now, roca = current_location()
    if roca is not None:
        # a chuva, o ZARC e o solo usam o ponto da roça; o Monte Carlo só tem clima dos exemplos
        nearest, nearest_km = nearest_preset(roca.lat, roca.lon)
        location_id = nearest.location_id
    else:
        location_id = location_now.location_id
    rain_location = location_now

    top = st.columns([3, 2])
    with top[0]:
        if roca is not None:
            st.markdown(f"**Sua roça:** {roca.label}")
        else:
            st.markdown(f"**Local:** {location_now.name}/{location_now.state} (município de exemplo)")
    with top[1]:
        navigation.link("satelite", "Marcar ou trocar a roça no mapa")
        if roca is not None and st.button("Voltar aos municípios de exemplo"):
            clear_roca()
            st.rerun()
    with st.expander("Simular outra data"):
        keep("data_simulada", date.today())
        as_of = st.date_input(
            "Data",
            max_value=date.today(),
            format="DD/MM/YYYY",
            **watch("data_simulada"),
            help="O atraso da chuva é calculado para esta data. Útil para mostrar outra época do ano.",
        )
    if as_of != date.today():
        st.caption(f"Simulando o dia **{as_of:%d/%m/%Y}**.")

    # O solo vem do perfil do local (Início): mapa SoilGrids/SRTM ou análise de campo.
    profile = soil_profile(rain_location)
    suitability = evaluate(profile)

    try:
        rain_report = _rain_delay_report(rain_location.model_dump_json(), as_of)
    except RainDataUnavailable as exc:
        st.error(
            f"**Não foi possível calcular o atraso da chuva.** {exc} "
            "A simulação abaixo roda SEM atraso de chuva."
        )
        safra_delay_days = 0
        rain_report = None
    else:
        _render_rain_section(rain_report)
        safra_delay_days = rain_report.motor_delay_days
    veranico = rain_report.veranico if rain_report is not None else None
    if veranico is not None and veranico.seasons_with_onset:
        veranico_args = (round(veranico.probability, 3), veranico.veranico_lengths)
        typical_veranico = veranico.typical_longest
    else:
        veranico_args, typical_veranico = (None, ()), 7

    st.caption("**Solo por cultura:** " + " · ".join(f"{c.name}: {c.label.lower()}" for c in suitability))
    navigation.link("inicio", "Ver o perfil do solo e ajustar com análise de campo")
    st.divider()
    if roca is not None:
        st.warning(
            f"**Daqui para baixo, a simulação usa o clima de exemplo de {nearest.name}/{nearest.state}**, "
            f"o município de exemplo mais perto da sua roça (a {nearest_km:.0f} km). "
            "Só a chuva e a janela do ZARC acima são do ponto da sua roça."
        )

    df_matrix = _risk_matrix(location_id, safra_delay_days, typical_veranico, *veranico_args)
    corn_row = df_matrix.filter(
        (df_matrix["crop_id"] == "milho_sertanejo") & (df_matrix["delay_days"] == safra_delay_days)
    )
    corn_risk_pct = float(corn_row["failure_prob_pct"][0]) if corn_row.height > 0 else 50.0
    traffic_light = classify_traffic_light(corn_risk_pct)

    # Banner Semáforo Agrícola no topo
    if traffic_light.value == "verde":
        st.success(f"**SEMÁFORO VERDE — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")
    elif traffic_light.value == "amarelo":
        st.warning(f"**SEMÁFORO AMARELO — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")
    else:
        st.error(f"**SEMÁFORO VERMELHO — {traffic_light.guidance}** (atraso {safra_delay_days}d | risco milho: {corn_risk_pct:.0f}%)")

    st.subheader("Rotações")
    keep("horizonte", DEFAULT_HORIZON)
    horizon_years = st.segmented_control(
        "Horizonte da simulação",
        options=HORIZONS,
        format_func=lambda h: "1 ano" if h == 1 else f"{h} anos",
        **watch("horizonte"),
        help="Quantos anos à frente os 10.000 cenários simulam. Vale para os painéis abaixo.",
    ) or DEFAULT_HORIZON
    (
        location,
        config,
        climate_stats,
        results,
        df_scoreboard,
        df_balance,
        df_pareto,
        df_nutrients,
        df_climate_annual,
    ) = _run_cached_simulation(
        location_id=location_id,
        horizon_years=horizon_years,
        initial_soil_val=int(initial_markov_state(profile.get("mo_pct"))),
        safra_delay_days=safra_delay_days,
        veranico_prob=veranico_args[0],
        veranico_lengths=veranico_args[1],
        initial_om_pct=round(profile.get("mo_pct"), 2),
        initial_n_kg_ha=round(available_nitrogen_kg_ha(profile), 1),
        soil_factors=tuple(sorted((c.crop_id, round(c.yield_factor, 3)) for c in suitability)),
    )
    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    resilient = rank_by_survival(results)[0]
    risk = loss_risk_label(horizon_years).capitalize()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Só Milho (Perda em 10)", f"{traditional.loss_years_of_10} de 10 anos", delta=f"{risk}: {traditional.prob_two_consecutive_losses*100:.0f}%", delta_color="inverse")
    c2.metric(resilient.strategy.short_name, f"Sobrevive {resilient.survival_score_of_10} de 10", delta=f"{risk}: {resilient.prob_two_consecutive_losses*100:.0f}%")
    c3.metric("Forragem Garantida", f"{resilient.expected_forage_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."))
    c4.metric("Latência Total", f"{sum(r.execution_ms for r in results):.0f} ms", delta=f"DuckDB: {climate_stats.query_ms:.1f} ms")

    tab_pocket, tab_radio, tab_emater, tab_lakehouse = st.tabs(
        [
            "Conselheiro de Bolso (Semáforo & Balança)",
            "O Rádio do Tempo (Áudio + WhatsApp)",
            "Ficha 'O Que Não Sabemos' (EMATER / PDF)",
            "Lakehouse NASA + ZARC (DuckDB)",
        ]
    )

    with tab_pocket:
        st.subheader("Balança: O que pesa mais para a sua família hoje?")
        priority_choice = st.radio(
            "Clique na sua prioridade:",
            options=[
                BalancePriority.EQUILIBRADO,
                BalancePriority.COMIDA,
                BalancePriority.FORRAGEM,
                BalancePriority.ESCUDO,
            ],
            format_func=lambda p: {
                BalancePriority.EQUILIBRADO: "Equilíbrio Geral",
                BalancePriority.COMIDA: "Comida na Mesa (Grãos)",
                BalancePriority.FORRAGEM: "Salvar o Rebanho (Forragem/Palma)",
                BalancePriority.ESCUDO: "Escudo (Evitar 2 Anos de Perda)" if horizon_years >= 2 else "Escudo (Evitar Perder a Safra)",
            }[p],
            horizontal=True,
        )
        chosen = select_by_balance_priority(results, priority_choice)
        st.info(
            f"**Opção recomendada pela Balança:** {chosen.strategy.name} — "
            f"{chosen.expected_food_kg_ha_year:,.0f} kg/ha·ano de grão | "
            f"{chosen.expected_forage_kg_ha_year:,.0f} kg/ha·ano de forragem | "
            f"Sobrevive **{chosen.survival_score_of_10} de 10 anos**.".replace(",", ".")
        )

        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(plot_survival_scoreboard(df_scoreboard), width="stretch")
        with col_r:
            st.plotly_chart(plot_balance_scale_bars(df_balance), width="stretch")

        st.plotly_chart(plot_planting_window_heatmap(df_matrix), width="stretch")

    with tab_radio:
        st.subheader("O Rádio do Tempo — Resumo Falado para WhatsApp")
        script = compose_radio_script(
            farmer_name="",
            location=location,
            delay_days=safra_delay_days,
            traffic_light=traffic_light,
            traditional_result=traditional,
            resilient_result=resilient,
            horizon_years=horizon_years,
        )
        st.text_area("Roteiro do Áudio (Linguagem Acessível)", value=script, height=130)

        settings = get_settings()
        tts = create_tts_provider(settings.tts_provider, settings.openai_api_key)
        audio_res = tts.synthesize(script)
        st.audio(audio_res.audio_bytes, format=audio_res.mime_type)
        st.download_button(
            label=f"Baixar Áudio ({audio_res.file_extension.upper()})",
            data=audio_res.audio_bytes,
            file_name=f"radio_do_tempo_{location.location_id}.{audio_res.file_extension}",
            mime=audio_res.mime_type,
        )

        st.divider()
        st.subheader("Pré-visualização e Disparo WhatsApp (Twilio API)")
        wa_msg = build_whatsapp_summary_message(
            farmer_name="",
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
        st.subheader("Ficha Técnica 'O Que Não Sabemos' (1 Página A4 para EMATER/Cooperativa)")
        pdf_bytes = generate_one_pager_pdf(
            location=location,
            config=config,
            traffic_light=traffic_light,
            scoreboard=df_scoreboard,
            results=results,
        )
        st.download_button(
            label="Exportar Ficha 'O Que Não Sabemos' (PDF 1 Página)",
            data=pdf_bytes,
            file_name=f"ficha_resiliencia_{location.location_id}.pdf",
            mime="application/pdf",
        )

        with st.expander("O Que Não Sabemos — Limitações Explícitas do Algoritmo", expanded=True):
            for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
                st.markdown(f"{idx}. {item}")

        col_p, col_n = st.columns(2)
        with col_p:
            st.plotly_chart(plot_pareto_frontier(df_pareto, horizon_years=horizon_years), width="stretch")
        with col_n:
            st.plotly_chart(plot_nutrient_dynamics(df_nutrients, metric="om_mean_pct"), width="stretch")
        st.dataframe(df_pareto.to_pandas(), width="stretch", hide_index=True)

    with tab_lakehouse:
        st.subheader("Local Data Lakehouse (CHIRPS/GPM + SMAP + ZARC em Parquet/DuckDB)")
        st.dataframe(df_climate_annual.to_pandas(), width="stretch", hide_index=True)


HOME_PAGE = navigation.register(
    "inicio", st.Page(home_page, title="Início", url_path="inicio", default=True)
)
PLANTIO_PAGE = navigation.register("plantio", st.Page(plantio_page, title="Plantio", url_path="plantio"))
SATELLITE_PAGE = navigation.register(
    "satelite", st.Page(satellite_page, title="Satélite", url_path="satelite")
)


def main() -> None:
    st.set_page_config(
        page_title="Acauã · Conselheiro do Sertão",
        layout="wide",
    )
    st.navigation([HOME_PAGE, PLANTIO_PAGE, SATELLITE_PAGE], position="top").run()


if __name__ == "__main__":
    main()
