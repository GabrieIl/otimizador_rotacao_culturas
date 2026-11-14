"""API HTTP de integração (Starlette) para Rádio do Tempo, Ficha PDF e Webhook WhatsApp (Twilio)."""

from __future__ import annotations

import base64
import re
from html import escape

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from crop_optimizer.accessibility import (
    build_whatsapp_summary_message,
    compose_radio_script,
    create_tts_provider,
    generate_one_pager_pdf,
)
from crop_optimizer.analytics import (
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.config import Settings, get_settings
from crop_optimizer.domain.models import LocationSpec, SimulationConfig, TrafficLightLevel
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, location_map
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
)
from crop_optimizer.lakehouse import LakehouseCatalog


def _parse_config(payload: dict[str, object]) -> SimulationConfig:
    return SimulationConfig(
        location_id=str(payload.get("location_id", "petrolina_pe")),
        horizon_years=int(payload.get("horizon_years", 5)),
        n_scenarios=int(payload.get("n_scenarios", 5_000)),
        safra_delay_days=int(payload.get("safra_delay_days", 14)),
        veranico_days=int(payload.get("veranico_days", 7)),
        farmer_name=str(payload.get("farmer_name", "Seu João")),
    )


def _run_simulation_bundle(
    settings: Settings,
    config: SimulationConfig,
):
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()

    stats = catalog.get_seasonal_climate_stats(config.location_id)
    locs = {loc.location_id: loc for loc in catalog.load_locations()}
    location: LocationSpec = locs.get(config.location_id) or location_map()["petrolina_pe"]
    crops = {c.crop_id: c for c in catalog.load_crops()}
    catalog.close()

    engine = MonteCarloRotationEngine(crops_catalog=crops)
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, stats, config)
    compute_pareto_frontier(results, criterion="two_year_loss")
    ranked = rank_by_survival(results)

    matrix = build_planting_window_risk_matrix(
        stats,
        delay_days_grid=[config.safra_delay_days],
        veranico_days=config.veranico_days,
        n_samples=min(2_000, config.n_scenarios),
    )
    corn_row = matrix.filter(matrix["crop_id"] == "milho_sertanejo")
    corn_risk = float(corn_row["failure_prob_pct"][0]) if corn_row.height > 0 else 50.0
    traffic_light: TrafficLightLevel = classify_traffic_light(corn_risk)

    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    resilient = ranked[0]
    return location, results, traditional, resilient, traffic_light, stats


def create_app(settings: Settings | None = None) -> Starlette:
    """Fábrica da aplicação HTTP Starlette para integração WhatsApp/Twilio e Back-office."""
    cfg_settings = settings or get_settings()

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "sertao-resilience-engine"})

    async def simulate(request: Request) -> JSONResponse:
        payload = await request.json() if await request.body() else {}
        config = _parse_config(payload)
        location, results, traditional, resilient, light, stats = _run_simulation_bundle(
            cfg_settings,
            config,
        )
        scoreboard = build_survival_scoreboard_frame(results)
        script = compose_radio_script(
            config.farmer_name,
            location,
            config.safra_delay_days,
            light,
            traditional,
            resilient,
        )
        return JSONResponse(
            {
                "location": location.model_dump(),
                "traffic_light": {
                    "level": light.value,
                    "emoji": light.emoji,
                    "guidance": light.guidance,
                },
                "scoreboard": scoreboard.to_dicts(),
                "radio_script": script,
                "duckdb_query_ms": round(stats.query_ms, 2),
            }
        )

    async def radio_do_tempo(request: Request) -> JSONResponse:
        payload = await request.json() if await request.body() else {}
        config = _parse_config(payload)
        location, _results, traditional, resilient, light, _stats = _run_simulation_bundle(
            cfg_settings,
            config,
        )
        script = compose_radio_script(
            config.farmer_name,
            location,
            config.safra_delay_days,
            light,
            traditional,
            resilient,
        )
        tts = create_tts_provider(cfg_settings.tts_provider, cfg_settings.openai_api_key)
        audio = tts.synthesize(script)
        return JSONResponse(
            {
                "script": audio.script,
                "provider": audio.provider_used,
                "mime_type": audio.mime_type,
                "audio_base64": base64.b64encode(audio.audio_bytes).decode("ascii"),
            }
        )

    async def ficha_pdf(request: Request) -> Response:
        payload = await request.json() if await request.body() else {}
        config = _parse_config(payload)
        location, results, _traditional, _resilient, light, _stats = _run_simulation_bundle(
            cfg_settings,
            config,
        )
        scoreboard = build_survival_scoreboard_frame(results)
        pdf_bytes = generate_one_pager_pdf(location, config, light, scoreboard, results)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="ficha_o_que_nao_sabemos.pdf"'},
        )

    async def whatsapp_webhook(request: Request) -> Response:
        form = await request.form()
        body = str(form.get("Body", "")).lower()
        delay_match = re.search(r"(\d{1,2})", body)
        delay_days = min(40, int(delay_match.group(1))) if delay_match else 14

        loc_id = "petrolina_pe"
        for candidate in ("quixada", "sousa", "irece", "petrolina"):
            if candidate in body:
                loc_id = {
                    "quixada": "quixada_ce",
                    "sousa": "sousa_pb",
                    "irece": "irece_ba",
                    "petrolina": "petrolina_pe",
                }[candidate]
                break

        config = SimulationConfig(location_id=loc_id, safra_delay_days=delay_days, n_scenarios=2_000)
        location, _results, traditional, resilient, light, _stats = _run_simulation_bundle(
            cfg_settings,
            config,
        )
        msg = build_whatsapp_summary_message(
            config.farmer_name,
            location,
            delay_days,
            light,
            traditional,
            resilient,
        )
        twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(msg)}</Message></Response>'
        return Response(content=twiml, media_type="application/xml")

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/api/v1/simulate", simulate, methods=["POST"]),
            Route("/api/v1/radio-do-tempo", radio_do_tempo, methods=["POST"]),
            Route("/api/v1/ficha-tecnica.pdf", ficha_pdf, methods=["POST"]),
            Route("/api/v1/whatsapp/webhook", whatsapp_webhook, methods=["POST"]),
        ]
    )
