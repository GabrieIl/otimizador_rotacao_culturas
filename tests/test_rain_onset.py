"""Testes do início da estação chuvosa, atraso da chuva e leitura da tábua do ZARC."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from crop_optimizer.config import get_settings, load_yaml_config
from crop_optimizer.engine.rain_onset import (
    OnsetCriteria,
    OnsetReference,
    _censored_quantile,
    assess_season,
    build_reference,
    detect_onset,
)
from crop_optimizer.ingestion.zarc_tabua import (
    DEC_COLUMNS,
    _circular_span,
    decendio_end_label,
    decendio_of,
    decendio_start_label,
    load_zarc_table,
    zarc_windows_for,
)

CRIT = OnsetCriteria()  # 20 mm em 3 dias, veranico máx 7 dias em 30


def _series(start: date, days: int) -> tuple[np.ndarray, np.ndarray]:
    dates = np.arange(np.datetime64(start), np.datetime64(start, "D") + np.timedelta64(days, "D"), dtype="datetime64[D]")
    return dates, np.zeros(days, dtype=np.float64)


def _wet_from(precip: np.ndarray, dates: np.ndarray, day: date, length: int = 60) -> None:
    """Chuva firme a partir de `day`: 10 mm a cada 3 dias."""
    i0 = int(np.searchsorted(dates, np.datetime64(day)))
    precip[i0 : i0 + 3] = 10.0
    for k in range(i0 + 3, min(i0 + length, precip.size), 3):
        precip[k] = 10.0


def test_detect_onset_first_firm_rain() -> None:
    dates, precip = _series(date(2020, 9, 1), 365)
    _wet_from(precip, dates, date(2021, 1, 10))
    det = detect_onset(dates, precip, date(2020, 9, 1), date(2021, 8, 31), CRIT)
    assert det.onset == date(2021, 1, 10)
    assert det.provisional is False


def test_false_start_followed_by_veranico_is_ignored() -> None:
    dates, precip = _series(date(2020, 9, 1), 365)
    precip[int(np.searchsorted(dates, np.datetime64("2020-12-01")))] = 30.0  # chuva isolada, depois seca
    _wet_from(precip, dates, date(2021, 1, 20))
    det = detect_onset(dates, precip, date(2020, 9, 1), date(2021, 8, 31), CRIT)
    assert det.onset == date(2021, 1, 20)


def test_no_rain_means_no_onset() -> None:
    dates, precip = _series(date(2020, 9, 1), 365)
    assert detect_onset(dates, precip, date(2020, 9, 1), date(2021, 8, 31), CRIT).onset is None


def test_onset_near_data_end_is_provisional() -> None:
    dates, precip = _series(date(2020, 9, 1), 365)
    _wet_from(precip, dates, date(2021, 1, 10))
    det = detect_onset(dates, precip, date(2020, 9, 1), date(2021, 1, 20), CRIT)
    assert det.onset == date(2021, 1, 10)
    assert det.provisional is True


def test_censored_quantile_counts_years_without_onset() -> None:
    assert _censored_quantile([10, 20, 30, None], 0.5) == 20
    assert _censored_quantile([10, None, None, None], 0.5) is None
    # descartar os anos secos daria mediana 10; com censura, fica mais tarde
    assert _censored_quantile([10, 20, None, None, None], 0.5) is None


def _reference(offsets: list[int | None]) -> OnsetReference:
    return OnsetReference(
        hydro_start_month=9,
        first_year=1991,
        last_year=1990 + len(offsets),
        season_years=list(range(1991, 1991 + len(offsets))),
        offsets=offsets,
        median_offset=_censored_quantile(offsets, 0.5),
        p25_offset=_censored_quantile(offsets, 0.25),
        p75_offset=_censored_quantile(offsets, 0.75),
    )


def test_assess_season_states_and_delay() -> None:
    dates, precip = _series(date(2020, 9, 1), 365)
    _wet_from(precip, dates, date(2021, 1, 10))
    # referência: mediana 100 dias após 01/09 = 10/12/2020
    ref = _reference([80, 90, 100, 110, 120, None, None, 95, 105, 100])
    ref_date = date(2020, 9, 1) + timedelta(days=ref.median_offset)

    before = assess_season(dates, precip, date(2020, 11, 1), ref, CRIT)
    assert before.state == "antes_da_epoca" and before.delay_days == 0

    late = assess_season(dates, precip, date(2020, 12, 30), ref, CRIT)
    assert late.state == "atrasada"
    assert late.delay_days == (date(2020, 12, 30) - ref_date).days
    # em 30/12 (120 dias) só os 2 anos sem chuva firme ainda estavam esperando: nenhum firmou depois
    assert late.still_came_of_10 == 0

    done = assess_season(dates, precip, date(2021, 3, 1), ref, CRIT)
    assert done.state == "firmou"
    assert done.onset_date == date(2021, 1, 10)
    assert done.delay_days == (date(2021, 1, 10) - ref_date).days
    assert done.motor_delay_days(max_days=20) == 20


def test_build_reference_on_regular_years() -> None:
    dates, precip = _series(date(2000, 1, 1), 365 * 4 + 1)
    for y in (2000, 2001, 2002):
        _wet_from(precip, dates, date(y + 1, 1, 15), length=90)
    ref = build_reference(dates, precip, CRIT, 2000, 2002)
    assert ref.years_without_onset == 0
    start = date(2000, ref.hydro_start_month, 1)
    assert ref.date_in(start, ref.median_offset) == date(2001, 1, 15)


def test_decendio_helpers_and_circular_span() -> None:
    assert decendio_of(1, 1) == 1 and decendio_of(1, 31) == 3 and decendio_of(12, 25) == 36
    assert decendio_start_label(32) == "11/nov"
    assert decendio_end_label(6) == "28/fev"
    assert _circular_span([33, 34, 35, 36, 1, 2, 3]) == (33, 3)
    assert _circular_span([5, 6, 7]) == (5, 7)


def test_load_zarc_table_from_csv(tmp_path) -> None:
    settings = get_settings(tmp_path)
    cfg = load_yaml_config("zarc")
    header = (
        "Nome_cultura;SafraIni;SafraFin;Cod_Cultura;Cod_Ciclo;Cod_Solo;geocodigo;UF;municipio;"
        "Cod_Clima;Nome_Clima;Cod_Outros_Manejos;Nome_Outros_Manejos;Produtividade;Cod_NM;"
        "Cod_Munic;Cod_Meso;Cod_Micro;Portaria;" + ";".join(DEC_COLUMNS)
    )

    def row(cultura: str, geo: str, manejo: str, decs: dict[int, int]) -> str:
        vals = ";".join(str(decs.get(i, 0)) for i in range(1, 37))
        return f"{cultura};2026;2027;1;20;2;{geo};BA;Irecê;0;x;1;{manejo};;;1;1;1;Port.1;{vals}"

    lines = [
        header,
        row("Sorgo Forrageiro", "2914604", "Sequeiro", {33: 40, 34: 30, 1: 40}),
        row("Sorgo Forrageiro", "2914604", "Irrigado", {10: 20}),
        row("Feijão Caupi", "9999999", "Sequeiro", {5: 20}),
    ]
    csv = settings.paths.bronze_source("zarc") / cfg["arquivo"]
    csv.write_text("﻿" + "\r\n".join(lines) + "\r\n", encoding="utf-8")

    table = load_zarc_table(["2914604"], settings)
    assert set(table["decendio"].to_list()) == {33, 34, 1}  # irrigado e outro município fora
    windows = zarc_windows_for(table, "2914604")
    sorgo = windows["sorgo_forrageiro"]
    assert sorgo is not None
    assert (sorgo.start_dec, sorgo.end_dec, sorgo.best_risk_pct) == (33, 1, 30)
    assert windows["milho_sertanejo"] is None
    # segunda leitura usa o recorte da silver mesmo sem o CSV
    csv.unlink()
    assert load_zarc_table(["2914604"], settings).height == table.height


def test_zarc_missing_csv_raises(tmp_path) -> None:
    from crop_optimizer.ingestion.zarc_tabua import ZarcDataUnavailable

    with (
        patch("crop_optimizer.ingestion.zarc_tabua.httpx.Client", side_effect=RuntimeError("offline")),
        pytest.raises(ZarcDataUnavailable, match="Não foi possível baixar"),
    ):
        load_zarc_table(["2914604"], get_settings(tmp_path))


def _sample_zarc_csv_bytes() -> bytes:
    header = (
        "Nome_cultura;SafraIni;SafraFin;Cod_Cultura;Cod_Ciclo;Cod_Solo;geocodigo;UF;municipio;"
        "Cod_Clima;Nome_Clima;Cod_Outros_Manejos;Nome_Outros_Manejos;Produtividade;Cod_NM;"
        "Cod_Munic;Cod_Meso;Cod_Micro;Portaria;" + ";".join(DEC_COLUMNS)
    )

    def row(cultura: str, geo: str, uf: str, mun: str, decs: dict[int, int]) -> str:
        vals = ";".join(str(decs.get(i, 0)) for i in range(1, 37))
        return f"{cultura};2026;2027;1;20;2;{geo};{uf};{mun};0;x;1;Sequeiro;;;1;1;1;Port.1;{vals}"

    lines = [
        header,
        row("Sorgo Forrageiro", "2914604", "BA", "Irecê", {33: 40, 34: 30, 1: 40}),
        row("Milho 1ª Safra", "2311306", "CE", "Quixadá", {5: 20, 6: 30}),
        row("Feijão Caupi", "2601102", "PE", "Araripina", {4: 20, 5: 20, 6: 30}),
    ]
    return ("\ufeff" + "\r\n".join(lines) + "\r\n").encode("utf-8")


def test_zarc_auto_download_and_region_switch(tmp_path) -> None:
    from crop_optimizer.analytics.rain_delay import fetch_location_zarc
    from crop_optimizer.domain.models import LocationSpec
    from crop_optimizer.ingestion.zarc_tabua import zarc_decendios_for_crops

    settings = get_settings(tmp_path)
    cfg = load_yaml_config("zarc")
    csv_bytes = _sample_zarc_csv_bytes()

    mock_stream_resp = MagicMock()
    mock_stream_resp.raise_for_status.return_value = None
    mock_stream_resp.headers = {"content-type": "text/csv; charset=utf-8"}
    mock_stream_resp.iter_bytes.return_value = [csv_bytes[:80], csv_bytes[80:]]

    stream_ctx = MagicMock()
    stream_ctx.__enter__.return_value = mock_stream_resp
    client_inst = MagicMock()
    client_inst.stream.return_value = stream_ctx

    with patch("crop_optimizer.ingestion.zarc_tabua.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value = client_inst
        table = load_zarc_table(["2914604"], settings)
        assert set(table["decendio"].to_list()) == {33, 34, 1}
        assert (settings.paths.bronze_source("zarc") / cfg["arquivo"]).exists()

        # Troca para outra região (ex.: roça marcada em Araripina/PE) reutiliza o CSV sem baixar de novo
        client_inst.stream.reset_mock()
        loc_roca = LocationSpec(
            location_id="roca_test",
            ibge_code="2601102",
            name="Araripina",
            state="PE",
            biome="",
            latitude=-7.57,
            longitude=-40.49,
        )
        rep = fetch_location_zarc(loc_roca, date(2026, 1, 1), date(2026, 2, 15), settings)
        assert rep.zarc_error is None
        caupi = next(w for w in rep.crop_windows if w.crop_id == "feijao_caupi")
        assert caupi.state == "aberta"
        assert rep.decendios_by_crop["feijao_caupi"][3] == 20
        client_inst.stream.assert_not_called()

    # Garante que decendios helper também lê corretamente
    decs = zarc_decendios_for_crops(load_zarc_table(["2601102"], settings), "2601102")
    assert decs["feijao_caupi"][5] == 30


def test_zarc_ckan_fallback_and_html_rejection(tmp_path) -> None:
    from crop_optimizer.ingestion.zarc_tabua import ZarcDataUnavailable

    settings = get_settings(tmp_path)
    cfg = load_yaml_config("zarc")
    csv_bytes = _sample_zarc_csv_bytes()

    html_resp = MagicMock()
    html_resp.raise_for_status.return_value = None
    html_resp.headers = {"content-type": "text/html"}
    html_ctx = MagicMock()
    html_ctx.__enter__.return_value = html_resp

    csv_resp = MagicMock()
    csv_resp.raise_for_status.return_value = None
    csv_resp.headers = {"content-type": "text/csv"}
    csv_resp.iter_bytes.return_value = [csv_bytes]
    csv_ctx = MagicMock()
    csv_ctx.__enter__.return_value = csv_resp

    ckan_resp = MagicMock()
    ckan_resp.raise_for_status.return_value = None
    ckan_resp.json.return_value = {
        "result": {"resources": [{"name": cfg["arquivo"], "format": "CSV", "url": "https://dados.exemplo/zarc.csv"}]}
    }

    client_inst = MagicMock()
    client_inst.stream.side_effect = [html_ctx, csv_ctx]
    client_inst.get.return_value = ckan_resp

    with patch("crop_optimizer.ingestion.zarc_tabua.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value = client_inst
        table = load_zarc_table(["2311306"], settings)
        assert set(table["decendio"].to_list()) == {5, 6}

    # Se até o fallback falhar com HTML, não deixa arquivo .part e levanta erro claro
    settings_fail = get_settings(tmp_path / "fail")
    client_fail = MagicMock()
    client_fail.stream.return_value = html_ctx
    client_fail.get.return_value = ckan_resp
    with (
        patch("crop_optimizer.ingestion.zarc_tabua.httpx.Client") as mock_client,
        pytest.raises(ZarcDataUnavailable, match="HTML"),
    ):
        mock_client.return_value.__enter__.return_value = client_fail
        load_zarc_table(["2311306"], settings_fail)
    assert not list(settings_fail.paths.bronze_source("zarc").glob("*.part"))
