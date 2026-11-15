"""Ícones das culturas em SVG, no estilo do mascote: formas cheias, petróleo + terracota + ocre.

Desenhados à mão para o projeto (sem banco de imagens). viewBox 64x64, fundo transparente.
"""

from __future__ import annotations

_P = "#163037"  # petróleo
_P2 = "#2C4A52"  # petróleo médio
_T = "#A46B4D"  # terracota da ilustração
_O = "#BB9252"  # ocre


def _svg(body: str) -> str:
    return f'<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{body}</svg>'


MILHO = _svg(
    f'<path d="M32 5c7.5 0 11.5 10 11.5 23S39.5 52 32 52s-11.5-11-11.5-24S24.5 5 32 5z" fill="{_O}"/>'
    f'<g stroke="{_P}" stroke-opacity=".28" stroke-width="1.6" fill="none">'
    '<path d="M23.2 17h17.6M21.6 24h20.8M21 31h22M21.4 38h21.2"/>'
    '<path d="M27.5 8v42M32 5v47M36.5 8v42"/></g>'
    f'<path d="M32 59c-9-4-17-15-17-31 4 9 10 14 17 17z" fill="{_P}"/>'
    f'<path d="M32 59c9-4 17-15 17-31-4 9-10 14-17 17z" fill="{_P2}"/>'
    f'<rect x="30" y="55" width="4" height="7" rx="1.5" fill="{_P}"/>'
)

FEIJAO_CAUPI = _svg(
    f'<path d="M8 46C18 26 34 13 56 8c-2 8-7 14-14 19C33 34 22 41 8 46z" fill="{_P}"/>'
    f'<ellipse cx="20" cy="38" rx="5" ry="3.4" transform="rotate(-32 20 38)" fill="{_T}"/>'
    f'<ellipse cx="30.5" cy="30.5" rx="5" ry="3.4" transform="rotate(-32 30.5 30.5)" fill="{_T}"/>'
    f'<ellipse cx="41" cy="22.5" rx="5" ry="3.4" transform="rotate(-32 41 22.5)" fill="{_T}"/>'
    f'<path d="M55 9l5-4" stroke="{_P}" stroke-width="3" stroke-linecap="round"/>'
    f'<path d="M14 58c-3-9 1-16 11-17-1 8-5 14-11 17z" fill="{_O}"/>'
    f'<path d="M27 58c0-8 5-13 13-12-2 7-7 11-13 12z" fill="{_O}" opacity=".8"/>'
)

SORGO = _svg(
    f'<path d="M32 61V29" stroke="{_P}" stroke-width="3.5" stroke-linecap="round"/>'
    f'<path d="M32 49c-9-2-15-9-17-18 9 2 14 8 17 18z" fill="{_P}"/>'
    f'<path d="M32 42c9-2 14-8 16-16-8 2-13 7-16 16z" fill="{_P2}"/>'
    + "".join(
        f'<circle cx="{x}" cy="{y}" r="3.6" fill="{_T}"/>'
        for x, y in ((32, 6), (27.5, 10.5), (36.5, 10.5), (25, 16), (32, 15), (39, 16),
                     (27.5, 21), (36.5, 21), (32, 25))
    )
)

PALMA = _svg(
    f'<ellipse cx="32" cy="45" rx="11.5" ry="14" fill="{_P}"/>'
    f'<ellipse cx="21" cy="24" rx="8" ry="11.5" transform="rotate(-24 21 24)" fill="{_P2}"/>'
    f'<ellipse cx="43" cy="22" rx="8" ry="11.5" transform="rotate(24 43 22)" fill="{_P}"/>'
    f'<ellipse cx="46.5" cy="9" rx="3.2" ry="4" fill="{_T}"/>'
    + "".join(
        f'<circle cx="{x}" cy="{y}" r="1.4" fill="{_O}"/>'
        for x, y in ((27, 40), (36, 38), (31, 48), (38, 50), (26, 52), (19, 22), (23, 29),
                     (42, 18), (45, 26), (40, 28))
    )
    + f'<rect x="17" y="58.5" width="30" height="3" rx="1.5" fill="{_O}"/>'
)

CAPIM_BUFFEL = _svg(
    f'<path d="M31 59C29 45 21 35 9 31c9 6 15 15 18 28z" fill="{_P}"/>'
    f'<path d="M33 59C35 45 43 35 55 31c-9 6-15 15-18 28z" fill="{_P}"/>'
    f'<path d="M30.5 59C28 42 24 27 17 15c9 10 14 26 15.5 44z" fill="{_P2}"/>'
    f'<path d="M33.5 59C36 42 40 27 47 15c-9 10-14 26-15.5 44z" fill="{_P2}"/>'
    f'<path d="M32 59V20" stroke="{_P}" stroke-width="2.4" stroke-linecap="round"/>'
    f'<ellipse cx="32" cy="12" rx="3.4" ry="9" fill="{_O}"/>'
    f'<ellipse cx="32" cy="12" rx="1.2" ry="6.5" fill="{_P}" opacity=".18"/>'
    f'<rect x="20" y="58.5" width="24" height="3" rx="1.5" fill="{_O}"/>'
)

# --- culturas adicionadas na Feature 9 ------------------------------------------------------

_C = "#F2EFEA"  # creme (brilho e polpa)


def _leaf(cx: float, cy: float, rx: float, ry: float, rot: float, fill: str) -> str:
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" transform="rotate({rot} {cx} {cy})" fill="{fill}"/>'


def _bean(cx: float, cy: float, rot: float, fill: str) -> str:
    """Grão em forma de rim."""
    return (f'<path d="M{cx - 7} {cy}c0-5 4-7.5 8-6.5 3 .7 3 2.5 6 2.3 2 0 2.5 2.4 2 4.2-1 4.5-6 7-10.5 6.5'
            f'-3.5-.4-5.5-3-5.5-6.5z" transform="rotate({rot} {cx} {cy})" fill="{fill}"/>')


FEIJAO_COMUM = _svg(
    _leaf(44, 15, 6, 11, 40, _P) + _leaf(52, 27, 5, 9, 80, _P2)
    + f'<path d="M44 26C40 34 36 40 30 44" stroke="{_P}" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
    + _bean(18, 40, -10, _T) + _bean(32, 50, 15, _T) + _bean(17, 54, 5, _O)
)

FAVA = _svg(
    f'<path d="M6 40C10 22 30 10 54 12c4 1 5 4 2 7C46 33 30 44 12 48c-5 1-7-3-6-8z" fill="{_O}"/>'
    + "".join(f'<circle cx="{x}" cy="{y}" r="5.4" fill="{_P}"/><circle cx="{x - 1.5}" cy="{y - 1.6}" r="1.6" fill="{_C}" opacity=".5"/>'
              for x, y in ((18, 37), (30, 29), (42, 21)))
    + f'<path d="M55 13l5-5" stroke="{_P}" stroke-width="3" stroke-linecap="round"/>'
    + f'<rect x="12" y="57" width="40" height="3" rx="1.5" fill="{_P2}" opacity=".5"/>'
)

MANDIOCA = _svg(
    "".join(_leaf(32 + 10 * dx, 12 + 3 * abs(dx), 3.6, 9, 30 * dx, _P if dx % 2 == 0 else _P2) for dx in (-2, -1, 0, 1, 2))
    + f'<path d="M32 18v14" stroke="{_P}" stroke-width="3" stroke-linecap="round"/>'
    + f'<path d="M31 31c-8 4-14 13-17 27 6-6 12-13 17-27z" fill="{_T}"/>'
    + f'<path d="M32 31c0 9 1 19 0 30 3-10 5-20 0-30z" fill="{_T}"/>'
    + f'<path d="M33 31c8 4 14 12 17 25-6-6-12-12-17-25z" fill="{_O}"/>'
)

BATATA_DOCE = _svg(
    f'<path d="M10 40c4-12 18-18 32-16s16 10 12 18-16 14-30 12S7 49 10 40z" fill="{_T}"/>'
    + f'<path d="M18 36c6-4 14-5 21-4" stroke="{_C}" stroke-width="1.6" opacity=".45" fill="none" stroke-linecap="round"/>'
    + f'<path d="M44 26c-2-8 1-15 8-19" stroke="{_P}" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
    + f'<path d="M52 7c-8-3-14 3-10 9 2 3 7 3 10-1 3-3 2-6 0-8z" fill="{_P}"/>'
    + f'<path d="M60 20c-6-4-12 0-10 5 1 3 6 4 9 1 2-2 2-4 1-6z" fill="{_P2}"/>'
)

CENOURA = _svg(
    _leaf(26, 12, 3.5, 10, -25, _P) + _leaf(32, 10, 3.5, 10, 0, _P2) + _leaf(38, 12, 3.5, 10, 25, _P)
    + f'<path d="M20 22h24c1 0 2 1 1.6 2.4L33.4 60c-.5 1.6-2.3 1.6-2.8 0L18.4 24.4C18 23 19 22 20 22z" fill="{_T}"/>'
    + f'<g stroke="{_C}" stroke-opacity=".45" stroke-width="1.6" stroke-linecap="round">'
    '<path d="M24 30h6M33 38h6M26 45h5M33 51h3"/></g>'
)

ALFACE = _svg(
    f'<path d="M32 58C14 58 5 46 7 32c2-11 9-18 15-17 2-6 7-9 10-9s8 3 10 9c6-1 13 6 15 17 2 14-7 26-25 26z" fill="{_P2}"/>'
    + f'<path d="M32 54c-12 0-18-9-17-19 1-8 6-13 10-12 2-4 5-6 7-6s5 2 7 6c4-1 9 4 10 12 1 10-5 19-17 19z" fill="{_P}"/>'
    + f'<path d="M32 49c-6 0-10-5-9-11 1-5 5-8 9-8s8 3 9 8c1 6-3 11-9 11z" fill="{_O}"/>'
    + f'<path d="M32 49V33" stroke="{_P}" stroke-width="1.6" opacity=".4"/>'
)

RUCULA = _svg(
    f'<path d="M28 60V30" stroke="{_P}" stroke-width="2.6" stroke-linecap="round"/>'
    f'<path d="M36 60V24" stroke="{_P2}" stroke-width="2.6" stroke-linecap="round"/>'
    + "".join(_leaf(x, y, 5.5 - i * .5, 4, r, _P if i % 2 == 0 else _P2) for i, (x, y, r) in
              enumerate(((22, 46, -20), (34, 48, 20), (21, 36, -25), (32, 38, 25), (24, 26, -10), (42, 30, 25), (40, 18, 10), (28, 18, -15))))
    + f'<rect x="14" y="58.5" width="36" height="3" rx="1.5" fill="{_O}"/>'
)

COENTRO = _svg(
    f'<g stroke="{_P}" stroke-width="2" stroke-linecap="round" fill="none">'
    '<path d="M32 60V36M32 44l-12-10M32 40l12-12M32 50l10-6"/></g>'
    + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>' for x, y, r, c in (
        (17, 30, 5, _P), (22, 25, 4, _P2), (13, 24, 3.6, _P2),
        (46, 25, 5, _P), (41, 20, 4, _P2), (50, 18, 3.6, _P2),
        (32, 30, 5, _P2), (28, 25, 3.6, _P), (36, 25, 3.6, _P),
        (44, 42, 4.2, _P2), (49, 38, 3.2, _P)))
    + f'<rect x="18" y="58.5" width="28" height="3" rx="1.5" fill="{_O}"/>'
)

CEBOLINHA = _svg(
    "".join(f'<path d="M{x} 50C{x} 34 {x + d} 18 {x + 2 * d} 5" stroke="{c}" stroke-width="4.2" fill="none" stroke-linecap="round"/>'
            for x, d, c in ((24, -3, _P), (29, -1, _P2), (34, 1, _P), (39, 3, _P2)))
    + f'<rect x="20" y="38" width="24" height="6" rx="2" fill="{_T}"/>'
    + f'<path d="M22 50h20l-2 9c-.4 1.5-1.5 2-3 2H27c-1.5 0-2.6-.5-3-2z" fill="{_O}"/>'
)

ESPINAFRE = _svg(
    f'<path d="M30 60C17 52 9 38 12 24c3-12 13-17 20-15-3 11-3 31-2 51z" fill="{_P}"/>'
    f'<path d="M34 60c13-8 21-22 18-36-3-12-13-17-20-15 3 11 3 31 2 51z" fill="{_P2}"/>'
    f'<path d="M30 58C24 44 22 30 28 14M34 58c6-14 8-28 2-44" stroke="{_O}" stroke-width="1.6" fill="none" opacity=".7"/>'
)

RABANETE = _svg(
    _leaf(25, 13, 5, 11, -30, _P) + _leaf(39, 13, 5, 11, 30, _P2) + _leaf(32, 11, 4, 10, 0, _P)
    + f'<circle cx="32" cy="38" r="15" fill="{_T}"/>'
    + f'<path d="M32 53c1 4 .6 7-1 9" stroke="{_T}" stroke-width="2" fill="none" stroke-linecap="round"/>'
    + f'<path d="M23 33c2-5 6-7 10-7" stroke="{_C}" stroke-width="2.4" opacity=".45" fill="none" stroke-linecap="round"/>'
)

TOMATE = _svg(
    f'<circle cx="32" cy="37" r="22" fill="{_T}"/>'
    + f'<path d="M20 31c2-6 7-10 13-11" stroke="{_C}" stroke-width="3" opacity=".4" fill="none" stroke-linecap="round"/>'
    + f'<path d="M32 18l-4-6 4 3 4-3-4 6 9-3-7 5 6 4-8-2-8 2 6-4-7-5z" fill="{_P}"/>'
    + f'<path d="M32 13V5" stroke="{_P}" stroke-width="2.6" stroke-linecap="round"/>'
)

PIMENTAO = _svg(
    f'<path d="M16 24c4-6 10-6 16-3 6-3 12-3 16 3 5 8 3 22-2 30-3 5-8 6-14 6s-11-1-14-6c-5-8-7-22-2-30z" fill="{_O}"/>'
    + f'<path d="M32 21c-2 10-2 24 0 39" stroke="{_P}" stroke-opacity=".2" stroke-width="2" fill="none"/>'
    + f'<path d="M22 30c0-3 2-5 4-6" stroke="{_C}" stroke-width="2.6" opacity=".5" fill="none" stroke-linecap="round"/>'
    + f'<path d="M26 20c2-3 10-3 12 0" stroke="{_P}" stroke-width="5" fill="none" stroke-linecap="round"/>'
    + f'<path d="M32 18c0-6 3-10 8-12" stroke="{_P}" stroke-width="3" fill="none" stroke-linecap="round"/>'
)

PIMENTA = _svg(
    f'<path d="M20 14c-4 14-4 30 4 44 1 2 3 1 3-1-2-14 0-28 4-40z" fill="{_T}"/>'
    f'<path d="M36 18c2 13 8 25 18 34 2 1 3-1 2-3-6-12-8-22-8-33z" fill="{_T}" opacity=".85"/>'
    f'<path d="M18 13c3-3 9-3 12 1l-1 4c-3-2-7-2-10 0z" fill="{_P}"/>'
    f'<path d="M35 17c3-3 9-3 13 0l-1 4c-3-2-7-2-11 0z" fill="{_P2}"/>'
    f'<path d="M24 12c0-4 2-7 5-8M41 16c0-4 2-7 5-8" stroke="{_P}" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
)

MORANGO = _svg(
    f'<path d="M32 60C18 50 10 38 12 28c2-8 10-10 20-8 10-2 18 0 20 8 2 10-6 22-20 32z" fill="{_T}"/>'
    + "".join(f'<ellipse cx="{x}" cy="{y}" rx="1.1" ry="1.7" fill="{_O}"/>' for x, y in (
        (22, 30), (30, 28), (38, 28), (44, 32), (19, 38), (27, 37), (35, 36), (42, 40),
        (24, 45), (32, 45), (38, 48), (30, 53)))
    + f'<path d="M32 22l-10-6 7 1-3-7 6 6 0-8 3 8 5-6-2 7 8-2z" fill="{_P}"/>'
)

MARACUJA = _svg(
    f'<path d="M44 14c6-6 14-4 15 2s-5 8-8 5c-2-2 0-5 3-4" stroke="{_P}" stroke-width="2" fill="none" stroke-linecap="round"/>'
    + _leaf(18, 14, 6, 10, -40, _P) + _leaf(12, 24, 5, 8, -80, _P2)
    + f'<circle cx="34" cy="38" r="20" fill="{_O}"/>'
    + "".join(f'<circle cx="{x}" cy="{y}" r="1" fill="{_P}" opacity=".35"/>' for x, y in (
        (26, 30), (40, 28), (46, 40), (30, 46), (38, 50), (22, 40)))
    + f'<path d="M24 30c3-5 8-7 13-7" stroke="{_C}" stroke-width="2.6" opacity=".5" fill="none" stroke-linecap="round"/>'
    + f'<path d="M34 18v-6" stroke="{_P}" stroke-width="2.6" stroke-linecap="round"/>'
)

MAMAO = _svg(
    f'<path d="M32 4c12 0 20 14 20 30S44 61 32 61 12 50 12 34 20 4 32 4z" fill="{_O}"/>'
    + f'<path d="M32 12c7 0 12 10 12 22s-5 19-12 19-12-7-12-19 5-22 12-22z" fill="{_T}"/>'
    + f'<path d="M32 22c3 0 5 6 5 12s-2 10-5 10-5-4-5-10 2-12 5-12z" fill="{_P}" opacity=".85"/>'
    + "".join(f'<circle cx="{x}" cy="{y}" r="1.2" fill="{_C}" opacity=".55"/>' for x, y in ((31, 28), (33, 34), (31, 40)))
)

BANANA = _svg(
    f'<path d="M10 22c2 20 16 34 38 34 4 0 6-3 3-5-17-2-28-14-32-30-1-4-9-4-9 1z" fill="{_O}"/>'
    f'<path d="M16 16c4 18 16 30 34 31 4 0 5-3 2-5C38 39 29 28 25 14c-1-4-10-3-9 2z" fill="{_O}" opacity=".85"/>'
    f'<path d="M14 18c4 16 14 28 30 33" stroke="{_T}" stroke-width="1.6" opacity=".5" fill="none"/>'
    f'<path d="M12 18l-2-8 7 1M19 14l-1-8 6 2" stroke="{_P}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    f'<circle cx="50" cy="53" r="2" fill="{_P}"/>'
)

LIMAO = _svg(
    _leaf(44, 14, 6, 12, 50, _P)
    + f'<path d="M38 20c-3-4-6-6-10-6" stroke="{_P}" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
    + f'<ellipse cx="30" cy="39" rx="20" ry="17" fill="{_P2}"/>'
    + f'<circle cx="30" cy="39" r="11" fill="{_O}" opacity=".9"/>'
    + "".join(f'<path d="M30 39l{dx} {dy}" stroke="{_P2}" stroke-width="1.4"/>' for dx, dy in (
        (0, -10), (8.7, -5), (8.7, 5), (0, 10), (-8.7, 5), (-8.7, -5)))
    + f'<circle cx="30" cy="39" r="1.8" fill="{_P2}"/>'
)


CROP_ICONS: dict[str, str] = {
    "milho_sertanejo": MILHO,
    "feijao_caupi": FEIJAO_CAUPI,
    "sorgo_forrageiro": SORGO,
    "palma_forrageira": PALMA,
    "capim_buffel": CAPIM_BUFFEL,
    "feijao_comum": FEIJAO_COMUM,
    "fava": FAVA,
    "mandioca": MANDIOCA,
    "batata_doce": BATATA_DOCE,
    "cenoura": CENOURA,
    "alface": ALFACE,
    "rucula": RUCULA,
    "coentro": COENTRO,
    "cebolinha": CEBOLINHA,
    "espinafre": ESPINAFRE,
    "rabanete": RABANETE,
    "tomate": TOMATE,
    "pimentao": PIMENTAO,
    "pimenta": PIMENTA,
    "morango": MORANGO,
    "maracuja": MARACUJA,
    "mamao": MAMAO,
    "banana": BANANA,
    "limao": LIMAO,
}
