"""Identidade visual do Acauã: cores, fontes, elemento gráfico e componentes de página.

Regras (docs/features/05-identidade-visual.md):
- base neutra (creme + petróleo); terracota é a única cor de destaque, usada pouco;
- um só elemento gráfico recorrente: o "pixel" ocre (quadradinhos em escada, como o pixel do
  satélite), em divisores e rótulos;
- Montserrat = títulos, Inter = texto, IBM Plex Mono = rótulos pequenos;
- no máximo 2 animações, desligadas com prefers-reduced-motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parent / "assets" / "marca"


@dataclass(frozen=True)
class Palette:
    petroleo: str = "#163037"  # ave, letreiro, texto
    petroleo_2: str = "#2C4A52"  # texto secundário em blocos
    texto_suave: str = "#56676B"  # legendas (5,2:1 sobre o creme)
    creme: str = "#F2EFEA"  # fundo das pranchas
    areia: str = "#E8E2D6"  # campos e blocos
    linha: str = "#D9D0BF"  # bordas
    terracota: str = "#9C6346"  # destaque (botões, CTA); 4,9:1 com branco
    terracota_ilustracao: str = "#A46B4D"  # peito da ave
    ocre: str = "#BB9252"  # só o elemento gráfico (pixel), nunca texto
    verde: str = "#266F49"
    amarelo: str = "#DDA848"
    vermelho: str = "#AA281E"


COLORS = Palette()
FONT_DISPLAY = "Montserrat, Inter, sans-serif"
FONT_TEXT = "Inter, sans-serif"
FONT_LABEL = "'IBM Plex Mono', ui-monospace, monospace"


def asset(name: str) -> str:
    return str(ASSETS / name)


# --- CSS -------------------------------------------------------------------------

def _css() -> str:
    c = COLORS
    return f"""
<style>
:root {{
  --acaua-petroleo: {c.petroleo};
  --acaua-petroleo-2: {c.petroleo_2};
  --acaua-texto-suave: {c.texto_suave};
  --acaua-creme: {c.creme};
  --acaua-areia: {c.areia};
  --acaua-linha: {c.linha};
  --acaua-terracota: {c.terracota};
  --acaua-ocre: {c.ocre};
  --acaua-verde: {c.verde};
  --acaua-amarelo: {c.amarelo};
  --acaua-vermelho: {c.vermelho};
  --acaua-fonte-display: {FONT_DISPLAY};
  --acaua-fonte-rotulo: {FONT_LABEL};
}}

/* respiro: uma seção = um objetivo */
[data-testid="stMainBlockContainer"] {{ padding-top: 5.5rem; padding-bottom: 4rem; max-width: 1180px; }}
h1, h2, h3 {{ letter-spacing: -0.01em; color: var(--acaua-petroleo); }}
h1 {{ margin-bottom: 0.25rem; }}

/* rótulo: o pixel ocre + texto mono pequeno */
.acaua-rotulo {{
  font-family: var(--acaua-fonte-rotulo); font-size: 0.72rem; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--acaua-texto-suave);
  display: flex; align-items: center; gap: 1.1rem; margin: 0 0 0.35rem 0;
}}
/* o pixel: dois quadradinhos em escada (desenhados em CSS; o st.html remove SVG) */
.acaua-rotulo::before {{
  content: ""; width: 6px; height: 6px; background: var(--acaua-ocre); flex: none;
  box-shadow: 8px -5px 0 0 var(--acaua-ocre);
}}
.acaua-subtitulo {{ color: var(--acaua-texto-suave); font-size: 1rem; margin: 0.15rem 0 0 0; }}
.acaua-fonte {{ font-family: var(--acaua-fonte-rotulo); font-size: 0.72rem; color: var(--acaua-texto-suave); }}

/* divisor: linha ocre fina com o pixel em escada na ponta */
.acaua-divisor {{ display: flex; align-items: flex-end; gap: 14px; margin: 2.5rem 0 1.75rem 0; padding-top: 10px; }}
.acaua-divisor::before {{
  content: ""; width: 6px; height: 6px; background: var(--acaua-ocre); flex: none; margin-right: 18px;
  box-shadow: 9px -4px 0 0 rgba(187,146,82,0.8), 18px -8px 0 0 rgba(187,146,82,0.55);
}}
.acaua-divisor .linha {{ flex: 1; height: 1px; background: var(--acaua-ocre); opacity: 0.55; margin-bottom: 2px; }}

/* métricas: número em display, rótulo discreto */
[data-testid="stMetricValue"] {{ font-family: var(--acaua-fonte-display); font-weight: 700; color: var(--acaua-petroleo); }}
[data-testid="stMetricLabel"] p {{ color: var(--acaua-texto-suave); }}

/* abas e controle de horizonte com a tipografia de título */
.stTabs [data-baseweb="tab"] p {{ font-family: var(--acaua-fonte-display); font-weight: 600; }}

/* aviso do Acauã (semáforo) */
.st-key-aviso-verde, .st-key-aviso-amarelo, .st-key-aviso-vermelho {{
  background: #FFFFFF80; border: 1px solid var(--acaua-linha); border-left-width: 10px;
  border-radius: 0.75rem; padding: 1.25rem 1.5rem;
}}
.st-key-aviso-verde {{ border-left-color: var(--acaua-verde); }}
.st-key-aviso-amarelo {{ border-left-color: var(--acaua-amarelo); }}
.st-key-aviso-vermelho {{ border-left-color: var(--acaua-vermelho); }}
.acaua-aviso-palavra {{ font-family: var(--acaua-fonte-display); font-weight: 800; font-size: 2.1rem;
  line-height: 1.1; margin: 0.1rem 0 0.4rem 0; }}
.acaua-aviso-palavra.verde {{ color: var(--acaua-verde); }}
.acaua-aviso-palavra.amarelo {{ color: #8A5E12; }}
.acaua-aviso-palavra.vermelho {{ color: var(--acaua-vermelho); }}
.acaua-aviso-detalhe {{ font-size: 1.05rem; color: var(--acaua-petroleo); margin: 0; }}

/* faixa de chamada: o único bloco grande na cor de destaque */
.st-key-acaua-cta {{ background: var(--acaua-terracota); border-radius: 0.9rem; padding: 2rem 2.25rem;
  margin-top: 2.5rem; }}
.st-key-acaua-cta p, .st-key-acaua-cta h3 {{ color: #FFFFFF; }}
.st-key-acaua-cta h3 {{ margin: 0 0 0.25rem 0; }}
.st-key-acaua-cta [data-testid="stPageLink"] a {{ background: #FFFFFF; border-radius: 0.5rem;
  padding: 0.55rem 1.1rem; display: inline-flex; }}
.st-key-acaua-cta [data-testid="stPageLink"] p {{ color: var(--acaua-terracota); font-weight: 600; }}

/* celular: o mascote não pode empurrar a informação para baixo */
@media (max-width: 640px) {{
  .st-key-acaua-mascote-cabecalho {{ display: none; }}
  .st-key-aviso-verde img, .st-key-aviso-amarelo img, .st-key-aviso-vermelho img {{
    max-width: 120px !important; height: auto !important;
  }}
  .acaua-aviso-palavra {{ font-size: 1.7rem; }}
}}

/* rodapé com o slogan */
.acaua-rodape {{ margin-top: 3rem; color: var(--acaua-texto-suave); font-size: 0.85rem; }}
.acaua-rodape strong {{ font-family: var(--acaua-fonte-display); color: var(--acaua-petroleo); }}

/* animações (no máximo 2): entrada do aviso e botão primário */
@media (prefers-reduced-motion: no-preference) {{
  .st-key-aviso-verde, .st-key-aviso-amarelo, .st-key-aviso-vermelho {{
    animation: acaua-surge 420ms ease-out both;
  }}
  @keyframes acaua-surge {{ from {{ opacity: 0; transform: translateY(6px); }} to {{ opacity: 1; transform: none; }} }}
  .stButton button[kind="primary"], .st-key-acaua-cta [data-testid="stPageLink"] a {{
    transition: transform 150ms ease-out;
  }}
  .stButton button[kind="primary"]:hover, .st-key-acaua-cta [data-testid="stPageLink"] a:hover {{
    transform: translateY(-1px);
  }}
}}
</style>
"""


def inject() -> None:
    """Aplica o CSS da marca (chamar uma vez por execução, antes das páginas)."""
    st.html(_css())


# --- componentes ---------------------------------------------------------------

def divider() -> None:
    """Divisor da marca: pixel em escada + linha ocre fina."""
    st.html('<div class="acaua-divisor"><div class="linha"></div></div>')


def label(text: str) -> None:
    """Rótulo pequeno em mono, com o pixel ocre."""
    st.html(f'<p class="acaua-rotulo">{escape(text)}</p>')


def page_header(eyebrow: str, title: str, subtitle: str | None = None, mascot: str | None = None) -> None:
    """Cabeçalho de página: rótulo, título e (opcional) uma pose do mascote à direita."""
    if mascot:
        left, right = st.columns([5, 1], vertical_alignment="center")
    else:
        left, right = st.container(), None
    with left:
        label(eyebrow)
        st.title(title, anchor=False)
        if subtitle:
            st.html(f'<p class="acaua-subtitulo">{escape(subtitle)}</p>')
    if right is not None and mascot:
        with right.container(key="acaua-mascote-cabecalho"):
            st.image(asset(mascot), width=120)


_AVISO = {
    # nível -> (palavra principal, pose do mascote). Palavras do CLAUDE.md, seção 8.
    "verde": ("Pode plantar", "mascote_broto.png"),
    "amarelo": ("Arriscado", "mascote_canto.png"),
    "vermelho": ("Não plante agora", "mascote_asas.png"),
}


def status_card(level: str, detail: str, extra: str | None = None) -> None:
    """O aviso do Acauã: cor + palavra + mascote (o semáforo nunca depende só da cor)."""
    word, mascot = _AVISO[level]
    with st.container(key=f"aviso-{level}"):
        art, text = st.columns([1, 4], vertical_alignment="center")
        art.image(asset(mascot), width="stretch")
        with text:
            label("O aviso do Acauã")
            st.html(f'<p class="acaua-aviso-palavra {level}">{escape(word)}</p>')
            st.html(f'<p class="acaua-aviso-detalhe">{escape(detail)}</p>')
            if extra:
                st.caption(extra)


def cta(title: str, body: str, page_name: str, link_label: str) -> None:
    """Faixa de chamada no fim da página (o único bloco grande em terracota)."""
    from crop_optimizer.app import navigation

    with st.container(key="acaua-cta"):
        st.subheader(title, anchor=False)
        st.markdown(body)
        navigation.link(page_name, link_label)


def footer(sources: str) -> None:
    st.html(
        '<div class="acaua-rodape"><strong>Acauã</strong> · O profeta da chuva que enxerga do espaço.'
        " Apoia a decisão, não substitui o agricultor e o técnico.</div>"
    )
    st.html(f'<p class="acaua-fonte">{escape(sources)}</p>')


# --- gráficos --------------------------------------------------------------------

def plotly_layout(fig, height: int | None = None):
    """Fundo transparente, fontes e cores da marca nos gráficos Plotly."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_TEXT, color=COLORS.petroleo, size=13),
        title_font=dict(family=FONT_DISPLAY, size=16, color=COLORS.petroleo),
        legend_font=dict(family=FONT_TEXT, size=12),
        colorway=[COLORS.petroleo, COLORS.terracota_ilustracao, COLORS.ocre, COLORS.verde, "#6E8A90"],
    )
    fig.update_xaxes(gridcolor=COLORS.linha, zerolinecolor=COLORS.linha, linecolor=COLORS.linha)
    fig.update_yaxes(gridcolor=COLORS.linha, zerolinecolor=COLORS.linha, linecolor=COLORS.linha)
    if height:
        fig.update_layout(height=height)
    return fig
