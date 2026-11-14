"""Tábua de risco oficial do ZARC (MAPA/Embrapa) a partir do CSV de dados abertos.

O CSV original fica intacto em data/bronze/zarc/. O recorte dos municípios do catálogo
(manejo sequeiro, formato longo: uma linha por decêndio com risco) vai para data/silver/zarc/.

Cada linha da tábua é uma combinação município x cultura x solo x ciclo; as colunas
dec1..dec36 trazem o risco (20, 30 ou 40 %) de plantar naquele decêndio, ou 0 quando
o plantio não é indicado.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from crop_optimizer.config import Settings, get_settings, load_yaml_config

SOURCE_DIR = "zarc"
DEC_COLUMNS = [f"dec{i}" for i in range(1, 37)]
_MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


class ZarcDataUnavailable(RuntimeError):
    """O CSV do ZARC não está na bronze."""


@dataclass(slots=True)
class ZarcWindow:
    """Janela de plantio do ZARC para uma cultura num município (união de solos e ciclos)."""

    crop_id: str
    zarc_name: str
    decendios: list[int]  # decêndios com plantio indicado em pelo menos um solo/ciclo
    start_dec: int
    end_dec: int
    best_risk_pct: int  # menor risco encontrado (20, 30 ou 40)
    combos: int  # quantas combinações solo x ciclo têm janela
    portaria: str

    @property
    def label(self) -> str:
        return f"{decendio_start_label(self.start_dec)} a {decendio_end_label(self.end_dec)}"


def decendio_start_label(dec: int) -> str:
    month = (dec - 1) // 3
    day = (1, 11, 21)[(dec - 1) % 3]
    return f"{day:02d}/{_MONTHS_PT[month]}"


def decendio_end_label(dec: int) -> str:
    month = (dec - 1) // 3
    part = (dec - 1) % 3
    day = (10, 20, calendar.monthrange(2027, month + 1)[1])[part]
    return f"{day:02d}/{_MONTHS_PT[month]}"


def decendio_of(month: int, day: int) -> int:
    return (month - 1) * 3 + min(2, (day - 1) // 10) + 1


def _silver_path(settings: Settings, csv_name: str) -> Path:
    folder = settings.paths.silver / SOURCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder / csv_name.replace(".csv", ".parquet")


def load_zarc_table(ibge_codes: list[str], settings: Settings | None = None) -> pl.DataFrame:
    """Recorte longo da tábua: geocodigo, cultura, solo, ciclo, portaria, decendio, risco_pct."""
    cfg = load_yaml_config("zarc")
    settings = settings or get_settings()
    csv_path = settings.paths.bronze_source(SOURCE_DIR) / cfg["arquivo"]
    silver = _silver_path(settings, cfg["arquivo"])

    if silver.exists():
        cached = pl.read_parquet(silver)
        if set(ibge_codes) <= set(cached["geocodigo"].unique().to_list()):
            return cached.filter(pl.col("geocodigo").is_in(ibge_codes))

    if not csv_path.exists():
        raise ZarcDataUnavailable(
            f"Tábua do ZARC não encontrada em {csv_path}. Baixe '{cfg['arquivo']}' em "
            "dados.agricultura.gov.br (Tábua de risco ZARC) e coloque nessa pasta."
        )

    wide = (
        pl.scan_csv(csv_path, separator=";", infer_schema=False, encoding="utf8-lossy")
        .filter(pl.col("geocodigo").is_in(ibge_codes) & (pl.col("Nome_Outros_Manejos") == cfg["manejo"]))
        .collect()
    )
    long = (
        wide.select(
            "geocodigo",
            "municipio",
            "UF",
            pl.col("Nome_cultura").alias("cultura"),
            pl.col("Cod_Solo").alias("cod_solo"),
            pl.col("Cod_Ciclo").alias("cod_ciclo"),
            pl.col("Portaria").alias("portaria"),
            *DEC_COLUMNS,
        )
        .unpivot(
            index=["geocodigo", "municipio", "UF", "cultura", "cod_solo", "cod_ciclo", "portaria"],
            on=DEC_COLUMNS,
            variable_name="decendio",
            value_name="risco_pct",
        )
        .with_columns(
            pl.col("decendio").str.replace("dec", "").cast(pl.Int16),
            pl.col("risco_pct").cast(pl.Int16),
        )
        .filter(pl.col("risco_pct") > 0)
    )
    long.write_parquet(silver)
    return long


def _circular_span(decs: list[int]) -> tuple[int, int]:
    """Início e fim da janela olhando o ano como círculo (ex.: nov-jan cruza a virada)."""
    present = sorted(set(decs))
    if len(present) == 36:
        return 1, 36
    # maior intervalo sem plantio separa o fim do início
    best_gap, start = -1, present[0]
    for i, dec in enumerate(present):
        nxt = present[(i + 1) % len(present)]
        gap = (nxt - dec - 1) % 36
        if gap > best_gap:
            best_gap, start = gap, nxt
    end = present[(present.index(start) - 1) % len(present)]
    return start, end


def zarc_windows_for(
    table: pl.DataFrame, ibge_code: str, crop_map: dict[str, str] | None = None
) -> dict[str, ZarcWindow | None]:
    """Janela por cultura do motor; None quando o ZARC não indica plantio de sequeiro."""
    crop_map = crop_map or load_yaml_config("zarc")["culturas"]
    local = table.filter(pl.col("geocodigo") == ibge_code)
    out: dict[str, ZarcWindow | None] = {}
    for crop_id, zarc_name in crop_map.items():
        rows = local.filter(pl.col("cultura") == zarc_name)
        if rows.is_empty():
            out[crop_id] = None
            continue
        decs = rows["decendio"].to_list()
        start, end = _circular_span(decs)
        out[crop_id] = ZarcWindow(
            crop_id=crop_id,
            zarc_name=zarc_name,
            decendios=sorted(set(decs)),
            start_dec=start,
            end_dec=end,
            best_risk_pct=int(rows["risco_pct"].min()),
            combos=rows.select("cod_solo", "cod_ciclo").unique().height,
            portaria=rows["portaria"][0],
        )
    return out
