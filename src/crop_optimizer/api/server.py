"""API HTTP de integração (Starlette) para Rádio do Tempo, Ficha PDF e Webhook WhatsApp (Twilio)."""

from __future__ import annotations

import base64
import re

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from crop_optimizer.accessibility import (
    compose_radio_script,
    create_tts_provider,
    generate_one_pager_pdf,
)
from crop_optimizer.agente.voz import audio_dir
from crop_optimizer.analytics import (
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.canais.whatsapp import MensagemWhatsApp, WhatsAppService, twiml
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

_MEDIA_NAME = re.compile(r"[0-9a-f]{32}\.(ogg|mp3)")


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
        n_samples=min(2_000, config.n_scenarios),
        config=config,
    )
    corn_row = matrix.filter(matrix["crop_id"] == "milho_sertanejo")
    corn_risk = float(corn_row["failure_prob_pct"][0]) if corn_row.height > 0 else 50.0
    traffic_light: TrafficLightLevel = classify_traffic_light(corn_risk)

    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    resilient = ranked[0]
    return location, results, traditional, resilient, traffic_light, stats


def create_app(
    settings: Settings | None = None, whatsapp: WhatsAppService | None = None, somente_whatsapp: bool = False
) -> Starlette:
    """Fábrica da aplicação HTTP Starlette para integração WhatsApp/Twilio e Back-office.

    `somente_whatsapp=True` deixa só /health, o webhook e /media: é o modo para expor na internet (túnel),
    porque as outras rotas não têm senha e a do Rádio do Tempo gasta crédito da OpenAI.
    """
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
                    "label": light.label,
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

    service: dict[str, WhatsAppService] = {}

    def whatsapp_service() -> WhatsAppService:
        if "svc" not in service:  # criado na primeira mensagem (o resto da API não precisa da OpenAI)
            service["svc"] = whatsapp or WhatsAppService(cfg_settings)
        return service["svc"]

    async def whatsapp_webhook(request: Request) -> Response:
        """Twilio WhatsApp: responde na hora e atende em segundo plano (texto, áudio ou localização)."""
        svc = whatsapp_service()
        params = {k: str(v) for k, v in (await request.form()).items()}
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not svc.assinatura_ok(path, params, request.headers.get("X-Twilio-Signature")):
            return Response("assinatura inválida", status_code=403)
        msg = MensagemWhatsApp.from_form(params)
        if not svc.nova(msg.sid):
            return Response(twiml(), media_type="application/xml")
        return Response(
            svc.resposta_imediata(msg),
            media_type="application/xml",
            background=BackgroundTask(svc.processar, msg),
        )

    async def media(request: Request) -> Response:
        """Áudio das respostas, para o Twilio baixar (nome = hash do texto; nada além desta pasta)."""
        name = request.path_params["name"]
        if not _MEDIA_NAME.fullmatch(name):
            return Response(status_code=404)
        path = audio_dir(cfg_settings) / name
        if not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, media_type="audio/ogg" if name.endswith(".ogg") else "audio/mpeg")

    whatsapp_routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/v1/whatsapp/webhook", whatsapp_webhook, methods=["POST"]),
        Route("/media/{name}", media, methods=["GET"]),
    ]
    if somente_whatsapp:
        return Starlette(routes=whatsapp_routes)
    return Starlette(
        routes=[
            *whatsapp_routes,
            Route("/api/v1/simulate", simulate, methods=["POST"]),
            Route("/api/v1/radio-do-tempo", radio_do_tempo, methods=["POST"]),
            Route("/api/v1/ficha-tecnica.pdf", ficha_pdf, methods=["POST"]),
        ]
    )
