"""Veredito por cultura para "O que devo plantar agora?".

Junta, nesta ordem, o que já temos de fonte:
1. ZARC (MAPA/Embrapa): se a cultura não é indicada no município, não plante;
2. a chuva desta safra: sem chuva firme, espere;
3. a janela oficial do ZARC: ainda não abriu (espere) ou já fechou (fora da janela);
4. o risco simulado com o atraso de hoje (semáforo): pode plantar / arriscado / não plante.

Culturas perenes sem janela no ZARC (palma, capim-buffel) pulam os passos 1 e 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crop_optimizer.analytics.rain_delay import CropWindowStatus, fmt_date
from crop_optimizer.analytics.views import classify_traffic_light
from crop_optimizer.engine.rain_onset import RainSeasonStatus

Level = Literal["verde", "amarelo", "vermelho", "espera"]
WORDS = {"verde": "Pode plantar", "amarelo": "Arriscado", "vermelho": "Não plante agora"}


@dataclass(frozen=True, slots=True)
class CropVerdict:
    crop_id: str
    level: Level
    word: str
    reason: str
    risk_of_10: int  # em quantos de cada 10 anos a roça quebra, com o atraso de hoje


def crop_verdict(
    crop_id: str,
    risk_pct: float,
    status: RainSeasonStatus | None,
    window: CropWindowStatus | None,
    delay_days: int,
) -> CropVerdict:
    of_10 = round(risk_pct / 10)
    if window is not None and window.state == "sem_indicacao":
        return CropVerdict(crop_id, "vermelho", "Não plante",
                           "O zoneamento oficial (ZARC) não indica esta cultura em sequeiro neste município.", of_10)
    if status is not None and status.state in ("antes_da_epoca", "atrasada", "sem_referencia"):
        if status.state == "atrasada":
            reason = f"A chuva está {status.delay_days} dias atrasada e ainda não firmou."
        else:
            reason = f"A chuva ainda não firmou. Em ano normal, firma por volta de {fmt_date(status.reference_date)}."
        return CropVerdict(crop_id, "espera", "Espere a chuva firmar", reason, of_10)
    if window is not None and window.state == "ainda_nao_abriu":
        return CropVerdict(crop_id, "espera", "Espere a janela abrir",
                           f"A janela oficial abre em {fmt_date(window.opens)}.", of_10)
    if window is not None and window.state == "fechou":
        return CropVerdict(crop_id, "vermelho", "Fora da janela",
                           f"A janela oficial fechou em {fmt_date(window.closes)}.", of_10)
    level = classify_traffic_light(risk_pct).value
    atraso = f"com {delay_days} dias de atraso da chuva" if delay_days > 0 else "com a chuva no tempo"
    reason = f"Plantando agora, {atraso}, a roça quebra em {of_10} de cada 10 anos."
    if status is not None and status.state == "firmando":
        reason += " A chuva atingiu o critério de início, mas ainda falta confirmar que não vem veranico."
    return CropVerdict(crop_id, level, WORDS[level], reason, of_10)
