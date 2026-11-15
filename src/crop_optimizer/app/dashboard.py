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
from crop_optimizer.analytics.rain_delay import CropWindowStatus, describe_status, fmt_date
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
    rain_chance,
    rain_series,
    soil_profile,
    water_by_crop,
    zarc_decendios,
)
from crop_optimizer.app.common import lakehouse_catalog as _get_lakehouse_catalog
from crop_optimizer.app.common import rain_delay_report as _rain_delay_report
from crop_optimizer.app.home_page import crop_names, home_page
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.app.satellite_page import satellite_page
from crop_optimizer.app.state import arrived, keep, store, stored, watch
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.models import BalancePriority, SimulationConfig, SoilHealthState
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES
from crop_optimizer.domain.roca import nearest_preset
from crop_optimizer.engine import MonteCarloRotationEngine, compute_pareto_frontier
from crop_optimizer.engine.pareto import annual_profit, rank_by_balance_priority
from crop_optimizer.engine.rain_onset import OnsetCriteria
from crop_optimizer.ingestion.power_temperature import TemperatureUnavailable
from crop_optimizer.ingestion.rain_history import RainDataUnavailable
from crop_optimizer.ingestion.zarc_tabua import decendio_end_label, decendio_start_label

DELAY_GRID = [0, 7, 14, 21, 28, 35]
N_SCENARIOS = 10_000  # fixo: cenários do Monte Carlo
HORIZONS = [1, 2, 3, 5, 10]  # anos; filtro do ranking das rotações
DEFAULT_HORIZON = 5
_TONE_PILL = {"verde": "Pode plantar", "amarelo": "Arriscado", "vermelho": "Não plante", "espera": "Espere"}
_PRIORITY = {
    BalancePriority.EQUILIBRADO: "Equilíbrio",
    BalancePriority.COMIDA: "Produção de grãos",
    BalancePriority.FORRAGEM: "Forragem",
    BalancePriority.ESCUDO: "Estabilidade",
    BalancePriority.RENDA: "Renda",
}


def _round5(mm: float) -> int:
    return max(5, int(5 * round(mm / 5)))


def _water_block(crop_id: str, crop_name: str, water: dict | None, veranico_days: int | None,
                 texture_group: str, depth_cm: float | None) -> dict | None:
    """Bloco "água" do aviso: dias que a lavoura aguenta x veranico típico, e a água no solo hoje."""
    if water is None or crop_id not in water:
        return None
    hold, today = water[crop_id]
    nome = crop_name.lower()
    o_nome = f"{'a' if nome.startswith('palma') else 'o'} {nome}"
    bars = []
    if veranico_days:
        bars.append({"label": "Veranico típico daqui", "days": veranico_days, "tone": "veranico"})
    if hold.days is None:
        phrase = (f"A {nome} guarda água na própria raquete e atravessa veranicos longos: "
                  "a conta de dias sem chuva não se aplica a ela.")
    else:
        short = veranico_days is not None and hold.days < veranico_days
        bars.append({"label": f"Quanto {o_nome} aguenta", "days": hold.days,
                     "tone": "curto" if short else ("ok" if veranico_days else "neutro")})
        if veranico_days is None:
            head = f"Na floração, {o_nome} aguenta {hold.days} dias sem chuva neste solo."
        elif short:
            head = f"O veranico daqui costuma passar do que {o_nome} aguenta: {veranico_days} dias contra {hold.days}."
        else:
            head = f"{crop_name} aguenta o veranico típico daqui: {hold.days} dias contra {veranico_days}."
        depth = (f" O solo raso ({depth_cm:.0f} cm) limita a raiz." if hold.limited_by_depth else
                 "" if depth_cm is not None else
                 " Profundidade do solo não informada: contamos a raiz inteira (em solo raso, aguenta menos).")
        etc = f"{hold.etc_mm_day:.1f}".replace(".", ",")
        phrase = (f"{head} Neste solo ({TEXTURE_LABELS[texture_group]}), a raiz alcança cerca de "
                  f"{hold.raw_mm:.0f} mm de água sem sofrer e, na floração, a lavoura gasta {etc} mm por dia.{depth}")
    solo = None
    if today is not None:
        normal = "" if today.normal_fraction is None else (
            f" O normal desta data é {round(today.normal_fraction * 10)} de 10.")
        need = (f" Faltam cerca de {_round5(today.missing_mm)} mm de chuva para a camada da raiz ficar sem "
                "falta de água para plantar." if today.missing_mm > 0 else
                " A camada da raiz está sem falta de água para plantar.")
        solo = {"title": f"Água no solo em {fmt_date(today.day)}",
                "fill": round(today.fraction, 3),
                "normal": None if today.normal_fraction is None else round(today.normal_fraction, 3),
                "text": (f"O solo está com {round(today.fraction * 10)} de 10 partes da água que a camada da raiz "
                         f"segura.{normal}{need} Estimado com a chuva e a temperatura do NASA POWER.")}
    return {"title": "Quantos dias a terra segura a lavoura", "bars": bars, "phrase": phrase, "solo": solo}


def _climate_stats(location_id: str, veranico_prob: float | None, veranico_lengths: tuple[int, ...]):
    """Estatísticas do lakehouse com o veranico trocado pelo observado na chuva real (NASA POWER)."""
    stats = _get_lakehouse_catalog().get_seasonal_climate_stats(location_id)
    if veranico_prob is None:
        return stats
    return replace(stats, veranico_prob=veranico_prob, veranico_lengths=veranico_lengths)


def _rotation_drought(sequence: list[str], names: dict[str, str], water: dict | None) -> str:
    """A lavoura mais sensível da rotação e quantos dias ela aguenta sem chuva na floração."""
    if water is None:
        return ""
    days = [(water[c][0].days, c) for c in sequence if c in water and water[c][0].days is not None]
    if not days:
        return "aguenta veranicos longos (palma)"
    d, crop = min(days)
    return f"aguenta {d} dias sem chuva ({names.get(crop, crop).lower()})"


def _soil_config(location_id: str, soil: dict) -> SimulationConfig:
    """Configuração do motor com o solo de hoje (a mesma no aviso e no ranking)."""
    return SimulationConfig(
        location_id=location_id,
        n_scenarios=N_SCENARIOS,
        initial_soil_state=SoilHealthState(soil["initial_soil_val"]),
        initial_organic_matter_pct=soil["initial_om_pct"],
        initial_nitrogen_kg_ha=soil["initial_n_kg_ha"],
        soil_crop_factors=dict(soil["soil_factors"]),
        veranico_days=0,  # o veranico vem do sorteio com o histórico real, não de um valor fixo
    )


@st.cache_data(show_spinner="Rodando 10.000 cenários por cultura...")
def _risk_matrix(location_id: str, safra_delay_days: int, veranico_prob: float | None,
                 veranico_lengths: tuple[int, ...], soil_items: tuple):
    """Matriz atraso x cultura do aviso: o mesmo motor e a mesma régua do ranking (1 ano, 1 cultura)."""
    return build_planting_window_risk_matrix(
        _climate_stats(location_id, veranico_prob, veranico_lengths),
        delay_days_grid=sorted({*DELAY_GRID, safra_delay_days}),
        n_samples=N_SCENARIOS,
        config=_soil_config(location_id, dict(soil_items)),
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


def _zarc_data(crop_id: str, window: CropWindowStatus | None, ibge: str | None, today: date, report) -> dict:
    zarc_name = load_yaml_config("zarc")["culturas"].get(crop_id)
    source = f"ZARC {load_yaml_config('zarc')['safra']} (MAPA/Embrapa), sequeiro"
    if zarc_name is None:
        return {"has_window": False, "state_txt": "Sem janela oficial no ZARC",
                "detail": "Esta cultura não tem janela anual na tábua do ZARC (é perene). O aviso usa só o risco do clima.",
                "source": source}
    if report is not None and report.zarc_error:
        return {"has_window": False, "state_txt": "ZARC indisponível", "detail": report.zarc_error, "source": source}
    if window is None or window.window is None:
        return {"has_window": False, "state_txt": "Não indicado neste município",
                "detail": "O ZARC não indica plantio desta cultura em sequeiro aqui: em todos os solos e ciclos, "
                          "o risco passa de 40% ou o município não foi zoneado.", "source": source}
    labels = [f"{decendio_start_label(i)} a {decendio_end_label(i)}" for i in range(1, 37)]
    doy = (today - date(today.year, 1, 1)).days
    return {"has_window": True, "decendios": zarc_decendios(ibge, zarc_name), "labels": labels,
            "today_pos": round(100 * (doy + 0.5) / 365, 2), "state_txt": window.phrase, "source": source}


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
    return {"title": "Se a chuva atrasar: em quantos de cada 10 anos dá quebra de safra", "phrase": phrase,
            "points": points}


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
    suitability = evaluate(profile)
    loc_json = rain_location.model_dump_json()
    try:
        report = _rain_delay_report(loc_json, as_of)
        series = rain_series(loc_json, date.today())
    except RainDataUnavailable as exc:
        report, series = None, None
        st.error(f"**Não foi possível calcular o atraso da chuva.** {exc} Os avisos consideram chuva sem atraso.")
    delay = report.motor_delay_days if report is not None else 0
    veranico = report.veranico if report is not None else None
    if veranico is not None and veranico.seasons_with_onset:
        veranico_args = (round(veranico.probability, 3), veranico.veranico_lengths)
    else:
        veranico_args = (None, ())
    soil_args = {
        "initial_soil_val": int(initial_markov_state(profile.get("mo_pct"))),
        "initial_om_pct": round(profile.get("mo_pct"), 2),
        "initial_n_kg_ha": round(available_nitrogen_kg_ha(profile), 1),
        "soil_factors": tuple(sorted((c.crop_id, round(c.yield_factor, 3)) for c in suitability)),
    }
    df_matrix = _risk_matrix(location_id, delay, *veranico_args, tuple(soil_args.items()))

    # --- o que plantar: seletor + janela + aviso --------------------------------------
    names = crop_names()
    windows = {cw.crop_id: cw for cw in (report.crop_windows if report is not None else [])}
    zarc_crops = set(load_yaml_config("zarc")["culturas"])
    verdicts = {}
    for crop_id in names:
        row = df_matrix.filter((df_matrix["crop_id"] == crop_id) & (df_matrix["delay_days"] == delay))
        risk = float(row["failure_prob_pct"][0]) if row.height else 50.0
        window = windows.get(crop_id)
        if crop_id in zarc_crops and window is None and report is not None and report.zarc_error is None:
            window = CropWindowStatus(crop_id, None, "sem_indicacao")
        verdicts[crop_id] = crop_verdict(crop_id, risk, report.status if report else None, window, delay)
    items = [{"id": c, "name": names[c], "icon": CROP_ICONS[c], "status": _TONE_PILL[verdicts[c].level],
              "tone": verdicts[c].level} for c in names]
    chosen = stored("cultura", next(iter(names)))
    chosen = components.crop_combo(items, chosen if chosen in names else next(iter(names)), key="combo_plantio")
    store("cultura", chosen)
    verdict = verdicts[chosen]

    texture_group = texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    veranico_typical = veranico.typical_longest if veranico is not None and veranico.seasons_with_onset else None
    try:
        water = water_by_crop(loc_json, as_of, texture_group, profile.depth_m, tuple(names))
    except (RainDataUnavailable, TemperatureUnavailable) as exc:
        water = None
        st.warning(f"Não foi possível calcular a água da roça: {exc}")

    st.html('<div style="height:.75rem"></div>')
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        ibge = rain_location.ibge_code
        components.zarc_window(_zarc_data(chosen, windows.get(chosen), ibge, as_of, report), key="zarc_plantio")
    with right:
        foot = None
        if roca is not None:
            foot = (f"O risco usa o clima de exemplo de {nearest.name}/{nearest.state} (a {nearest_km:.0f} km da roça). "
                    "A chuva e o ZARC são do ponto da roça.")
        components.crop_hero({"icon": CROP_ICONS[chosen], "eyebrow": "O aviso do Acauã", "title": names[chosen],
                              "verdict": verdict.word, "tone": verdict.level, "text": verdict.reason,
                              "agua": _water_block(chosen, names[chosen], water, veranico_typical, texture_group,
                                                   profile.depth_cm),
                              "foot": foot},
                             key="aviso_plantio")
    st.html('<div style="height:.75rem"></div>')
    components.delay_risk(_delay_data(df_matrix, chosen, delay), key="atraso_plantio")

    # --- por quê ------------------------------------------------------------------
    if report is not None and series is not None:
        theme.divider()
        _why_section(report, series, loc_json, as_of)

    # --- ranking das rotações ---------------------------------------------------------
    theme.divider()
    theme.label("Ranking das rotações · 10.000 cenários")
    st.header("Qual plano rende mais estável?", anchor=False)
    st.markdown("Da melhor para a pior rotação, conforme o que pesa mais no seu plano.")
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
    (location, config, climate_stats, results, df_scoreboard, df_balance, df_pareto, df_nutrients,
     df_climate_annual) = _run_cached_simulation(
        location_id=location_id,
        horizon_years=horizon_years,
        initial_soil_val=soil_args["initial_soil_val"],
        safra_delay_days=delay,
        veranico_prob=veranico_args[0],
        veranico_lengths=veranico_args[1],
        initial_om_pct=soil_args["initial_om_pct"],
        initial_n_kg_ha=soil_args["initial_n_kg_ha"],
        soil_factors=soil_args["soil_factors"],
    )
    ranked = rank_by_balance_priority(results, priority)
    risk_txt = ("quebra de safra" if horizon_years == 1 else "2 quebras de safra seguidas")
    items = [{
        "id": r.strategy.strategy_id, "name": r.strategy.short_name or r.strategy.name,
        "aguenta": r.survival_score_of_10,
        "risco": f"{risk_txt} em {round(r.prob_two_consecutive_losses * 10)} de 10 cenários",
        "graos": f"{r.expected_food_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."),
        "forragem": f"{r.expected_forage_kg_ha_year:,.0f} kg/ha·ano".replace(",", "."),
        "renda": f"R$ {annual_profit(r):,.0f}/ha·ano".replace(",", "."),
        "seca": _rotation_drought(r.strategy.annual_sequence, names, water),
        "nota": score,
    } for r, score in ranked]
    detail = components.rotation_ranking(items, stored("rotacao_detalhe", ""), key="ranking_rotacoes")
    st.caption("Colhe = anos sem quebra de safra (colher menos da metade do normal). Renda estimada com preços e "
               "custos de referência fixos do modelo, não com a cotação de hoje. Os dias de seca são da lavoura "
               "mais sensível da rotação, na floração, neste solo.")
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
    pdf_bytes = generate_one_pager_pdf(location=location, config=config, traffic_light=traffic_light,
                                       scoreboard=df_scoreboard, results=results)
    st.download_button("Baixar a ficha técnica (PDF, 1 página)", data=pdf_bytes,
                       file_name=f"ficha_acaua_{location.location_id}.pdf", mime="application/pdf", type="primary")
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
