"""Planejamento dos talhões: o calendário de cada talhão, da cultura de hoje às próximas da rotação.

Regras:
- **A cultura plantada hoje** fica até a colheita (plantio + ciclo). Perene plantada (banana, palma...)
  fica no talhão o tempo todo, nos dois modos.
- **Safra de sequeiro**: o plantio é no dia em que a chuva costuma firmar (mediana de 1991-2020 do
  critério de Sivakumar, a mesma referência do atraso da chuva). Ciclo = soma das fases da FAO-56
  (config/agua.yaml) ou `ciclo_dias` do registro.
- **Modo "como planta hoje"**: cada talhão repete a cultura de hoje. Sequeiro: uma vez por safra. Com rega:
  replanta logo depois da colheita. Talhão sem cultura fica vazio.
- **Modo "plano do ranking"**: as culturas perenes da rotação ficam fixas nos talhões menores; as anuais
  giram entre os outros talhões, uma posição a cada safra (talhão j planta anuais[(j + safra) mod n]).
  Se a rotação só tem perenes, elas se repartem entre os talhões.

A simulação do ranking divide a área igualmente entre as culturas da rotação. Aqui elas vão para talhões de
tamanhos diferentes: a tela avisa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from crop_optimizer.analytics.agua import crop_water
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.crop_registry import crop_info, is_irrigated
from crop_optimizer.domain.fazenda import Fazenda, Talhao
from crop_optimizer.engine.rain_onset import OnsetReference

Mode = Literal["hoje", "ranking"]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


@dataclass(frozen=True, slots=True)
class Cultivo:
    crop_id: str
    inicio: date
    fim: date | None  # None = perene (até o fim do horizonte)
    origem: Literal["hoje", "plano", "perene"]


def cycle_days(crop_id: str) -> int:
    info = crop_info(crop_id)
    if "ciclo_dias" in info:
        return int(info["ciclo_dias"])
    return int(sum(crop_water(crop_id).phases)) or 365


def is_perennial_crop(crop_id: str) -> bool:
    return bool(crop_info(crop_id).get("perene")) or crop_water(crop_id).reserve_in_plant


def season_starts(ref: OnsetReference, start: date, years: int) -> list[date]:
    """Datas em que a chuva costuma firmar, de `start` em diante (uma por ano hidrológico)."""
    if ref.median_offset is None:
        return []
    out = []
    for y in range(start.year - 1, start.year + years + 1):
        d = date(y, ref.hydro_start_month, 1) + timedelta(days=ref.median_offset)
        if d >= start:
            out.append(d)
    return out


def layout(fazenda: Fazenda, crops: list[str]) -> tuple[dict[str, tuple], list[str]]:
    """Onde cada cultura da rotação fica: ('fixa', crop) | ('perene', crop) | ('gira', j) | ('vazio',)."""
    perennials = [c for c in crops if is_perennial_crop(c)]
    annuals = [c for c in crops if not is_perennial_crop(c)]
    out: dict[str, tuple] = {}
    free = []
    for t in fazenda.talhoes:
        if t.cultura and is_perennial_crop(t.cultura):
            out[t.id] = ("fixa", t.cultura)
        else:
            free.append(t)
    if not annuals:
        for i, t in enumerate(free):
            out[t.id] = ("perene", perennials[i % len(perennials)]) if perennials else ("vazio",)
        return out, annuals
    n_per = min(len(perennials), max(0, len(free) - 1))
    smallest = sorted(free, key=lambda t: t.area_ha)[:n_per]
    for crop, t in zip(perennials, smallest, strict=False):
        out[t.id] = ("perene", crop)
    rotating = [t for t in free if t.id not in out]
    for j, t in enumerate(rotating):
        out[t.id] = ("gira", j)
    return out, annuals


def plan_talhao(talhao: Talhao, mode: Mode, place: tuple, annuals: list[str], seasons: list[date],
                today: date, end: date) -> list[Cultivo]:
    out: list[Cultivo] = []
    cursor = today
    if talhao.cultura and talhao.plantio:
        if is_perennial_crop(talhao.cultura):
            return [Cultivo(talhao.cultura, talhao.plantio, None, "perene")]
        harvest = talhao.plantio + timedelta(days=cycle_days(talhao.cultura))
        if harvest >= date(today.year, 1, 1):  # aparece no ano corrente, mesmo já colhida
            out.append(Cultivo(talhao.cultura, talhao.plantio, harvest, "hoje"))
            cursor = max(today, harvest)

    if mode == "hoje":
        crop = talhao.cultura
        if not crop:
            return out
        cycle = cycle_days(crop)
        if is_irrigated(crop):
            start = cursor + timedelta(days=7)  # uma semana para preparar o canteiro de novo
            while start < end:
                out.append(Cultivo(crop, start, start + timedelta(days=cycle), "hoje"))
                start += timedelta(days=cycle + 7)
        else:
            out += [Cultivo(crop, s, s + timedelta(days=cycle), "hoje") for s in seasons if cursor <= s < end]
        return out

    kind = place[0]
    if kind == "perene":
        first = next((s for s in seasons if s >= cursor), None)
        if first is not None and first < end:
            out.append(Cultivo(place[1], first, None, "perene"))
    elif kind == "gira" and annuals:
        j = place[1]
        for k, s in enumerate(seasons):
            if s < cursor or s >= end:
                continue
            crop = annuals[(j + k) % len(annuals)]
            out.append(Cultivo(crop, s, s + timedelta(days=cycle_days(crop)), "plano"))
    return out


def plan_farm(fazenda: Fazenda, mode: Mode, rotation: list[str], ref: OnsetReference, today: date,
              years: int) -> dict[str, list[Cultivo]]:
    end = date(today.year + years, 12, 31)
    seasons = season_starts(ref, today, years + 1)
    places, annuals = layout(fazenda, rotation)
    return {t.id: plan_talhao(t, mode, places.get(t.id, ("vazio",)), annuals, seasons, today, end)
            for t in fazenda.talhoes}


def crop_now(cultivos: list[Cultivo], today: date) -> tuple[str | None, str]:
    """Cultura do talhão hoje (ou a próxima) e o rótulo para o desenho."""
    for c in cultivos:
        if c.inicio <= today and (c.fim is None or c.fim >= today):
            return c.crop_id, "agora"
    upcoming = [c for c in cultivos if c.inicio > today]
    if upcoming:
        return upcoming[0].crop_id, "próxima"
    return None, "livre"


def month_grid(cultivos: list[Cultivo], today: date, years: int) -> list[dict]:
    """Calendário: uma linha por ano, 12 meses; em cada mês, as culturas no talhão e o estado delas."""
    rows = []
    for y in range(today.year, today.year + years + 1):
        months = []
        for m in range(1, 13):
            m_start = date(y, m, 1)
            m_end = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
            itens = []
            for c in cultivos:
                if c.inicio > m_end or (c.fim is not None and c.fim < m_start):
                    continue
                if m_start <= c.inicio <= m_end:
                    estado = "plantio"
                elif c.fim is not None and m_start <= c.fim <= m_end:
                    estado = "colheita"
                else:
                    estado = "perene" if c.fim is None else "cresce"
                itens.append({"id": c.crop_id, "estado": estado, "origem": c.origem})
            months.append({"m": MONTHS[m - 1], "itens": itens, "passado": m_end < today,
                           "hoje": m_start <= today <= m_end})
        rows.append({"ano": y, "meses": months})
    return rows


def plan_rows(fazenda: Fazenda, plan: dict[str, list[Cultivo]]) -> list[dict]:
    """O plano em tabela (para baixar): talhão, cultura, plantio, colheita."""
    names = {k: v["nome"] for k, v in load_yaml_config("aptidao")["culturas"].items()}
    rows = []
    for t in fazenda.talhoes:
        for c in plan.get(t.id, []):
            rows.append({"talhao": t.nome, "area_ha": t.area_ha, "cultura": names.get(c.crop_id, c.crop_id),
                         "plantio": c.inicio.isoformat(), "colheita": c.fim.isoformat() if c.fim else "perene",
                         "origem": {"hoje": "plantada hoje", "plano": "rotação", "perene": "perene"}[c.origem]})
    return rows


def treemap(areas: list[float], width: float = 100.0, height: float = 56.0) -> list[tuple[float, float, float, float]]:
    """Retângulos (x, y, w, h) proporcionais às áreas, em faixas alternadas (slice-and-dice ordenado).

    Devolve na mesma ordem de `areas`.
    """
    order = sorted(range(len(areas)), key=lambda i: -areas[i])
    rects: dict[int, tuple[float, float, float, float]] = {}
    x, y, w, h = 0.0, 0.0, width, height
    remaining = list(order)
    total = sum(areas[i] for i in remaining) or 1.0
    while remaining:
        # faixa com 1 ou 2 talhões, cortando sempre o lado mais comprido
        take = remaining[:2] if len(remaining) > 2 else remaining
        share = sum(areas[i] for i in take) / total
        if w >= h:
            strip_w = w * share if len(remaining) > len(take) else w
            yy = y
            for i in take:
                hh = h * areas[i] / max(sum(areas[k] for k in take), 1e-9)
                rects[i] = (x, yy, strip_w, hh)
                yy += hh
            x, w = x + strip_w, w - strip_w
        else:
            strip_h = h * share if len(remaining) > len(take) else h
            xx = x
            for i in take:
                ww = w * areas[i] / max(sum(areas[k] for k in take), 1e-9)
                rects[i] = (xx, y, ww, strip_h)
                xx += ww
            y, h = y + strip_h, h - strip_h
        total -= sum(areas[i] for i in take)
        remaining = remaining[len(take):]
    return [rects[i] for i in range(len(areas))]
