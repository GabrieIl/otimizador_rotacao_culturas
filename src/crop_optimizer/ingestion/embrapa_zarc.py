"""Metadados de Zoneamento Agrícola de Risco Climático (ZARC - Embrapa/MAPA) para o Semiárido."""

from __future__ import annotations

import calendar
from datetime import date

import polars as pl

from crop_optimizer.config import Settings, load_yaml_config
from crop_optimizer.domain.models import CropSpec, LocationSpec, SeasonSlot
from crop_optimizer.ingestion.zarc_tabua import (
    ZarcDataUnavailable,
    _filter_crop_rows,
    is_zarc_csv_cached,
    load_zarc_table,
    zarc_windows_for,
)


def _dec_start_doy(dec: int) -> int:
    month = (dec - 1) // 3 + 1
    day = (1, 11, 21)[(dec - 1) % 3]
    return date(2025, month, day).timetuple().tm_yday


def _dec_end_doy(dec: int) -> int:
    month, part = (dec - 1) // 3 + 1, (dec - 1) % 3
    day = (10, 20, min(28, calendar.monthrange(2025, month)[1]))[part]
    return date(2025, month, day).timetuple().tm_yday


def _soil_group_from_label(soil_type: str) -> str | None:
    lower = soil_type.lower()
    if "muito argil" in lower:
        return "muito_argilosa"
    if "argil" in lower:
        return "argilosa"
    if "arenos" in lower and "franco" not in lower:
        return "arenosa"
    if any(tok in lower for tok in ("franco", "média", "media", "tipo 2")):
        return "media"
    if "tipo 1" in lower:
        return "arenosa"
    if "tipo 3" in lower:
        return "argilosa"
    return None


class EmbrapaZarcSource:
    """Fornece janelas recomendadas de plantio e faixas de risco (20%, 30%, 40%) por município e cultura."""

    def __init__(self, settings: Settings | None = None, allow_download: bool = False) -> None:
        self.settings = settings
        self.allow_download = allow_download

    def _load_real_table(self, locations: list[LocationSpec]) -> pl.DataFrame | None:
        ibges = sorted({loc.ibge_code for loc in locations if loc.ibge_code})
        if not ibges:
            return None
        settings = self.settings
        silver_exists = False
        if settings is not None:
            filename = load_yaml_config("zarc")["arquivo"].replace(".csv", ".parquet")
            silver_exists = (settings.paths.silver / "zarc" / filename).exists()
        if not self.allow_download and not silver_exists and not is_zarc_csv_cached(settings):
            return None
        try:
            return load_zarc_table(ibges, settings)
        except ZarcDataUnavailable:
            return None

    def fetch_zarc_windows(
        self,
        locations: list[LocationSpec],
        crops: list[CropSpec],
    ) -> pl.DataFrame:
        real_table = self._load_real_table(locations)
        zarc_culturas: dict[str, str] = load_yaml_config("zarc")["culturas"]
        rows: list[dict[str, object]] = []
        for loc in locations:
            soil_group = _soil_group_from_label(loc.soil_type)
            win_map = (
                zarc_windows_for(real_table, loc.ibge_code, soil_group=soil_group)
                if real_table is not None and loc.ibge_code
                else {}
            )
            for crop in crops:
                real_win = win_map.get(crop.crop_id)
                if real_win is not None and real_table is not None and loc.ibge_code:
                    ideal_start = _dec_start_doy(real_win.start_dec)
                    ideal_end = _dec_end_doy(real_win.end_dec)
                    cut20, cut30, cut40 = self._risk_cutoffs_from_table(
                        real_table,
                        loc.ibge_code,
                        zarc_culturas.get(crop.crop_id, ""),
                        soil_group,
                        ideal_end,
                    )
                    source = "zarc_mapa_2026_2027"
                else:
                    ideal_start, ideal_end, cut20 = self._window_for(loc, crop)
                    cut30 = ((cut20 + 10 - 1) % 365) + 1
                    cut40 = ((cut20 + 20 - 1) % 365) + 1
                    source = "estimativa_clima_offline"
                rows.append(
                    {
                        "location_id": loc.location_id,
                        "crop_id": crop.crop_id,
                        "soil_type": loc.soil_type,
                        "slot": crop.slot.value,
                        "ideal_start_doy": ideal_start,
                        "ideal_end_doy": ideal_end,
                        "risk_20_cutoff_doy": cut20,
                        "risk_30_cutoff_doy": cut30,
                        "risk_40_cutoff_doy": cut40,
                        "min_rain_cycle_mm": self._min_rain_mm(crop),
                        "frost_threshold_c": 2.0 if loc.frost_prone else -99.0,
                        "source": source,
                    }
                )
        return pl.DataFrame(rows)

    @staticmethod
    def _risk_cutoffs_from_table(
        table: pl.DataFrame,
        ibge_code: str,
        zarc_name: str,
        soil_group: str | None,
        fallback_end_doy: int,
    ) -> tuple[int, int, int]:
        local = table.filter(pl.col("geocodigo") == ibge_code)
        rows, _ = _filter_crop_rows(local, zarc_name, soil_group=soil_group)
        if rows.height == 0:
            return (
                fallback_end_doy,
                ((fallback_end_doy + 10 - 1) % 365) + 1,
                ((fallback_end_doy + 20 - 1) % 365) + 1,
            )
        cutoffs: list[int] = []
        for pct in (20, 30, 40):
            sub = rows.filter(pl.col("risco_pct") <= pct)
            if sub.height == 0:
                cutoffs.append(fallback_end_doy)
            else:
                # decêndio mais tardio dentro da faixa de risco
                last_dec = max(int(d) for d in sub["decendio"].to_list())
                cutoffs.append(_dec_end_doy(last_dec))
        return (cutoffs[0], cutoffs[1], cutoffs[2])

    @staticmethod
    def _window_for(loc: LocationSpec, crop: CropSpec) -> tuple[int, int, int]:
        start = loc.rainy_season_start_doy
        if crop.slot == SeasonSlot.SAFRA:
            # No Semiárido a janela segura para milho é curta (20-35 dias após o início das águas)
            span = 28 if crop.crop_id == "milho_sertanejo" else 42
            end = ((start + span - 1) % 365) + 1
            cutoff = ((end + 10 - 1) % 365) + 1
            return (start, end, cutoff)
        if crop.slot == SeasonSlot.SAFRINHA:
            s_start = ((start + 25 - 1) % 365) + 1
            s_end = ((s_start + 45 - 1) % 365) + 1
            cutoff = ((s_end + 12 - 1) % 365) + 1
            return (s_start, s_end, cutoff)
        # Palma / Capim-Buffel: janela ampla durante toda a estação chuvosa
        c_end = ((start + 85 - 1) % 365) + 1
        cutoff = ((c_end + 25 - 1) % 365) + 1
        return (start, c_end, cutoff)

    @staticmethod
    def _min_rain_mm(crop: CropSpec) -> float:
        mapping = {
            "milho_sertanejo": 440.0,
            "feijao_caupi": 290.0,
            "sorgo_forrageiro": 260.0,
            "palma_forrageira": 180.0,
            "capim_buffel": 200.0,
        }
        return mapping.get(crop.crop_id, 300.0)
