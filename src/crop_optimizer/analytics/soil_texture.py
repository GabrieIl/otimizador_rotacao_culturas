"""Classe textural pelo triângulo textural (USDA, o mesmo usado pela SBCS) e tipo de terreno.

Regras do triângulo: USDA Soil Survey Manual / calculadora de textura do NRCS; nomes em português como
no Manual de descrição e coleta de solo no campo (SBCS). Com mais de 60% de argila, a SBCS chama de
"muito argilosa".
"""

from __future__ import annotations


def texture_class(sand: float, clay: float, silt: float | None = None) -> str:
    """Classe textural a partir de areia, argila e silte (%). Silte = 100 - areia - argila se faltar."""
    s, c = float(sand), float(clay)
    si = 100.0 - s - c if silt is None else float(silt)
    if c > 60:
        return "muito argilosa"
    if s > 85 and si + 1.5 * c < 15:
        return "areia"
    if 70 <= s <= 90 and si + 1.5 * c >= 15 and si + 2 * c < 30:
        return "areia franca"
    if (c <= 20 and s >= 52 and si + 2 * c >= 30) or (c < 7 and si < 50 and 43 <= s < 52):
        return "franco-arenosa"
    if 7 <= c <= 27 and 28 <= si < 50 and s <= 52:
        return "franca"
    if (si >= 50 and 12 <= c < 27) or (50 <= si < 80 and c < 12):
        return "franco-siltosa"
    if si >= 80 and c < 12:
        return "silte"
    if 20 <= c < 35 and si < 28 and s > 45:
        return "franco-argiloarenosa"
    if 27 <= c < 40 and 20 < s <= 45:
        return "franco-argilosa"
    if 27 <= c < 40 and s <= 20:
        return "franco-argilossiltosa"
    if c >= 35 and s > 45:
        return "argiloarenosa"
    if c >= 40 and si >= 40:
        return "argilossiltosa"
    return "argila"
