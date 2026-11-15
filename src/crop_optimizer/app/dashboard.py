"""Acauã: navegação e página Plantio ("O que devo plantar agora?")."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import polars as pl
import streamlit as st

from crop_optimizer.accessibility import WHAT_WE_DONT_KNOW_ITEMS, generate_one_pager_pdf
from crop_optimizer.analytics import (
    build_balance_tradeoff_frame,
    build_nutrient_dynamics_frame,
    build_pareto_frontier_frame,
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
    talhoes,
)
from crop_optimizer.analytics.crop_advice import crop_verdict, irrigated_verdict
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
    water_by_crop,
)
from crop_optimizer.app.common import lakehouse_catalog as _get_lakehouse_catalog
from crop_optimizer.app.common import rain_delay_report as _rain_delay_report
from crop_optimizer.app.common import zarc_status as _zarc_status
from crop_optimizer.app.home_page import crop_names, home_page
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.app.satellite_page import satellite_page
from crop_optimizer.app.state import arrived, keep, set_roca, store, stored, watch
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.crop_registry import (
    crop_info,
    group_names,
    is_irrigated,
    is_perennial,
    ordered_ids,
    sequeiro_ids,
)
from crop_optimizer.domain.fazenda import load_fazenda
from crop_optimizer.domain.models import (
    BalancePriority,
    RotationStrategy,
    SimulationConfig,
    SoilHealthState,
)
from crop_optimizer.domain.presets import crop_map
from crop_optimizer.domain.roca import Roca, nearest_preset
from crop_optimizer.engine import MonteCarloRotationEngine, compute_pareto_frontier
from crop_optimizer.engine.candidates import CURRENT_ID, candidate_strategies, current_strategy
from crop_optimizer.engine.pareto import annual_profit, rank_by_balance_priority
from crop_optimizer.engine.rain_onset import OnsetCriteria, season_start_for
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, resolve_place
from crop_optimizer.ingestion.power_temperature import TemperatureUnavailable
from crop_optimizer.ingestion.rain_history import RainDataUnavailable
from crop_optimizer.ingestion.zarc_tabua import (
    cycle_label,
    decendio_end_label,
    decendio_start_label,
)

DELAY_GRID = [0, 7, 14, 21, 28, 35]
N_SCENARIOS = 10_000  # fixo: cenários do Monte Carlo
HORIZONS = [1, 2, 3, 5, 10]  # anos; filtro do ranking das rotações
TOP_ROTATIONS = 5  # rotações mostradas no ranking (mais a de hoje)
DEFAULT_HORIZON = 5
_TONE_PILL = {"verde": "Pode plantar", "amarelo": "Arriscado", "vermelho": "Não plante", "espera": "Espere",
              "rega": "Com rega"}
_TONE = {"verde": "verde", "amarelo": "amarelo", "vermelho": "vermelho", "espera": "espera", "rega": "neutro"}
_PRIORITY = {
    BalancePriority.EQUILIBRADO: "Equilíbrio",
    BalancePriority.COMIDA: "Produção de grãos",
    BalancePriority.FORRAGEM: "Forragem",
    BalancePriority.ESCUDO: "Estabilidade",
    BalancePriority.RENDA: "Renda",
}


RainOverride = tuple[str, float, float, float, float]


def _round5(mm: float) -> int:
    return max(5, int(5 * round(mm / 5)))


def _water_block(crop_id: str, crop_name: str, water: dict | None, veranico_days: int | None,
                 texture_group: str, depth_cm: float | None) -> dict | None:
    """Bloco "água" do aviso.

    Sequeiro: dias que a lavoura aguenta x veranico típico, e quanta chuva falta para plantar.
    Irrigada: intervalo de rega neste solo e quanto a primeira rega precisa para encher a camada da raiz.
    """
    if water is None or crop_id not in water:
        return None
    hold, today, plan = water[crop_id]
    nome = crop_name.lower()
    o_nome = f"{'a' if crop_info(crop_id).get('feminino') else 'o'} {nome}"
    soil_txt = TEXTURE_LABELS[texture_group]
    depth = (f" O solo raso ({depth_cm:.0f} cm) limita a raiz." if (plan or hold).limited_by_depth else
             "" if depth_cm is not None else
             " Profundidade do solo não informada: contamos a raiz inteira (em solo raso, a água acaba antes).")
    if plan is not None:
        peak = f"{plan.peak_mm_day:.1f}".replace(".", ",")
        zr = f"{plan.zr_m:.1f}".replace(".", ",")
        phrase = (f"A raiz {'da' if o_nome.startswith('a ') else 'do'} {nome} vai até cerca de {zr} m. Neste solo "
                  f"({soil_txt}), ela tira sem sofrer uns {plan.liters_per_m2:.0f} litros por m²; no pico, a lavoura "
                  f"gasta {peak} litros por m² por dia. Por isso, o intervalo entre regas é de no máximo "
                  f"{plan.interval_days} {'dia' if plan.interval_days == 1 else 'dias'}.{depth}")
        bars = [{"label": "Intervalo máximo entre regas", "days": plan.interval_days, "tone": "neutro"}]
        solo = None
        if today is not None:
            first = (f" A primeira rega precisa de cerca de {_round5(today.taw_mm * (1 - today.fraction))} litros "
                     "por m² para encher a camada da raiz." if today.fraction < 0.9 else "")
            solo = {"title": f"Água no solo em {fmt_date(today.day)}", "fill": round(today.fraction, 3),
                    "normal": None if today.normal_fraction is None else round(today.normal_fraction, 3),
                    "text": (f"O solo está com {round(today.fraction * 10)} de 10 partes da água que a camada da raiz "
                             f"segura.{first} Estimado com a chuva e a temperatura do NASA POWER.")}
        return {"title": "A rega neste solo", "bars": bars, "phrase": phrase, "solo": solo}

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
        etc = f"{hold.etc_mm_day:.1f}".replace(".", ",")
        phrase = (f"{head} Neste solo ({soil_txt}), a raiz alcança cerca de "
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


def _rotation_drought(sequence: list[str], names: dict[str, str], water: dict | None) -> str:
    """A lavoura mais sensível da rotação e quantos dias ela aguenta sem chuva na floração."""
    if water is None:
        return ""
    days = [(water[c][0].days, c) for c in sequence if c in water and water[c][0].days is not None]  # (dias, cultura)
    if not days:
        return "aguenta veranicos longos (palma)"
    d, crop = min(days)
    return f"aguenta {d} dias sem chuva ({names.get(crop, crop).lower()})"


def _num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",").replace(",0", "") if digits == 1 else f"{v:.{digits}f}".replace(".", ",")


def _fmt_month(d: date) -> str:
    return f"{talhoes.MONTHS[d.month - 1]}/{d:%y}"


def _talhoes_section(fazenda, report, ranked, names: dict[str, str], horizon_years: int, as_of: date,
                     detail: str) -> None:
    """Quadro da fazenda + calendário de rotação do talhão escolhido + plano completo para baixar."""
    theme.divider()
    theme.label("Planejamento dos talhões")
    st.header("O plano da fazenda", anchor=False)
    if fazenda is None or not fazenda.talhoes:
        st.markdown("Cadastre a área da fazenda e os talhões na página Início (seção **Sua roça**) para ver o "
                    "plano de cada talhão aqui.")
        navigation.link("inicio", "Cadastrar os talhões na Início")
        return
    if report is None or report.status.reference.median_offset is None:
        st.warning("Sem a referência de quando a chuva costuma firmar neste ponto, não dá para marcar as datas de "
                   "plantio do plano.")
        return
    st.markdown("Clique num talhão para ver o calendário dele: a cultura de hoje até a colheita e as próximas da "
                "rotação, safra a safra.")
    by_id = {r.strategy.strategy_id: r for r, _ in ranked}
    options = [r.strategy.strategy_id for r, _ in ranked]
    keep("plano_modo", "ranking")
    keep("plano_rotacao", options[0])
    if detail and detail in by_id and st.session_state.get("_plano_ultimo_detalhe") != detail:
        st.session_state["_plano_ultimo_detalhe"] = detail
        store("plano_rotacao", detail)
        st.session_state["plano_rotacao"] = detail
    if st.session_state.get("plano_rotacao") not in options:
        st.session_state["plano_rotacao"] = options[0]
        store("plano_rotacao", options[0])
    c_mode, c_rot = st.columns([1, 1.6])
    with c_mode:
        mode = st.segmented_control("Mostrar", options=["ranking", "hoje"],
                                    format_func={"ranking": "Rotação do ranking", "hoje": "Como planta hoje"}.get,
                                    **watch("plano_modo")) or "ranking"
    with c_rot:
        rot_id = st.selectbox("Rotação do ranking", options=options,
                              format_func=lambda i: f"{options.index(i) + 1}º  {by_id[i].strategy.short_name or by_id[i].strategy.name}",
                              disabled=mode == "hoje", **watch("plano_rotacao"))
    crops = list(by_id[rot_id].strategy.annual_sequence) if mode == "ranking" else []
    years = max(2, horizon_years)
    plan = talhoes.plan_farm(fazenda, mode, crops, report.status.reference, as_of, years)

    # --- quadro --------------------------------------------------------------------------
    rest = max(0.0, fazenda.area_total_ha - fazenda.area_talhoes_ha)
    areas = [t.area_ha for t in fazenda.talhoes] + ([rest] if rest > 0.01 * fazenda.area_total_ha else [])
    rects = talhoes.treemap(areas)
    cells = []
    for t, rect in zip(fazenda.talhoes, rects, strict=False):
        crop, label = talhoes.crop_now(plan[t.id], as_of)
        cells.append({"id": t.id, "nome": t.nome, "area": f"{_num(t.area_ha)} ha", "rect": [round(v, 3) for v in rect],
                      "icon": CROP_ICONS.get(crop, "") if crop else "", "crop": names.get(crop, "") if crop else "",
                      "label": {"agora": "plantada agora", "próxima": "próxima cultura", "livre": "sem cultura"}[label]})
    if len(rects) > len(fazenda.talhoes):
        cells.append({"id": "_resto", "nome": "Sem talhão", "area": f"{_num(rest)} ha", "rect": list(rects[-1]),
                      "resto": True})
    keep("talhao", fazenda.talhoes[0].id)
    chosen = stored("talhao", fazenda.talhoes[0].id)
    if chosen not in plan:
        chosen = fazenda.talhoes[0].id
    legend = (f"Fazenda de {_num(fazenda.area_total_ha)} ha, {len(fazenda.talhoes)} talhões. Desenho em proporção à "
              "área (não é o formato real).")
    chosen = components.farm_board({"talhoes": cells, "legend": legend}, chosen, key="fazenda_plantio")
    store("talhao", chosen)

    # --- calendário do talhão escolhido ------------------------------------------------------------
    t = next(x for x in fazenda.talhoes if x.id == chosen)
    grid = talhoes.month_grid(plan[t.id], as_of, years)
    state_txt = {"plantio": "plantio", "colheita": "colheita", "cresce": "na roça", "perene": "perene"}
    for row in grid:
        for m in row["meses"]:
            for it in m["itens"]:
                it.update(icon=CROP_ICONS.get(it["id"], ""), nome=names.get(it["id"], it["id"]),
                          estado_txt=state_txt[it["estado"]])
    seq = " → ".join(f"{names.get(c.crop_id, c.crop_id)} ({_fmt_month(c.inicio)})" for c in plan[t.id][:6])
    rot_name = by_id[rot_id].strategy.short_name or by_id[rot_id].strategy.name
    sub = (f"{_num(t.area_ha)} ha. " + (f"Rotação: {rot_name}. " if mode == "ranking" else "Repetindo o que planta hoje. ")
           + (f"Sequência: {seq}." if seq else ""))
    has_any = any(m["itens"] for row in grid for m in row["meses"])
    components.talhao_calendar({
        "eyebrow": "Calendário do talhão", "title": t.nome, "sub": sub, "rows": grid if has_any else [],
        "empty": ("Este talhão não tem cultura plantada hoje, então não há o que repetir. Veja a rotação do ranking."
                  if mode == "hoje" else "Nenhuma cultura da rotação cabe neste talhão."),
    }, key="calendario_talhao")

    # --- o plano completo --------------------------------------------------------------------------
    rows = talhoes.plan_rows(fazenda, plan)
    with st.expander("O plano completo da fazenda (todos os talhões)"):
        for x in fazenda.talhoes:
            items = " → ".join(f"{names.get(c.crop_id, c.crop_id)} ({_fmt_month(c.inicio)})" for c in plan[x.id])
            st.markdown(f"**{x.nome}** ({_num(x.area_ha)} ha): {items or 'sem cultura'}")
        if rows:
            st.download_button("Baixar o plano (CSV)", data=pl.DataFrame(rows).write_csv().encode("utf-8"),
                               file_name="plano_talhoes_acaua.csv", mime="text/csv")
    st.caption("O plantio de sequeiro é marcado no dia em que a chuva costuma firmar aqui (mediana 1991-2020); a "
               "colheita, pelo ciclo da cultura (FAO-56). Culturas perenes ficam no talhão; as anuais giram de um "
               "talhão para o outro a cada safra. A simulação do ranking supõe áreas iguais para as culturas da "
               "rotação; os talhões têm tamanhos diferentes.")


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
def _risk_matrix(
    location_id: str,
    safra_delay_days: int,
    veranico_prob: float | None,
    veranico_lengths: tuple[int, ...],
    soil_items: tuple,
    rain_override: RainOverride | None = None,
):
    """Matriz atraso x cultura do aviso: o mesmo motor e a mesma régua do ranking (1 ano, 1 cultura)."""
    return build_planting_window_risk_matrix(
        _climate_stats(location_id, veranico_prob, veranico_lengths, rain_override),
        delay_days_grid=sorted({*DELAY_GRID, safra_delay_days}),
        n_samples=N_SCENARIOS,
        config=_soil_config(location_id, dict(soil_items)),
    )


_KEEP_SCENARIOS = 1_000  # cenários guardados no cache para os gráficos (as notas usam os 10.000)


def _slim(res):
    """Resultado com só os primeiros cenários nas matrizes: guarda centenas de rotações sem estourar a memória."""
    k = _KEEP_SCENARIOS
    soil = res.soil_output
    return replace(
        res,
        npv_profit_brl_ha=res.npv_profit_brl_ha[:k],
        annual_profit_brl_ha=res.annual_profit_brl_ha[:k],
        annual_food_kg_ha=res.annual_food_kg_ha[:k],
        annual_forage_kg_ha=res.annual_forage_kg_ha[:k],
        relative_harvest=None if res.relative_harvest is None else res.relative_harvest[:k],
        soil_output=replace(soil, states=soil.states[:k], nitrogen_kg_ha=soil.nitrogen_kg_ha[:k],
                            organic_matter_pct=soil.organic_matter_pct[:k],
                            fertilizer_savings_brl_ha=soil.fertilizer_savings_brl_ha[:k],
                            yield_multiplier=soil.yield_multiplier[:k]),
    )


@st.cache_data(show_spinner=False, max_entries=4000)
def _simulate_one(strategy_key: tuple, config_json: str, location_id: str, veranico_prob: float | None,
                  veranico_lengths: tuple[int, ...], rain_override: RainOverride | None = None):
    """Uma rotação, 10.000 cenários. Fica no cache: mudar a restrição só escolhe outras do cache."""
    strategy_id, name, description, crops = strategy_key
    strategy = RotationStrategy(strategy_id=strategy_id, name=name, short_name=name, description=description,
                                annual_sequence=list(crops))
    config = SimulationConfig.model_validate_json(config_json)
    catalog = {**crop_map(), **{c.crop_id: c for c in _get_lakehouse_catalog().load_crops()}}
    res = MonteCarloRotationEngine(crops_catalog=catalog).simulate_strategy(
        strategy, _climate_stats(location_id, veranico_prob, veranico_lengths, rain_override), config)
    return _slim(res), build_nutrient_dynamics_frame([res])


def _run_simulation(strategies: list[RotationStrategy], location_id: str, horizon_years: int, initial_soil_val: int,
                    safra_delay_days: int, veranico_prob: float | None, veranico_lengths: tuple[int, ...],
                    initial_om_pct: float, initial_n_kg_ha: float, soil_factors: tuple[tuple[str, float], ...],
                    rain_override: RainOverride | None = None):
    catalog = _get_lakehouse_catalog()
    location = {loc.location_id: loc for loc in catalog.load_locations()}[location_id]
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
    config_json = config.model_dump_json()
    results, nutrients = [], []
    with st.spinner(f"Rodando 10.000 cenários para {len(strategies)} rotações..."):
        for strat in strategies:
            key = (strat.strategy_id, strat.short_name or strat.name, strat.description, tuple(strat.annual_sequence))
            res, df_n = _simulate_one(key, config_json, location_id, veranico_prob, veranico_lengths, rain_override)
            results.append(res)
            nutrients.append(df_n)
    compute_pareto_frontier(results, criterion="two_year_loss")
    return (location, config, _climate_stats(location_id, veranico_prob, veranico_lengths, rain_override), results,
            build_survival_scoreboard_frame(results), build_balance_tradeoff_frame(results),
            build_pareto_frontier_frame(results), pl.concat(nutrients, how="vertical_relaxed"),
            catalog.get_annual_climate_summary(location_id))


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
        if is_irrigated(crop_id):
            detail = "Sem janela de sequeiro no ZARC — no semiárido, esta cultura vai com rega."
        elif is_perennial(crop_id):
            detail = "Esta cultura não tem janela anual na tábua do ZARC (é perene). O aviso usa só o risco do clima."
        else:
            detail = "Esta cultura não está na tábua anual do ZARC usada aqui para sequeiro. O aviso usa só o risco do clima."
        return {
            "has_window": False,
            "state_txt": "Sem janela oficial no ZARC",
            "detail": detail,
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
    else:
        veranico_args = (None, ())
    soil_args = {
        "initial_soil_val": int(initial_markov_state(profile.get("mo_pct"))),
        "initial_om_pct": round(profile.get("mo_pct"), 2),
        "initial_n_kg_ha": round(available_nitrogen_kg_ha(profile), 1),
        "soil_factors": tuple(sorted((c.crop_id, round(c.yield_factor, 3)) for c in suitability)),
    }

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

    df_matrix = _risk_matrix(
        location_id,
        delay,
        *veranico_args,
        tuple(soil_args.items()),
        rain_override=rain_override,
    )

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
    raw_names = crop_names()
    order = ordered_ids()
    crop_order = [c for c in order if c in raw_names] + [c for c in raw_names if c not in order]
    names = {c: raw_names[c] for c in crop_order}
    texture_group = soil_group
    veranico_typical = veranico.typical_longest if veranico is not None and veranico.seasons_with_onset else None
    try:
        water = water_by_crop(loc_json, as_of, texture_group, profile.depth_m, tuple(names))
    except (RainDataUnavailable, TemperatureUnavailable) as exc:
        water = None
        st.warning(f"Não foi possível calcular a água da roça: {exc}")

    windows = {cw.crop_id: cw for cw in zarc_res.crop_windows}
    zarc_crops = set(zarc_cfg["culturas"])
    verdicts = {}
    for crop_id in names:
        if is_irrigated(crop_id):
            plan = water[crop_id][2] if water is not None and crop_id in water else None
            verdicts[crop_id] = irrigated_verdict(crop_id, names[crop_id], plan)
            continue
        row = df_matrix.filter((df_matrix["crop_id"] == crop_id) & (df_matrix["delay_days"] == delay))
        risk = float(row["failure_prob_pct"][0]) if row.height else 50.0
        window = windows.get(crop_id)
        if crop_id in zarc_crops and window is None and zarc_res.zarc_error is None:
            window = CropWindowStatus(crop_id, None, "sem_indicacao")
        verdicts[crop_id] = crop_verdict(crop_id, risk, report.status if report else None, window, delay)
    groups = group_names()
    items = [{"id": c, "name": names[c], "icon": CROP_ICONS[c], "status": _TONE_PILL[verdicts[c].level],
              "tone": _TONE[verdicts[c].level], "group": groups.get(crop_info(c).get("grupo"), "")} for c in names]
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
                              "verdict": verdict.word, "tone": _TONE[verdict.level], "text": verdict.reason,
                              "agua": _water_block(chosen, names[chosen], water, veranico_typical, texture_group,
                                                   profile.depth_cm),
                              "foot": foot},
                             key="aviso_plantio")
    if not is_irrigated(chosen):
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
    seq_names = {c: names[c] for c in sequeiro_ids() if c in names}
    c_req, c_exc = st.columns(2)
    with c_req:
        keep("rot_precisa", [])
        required = st.multiselect("A rotação precisa ter", options=list(seq_names),
                                  format_func=lambda c: seq_names[c], placeholder="Nenhuma exigência",
                                  **watch("rot_precisa"))
    with c_exc:
        keep("rot_sem", [])
        excluded = st.multiselect("A rotação não pode ter", options=list(seq_names),
                                  format_func=lambda c: seq_names[c], placeholder="Nenhuma restrição",
                                  **watch("rot_sem"))
    fazenda = load_fazenda(rain_location.location_id)
    crops_now = [t.cultura for t in fazenda.talhoes if t.cultura] if fazenda else []
    current = current_strategy(crops_now)
    candidates = candidate_strategies(required, excluded)
    if set(required) & set(excluded):
        st.warning("A mesma cultura está em \"precisa ter\" e em \"não pode ter\". Tire de um dos dois.")
    elif not candidates:
        st.warning("Nenhuma rotação de 1 a 3 culturas cumpre essas restrições.")
    same_as_current = {tuple(sorted(c.annual_sequence)) for c in [current]}
    candidates = [c for c in candidates if tuple(sorted(c.annual_sequence)) not in same_as_current]
    (_sim_loc, config, climate_stats, results, df_scoreboard, df_balance, df_pareto, df_nutrients,
     df_climate_annual) = _run_simulation(
        [current, *candidates],
        location_id=location_id,
        horizon_years=horizon_years,
        initial_soil_val=soil_args["initial_soil_val"],
        safra_delay_days=delay,
        veranico_prob=veranico_args[0],
        veranico_lengths=veranico_args[1],
        initial_om_pct=soil_args["initial_om_pct"],
        initial_n_kg_ha=soil_args["initial_n_kg_ha"],
        soil_factors=soil_args["soil_factors"],
        rain_override=rain_override,
    )
    ranked_all = rank_by_balance_priority(results, priority)
    top = [(r, sc) for r, sc in ranked_all if r.strategy.strategy_id != CURRENT_ID][:TOP_ROTATIONS]
    current_pos = next(i for i, (r, _) in enumerate(ranked_all) if r.strategy.strategy_id == CURRENT_ID)
    ranked = sorted([*top, ranked_all[current_pos]], key=lambda item: -item[1])
    n_ok = len(results) - 1
    st.caption(f"{n_ok} {'rotação cumpre' if n_ok == 1 else 'rotações cumprem'} as restrições; aparecem as "
               f"{min(TOP_ROTATIONS, n_ok)} melhores e, para comparar, o jeito que a roça planta hoje "
               f"(em {current_pos + 1}º lugar entre {len(results)}).")
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

    _talhoes_section(fazenda, report, ranked, names, horizon_years, as_of, detail)

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
