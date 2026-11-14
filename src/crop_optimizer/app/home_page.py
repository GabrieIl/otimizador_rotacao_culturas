"""Página "Início": perfil do local (chuva, solo, relevo, janelas) e limitação do solo por cultura."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

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
from crop_optimizer.app import theme
from crop_optimizer.app.common import (
    current_location,
    example_selector,
    rain_delay_report,
    rain_series,
    soil_profile,
)
from crop_optimizer.app.state import arrived
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.soil_profile import (
    ATTRIBUTES,
    FIELD_ONLY,
    SoilProfile,
    clear_field_data,
    save_field_data,
)
from crop_optimizer.ingestion.rain_history import RainDataUnavailable

_SOURCE_BADGE = {
    "campo": "análise de campo",
    "satelite": "mapa/satélite",
    "referencia": "típico do semiárido (assumido)",
}
_ZARC_LABELS = {"milho_sertanejo": "Milho", "feijao_caupi": "Feijão-caupi", "sorgo_forrageiro": "Sorgo"}


def _fmt(attr: str, value: float) -> str:
    _, unit, digits = ATTRIBUTES[attr]
    return f"{value:.{digits}f} {unit}".strip()


def _attr_class(attr: str, profile: SoilProfile) -> str:
    cls = load_yaml_config("aptidao")["classes_analise"]
    v = profile.get(attr)
    if attr == "mo_pct":
        return CLASS_LABELS[classify(v, cls["mo_pct"])]
    if attr == "p_mehlich":
        return CLASS_LABELS[phosphorus_class(v, profile.get("argila_pct"))]
    if attr == "k_mg_dm3":
        return CLASS_LABELS[classify(v, cls["k_mg_dm3"])]
    if attr == "v_pct":
        return CLASS_LABELS[classify(v, cls["v_pct"])]
    if attr == "ctc_t":
        return CLASS_LABELS[classify(v, cls["ctc_t"])]
    if attr == "ph_h2o":
        return ["muito baixo", "baixo", "bom", "alto", "muito alto"][
            int(np.searchsorted(cls["ph_agronomico"], v, side="right"))
        ]
    if attr == "declividade_pct":
        return relief_class(v)["nome"]
    if attr in ("argila_pct", "areia_pct"):
        return "textura " + TEXTURE_LABELS[texture_class(profile.get("areia_pct"), profile.get("argila_pct"))]
    return ""


def _soil_table(profile: SoilProfile) -> pd.DataFrame:
    rows = []
    for attr, (label, _, _) in ATTRIBUTES.items():
        item = profile.values[attr]
        faixa = (
            f"{_fmt(attr, item.low)} a {_fmt(attr, item.high)}"
            if item.low is not None and item.high is not None
            else ""
        )
        rows.append(
            {
                "Atributo": label,
                "Valor": _fmt(attr, item.value),
                "Classe": _attr_class(attr, profile),
                "De onde veio": _SOURCE_BADGE[item.source],
                "Faixa provável (mapa)": faixa,
            }
        )
    return pd.DataFrame(rows)


def _suitability_table(results: list[CropSuitability]) -> pd.DataFrame:
    rows = []
    for c in results:
        lim = c.limiting
        effect = (c.yield_factor - 1.0) * 100
        rows.append(
            {
                "Cultura": c.name,
                "Situação do solo": f"{c.label}",
                "Índice (0-100)": round(c.index),
                "O que mais limita": "nada" if lim.degree == "nula" else f"{lim.label} ({DEGREE_LABELS[lim.degree]})",
                "Na simulação": "igual à roça típica" if abs(effect) < 1 else f"{effect:+.0f}% vs roça típica",
            }
        )
    return pd.DataFrame(rows)


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
    if roca is not None:
        theme.page_header("Perfil do local", roca.municipio and f"{roca.municipio}/{roca.uf}" or "Sua roça",
                          f"Sua roça · {roca.lat:.4f}, {roca.lon:.4f}", mascot="mascote_frente.png")
    else:
        theme.page_header("Perfil do local", f"{location.name}/{location.state}",
                          "Município de exemplo. Marque a sua roça no mapa para ver o ponto dela.",
                          mascot="mascote_frente.png")
        left, _ = st.columns([2, 3])
        with left:
            location = example_selector()

    today = date.today()
    loc_json = location.model_dump_json()

    # --- chuva -------------------------------------------------------------
    report = None
    annual = None
    try:
        report = rain_delay_report(loc_json, today)
        series = rain_series(loc_json, today)
        years = series.dates.astype("datetime64[Y]").astype(int) + 1970
        ref = report.status.reference
        mask = (years >= ref.first_year) & (years <= ref.last_year)
        annual = float(np.nansum(series.precip_mm[mask])) / (ref.last_year - ref.first_year + 1)
    except RainDataUnavailable as exc:
        st.error(f"Chuva indisponível: {exc}")

    profile = soil_profile(location)
    results = evaluate(profile)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Chuva no ano (média 1991-2020)", f"{annual:.0f} mm" if annual is not None else "—")
    c2.metric("A chuva costuma firmar em", fmt_date(report.status.reference_date) if report else "—")
    c3.metric("Altitude", f"{profile.elevation_m:.0f} m" if profile.elevation_m is not None else "—")
    slope = profile.values["declividade_pct"]
    c4.metric("Relevo", f"{relief_class(slope.value)['nome']}", help=f"Declividade de {slope.value:.1f}%")
    if report is not None:
        title, _, level = describe_status(report.status)
        getattr(st, level)(f"**Chuva agora:** {title}.")

    for warning in profile.warnings:
        st.warning(warning)

    # --- solo por cultura ---------------------------------------------------
    theme.divider()
    theme.label("Solo por cultura")
    st.header("O solo é bom para quê?", anchor=False)
    st.markdown(
        "O mesmo solo pode ser bom para uma cultura e ruim para outra: pouco nitrogênio pesa no milho, "
        "mas não no feijão-caupi, que fixa o próprio nitrogênio. **O fator mais fraco manda.**"
    )
    st.dataframe(_suitability_table(results), hide_index=True, width="stretch")
    if any(c.any_assumed for c in results) or any(profile.source_of(a) == "referencia" for a in FIELD_ONLY):
        st.info(
            "Sem análise de solo, fósforo, potássio e V% foram **assumidos** com o valor típico do semiárido: "
            "não pesam nem a favor nem contra. Uma análise de campo muda o resultado."
        )
    for c in results:
        with st.expander(f"{c.name}: por que {c.label.lower()}?"):
            for f in sorted(c.factors, key=lambda f: f.rating):
                mark = " _(assumido)_" if f.assumed else ""
                st.markdown(f"- **{f.label}:** limitação {DEGREE_LABELS[f.degree]}. {f.reason}.{mark}")

    # --- atributos do solo --------------------------------------------------
    theme.divider()
    theme.label("Solo e relevo")
    st.header("De onde vem cada número", anchor=False)
    if profile.field_date:
        st.caption(f"Análise de campo informada em {profile.field_date}.")
    st.dataframe(_soil_table(profile), hide_index=True, width="stretch")
    _field_form(location.location_id, profile)

    # --- janelas oficiais ---------------------------------------------------
    if report is not None:
        theme.divider()
        theme.label(f"ZARC {report.zarc_safra or ''} · MAPA/Embrapa".strip())
        st.header("Janela oficial de plantio", anchor=False)
        if report.zarc_error:
            st.warning(report.zarc_error)
        else:
            for cw in report.crop_windows:
                st.markdown(f"- **{_ZARC_LABELS.get(cw.crop_id, cw.crop_id)}**: {cw.phrase}")

    # --- chamada final (o único bloco grande na cor de destaque) -----------
    if roca is None:
        theme.cta(
            "Este perfil é do município. E a sua roça?",
            "Marque o ponto da roça no mapa: a chuva, o solo e as janelas passam a ser os dela.",
            "satelite",
            "Marcar a roça no mapa",
        )
    else:
        theme.cta(
            "Com esse solo e essa chuva, dá para plantar agora?",
            "Veja o aviso do Acauã e qual roça aguenta mais nos próximos anos.",
            "plantio",
            "Ver se dá para plantar",
        )

    theme.footer(
        "Fontes: solo ISRIC SoilGrids 2.0 (250 m, 0-20 cm); relevo SRTM (Terrain Tiles/AWS); chuva NASA POWER; "
        "janelas ZARC (MAPA/Embrapa). Classes de análise: Alvarez V. et al. (1999). Limitação por cultura: "
        "Ramalho Filho & Beek (Embrapa) e Sys et al. (1991); exigências a revisar por agrônomo."
    )
