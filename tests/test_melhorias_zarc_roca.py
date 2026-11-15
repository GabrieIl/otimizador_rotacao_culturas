"""Testes das melhorias 2, 3, 4, 5, 6, 7 e 8 (clima local, solo/ciclo ZARC, busca, PDF, ELT, CLI e UI)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest

from crop_optimizer.accessibility import generate_one_pager_pdf
from crop_optimizer.analytics import build_survival_scoreboard_frame
from crop_optimizer.analytics.rain_delay import (
    CropWindowStatus,
    fetch_location_zarc,
    seasonal_stats_from_rain_series,
)
from crop_optimizer.app.home_page import _build_soil_compare_rows
from crop_optimizer.cli import main as cli_main
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig, TrafficLightLevel
from crop_optimizer.domain.presets import DEFAULT_CROPS, DEFAULT_STRATEGIES, location_map
from crop_optimizer.domain.roca import Roca
from crop_optimizer.domain.soil_profile import SoilValue, build_profile
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import MonteCarloRotationEngine
from crop_optimizer.ingestion.embrapa_zarc import EmbrapaZarcSource
from crop_optimizer.ingestion.geocode import GeocodeUnavailable, candidates_from_hits, search_places
from crop_optimizer.ingestion.rain_history import RainSeries
from crop_optimizer.ingestion.zarc_tabua import (
    ZarcWindow,
    download_zarc_csv,
    zarc_decendios_for_crops,
    zarc_windows_for,
)
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _make_rain_series(location_id: str, years: int = 7, wet_mm_day: float = 12.0) -> RainSeries:
    start = date(2018, 10, 1)
    total_days = years * 365
    dates = np.array([start + timedelta(days=i) for i in range(total_days)], dtype="datetime64[D]")
    months = np.array([(start + timedelta(days=i)).month for i in range(total_days)])
    precip = np.where((months >= 1) & (months <= 5), wet_mm_day, 0.2).astype(np.float64)
    return RainSeries(location_id=location_id, dates=dates, precip_mm=precip, source="NASA POWER")


def test_seasonal_stats_calibrates_from_point_rain_series_and_fallbacks() -> None:
    base = SeasonalClimateStats(
        location_id="petrolina_pe",
        safra_rain_mean_mm=410.0,
        safra_rain_std_mm=95.0,
        safrinha_rain_mean_mm=90.0,
        safrinha_rain_std_mm=30.0,
        safrinha_water_stress_prob=0.25,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.45,
        mean_gwet_safrinha=0.30,
        veranico_prob=0.35,
        query_ms=1.2,
    )
    series = _make_rain_series("roca_test", years=7, wet_mm_day=8.0)
    calibrated = seasonal_stats_from_rain_series(
        series,
        base,
        veranico_prob=0.5,
        veranico_lengths=(11, 14),
    )
    assert calibrated.location_id == "roca_test"
    # 5 meses (Jan-Mai ~151 dias) * 8 mm ~ 1208 mm -> diferente de base_stats (410 mm)
    assert calibrated.safra_rain_mean_mm > 900.0
    assert calibrated.safrinha_rain_mean_mm < 100.0
    assert calibrated.veranico_prob == 0.5
    assert calibrated.veranico_lengths == (11, 14)

    short_series = _make_rain_series("roca_curta", years=2)
    fallback = seasonal_stats_from_rain_series(short_series, base)
    assert fallback is base


def test_zarc_filters_by_soil_group_and_cycle_for_tipo_and_ad_codes(tmp_path: Path) -> None:
    settings = get_settings(str(tmp_path))
    settings.paths.ensure_dirs()
    silver_dir = settings.paths.silver / "zarc"
    silver_dir.mkdir(parents=True, exist_ok=True)
    # Tabela sintética cobrindo Tipo 1/2/3 (Caupi) e AD2..AD6 (Milho) com vários ciclos
    rows = []
    for dec in (4, 5, 6):
        rows.append(
            {
                "geocodigo": "9999999",
                "cultura": "Milho 1ª Safra",
                "cod_solo": "12",  # AD2 -> arenosa
                "cod_ciclo": "20",
                "portaria": "Portaria Teste",
                "decendio": dec,
                "risco_pct": 20,
            }
        )
    for dec in (7, 8, 9):
        rows.append(
            {
                "geocodigo": "9999999",
                "cultura": "Milho 1ª Safra",
                "cod_solo": "15",  # AD5 -> argilosa
                "cod_ciclo": "21",
                "portaria": "Portaria Teste",
                "decendio": dec,
                "risco_pct": 20,
            }
        )
    for dec in (1, 2, 3):
        rows.append(
            {
                "geocodigo": "9999999",
                "cultura": "Feijão Caupi",
                "cod_solo": "1",  # Tipo 1 -> arenosa
                "cod_ciclo": "20",
                "portaria": "Portaria Teste",
                "decendio": dec,
                "risco_pct": 20,
            }
        )
    rows.append(
        {
            "geocodigo": "9999999",
            "cultura": "Feijão Caupi",
            "cod_solo": "3",  # Tipo 3 -> argilosa / muito_argilosa
            "cod_ciclo": "22",
            "portaria": "Portaria Teste",
            "decendio": 10,
            "risco_pct": 30,
        }
    )
    table = pl.DataFrame(rows)

    win_arenosa = zarc_windows_for(table, "9999999", soil_group="arenosa")
    assert win_arenosa["milho_sertanejo"].start_dec == 4
    assert win_arenosa["milho_sertanejo"].end_dec == 6
    assert win_arenosa["feijao_caupi"].start_dec == 1
    assert win_arenosa["feijao_caupi"].available_cycles == ["20"]

    win_argilosa = zarc_windows_for(table, "9999999", soil_group="argilosa")
    assert win_argilosa["milho_sertanejo"].start_dec == 7
    assert win_argilosa["feijao_caupi"].start_dec == 10
    assert win_argilosa["feijao_caupi"].best_risk_pct == 30

    # Filtrando por ciclo incompatível com solo arenosa -> sem indicação
    win_cycle_mismatch = zarc_windows_for(table, "9999999", soil_group="arenosa", cycle_code="21")
    assert win_cycle_mismatch["milho_sertanejo"] is None

    decs = zarc_decendios_for_crops(table, "9999999", soil_group="argilosa", cycle_code="21")
    assert decs["milho_sertanejo"][6] == 20  # decêndio 7 -> índice 6
    assert decs["milho_sertanejo"][3] == 0  # decêndio 4 pertence a arenosa

    table.write_parquet(silver_dir / "dados-abertos-tabua-de-risco-safra-2026-2027.parquet")
    loc = location_map()["petrolina_pe"].model_copy(update={"ibge_code": "9999999"})
    report = fetch_location_zarc(loc, date(2026, 1, 1), date(2026, 2, 15), settings, soil_group="arenosa", cycle_code="20")
    assert report.soil_group == "arenosa"
    assert report.cycle_code == "20"
    milho = next(w for w in report.crop_windows if w.crop_id == "milho_sertanejo")
    assert milho.window is not None and milho.window.start_dec == 4


def test_search_places_resolves_candidates_and_handles_offline(tmp_path: Path) -> None:
    hits = [
        {
            "lat": "-7.882",
            "lon": "-40.081",
            "display_name": "Ouricuri, Pernambuco, Brasil",
            "address": {"city": "Ouricuri", "ISO3166-2-lvl4": "BR-PE", "country_code": "br"},
        },
        {
            "lat": "-7.890",
            "lon": "-40.090",
            "display_name": "Centro, Ouricuri, PE",
            "address": {"town": "Ouricuri", "ISO3166-2-lvl4": "BR-PE", "country_code": "br"},
        },
        {
            "lat": "48.856",
            "lon": "2.352",
            "display_name": "Paris, France",
            "address": {"city": "Paris", "ISO3166-2-lvl4": "FR-75", "country_code": "fr"},
        },
    ]
    muns_pe = [{"id": 2609907, "nome": "Ouricuri"}]
    candidates = candidates_from_hits(hits, {"PE": muns_pe})
    assert len(candidates) == 1
    assert candidates[0].label == "Ouricuri/PE"
    assert candidates[0].ibge_code == "2609907"

    settings = get_settings(str(tmp_path))
    settings.paths.ensure_dirs()
    with pytest.raises(GeocodeUnavailable):
        search_places("   ", settings=settings)

    with (
        patch("crop_optimizer.ingestion.geocode._search_nominatim", return_value=hits),
        patch("crop_optimizer.ingestion.geocode._municipalities", return_value=muns_pe),
    ):
        found = search_places("Ouricuri", uf="PE", settings=settings)
        assert len(found) == 1
        assert found[0].ibge_code == "2609907"

    with (
        patch("crop_optimizer.ingestion.geocode._search_nominatim", side_effect=GeocodeUnavailable("offline")),
        pytest.raises(GeocodeUnavailable),
    ):
        search_places("Ouricuri", settings=settings)


def test_one_pager_pdf_includes_custom_roca_soil_and_zarc_on_single_page() -> None:
    roca = Roca(lat=-7.882, lon=-40.081, municipio="Ouricuri", uf="PE", ibge_code="2609907")
    loc = roca.to_location()
    cfg = SimulationConfig(location_id=loc.location_id, n_scenarios=500, horizon_years=5, safra_delay_days=14)
    stats = SeasonalClimateStats(
        location_id=loc.location_id,
        safra_rain_mean_mm=510.0,
        safra_rain_std_mm=110.0,
        safrinha_rain_mean_mm=95.0,
        safrinha_rain_std_mm=30.0,
        safrinha_water_stress_prob=0.22,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.45,
        mean_gwet_safrinha=0.30,
        veranico_prob=0.35,
        query_ms=1.0,
    )
    results = MonteCarloRotationEngine().simulate_portfolio(DEFAULT_STRATEGIES, stats, cfg)
    scoreboard = build_survival_scoreboard_frame(results)
    profile = build_profile(satellite=None, terrain=None, field_data={"valores": {"p_mehlich": 12.0}})
    windows = [
        CropWindowStatus(
            "milho_sertanejo",
            ZarcWindow("milho_sertanejo", "Milho 1ª Safra", [4, 5, 6], 4, 6, 20, 2, "Portaria 10"),
            "aberta",
            date(2026, 2, 1),
            date(2026, 2, 28),
            days_left=10,
        ),
        CropWindowStatus("feijao_caupi", None, "sem_indicacao"),
    ]
    pdf_bytes = generate_one_pager_pdf(
        location=loc,
        config=cfg,
        traffic_light=TrafficLightLevel.AMARELO,
        scoreboard=scoreboard,
        results=results,
        reference_date=date(2026, 2, 18),
        soil_profile=profile,
        crop_windows=windows,
        zarc_safra="2026/2027",
        rain_source_note="Chuva calibrada pela serie NASA POWER do ponto.",
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert b"/Count 1" in pdf_bytes


def test_embrapa_zarc_source_uses_real_silver_when_cached_and_falls_back(tmp_path: Path) -> None:
    settings_off = get_settings(str(tmp_path / "offline"))
    summary_off = CropLakehouseEltPipeline(settings_off).run(
        locations=[location_map()["petrolina_pe"]],
        crops=DEFAULT_CROPS,
        start_date=date(2021, 1, 1),
        end_date=date(2022, 12, 31),
    )
    assert summary_off.zarc_rows == len(DEFAULT_CROPS)
    df_off = pl.read_parquet(settings_off.paths.dim_zarc_window)
    assert set(df_off["source"].to_list()) == {"estimativa_clima_offline"}

    settings_real = get_settings(str(tmp_path / "real"))
    settings_real.paths.ensure_dirs()
    silver_dir = settings_real.paths.silver / "zarc"
    silver_dir.mkdir(parents=True, exist_ok=True)
    petrolina = location_map()["petrolina_pe"]
    pl.DataFrame(
        [
            {
                "geocodigo": petrolina.ibge_code,
                "cultura": "Milho 1ª Safra",
                "cod_solo": "13",
                "cod_ciclo": "20",
                "portaria": "Portaria ZARC",
                "decendio": d,
                "risco_pct": 20 if d <= 5 else 30,
            }
            for d in (3, 4, 5, 6)
        ]
    ).write_parquet(silver_dir / "dados-abertos-tabua-de-risco-safra-2026-2027.parquet")

    src_real = EmbrapaZarcSource(settings=settings_real, allow_download=False)
    df_real = src_real.fetch_zarc_windows([petrolina], DEFAULT_CROPS)
    milho_row = df_real.filter(pl.col("crop_id") == "milho_sertanejo").row(0, named=True)
    palma_row = df_real.filter(pl.col("crop_id") == "palma_forrageira").row(0, named=True)
    assert milho_row["source"] == "zarc_mapa_2026_2027"
    assert palma_row["source"] == "estimativa_clima_offline"
    assert milho_row["ideal_start_doy"] == date(2025, 1, 21).timetuple().tm_yday
    assert milho_row["risk_20_cutoff_doy"] < milho_row["risk_30_cutoff_doy"]


def test_zarc_download_progress_callback_and_cli_cmd_zarc(tmp_path: Path) -> None:
    settings = get_settings(str(tmp_path))
    settings.paths.ensure_dirs()
    csv_body = (
        b"Nome_cultura;Cod_Ciclo;Cod_Solo;Portaria;UF;Municipio;geocodigo;Manejo;"
        + b";".join(f"d{i}".encode() for i in range(1, 37))
        + b"\n"
    )

    class _FakeResp:
        headers = {"Content-Length": str(len(csv_body))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, chunk_size: int = 65536):
            mid = len(csv_body) // 2
            yield csv_body[:mid]
            yield csv_body[mid:]

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method: str, url: str):
            return _FakeResp()

    seen: list[tuple[int, int | None]] = []
    with patch("crop_optimizer.ingestion.zarc_tabua.httpx.Client", _FakeClient):
        out_path = download_zarc_csv(settings=settings, progress_callback=lambda d, t: seen.append((d, t)))
    assert out_path.exists()
    assert len(seen) == 2
    assert seen[-1] == (len(csv_body), len(csv_body))

    fake_table = pl.DataFrame(
        [
            {
                "geocodigo": "2611101",
                "cultura": "Milho 1ª Safra",
                "cod_solo": "13",
                "cod_ciclo": "20",
                "portaria": "P1",
                "decendio": 4,
                "risco_pct": 20,
            }
        ]
    )
    with patch("crop_optimizer.ingestion.zarc_tabua.load_zarc_table", return_value=fake_table) as mock_load:
        cli_main(["zarc", "--data-dir", str(tmp_path), "--ibge", "2611101"])
    mock_load.assert_called_once()


def test_home_page_marks_assumed_reference_soil_values_distinctly() -> None:
    profile = build_profile(satellite=None, terrain=None, field_data=None)
    # Sem satélite/campo, todos vêm de "referencia"; forçamos mo_pct e ph_h2o como "satelite" para comparar
    profile.values["mo_pct"] = SoilValue(1.8, "satelite")
    profile.values["ph_h2o"] = SoilValue(6.1, "satelite")
    profile.values["ctc_t"] = SoilValue(6.5, "satelite")

    rows, assumed = _build_soil_compare_rows(profile, region=None)
    by_label = {r["label"]: r for r in rows}

    assert set(assumed) == {"Fósforo", "Potássio", "Cálcio e magnésio (V%)"}
    for label in assumed:
        assert by_label[label]["tone"] == "neutro"
        assert "(assumido)" in by_label[label]["class_txt"]

    assert "(assumido)" not in by_label["Matéria orgânica"]["class_txt"]
    assert by_label["Acidez (pH em água)"]["tone"] != "neutro"
