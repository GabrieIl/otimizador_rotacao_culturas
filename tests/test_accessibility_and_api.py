"""Testes de acessibilidade (Rádio do Tempo TTS, PDF One-Pager, WhatsApp Twilio) e API HTTP."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from crop_optimizer.accessibility import (
    GoogleTTSProvider,
    OfflineWavTTSProvider,
    OpenAITTSProvider,
    TwilioWhatsAppClient,
    build_whatsapp_summary_message,
    compose_radio_script,
    create_tts_provider,
    generate_one_pager_pdf,
)
from crop_optimizer.analytics import build_survival_scoreboard_frame
from crop_optimizer.api import create_app
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig, TrafficLightLevel
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, location_map
from crop_optimizer.engine import MonteCarloRotationEngine, rank_by_survival
from crop_optimizer.lakehouse.catalog import SeasonalClimateStats


def _sample_results():
    stats = SeasonalClimateStats(
        location_id="petrolina_pe",
        safra_rain_mean_mm=430.0,
        safra_rain_std_mm=150.0,
        safrinha_rain_mean_mm=165.0,
        safrinha_rain_std_mm=80.0,
        safrinha_water_stress_prob=0.45,
        frost_prob_safrinha=0.0,
        mean_gwet_safra=0.40,
        mean_gwet_safrinha=0.25,
        veranico_prob=0.35,
        mean_smap_moisture=0.23,
        query_ms=1.0,
    )
    cfg = SimulationConfig(location_id="petrolina_pe", n_scenarios=1_000, safra_delay_days=21)
    results = MonteCarloRotationEngine().simulate_portfolio(DEFAULT_STRATEGIES, stats, cfg)
    return location_map()["petrolina_pe"], cfg, results


def test_radio_do_tempo_tts_providers() -> None:
    loc, cfg, results = _sample_results()
    trad = results[0]
    res = rank_by_survival(results)[0]

    for light in (TrafficLightLevel.VERDE, TrafficLightLevel.AMARELO, TrafficLightLevel.VERMELHO):
        script = compose_radio_script("Seu João", loc, cfg.safra_delay_days, light, trad, res)
        assert "Seu João" in script
        assert loc.name in script

    offline_tts = create_tts_provider("offline")
    assert isinstance(offline_tts, OfflineWavTTSProvider)
    wav_out = offline_tts.synthesize(script)
    assert wav_out.audio_bytes[:4] == b"RIFF"
    assert wav_out.mime_type == "audio/wav"

    # Google TTS fallback quando sem rede
    with patch("crop_optimizer.accessibility.radio_tempo.gTTS.write_to_fp", side_effect=RuntimeError("no net")):
        gtts_fb = GoogleTTSProvider().synthesize(script)
        assert gtts_fb.provider_used == "offline_wav"

    # OpenAI TTS sem chave -> fallback; com mock -> mp3
    assert OpenAITTSProvider(api_key=None).synthesize(script).provider_used == "offline_wav"
    mock_resp = MagicMock()
    mock_resp.content = b"ID3FAKE_MP3"
    mock_resp.raise_for_status.return_value = None
    with patch("crop_optimizer.accessibility.radio_tempo.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
        oa_out = create_tts_provider("openai", openai_api_key="sk-test").synthesize(script)
        assert oa_out.provider_used == "openai_tts"
        assert oa_out.audio_bytes == b"ID3FAKE_MP3"


def test_one_pager_pdf_is_single_page_and_valid_pdf() -> None:
    loc, cfg, results = _sample_results()
    scoreboard = build_survival_scoreboard_frame(results)
    pdf_bytes = generate_one_pager_pdf(loc, cfg, TrafficLightLevel.AMARELO, scoreboard, results)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1_000
    # Garante estritamente 1 página (/Type /Page aparece 1 vez no catálogo além de /Pages)
    assert pdf_bytes.count(b"/Type /Page\n") + pdf_bytes.count(b"/Type /Page ") + pdf_bytes.count(b"/Type /Page\r") == 1 or b"/Count 1" in pdf_bytes


def test_whatsapp_twilio_client_dry_run_and_live_mock() -> None:
    loc, cfg, results = _sample_results()
    trad = results[0]
    res = rank_by_survival(results)[0]
    msg = build_whatsapp_summary_message("Dona Maria", loc, 21, TrafficLightLevel.VERMELHO, trad, res)
    assert "Dona Maria" in msg
    assert "🔴" in msg

    client_dry = TwilioWhatsAppClient()
    dry_res = client_dry.send_message("+5587999990000", msg)
    assert not dry_res.sent
    assert dry_res.mode == "simulated_dry_run"

    client_live = TwilioWhatsAppClient(account_sid="AC123", auth_token="secret")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"sid": "SM999"}
    mock_resp.raise_for_status.return_value = None
    with patch("crop_optimizer.accessibility.whatsapp.httpx.Client") as mock_http:
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp
        live_res = client_live.send_message("+5587999990000", msg, media_url="https://example.com/audio.wav")
        assert live_res.sent
        assert live_res.sid == "SM999"


def test_http_api_endpoints_and_twilio_webhook(tmp_path: Path) -> None:
    app = create_app(get_settings(data_dir=tmp_path))
    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_sim = client.post(
        "/api/v1/simulate",
        json={"location_id": "petrolina_pe", "safra_delay_days": 21, "n_scenarios": 1000},
    )
    assert r_sim.status_code == 200
    data = r_sim.json()
    assert "traffic_light" in data
    assert len(data["scoreboard"]) == len(DEFAULT_STRATEGIES)

    r_radio = client.post("/api/v1/radio-do-tempo", json={"location_id": "quixada_ce", "n_scenarios": 500})
    assert r_radio.status_code == 200
    decoded_audio = base64.b64decode(r_radio.json()["audio_base64"])
    assert decoded_audio[:4] == b"RIFF"

    r_pdf = client.post("/api/v1/ficha-tecnica.pdf", json={"location_id": "sousa_pb", "n_scenarios": 500})
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"] == "application/pdf"
    assert r_pdf.content.startswith(b"%PDF")

    r_wa = client.post("/api/v1/whatsapp/webhook", data={"Body": "atraso 28 quixada", "From": "whatsapp:+558899999999"})
    assert r_wa.status_code == 200
    assert "<Response><Message>" in r_wa.text
