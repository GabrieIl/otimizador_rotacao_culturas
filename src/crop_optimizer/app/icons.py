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

CROP_ICONS: dict[str, str] = {
    "milho_sertanejo": MILHO,
    "feijao_caupi": FEIJAO_CAUPI,
    "sorgo_forrageiro": SORGO,
    "palma_forrageira": PALMA,
    "capim_buffel": CAPIM_BUFFEL,
}
