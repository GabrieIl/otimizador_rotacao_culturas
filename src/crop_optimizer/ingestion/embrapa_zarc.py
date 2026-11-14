"""Metadados de Zoneamento Agrícola de Risco Climático (ZARC - Embrapa/MAPA) para o Semiárido."""

from __future__ import annotations

import polars as pl

from crop_optimizer.domain.models import CropSpec, LocationSpec, SeasonSlot


class EmbrapaZarcSource:
    """Fornece janelas recomendadas de plantio e faixas de risco (20%, 30%, 40%) por município e cultura."""

    def fetch_zarc_windows(
        self,
        locations: list[LocationSpec],
        crops: list[CropSpec],
    ) -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        for loc in locations:
            for crop in crops:
                ideal_start, ideal_end, cutoff_doy = self._window_for(loc, crop)
                rows.append(
                    {
                        "location_id": loc.location_id,
                        "crop_id": crop.crop_id,
                        "soil_type": loc.soil_type,
                        "slot": crop.slot.value,
                        "ideal_start_doy": ideal_start,
                        "ideal_end_doy": ideal_end,
                        "risk_20_cutoff_doy": cutoff_doy,
                        "risk_30_cutoff_doy": (cutoff_doy + 10) % 365 or 365,
                        "risk_40_cutoff_doy": (cutoff_doy + 20) % 365 or 365,
                        "min_rain_cycle_mm": self._min_rain_mm(crop),
                        "frost_threshold_c": 2.0 if loc.frost_prone else -99.0,
                    }
                )
        return pl.DataFrame(rows)

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
