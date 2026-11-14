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
from crop_optimizer.app import navigation, theme
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
    theme.label(f"Por quê · chuva da safra {s.season_label}")
    st.header("A chuva desta safra", anchor=False)
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
    location_now, roca = current_location()
    if roca is not None:
        # a chuva, o ZARC e o solo usam o ponto da roça; o Monte Carlo só tem clima dos exemplos
        nearest, nearest_km = nearest_preset(roca.lat, roca.lon)
        location_id = nearest.location_id
        subtitle = f"Sua roça: {roca.label}"
    else:
        location_id = location_now.location_id
        subtitle = f"{location_now.name}/{location_now.state} · município de exemplo"
    rain_location = location_now

    theme.page_header("Plantio", "Posso plantar agora?", subtitle)
    c_map, c_back, c_date = st.columns([1.2, 1.2, 1.6], vertical_alignment="center")
    with c_map:
        navigation.link("satelite", "Marcar ou trocar a roça no mapa")
    with c_back:
        if roca is not None and st.button("Voltar aos municípios de exemplo"):
            clear_roca()
            st.rerun()
    with c_date, st.expander("Simular outra data"):
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
        rain_report, rain_error = None, exc
        safra_delay_days = 0
    else:
        rain_error = None
        safra_delay_days = rain_report.motor_delay_days
    veranico = rain_report.veranico if rain_report is not None else None
    if veranico is not None and veranico.seasons_with_onset:
        veranico_args = (round(veranico.probability, 3), veranico.veranico_lengths)
        typical_veranico = veranico.typical_longest
    else:
        veranico_args, typical_veranico = (None, ()), 7

    df_matrix = _risk_matrix(location_id, safra_delay_days, typical_veranico, *veranico_args)
    corn_row = df_matrix.filter(
        (df_matrix["crop_id"] == "milho_sertanejo") & (df_matrix["delay_days"] == safra_delay_days)
    )
    corn_risk_pct = float(corn_row["failure_prob_pct"][0]) if corn_row.height > 0 else 50.0
    traffic_light = classify_traffic_light(corn_risk_pct)

    # 1. A resposta, direta
    delay_txt = f"{safra_delay_days} dias de atraso da chuva" if safra_delay_days else "sem atraso de chuva"
    corn_of_10 = round(corn_risk_pct / 10)
    theme.status_card(
        traffic_light.value,
        f"{traffic_light.guidance}. Plantando milho agora, a roça quebra em {corn_of_10} de cada 10 anos.",
        f"Considerando {delay_txt} e o veranico observado no local.",
    )
    if roca is not None:
        st.caption(
            f"O risco das culturas usa o clima de exemplo de {nearest.name}/{nearest.state}, o município de "
            f"exemplo mais perto da sua roça (a {nearest_km:.0f} km). A chuva, o veranico e o ZARC abaixo são do "
            "ponto da sua roça."
        )
    with st.expander("Ver o risco de cada cultura conforme o atraso da chuva"):
        st.plotly_chart(plot_planting_window_heatmap(df_matrix), width="stretch")

    # 2. Por quê: a chuva
    theme.divider()
    if rain_report is not None:
        _render_rain_section(rain_report)
    else:
        st.error(f"**Não foi possível calcular o atraso da chuva.** {rain_error} O aviso acima considera chuva sem atraso.")
    st.caption("**Solo por cultura:** " + " · ".join(f"{c.name}: {c.label.lower()}" for c in suitability))
    navigation.link("inicio", "Ver o perfil do solo e ajustar com análise de campo")

    # 3. Qual roça aguenta mais?
    theme.divider()
    theme.label("Rotações · 10.000 cenários")
    st.header("Qual roça aguenta mais?", anchor=False)
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

    c1, c2, c3 = st.columns(3)
    c1.metric("Só milho perde a roça em", f"{traditional.loss_years_of_10} de 10 anos", delta=f"{risk}: {traditional.prob_two_consecutive_losses*100:.0f}%", delta_color="off", delta_arrow="off")
    c2.metric(f"{resilient.strategy.short_name} aguenta", f"{resilient.survival_score_of_10} de 10 anos", delta=f"{risk}: {resilient.prob_two_consecutive_losses*100:.0f}%", delta_color="off", delta_arrow="off")
    c3.metric("Forragem garantida", f"{resilient.expected_forage_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."))

    tab_pocket, tab_radio, tab_emater, tab_lakehouse = st.tabs(
        ["Balança", "Rádio do Tempo", "Ficha para o técnico", "Dados"]
    )

    with tab_pocket:
        st.subheader("O que pesa mais para a sua família hoje?", anchor=False)
        priority_choice = st.radio(
            "Prioridade",
            options=[
                BalancePriority.EQUILIBRADO,
                BalancePriority.COMIDA,
                BalancePriority.FORRAGEM,
                BalancePriority.ESCUDO,
            ],
            format_func=lambda p: {
                BalancePriority.EQUILIBRADO: "Equilíbrio",
                BalancePriority.COMIDA: "Comida na mesa",
                BalancePriority.FORRAGEM: "Salvar o rebanho",
                BalancePriority.ESCUDO: "Evitar 2 anos de perda" if horizon_years >= 2 else "Evitar perder a safra",
            }[p],
            horizontal=True,
            label_visibility="collapsed",
        )
        chosen = select_by_balance_priority(results, priority_choice)
        st.info(
            f"**Indicada pela Balança: {chosen.strategy.name}.** "
            f"{chosen.expected_food_kg_ha_year:,.0f} kg/ha·ano de grão · "
            f"{chosen.expected_forage_kg_ha_year:,.0f} kg/ha·ano de forragem · "
            f"aguenta **{chosen.survival_score_of_10} de 10 anos**.".replace(",", ".")
        )

        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(plot_survival_scoreboard(df_scoreboard), width="stretch")
        with col_r:
            st.plotly_chart(plot_balance_scale_bars(df_balance), width="stretch")

    with tab_radio:
        st.subheader("O resumo falado, para mandar no WhatsApp", anchor=False)
        script = compose_radio_script(
            farmer_name="",
            location=location,
            delay_days=safra_delay_days,
            traffic_light=traffic_light,
            traditional_result=traditional,
            resilient_result=resilient,
            horizon_years=horizon_years,
        )
        st.text_area("Roteiro do áudio", value=script, height=130)

        settings = get_settings()
        tts = create_tts_provider(settings.tts_provider, settings.openai_api_key)
        audio_res = tts.synthesize(script)
        st.audio(audio_res.audio_bytes, format=audio_res.mime_type)
        st.download_button(
            label=f"Baixar áudio ({audio_res.file_extension.upper()})",
            data=audio_res.audio_bytes,
            file_name=f"radio_do_tempo_{location.location_id}.{audio_res.file_extension}",
            mime=audio_res.mime_type,
        )

        theme.divider()
        st.subheader("Mensagem de WhatsApp", anchor=False)
        wa_msg = build_whatsapp_summary_message(
            farmer_name="",
            location=location,
            delay_days=safra_delay_days,
            traffic_light=traffic_light,
            traditional_result=traditional,
            resilient_result=resilient,
        )
        st.code(wa_msg, language="markdown")
        wa_number = st.text_input("Número do WhatsApp (formato +55...)", value="+5587999990000")
        if st.button("Enviar pelo WhatsApp (Twilio)", type="primary"):
            client = TwilioWhatsAppClient(
                account_sid=settings.twilio_account_sid,
                auth_token=settings.twilio_auth_token,
                from_number=settings.twilio_whatsapp_from,
            )
            dispatch = client.send_message(wa_number, wa_msg)
            st.success(f"Disparo processado ({dispatch.mode}) para {dispatch.to_number} | SID: {dispatch.sid}")

    with tab_emater:
        st.subheader("Ficha de 1 página: o que o modelo vê e o que não vê", anchor=False)
        pdf_bytes = generate_one_pager_pdf(
            location=location,
            config=config,
            traffic_light=traffic_light,
            scoreboard=df_scoreboard,
            results=results,
        )
        st.download_button(
            label="Baixar a ficha (PDF)",
            data=pdf_bytes,
            file_name=f"ficha_acaua_{location.location_id}.pdf",
            mime="application/pdf",
            type="primary",
        )

        with st.expander("O que não sabemos: limites do modelo", expanded=True):
            for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
                st.markdown(f"{idx}. {item}")

        col_p, col_n = st.columns(2)
        with col_p:
            st.plotly_chart(plot_pareto_frontier(df_pareto, horizon_years=horizon_years), width="stretch")
        with col_n:
            st.plotly_chart(plot_nutrient_dynamics(df_nutrients, metric="om_mean_pct"), width="stretch")
        st.dataframe(df_pareto.to_pandas(), width="stretch", hide_index=True)

    with tab_lakehouse:
        st.subheader("Clima por ano usado na simulação", anchor=False)
        st.dataframe(df_climate_annual.to_pandas(), width="stretch", hide_index=True)
        st.caption(
            f"Simulação: {sum(r.execution_ms for r in results):.0f} ms para {len(results)} rotações x "
            f"{N_SCENARIOS:,} cenários; consulta ao lakehouse (DuckDB) em {climate_stats.query_ms:.1f} ms.".replace(",", ".")
        )

    theme.footer(
        "Fontes: chuva NASA POWER (MERRA-2/GEOS-IT); janelas ZARC (MAPA/Embrapa); solo ISRIC SoilGrids; "
        "relevo SRTM. Detalhes em docs/referencias.md."
    )


HOME_PAGE = navigation.register(
    "inicio", st.Page(home_page, title="Início", url_path="inicio", default=True)
)
PLANTIO_PAGE = navigation.register("plantio", st.Page(plantio_page, title="Plantio", url_path="plantio"))
SATELLITE_PAGE = navigation.register(
    "satelite", st.Page(satellite_page, title="Satélite", url_path="satelite")
)


def main() -> None:
    st.set_page_config(page_title="Acauã", page_icon=theme.asset("icone.png"), layout="wide")
    theme.inject()
    # sem barra lateral o Streamlit mostraria o icon_image; queremos o letreiro "Acauã" sempre
    st.logo(theme.asset("logo_marca.png"), size="large")
    st.navigation([HOME_PAGE, PLANTIO_PAGE, SATELLITE_PAGE], position="top").run()


if __name__ == "__main__":
    main()
