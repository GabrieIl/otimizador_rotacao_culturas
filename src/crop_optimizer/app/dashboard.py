"""Acauã: navegação e página Plantio ("O que devo plantar agora?")."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import streamlit as st

from crop_optimizer.accessibility import WHAT_WE_DONT_KNOW_ITEMS, generate_one_pager_pdf
from crop_optimizer.analytics import (
    build_balance_tradeoff_frame,
    build_nutrient_dynamics_frame,
    build_pareto_frontier_frame,
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.analytics.crop_advice import crop_verdict
from crop_optimizer.analytics.rain_calendar import calendar_months, dry_spells
from crop_optimizer.analytics.rain_delay import (
    CropWindowStatus,
    describe_status,
    fmt_date,
    seasonal_stats_from_rain_series,
)
from crop_optimizer.analytics.soil_suitability import (
    TEXTURE_LABELS,
    available_nitrogen_kg_ha,
    evaluate,
    initial_markov_state,
    texture_class,
)
from crop_optimizer.analytics.views import loss_risk_label
from crop_optimizer.app import components, navigation, theme
from crop_optimizer.app.charts import (
    plot_nutrient_dynamics,
    plot_pareto_frontier,
    plot_rotation_soil,
    plot_rotation_years,
)
from crop_optimizer.app.common import (
    current_location,
    ensure_zarc_downloaded_with_progress,
    rain_chance,
    rain_series,
    soil_profile,
)
from crop_optimizer.app.common import lakehouse_catalog as _get_lakehouse_catalog
from crop_optimizer.app.common import rain_delay_report as _rain_delay_report
from crop_optimizer.app.common import zarc_status as _zarc_status
from crop_optimizer.app.home_page import crop_names, home_page
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.app.satellite_page import satellite_page
from crop_optimizer.app.state import arrived, keep, set_roca, store, stored, watch
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import BalancePriority, SimulationConfig, SoilHealthState
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.domain.roca import Roca, nearest_preset
from crop_optimizer.engine import MonteCarloRotationEngine, compute_pareto_frontier
from crop_optimizer.engine.pareto import rank_by_balance_priority
from crop_optimizer.engine.rain_onset import OnsetCriteria, season_start_for
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, resolve_place
from crop_optimizer.ingestion.rain_history import RainDataUnavailable
from crop_optimizer.ingestion.zarc_tabua import (
    cycle_label,
    decendio_end_label,
    decendio_start_label,
)

DELAY_GRID = [0, 7, 14, 21, 28, 35]
N_SCENARIOS = 10_000  # fixo: cenários do Monte Carlo
HORIZONS = [1, 2, 3, 5, 10]  # anos; filtro do ranking das rotações
DEFAULT_HORIZON = 5
_TONE_PILL = {"verde": "Pode plantar", "amarelo": "Arriscado", "vermelho": "Não plante", "espera": "Espere"}
_PRIORITY = {
    BalancePriority.EQUILIBRADO: "Equilíbrio",
    BalancePriority.COMIDA: "Comida na mesa",
    BalancePriority.FORRAGEM: "Salvar o rebanho",
    BalancePriority.ESCUDO: "Evitar anos de perda",
}


RainOverride = tuple[str, float, float, float, float]


def _climate_stats(
    location_id: str,
    veranico_prob: float | None,
    veranico_lengths: tuple[int, ...],
    rain_override: RainOverride | None = None,
):
    """Estatísticas do lakehouse calibradas com chuva/veranico reais do ponto (NASA POWER)."""
    stats = _get_lakehouse_catalog().get_seasonal_climate_stats(location_id)
    if rain_override is not None:
        pt_id, safra_mean, safra_std, safrinha_mean, safrinha_std = rain_override
        stats = replace(
            stats,
            location_id=pt_id,
            safra_rain_mean_mm=safra_mean,
            safra_rain_std_mm=safra_std,
            safrinha_rain_mean_mm=safrinha_mean,
            safrinha_rain_std_mm=safrinha_std,
        )
    if veranico_prob is None:
        return stats
    return replace(stats, veranico_prob=veranico_prob, veranico_lengths=veranico_lengths)


@st.cache_data(show_spinner=False)
def _risk_matrix(
    location_id: str,
    safra_delay_days: int,
    typical_veranico_days: int,
    veranico_prob: float | None,
    veranico_lengths: tuple[int, ...],
    rain_override: RainOverride | None = None,
):
    """Matriz atraso x cultura do semáforo (não depende do horizonte)."""
    return build_planting_window_risk_matrix(
        _climate_stats(location_id, veranico_prob, veranico_lengths, rain_override),
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
    rain_override: RainOverride | None = None,
):
    catalog = _get_lakehouse_catalog()
    climate_stats = _climate_stats(location_id, veranico_prob, veranico_lengths, rain_override)
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


def _zarc_data(
    crop_id: str,
    window: CropWindowStatus | None,
    today: date,
    zarc_res,
    place_name: str,
) -> dict:
    zarc_cfg = load_yaml_config("zarc")
    zarc_name = zarc_cfg["culturas"].get(crop_id)
    soil_lbl = TEXTURE_LABELS.get(zarc_res.soil_group) if getattr(zarc_res, "soil_group", None) else None
    cyc_code = getattr(zarc_res, "cycle_code", None)
    filters = []
    if soil_lbl:
        filters.append(f"solo {soil_lbl}")
    if cyc_code:
        filters.append(f"ciclo {cycle_label(cyc_code)}")
    filter_txt = f" ({', '.join(filters)})" if filters else ""
    source = f"ZARC {zarc_cfg['safra']} (MAPA/Embrapa), sequeiro · {place_name}{filter_txt}"
    if zarc_name is None:
        return {
            "has_window": False,
            "state_txt": "Sem janela oficial no ZARC",
            "detail": "Esta cultura não tem janela anual na tábua do ZARC (é perene). O aviso usa só o risco do clima.",
            "source": source,
        }
    if zarc_res.zarc_error:
        return {
            "has_window": False,
            "state_txt": "ZARC indisponível",
            "detail": zarc_res.zarc_error,
            "source": source,
        }
    if window is None or window.window is None:
        soil_msg = f" para solo de textura {soil_lbl}" if soil_lbl else " para o perfil selecionado"
        cyc_msg = f" no ciclo {cycle_label(cyc_code)}" if cyc_code else ""
        return {
            "has_window": False,
            "state_txt": "Não indicado para este perfil",
            "detail": (
                f"O ZARC não indica plantio desta cultura em sequeiro neste município{soil_msg}{cyc_msg}: "
                "o risco passa de 40% ou essa combinação não foi zoneada."
            ),
            "source": source,
        }
    labels = [f"{decendio_start_label(i)} a {decendio_end_label(i)}" for i in range(1, 37)]
    doy = (today - date(today.year, 1, 1)).days
    decs = zarc_res.decendios_by_crop.get(crop_id) or [0] * 36
    source_full = f"{source} · {window.window.portaria}" if window.window.portaria else source
    return {
        "has_window": True,
        "decendios": decs,
        "labels": labels,
        "today_pos": round(100 * (doy + 0.5) / 365, 2),
        "state_txt": window.phrase,
        "source": source_full,
    }


def _zarc_error_actions(roca: Roca | None, rain_location) -> None:
    if roca is not None and not rain_location.ibge_code:
        if st.button("Tentar identificar município novamente", key="retry_ibge_zarc"):
            try:
                place = resolve_place(roca.lat, roca.lon)
            except GeocodeUnavailable as exc:
                st.warning(f"Não foi possível identificar o município agora: {exc}")
                return
            aviso = None if place.ibge_code else "Município achado, mas sem código no IBGE: o ZARC não vai aparecer."
            set_roca(
                Roca(
                    lat=roca.lat,
                    lon=roca.lon,
                    municipio=place.municipio,
                    uf=place.uf,
                    ibge_code=place.ibge_code,
                    aviso_municipio=aviso,
                )
            )
            st.session_state["_zarc_tentativa"] = st.session_state.get("_zarc_tentativa", 0) + 1
            st.rerun()
        return

    st.warning("Não foi possível baixar ou ler os dados do ZARC agora. Os avisos continuam usando a chuva e o risco simulado.")
    if st.button("Tentar baixar dados do ZARC novamente", key="retry_zarc"):
        st.session_state["_zarc_tentativa"] = st.session_state.get("_zarc_tentativa", 0) + 1
        st.rerun()


def _delay_data(df_matrix, crop_id: str, delay: int) -> dict:
    rows = df_matrix.filter(df_matrix["crop_id"] == crop_id).sort("delay_days")
    points = []
    for r in rows.iter_rows(named=True):
        if r["delay_days"] not in DELAY_GRID and r["delay_days"] != delay:
            continue
        points.append({"label": "no tempo" if r["delay_days"] == 0 else f"+{r['delay_days']} dias",
                       "of10": round(r["failure_prob_pct"] / 10),
                       "tone": classify_traffic_light(r["failure_prob_pct"]).value,
                       "current": r["delay_days"] == delay})
    phrase = (f"Hoje a chuva está {delay} dias atrasada." if delay > 0
              else "Hoje não há atraso de chuva a considerar.")
    return {"title": "Se a chuva atrasar: em quantos de cada 10 anos a roça quebra", "phrase": phrase, "points": points}


def _why_section(report, series, location_json: str, as_of: date) -> None:
    s = report.status
    theme.label(f"Por quê · chuva da safra {s.season_label}")
    st.header("A chuva desta safra", anchor=False)
    title, body, level = describe_status(s)
    getattr(st, level)(f"**{title}.** {body}")
    c1, c2, c3 = st.columns(3)
    c1.metric("A chuva firmou em", fmt_date(s.onset_date) if s.onset_date else "Ainda não")
    c2.metric("Em ano normal firma em", fmt_date(s.reference_date),
              help=f"Metade dos anos entre {fmt_date(s.reference_early)} e {fmt_date(s.reference_late)} (1991-2020).")
    c3.metric("Atraso", "—" if s.state in ("antes_da_epoca", "sem_referencia") else f"{s.delay_days} dias")

    crit = OnsetCriteria.from_config()
    vcfg = load_yaml_config("chuva")["veranico"]
    veranicos = []
    if s.onset_date is not None:
        end = min(s.data_until, s.onset_date + timedelta(days=int(vcfg["janela_apos_inicio_dias"])))
        veranicos = dry_spells(series, s.onset_date + timedelta(days=3), end, int(vcfg["dias_minimos"]), crit.wet_day_mm)
    v = report.veranico
    patterns = [f"Em ano normal, a chuva firma por volta de **{fmt_date(s.reference_date)}**."]
    if v is not None and v.seasons_with_onset:
        patterns.append(f"Veranico de {v.min_days} dias ou mais depois de a chuva firmar: em **{v.of_10} de cada 10 anos**; "
                        f"a maior seca dentro da safra costuma durar **{v.typical_longest} dias**.")
    if veranicos:
        patterns.append(f"Nesta safra já houve **{len(veranicos)} veranico(s)** (marcados no calendário).")
    if report.veranico_alert:
        patterns.append(f"**{report.veranico_alert}**")
    st.markdown(" ".join(patterns))
    months = calendar_months(series, s.season_start, 9, as_of, rain_chance(location_json, date.today()),
                             onset=s.onset_date, normal_onset=s.reference_date, veranicos=veranicos,
                             wet_mm=crit.wet_day_mm)
    components.rain_calendar(months, {"inicio": s.onset_date is not None, "normal": True, "veranico": bool(veranicos)},
                             key="calendario_safra")
    st.caption(
        f"A chuva \"firma\" quando caem {crit.rain_3d_mm:.0f} mm em 3 dias sem veranico de mais de "
        f"{crit.max_dry_spell_days} dias nos {crit.check_window_days} seguintes (Sivakumar, 1988). Fonte: {report.source}, "
        f"dados até {s.data_until:%d/%m/%Y}."
    )


def plantio_page() -> None:
    arrived("plantio")
    location_now, roca = current_location()
    if roca is not None:
        # a chuva, o ZARC e o solo usam o ponto da roça; o Monte Carlo só tem clima dos exemplos
        nearest, nearest_km = nearest_preset(roca.lat, roca.lon)
        location_id = nearest.location_id
        where = f"Sua roça: {roca.label}"
    else:
        location_id = location_now.location_id
        where = f"{location_now.name}/{location_now.state} · município de exemplo"
    rain_location = location_now
    as_of = stored("data_simulada", date.today())

    theme.label("Plantio")
    st.title("O que devo plantar agora?", anchor=False)
    c_btn, c_loc = st.columns([1, 2.6], vertical_alignment="center")
    with c_btn, st.container(key="acaua-editar"):
        navigation.link("satelite", "Marcar ou trocar a roça no mapa")
    c_loc.html(f'<p class="acaua-subtitulo">{where}</p>')
    if as_of != date.today():
        st.caption(f"Simulando o dia **{as_of:%d/%m/%Y}** (mude no rodapé).")

    profile = soil_profile(rain_location)
    soil_group = texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    suitability = evaluate(profile)
    loc_json = rain_location.model_dump_json()

    zarc_cfg = load_yaml_config("zarc")
    cycle_labels = {str(k): str(v) for k, v in zarc_cfg.get("ciclos", {}).items()}
    keep("ciclo_zarc", "todos")
    cycle_sel = stored("ciclo_zarc", "todos")
    cycle_code = None if cycle_sel == "todos" else str(cycle_sel)

    ensure_zarc_downloaded_with_progress()
    try:
        report = _rain_delay_report(loc_json, as_of, soil_group=soil_group, cycle_code=cycle_code)
        series = rain_series(loc_json, date.today())
    except RainDataUnavailable as exc:
        report, series = None, None
        st.error(f"**Não foi possível calcular o atraso da chuva.** {exc} Os avisos consideram chuva sem atraso.")
    delay = report.motor_delay_days if report is not None else 0
    veranico = report.veranico if report is not None else None
    if veranico is not None and veranico.seasons_with_onset:
        veranico_args = (round(veranico.probability, 3), veranico.veranico_lengths)
        typical_veranico = veranico.typical_longest
    else:
        veranico_args, typical_veranico = (None, ()), 7

    rain_override: RainOverride | None = None
    if series is not None:
        base_stats = _get_lakehouse_catalog().get_seasonal_climate_stats(location_id)
        pt_stats = seasonal_stats_from_rain_series(
            series,
            base_stats,
            veranico_prob=veranico_args[0],
            veranico_lengths=veranico_args[1],
        )
        if pt_stats.location_id == series.location_id:
            rain_override = (
                pt_stats.location_id,
                pt_stats.safra_rain_mean_mm,
                pt_stats.safra_rain_std_mm,
                pt_stats.safrinha_rain_mean_mm,
                pt_stats.safrinha_rain_std_mm,
            )

    df_matrix = _risk_matrix(location_id, delay, typical_veranico, *veranico_args, rain_override=rain_override)

    # --- o que plantar: seletor + janela + aviso --------------------------------------
    zarc_season_start = report.status.season_start if report is not None else season_start_for(as_of, 1)
    zarc_as_of = report.status.data_until if report is not None else as_of
    zarc_res = _zarc_status(
        loc_json,
        zarc_season_start,
        zarc_as_of,
        st.session_state.get("_zarc_tentativa", 0),
        soil_group=soil_group,
        cycle_code=cycle_code,
    )
    names = crop_names()
    windows = {cw.crop_id: cw for cw in zarc_res.crop_windows}
    zarc_crops = set(zarc_cfg["culturas"])
    verdicts = {}
    for crop_id in names:
        row = df_matrix.filter((df_matrix["crop_id"] == crop_id) & (df_matrix["delay_days"] == delay))
        risk = float(row["failure_prob_pct"][0]) if row.height else 50.0
        window = windows.get(crop_id)
        if crop_id in zarc_crops and window is None and zarc_res.zarc_error is None:
            window = CropWindowStatus(crop_id, None, "sem_indicacao")
        verdicts[crop_id] = crop_verdict(crop_id, risk, report.status if report else None, window, delay)
    items = [{"id": c, "name": names[c], "icon": CROP_ICONS[c], "status": _TONE_PILL[verdicts[c].level],
              "tone": verdicts[c].level} for c in names]
    chosen = stored("cultura", next(iter(names)))
    chosen = components.crop_combo(items, chosen if chosen in names else next(iter(names)), key="combo_plantio")
    store("cultura", chosen)
    verdict = verdicts[chosen]

    place_name = f"{rain_location.name}/{rain_location.state}" if rain_location.state else rain_location.name
    st.html('<div style="height:.75rem"></div>')
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        components.zarc_window(_zarc_data(chosen, windows.get(chosen), as_of, zarc_res, place_name), key="zarc_plantio")
        if chosen in zarc_crops and not zarc_res.zarc_error:
            cycle_opts = ["todos"] + list(cycle_labels)
            st.selectbox(
                "Ciclo da cultivar no ZARC",
                cycle_opts,
                format_func=lambda c: "Todos os ciclos disponíveis" if c == "todos" else cycle_labels.get(c, c),
                **watch("ciclo_zarc"),
            )
            cw = windows.get(chosen)
            if cw and cw.window and cw.window.available_cycles:
                avail_txt = ", ".join(cycle_labels.get(c, c) for c in cw.window.available_cycles)
                st.caption(f"Ciclos com indicação ZARC neste solo: {avail_txt}.")
        if zarc_res.zarc_error and chosen in zarc_crops:
            _zarc_error_actions(roca, rain_location)
    with right:
        foot = None
        if rain_override is not None:
            foot = (
                f"Chuva histórica (NASA POWER) e ZARC filtrados para solo {TEXTURE_LABELS[soil_group]} "
                f"em {place_name}."
            )
        elif roca is not None:
            foot = (f"O risco usa o clima de exemplo de {nearest.name}/{nearest.state} (a {nearest_km:.0f} km da roça). "
                    "A chuva e o ZARC são do ponto da roça.")
        components.crop_hero({"icon": CROP_ICONS[chosen], "eyebrow": "O aviso do Acauã", "title": names[chosen],
                              "verdict": verdict.word, "tone": verdict.level, "text": verdict.reason, "foot": foot},
                             key="aviso_plantio")
    st.html('<div style="height:.75rem"></div>')
    components.delay_risk(_delay_data(df_matrix, chosen, delay), key="atraso_plantio")

    # --- por quê ------------------------------------------------------------------
    if report is not None and series is not None:
        theme.divider()
        _why_section(report, series, loc_json, as_of)

    # --- ranking das rotações ---------------------------------------------------------
    theme.divider()
    theme.label("Rotações · 10.000 cenários")
    st.header("Ranking das rotações", anchor=False)
    st.markdown("Da rotação que mais aguenta para a que menos aguenta, conforme o que pesa mais para a família.")
    c_h, c_p = st.columns([1, 1.4])
    with c_h:
        keep("horizonte", DEFAULT_HORIZON)
        horizon_years = st.segmented_control(
            "Anos à frente", options=HORIZONS, format_func=lambda h: "1 ano" if h == 1 else f"{h} anos",
            **watch("horizonte"),
        ) or DEFAULT_HORIZON
    with c_p:
        keep("prioridade", BalancePriority.EQUILIBRADO)
        priority = st.segmented_control(
            "O que pesa mais", options=list(_PRIORITY), format_func=lambda p: _PRIORITY[p], **watch("prioridade"),
        ) or BalancePriority.EQUILIBRADO
    (_sim_loc, config, climate_stats, results, df_scoreboard, df_balance, df_pareto, df_nutrients,
     df_climate_annual) = _run_cached_simulation(
        location_id=location_id,
        horizon_years=horizon_years,
        initial_soil_val=int(initial_markov_state(profile.get("mo_pct"))),
        safra_delay_days=delay,
        veranico_prob=veranico_args[0],
        veranico_lengths=veranico_args[1],
        initial_om_pct=round(profile.get("mo_pct"), 2),
        initial_n_kg_ha=round(available_nitrogen_kg_ha(profile), 1),
        soil_factors=tuple(sorted((c.crop_id, round(c.yield_factor, 3)) for c in suitability)),
        rain_override=rain_override,
    )
    ranked = rank_by_balance_priority(results, priority)
    risk_txt = ("perde a safra" if horizon_years == 1 else "2 anos seguidos de perda")
    items = [{
        "id": r.strategy.strategy_id, "name": r.strategy.short_name or r.strategy.name,
        "aguenta": r.survival_score_of_10,
        "risco": f"{risk_txt} em {round(r.prob_two_consecutive_losses * 10)} de 10 cenários",
        "comida": f"{r.expected_food_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."),
        "forragem": f"{r.expected_forage_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."),
        "nota": score,
    } for r, score in ranked]
    detail = components.rotation_ranking(items, stored("rotacao_detalhe", ""), key="ranking_rotacoes")
    store("rotacao_detalhe", detail)
    by_id = {r.strategy.strategy_id: r for r in results}
    if detail and detail in by_id:
        res = by_id[detail]
        name = res.strategy.short_name or res.strategy.name
        st.subheader(f"{name} em detalhe", anchor=False)
        st.markdown(f"{res.strategy.description} A faixa clara vai dos 10% piores aos 10% melhores cenários.")
        st.plotly_chart(plot_rotation_years(res, config.family_food_target_kg_year, config.herd_forage_target_kg_year),
                        width="stretch")
        st.plotly_chart(plot_rotation_soil(df_nutrients, name), width="stretch")

    # --- ficha técnica ---------------------------------------------------------------
    theme.divider()
    theme.label("Para o técnico")
    st.header("Ficha técnica", anchor=False)
    milho = df_matrix.filter((df_matrix["crop_id"] == "milho_sertanejo") & (df_matrix["delay_days"] == delay))
    traffic_light = classify_traffic_light(float(milho["failure_prob_pct"][0]) if milho.height else 50.0)
    rain_note = "Chuva calibrada pela serie NASA POWER do ponto." if rain_override is not None else None
    pdf_bytes = generate_one_pager_pdf(
        location=rain_location,
        config=config,
        traffic_light=traffic_light,
        scoreboard=df_scoreboard,
        results=results,
        soil_profile=profile,
        crop_windows=zarc_res.crop_windows,
        zarc_safra=zarc_res.zarc_safra,
        zarc_error=zarc_res.zarc_error,
        rain_source_note=rain_note,
    )
    st.download_button("Baixar a ficha técnica (PDF, 1 página)", data=pdf_bytes,
                       file_name=f"ficha_acaua_{rain_location.location_id}.pdf", mime="application/pdf", type="primary")
    with st.expander("O que não sabemos: limites do modelo"):
        for idx, item in enumerate(WHAT_WE_DONT_KNOW_ITEMS, start=1):
            st.markdown(f"{idx}. {item}")
    with st.expander("Gráficos técnicos (fronteira de risco e matéria orgânica de todas as rotações)"):
        st.plotly_chart(plot_pareto_frontier(df_pareto, horizon_years=horizon_years), width="stretch")
        st.plotly_chart(plot_nutrient_dynamics(df_nutrients, metric="om_mean_pct"), width="stretch")
        st.caption(f"{loss_risk_label(horizon_years).capitalize()}; simulação de {N_SCENARIOS:,} cenários em "
                   f"{sum(r.execution_ms for r in results):.0f} ms.".replace(",", "."))

    # --- rodapé (com a opção de teste) -------------------------------------------------
    theme.footer(
        "Fontes: chuva NASA POWER (MERRA-2/GEOS-IT); janelas ZARC (MAPA/Embrapa); solo ISRIC SoilGrids; "
        "relevo SRTM. Detalhes em docs/referencias.md."
    )
    with st.expander("Simular outra data (para testes)"):
        keep("data_simulada", date.today())
        st.date_input("Data usada no cálculo da chuva", max_value=date.today(), format="DD/MM/YYYY",
                      **watch("data_simulada"),
                      help="Para mostrar outra época do ano. Vale para esta página.")


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
