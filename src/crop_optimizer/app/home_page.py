"""Página "Início": a roça, a chuva do ano, o solo do lugar (com a região), o solo por cultura e o terreno."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import streamlit as st

from crop_optimizer.analytics.rain_calendar import calendar_months, dry_spells, year_to_date
from crop_optimizer.analytics.rain_delay import describe_status, fmt_date
from crop_optimizer.analytics.soil_suitability import (
    CLASS_LABELS,
    DEGREE_LABELS,
    TEXTURE_LABELS,
    CropSuitability,
    classify,
    evaluate,
    phosphorus_class,
    relief_class,
    texture_class,
)
from crop_optimizer.analytics.soil_texture import texture_class as texture_triangle
from crop_optimizer.app import components, navigation, theme
from crop_optimizer.app.common import (
    current_location,
    example_selector,
    rain_chance,
    rain_delay_report,
    rain_series,
    region_soil,
    soil_profile,
)
from crop_optimizer.app.icons import CROP_ICONS
from crop_optimizer.app.state import arrived, store, stored
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.soil_profile import (
    ATTRIBUTES,
    DEPTH_FIELD,
    SoilProfile,
    clear_field_data,
    save_field_data,
)
from crop_optimizer.engine.rain_onset import OnsetCriteria
from crop_optimizer.ingestion.rain_history import RainDataUnavailable

_SOURCE = {"campo": "análise de campo", "satelite": "mapa SoilGrids (250 m)", "referencia": "típico do semiárido (assumido)"}
_CLASS_TONE = {"muito_baixo": "vermelho", "baixo": "amarelo", "medio": "neutro", "bom": "verde", "muito_bom": "verde"}
_SUIT_TONE = {"S1": "verde", "S2": "amarelo", "S3": "vermelho", "N": "vermelho"}
_DEGREE_TONE = {"nula": "verde", "ligeira": "verde", "moderada": "amarelo", "forte": "vermelho", "muito_forte": "vermelho"}
_SENS = {"alta": "exige muito", "media": "exige médio", "baixa": "exige pouco", "nula": "não depende do solo"}
RELIEF_STEPS = ["plano", "suave ondulado", "ondulado", "forte ondulado", "montanhoso", "escarpado"]


def crop_names() -> dict[str, str]:
    return {k: v["nome"] for k, v in load_yaml_config("aptidao")["culturas"].items()}


def _num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


# --- sua roça ----------------------------------------------------------------------

def _roca_section(location, roca) -> None:
    theme.label("Sua roça")
    if roca is not None:
        st.title(roca.municipio and f"{roca.municipio}/{roca.uf}" or "Sua roça", anchor=False)
        lat, lon, where, obs = roca.lat, roca.lon, roca.municipio and f"{roca.municipio}/{roca.uf}" or "não identificado", ""
    else:
        st.title("Sua roça ainda não está marcada", anchor=False)
        st.html('<p class="acaua-subtitulo">Por enquanto, os dados abaixo são de um município de exemplo. Marque a roça '
                "no mapa para ver a chuva, o solo e as janelas do ponto dela.</p>")
        lat, lon, where = location.latitude, location.longitude, f"{location.name}/{location.state}"
        obs = "município de exemplo"
    st.html(
        f'''<div class="acaua-roca">
          <div><p class="k">Município</p><p class="v">{where}</p><p class="obs">{obs}</p></div>
          <div><p class="k">Latitude</p><p class="v num">{_num(lat, 4)}</p></div>
          <div><p class="k">Longitude</p><p class="v num">{_num(lon, 4)}</p></div></div>'''
    )
    if roca is None:
        c1, c2 = st.columns([1.3, 2], vertical_alignment="bottom")
        with c1, st.container(key="acaua-configurar"):
            navigation.link("satelite", "Configurar a localização da roça")
        with c2:
            example_selector()
    else:
        with st.container(key="acaua-editar"):
            navigation.link("satelite", "Editar local")


# --- chuva -------------------------------------------------------------------------

def _rain_section(location, today: date) -> None:
    loc_json = location.model_dump_json()
    try:
        report = rain_delay_report(loc_json, today)
        series = rain_series(loc_json, today)
    except RainDataUnavailable as exc:
        st.error(f"Chuva indisponível: {exc}")
        return
    ytd = year_to_date(series, today)
    s = report.status
    theme.label(f"Chuva · {ytd.year}")
    st.header("A chuva deste ano", anchor=False)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        f"Choveu em {ytd.year} até {fmt_date(ytd.until)}",
        f"{ytd.total_mm:.0f} mm",
        delta=f"{ytd.diff_pct:+.0f}% vs média",
        delta_color="normal",
        help="Comparado com a média de 1991 a 2020 no mesmo período (1º de janeiro até a mesma data).",
    )
    c2.metric(f"Média até {fmt_date(ytd.until)}", f"{ytd.normal_mm:.0f} mm", help="Média de 1991 a 2020.")
    c3.metric("Média do ano inteiro", f"{ytd.normal_annual_mm:.0f} mm", help="Média de 1991 a 2020.")
    c4.metric("A chuva costuma firmar em", fmt_date(s.reference_date))
    title, body, level = describe_status(s)
    getattr(st, level)(f"**{title}.** {body}")

    crit = OnsetCriteria.from_config()
    vcfg = load_yaml_config("chuva")["veranico"]
    veranicos = []
    if s.onset_date is not None:
        end = min(s.data_until, s.onset_date + timedelta(days=int(vcfg["janela_apos_inicio_dias"])))
        veranicos = dry_spells(series, s.onset_date + timedelta(days=3), end, int(vcfg["dias_minimos"]), crit.wet_day_mm)
    months = calendar_months(
        series, date(ytd.year, 1, 1), 12, today, rain_chance(loc_json, today),
        onset=s.onset_date, normal_onset=s.reference_date, veranicos=veranicos, wet_mm=crit.wet_day_mm,
    )
    st.markdown("**Calendário da chuva.** A cor de cada dia mostra a chance de chover naquela data (1991-2020): "
                "quanto mais escuro, mais anos choveu. O ícone mostra se de fato choveu e quanto (fraca, moderada "
                "ou forte). Use as setas para ver outros meses e passe o mouse num dia para ver os milímetros.")
    components.rain_calendar(
        months,
        {"inicio": s.onset_date is not None and s.onset_date.year == ytd.year,
         "normal": s.reference_date is not None and s.reference_date.year == ytd.year,
         "veranico": bool(veranicos)},
        key="calendario_inicio",
    )
    st.caption(f"Fonte: {report.source}, dados até {s.data_until:%d/%m/%Y}; cada ponto cobre uns 50 km.")


# --- o solo do lugar (com a região) -----------------------------------------------------

def _scale(local: float, values: np.ndarray | None, fmt, more: str) -> dict | None:
    if values is None or values.size < 20:
        return None
    p = np.percentile(values, [2, 10, 50, 90, 98])
    pct = float(np.mean(values < local) * 100)
    return {"low": float(p[0]), "p10": float(p[1]), "p50": float(p[2]), "p90": float(p[3]), "high": float(p[4]),
            "local": float(local), "low_txt": fmt(p[0]), "p50_txt": fmt(p[2]), "high_txt": fmt(p[4]),
            "phrase": f"O seu ponto tem {more} que {pct:.0f}% da região."}


def _build_soil_compare_rows(profile: SoilProfile, region: dict | None = None) -> tuple[list[dict], list[str]]:
    """Prepara as linhas da tabela comparativa de solo destacando o que é assumido por referência."""
    cls = load_yaml_config("aptidao")["classes_analise"]
    fator = float(load_yaml_config("aptidao")["fator_carbono_para_mo"])
    assumed: list[str] = []

    def reg(prop, convert=lambda a: a):
        return None if region is None or prop not in region else convert(np.asarray(region[prop]))

    def row(attr, label, value_txt, class_key, tone, scale, note=None):
        item = profile.values[attr] if attr else None
        source = _SOURCE[item.source] if item else "mapa SoilGrids (250 m)"
        if item is not None and item.source == "referencia":
            tone = "neutro"
            class_key = f"{class_key} (assumido)"
            assumed.append(label)
            if scale:
                scale["phrase"] = "Sem dado no seu ponto: o valor é o típico do semiárido. A régua mostra a região."
            note = "Nenhum satélite mede este dado: usando valor típico do semiárido. Informe a análise de solo abaixo."
        elif item is not None and item.source == "campo" and scale:
            scale["phrase"] += " (sua análise comparada com o mapa da região)"
        return {
            "label": label,
            "value_txt": value_txt,
            "class_txt": class_key,
            "tone": tone,
            "source_txt": source,
            "scale": scale,
            "note": note,
        }

    mo = profile.get("mo_pct")
    mo_cls = classify(mo, cls["mo_pct"])
    p_val = profile.get("p_mehlich")
    p_cls = phosphorus_class(p_val, profile.get("argila_pct"))
    k_cls = classify(profile.get("k_mg_dm3"), cls["k_mg_dm3"])
    v_cls = classify(profile.get("v_pct"), cls["v_pct"])
    ph = profile.get("ph_h2o")
    ph_cls = ["muito baixo", "baixo", "bom", "alto", "muito alto"][int(np.searchsorted(cls["ph_agronomico"], ph, side="right"))]
    ctc = profile.get("ctc_t")
    ctc_cls = classify(ctc, cls["ctc_t"])
    only_lab = "Nenhum mapa de satélite mede este dado; só a análise de solo."
    rows = [
        row("mo_pct", "Matéria orgânica", f"{_num(mo, 2)}%", CLASS_LABELS[mo_cls], _CLASS_TONE[mo_cls],
            _scale(mo, reg("soc", lambda a: a / 10 * fator), lambda v: f"{_num(v, 1)}%", "mais matéria orgânica")),
    ]
    if profile.n_total_g_kg is not None:
        n = profile.n_total_g_kg
        rows.append(row(None, "Nitrogênio total", f"{_num(n, 2)} g/kg", "segue a matéria orgânica", "neutro",
                        _scale(n, reg("nitrogen"), lambda v: f"{_num(v, 2)} g/kg", "mais nitrogênio")))
    rows += [
        row("p_mehlich", "Fósforo", f"{_num(p_val, 1)} mg/dm³", CLASS_LABELS[p_cls], _CLASS_TONE[p_cls], None, only_lab),
        row("k_mg_dm3", "Potássio", f"{profile.get('k_mg_dm3'):.0f} mg/dm³", CLASS_LABELS[k_cls], _CLASS_TONE[k_cls], None, only_lab),
        row("v_pct", "Cálcio e magnésio (V%)", f"{profile.get('v_pct'):.0f}%", CLASS_LABELS[v_cls], _CLASS_TONE[v_cls], None, only_lab),
        row("ph_h2o", "Acidez (pH em água)", _num(ph, 1), ph_cls, "verde" if ph_cls == "bom" else "amarelo",
            _scale(ph, reg("phh2o"), lambda v: _num(v, 1), "pH mais alto")),
        row("ctc_t", "Capacidade de segurar nutrientes (CTC)", f"{_num(ctc, 1)} cmolc/dm³", CLASS_LABELS[ctc_cls],
            _CLASS_TONE[ctc_cls], _scale(ctc, reg("cec"), lambda v: _num(v, 1), "CTC maior")),
    ]
    return rows, assumed


def _soil_place_section(location, profile: SoilProfile) -> None:
    theme.label("O solo do lugar")
    st.header("Como é o solo daqui", anchor=False)
    st.markdown(
        "Cada fator do solo comparado com a **região**: um quadrado de uns 55 km em volta do ponto, no mesmo mapa "
        "(SoilGrids, camada de 0 a 20 cm). A faixa escura é onde fica a maior parte da região; o ponto terracota é o seu."
    )
    region = region_soil(location.latitude, location.longitude)
    rows, assumed = _build_soil_compare_rows(profile, region)
    if assumed:
        st.info(
            f"Itens marcados como **(assumido)** ({', '.join(assumed)}) usam valores típicos do semiárido "
            "porque o satélite não os mede; informe os dados em **Se você tiver análise de solo** abaixo para substituí-los."
        )
    if region is None:
        st.info("A comparação com a região está indisponível agora (serviço de mapas do SoilGrids fora do ar).")
    components.soil_compare(rows, key="solo_regiao")
    for warning in profile.warnings:
        st.caption(warning)


# --- solo por cultura -----------------------------------------------------------------

def _crop_detail(c: CropSuitability) -> dict:
    cfg = load_yaml_config("aptidao")
    req = cfg["culturas"][c.crop_id]
    lim = c.limiting
    verdict = {
        "S1": f"O solo é bom para {c.name.lower()}",
        "S2": f"Serve para {c.name.lower()}, com atenção a {lim.label.lower()}",
        "S3": f"O solo limita {c.name.lower()}: {lim.label.lower()}",
        "N": f"O solo não é bom para {c.name.lower()}",
    }[c.suit_class]
    reqs = [
        {"k": "Nitrogênio", "v": _SENS[req["nitrogenio"]]},
        {"k": "Fósforo", "v": _SENS[req["fosforo"]]},
        {"k": "Potássio", "v": _SENS[req["potassio"]]},
        {"k": "Falta de água", "v": {"alta": "sofre muito", "media": "sofre médio", "baixa": "aguenta bem", "nula": "aguenta muito bem"}[req["agua"]]},
        {"k": "pH bom", "v": f"{_num(req['ph_otimo'][0])} a {_num(req['ph_otimo'][1])}"},
    ]
    factors = [
        {"tone": _DEGREE_TONE[f.degree], "grau": DEGREE_LABELS[f.degree], "label": f.label,
         "reason": f.reason}
        for f in sorted(c.factors, key=lambda f: f.rating)
    ]
    return {
        "icon": CROP_ICONS[c.crop_id], "eyebrow": "Solo para esta cultura", "title": c.name,
        "verdict": verdict, "tone": _SUIT_TONE[c.suit_class],
        "text": cfg["descricao_culturas"][c.crop_id],
        "score": c.index, "score_label": f"nota do solo · {c.label}",
        "reqs": reqs, "factors": factors, "factors_title": "O que pesa, do mais fraco ao mais forte",
        "foot": "Comparação fator por fator (Ramalho Filho & Beek; notas de Sys et al.). "
                "Exigências das culturas em revisão por agrônomo.",
    }


def _crop_soil_section(results: list[CropSuitability]) -> None:
    theme.label("Solo por cultura")
    st.header("O solo é bom para quê?", anchor=False)
    st.markdown("O mesmo solo pode ser bom para uma cultura e ruim para outra. **Escolha uma cultura** para ver o porquê.")
    by_id = {c.crop_id: c for c in results}
    items = [{"id": c.crop_id, "name": c.name, "icon": CROP_ICONS[c.crop_id], "status": c.label,
              "tone": _SUIT_TONE[c.suit_class]} for c in results]
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        chosen = stored("cultura", results[0].crop_id)
        chosen = components.crop_cards(items, chosen if chosen in by_id else results[0].crop_id, key="cards_inicio")
        store("cultura", chosen)
    with right:
        components.crop_hero(_crop_detail(by_id[chosen]), key="destaque_inicio")


# --- solo e relevo ---------------------------------------------------------------------

def _terrain_section(location, profile: SoilProfile) -> None:
    theme.label("Solo e relevo")
    st.header("O terreno", anchor=False)
    sand, clay = profile.get("areia_pct"), profile.get("argila_pct")
    silt = max(0.0, 100.0 - sand - clay)
    tri = texture_triangle(sand, clay, silt)
    group = texture_class(sand, clay)
    cad = load_yaml_config("aptidao")["cad_mm_por_m"][group]
    slope = profile.get("declividade_pct")
    relief = relief_class(slope)
    src_tex = _SOURCE[profile.source_of("areia_pct")]
    elev = profile.elevation_m
    data = {
        "tipo": f"{relief['nome'].capitalize()}, textura {tri}",
        "tipo_txt": (f"Relevo {relief['nome']} ({_num(slope)}% de declividade) e solo de textura {tri} "
                     f"(grupamento {TEXTURE_LABELS[group]}), que segura cerca de {cad} mm de água por metro de solo. "
                     "Classes do triângulo textural (SBCS/USDA) e de relevo da Embrapa."),
        "gran": {"areia": sand, "silte": silt, "argila": clay},
        "cards": [
            {"kind": "gran", "label": "Areia, silte e argila", "value": tri.capitalize(),
             "text": "Mais areia: a água escorre e seca rápido. Mais argila: segura mais água e nutrientes.",
             "source": src_tex},
            {"kind": "escala", "label": "Relevo", "value": f"{relief['nome'].capitalize()} ({_num(slope)}%)",
             "steps": RELIEF_STEPS, "on": RELIEF_STEPS.index(relief["nome"]),
             "text": "Quanto mais inclinado, mais a chuva forte leva a terra embora.",
             "source": "SRTM (Terrain Tiles), pixel de ~38 m"},
            {"kind": "", "label": "Água que o solo segura", "value": f"{cad} mm por metro",
             "text": f"Valor de referência para solo de textura {TEXTURE_LABELS[group]} (em revisão por agrônomo).",
             "source": "config/aptidao.yaml"},
            {"kind": "", "label": "Altitude", "value": f"{elev:.0f} m" if elev is not None else "—",
             "text": "Altura do terreno em relação ao nível do mar.", "source": "SRTM (Terrain Tiles)"},
        ],
    }
    components.terrain_panel(data, key="terreno_inicio")
    _field_form(location.location_id, profile)


def _field_form(location_id: str, profile: SoilProfile) -> None:
    current = {a: v.value for a, v in profile.values.items() if v.source == "campo"}
    with st.expander("Tenho análise de solo da roça (deixa o resultado mais preciso)", expanded=False):
        st.caption(
            "Copie os números do laudo do laboratório (camada 0-20 cm). Deixe vazio o que não tiver: "
            "o app usa o mapa de satélite ou o valor típico da região. Fósforo, potássio e V% "
            "**só a análise mede**. Os dados ficam só neste computador."
        )
        with st.form(f"campo_{location_id}"):
            cols = st.columns(3)
            entered: dict[str, float | None] = {}
            for i, (attr, (label, unit, digits)) in enumerate(ATTRIBUTES.items()):
                entered[attr] = cols[i % 3].number_input(
                    f"{label}{f' ({unit})' if unit else ''}",
                    min_value=0.0,
                    value=current.get(attr),
                    step=10 ** (-digits) if digits else 1.0,
                    format=f"%.{digits}f",
                    key=f"campo_{location_id}_{attr}",
                )
            entered[DEPTH_FIELD] = cols[0].number_input(
                "Profundidade do solo até a pedra (cm)",
                min_value=0.0, max_value=300.0, value=profile.depth_cm, step=5.0, format="%.0f",
                key=f"campo_{location_id}_{DEPTH_FIELD}",
                help="Deixe vazio se o solo é fundo ou se não sabe. Solo raso segura menos água para a raiz.",
            )
            nota = st.text_input("Observação (laboratório, data da coleta...)", key=f"campo_{location_id}_nota")
            c1, c2 = st.columns(2)
            if c1.form_submit_button("Salvar análise", type="primary"):
                save_field_data(location_id, entered, nota)
                st.rerun()
            if c2.form_submit_button("Apagar análise salva"):
                clear_field_data(location_id)
                st.rerun()


def home_page() -> None:
    arrived("inicio")
    location, roca = current_location()
    today = date.today()
    _roca_section(location, roca)
    location, roca = current_location()  # o seletor de exemplo pode ter mudado o local
    profile = soil_profile(location)
    results = evaluate(profile)
    theme.divider()
    _rain_section(location, today)
    theme.divider()
    _soil_place_section(location, profile)
    theme.divider()
    _crop_soil_section(results)
    theme.divider()
    _terrain_section(location, profile)
    theme.cta(
        "Com esse solo e essa chuva, o que plantar agora?",
        "Veja o aviso do Acauã para cada cultura e qual plano rende mais estável nos próximos anos.",
        "plantio",
        "Ver o que plantar agora",
    )
    theme.footer(
        "Fontes: chuva NASA POWER; solo ISRIC SoilGrids 2.0 (250 m, 0-20 cm) e mapas WCS para a região; relevo SRTM "
        "(Terrain Tiles/AWS). Classes de análise: Alvarez V. et al. (1999). Limitação por cultura: Ramalho Filho & "
        "Beek (Embrapa) e Sys et al. (1991); exigências a revisar por agrônomo."
    )
