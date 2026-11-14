"""Conector de preços agropecuários regionais (referência CONAB / B3 / Feira Local)."""

from __future__ import annotations

from datetime import date

import polars as pl

from crop_optimizer.domain.models import CropSpec


class B3MarketDataSource:
    """Fornece preços de referência, volatilidade anualizada e custos de insumos."""

    def fetch_market_prices(self, crops: list[CropSpec]) -> pl.DataFrame:
        ref_date = date(2026, 10, 1)
        rows: list[dict[str, object]] = []
        for crop in crops:
            rows.append(
                {
                    "crop_id": crop.crop_id,
                    "reference_date": ref_date,
                    "ticker_ref": self._ticker(crop.crop_id),
                    "spot_price_brl_ton": crop.base_price_brl_ton,
                    "annual_volatility": crop.price_volatility,
                    "direct_cost_brl_ha": crop.direct_cost_brl_ha,
                    "n_fertilizer_brl_kg": 6.20,
                    "currency": "BRL",
                }
            )
        return pl.DataFrame(rows).with_columns(pl.col("reference_date").cast(pl.Date))

    @staticmethod
    def _ticker(crop_id: str) -> str:
        tickers = {
            "milho_sertanejo": "CCM_B3_PGM",
            "feijao_caupi": "CAUPI_CONAB",
            "sorgo_forrageiro": "SRG_CEPEA",
            "palma_forrageira": "FORRAGEM_LOCAL",
            "capim_buffel": "FENO_LOCAL",
        }
        return tickers.get(crop_id, "SPOT_LOCAL")
