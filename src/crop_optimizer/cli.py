"""CLI unificada para ELT assíncrono, simulação de sobrevivência, API WhatsApp e Dashboard."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn

from crop_optimizer.accessibility import compose_radio_script
from crop_optimizer.analytics import (
    build_planting_window_risk_matrix,
    build_survival_scoreboard_frame,
    classify_traffic_light,
)
from crop_optimizer.api import create_app
from crop_optimizer.config import get_settings
from crop_optimizer.domain.models import SimulationConfig
from crop_optimizer.domain.presets import DEFAULT_STRATEGIES, location_map
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import (
    MonteCarloRotationEngine,
    compute_pareto_frontier,
    rank_by_survival,
)
from crop_optimizer.lakehouse.catalog import LakehouseCatalog


def cmd_elt(
    data_dir: str | None = None,
    mode: str | None = None,
    include_zarc: bool = False,
) -> None:
    settings = get_settings(data_dir)
    if mode in ("offline", "online"):
        settings.ingestion_mode = mode  # type: ignore[assignment]
    summary = CropLakehouseEltPipeline(settings, include_zarc_download=include_zarc).run()
    print(
        f"[ELT] Concluído em {summary.elapsed_ms:.1f} ms | "
        f"Clima: {summary.climate_rows} linhas | "
        f"ZARC: {summary.zarc_rows} | Mercado: {summary.market_rows}"
    )


def cmd_zarc(data_dir: str | None = None, ibge_codes: list[str] | None = None) -> None:
    """Pré-baixa a tábua ZARC oficial (MAPA/Embrapa) e gera o recorte Silver para os exemplos."""
    from crop_optimizer.domain.presets import DEFAULT_LOCATIONS
    from crop_optimizer.ingestion.zarc_tabua import load_zarc_table

    settings = get_settings(data_dir)
    codes = ibge_codes or [loc.ibge_code for loc in DEFAULT_LOCATIONS if loc.ibge_code]
    last_mb = -1

    def _on_progress(downloaded: int, total: int | None) -> None:
        nonlocal last_mb
        mb = int(downloaded // (10 * 1024 * 1024))
        if mb > last_mb:
            last_mb = mb
            if total and total > 0:
                print(f"[ZARC] Baixando: {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB...")
            else:
                print(f"[ZARC] Baixando: {downloaded / 1e6:.1f} MB...")

    table = load_zarc_table(codes, settings, progress_callback=_on_progress)
    print(f"[ZARC] Cache atualizado com {table.height} linhas para {len(codes)} município(s).")


def cmd_simulate(
    location_id: str = "petrolina_pe",
    n_scenarios: int = 10_000,
    horizon_years: int = 5,
    delay_days: int = 14,
    veranico_days: int = 7,
    data_dir: str | None = None,
) -> None:
    settings = get_settings(data_dir)
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()

    stats = catalog.get_seasonal_climate_stats(location_id)
    locs = {loc.location_id: loc for loc in catalog.load_locations()}
    location = locs.get(location_id) or location_map()["petrolina_pe"]
    crops = {c.crop_id: c for c in catalog.load_crops()}
    catalog.close()

    engine = MonteCarloRotationEngine(crops_catalog=crops)
    config = SimulationConfig(
        location_id=location_id,
        n_scenarios=n_scenarios,
        horizon_years=horizon_years,
        safra_delay_days=delay_days,
        veranico_days=veranico_days,
    )
    results = engine.simulate_portfolio(DEFAULT_STRATEGIES, stats, config)
    compute_pareto_frontier(results, criterion="two_year_loss")
    ranked = rank_by_survival(results)
    scoreboard = build_survival_scoreboard_frame(results)

    matrix = build_planting_window_risk_matrix(
        stats,
        delay_days_grid=[delay_days],
        n_samples=min(2_000, n_scenarios),
        config=config,
    )
    corn_row = matrix.filter(matrix["crop_id"] == "milho_sertanejo")
    light = classify_traffic_light(float(corn_row["failure_prob_pct"][0]))

    by_id = {r.strategy.strategy_id: r for r in results}
    traditional = by_id.get("so_milho_tradicional", results[0])
    resilient = ranked[0]

    total_ms = sum(r.execution_ms for r in results)
    print(f"[DuckDB] Consulta climática ({location_id}): {stats.query_ms:.2f} ms")
    print(
        f"[Monte Carlo] {len(results)} estratégias x {n_scenarios:,} cenários "
        f"em {total_ms:.1f} ms ({total_ms / 1000.0:.3f} s) | Semáforo: {light.label} - {light.guidance}"
    )
    print(
        scoreboard.select(
            [
                "short_name",
                "survival_score_of_10",
                "prob_two_consecutive_losses_pct",
                "expected_food_kg_ha_year",
                "expected_forage_kg_ha_year",
                "food_score",
                "forage_score",
                "shield_score",
            ]
        )
    )
    print("\n[Rádio do Tempo]")
    print(compose_radio_script(config.farmer_name, location, delay_days, light, traditional, resilient))


def cmd_app(extra_args: list[str] | None = None) -> None:
    dashboard_path = Path(__file__).resolve().parent / "app" / "dashboard.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(dashboard_path), *(extra_args or [])]
    subprocess.run(cmd, check=True)


def cmd_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(create_app(), host=host, port=port)


def cmd_whatsapp(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve só o WhatsApp (webhook, /media e /health), para expor pelo túnel. Recusa subir sem a assinatura."""
    settings = get_settings()
    missing = [name for name, value in (("ACAUA_PUBLIC_URL", settings.public_url),
                                        ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                                        ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                                        ("OPENAI_API_KEY", settings.openai_api_key)) if not value]
    if missing:
        sys.exit(f"Falta no .env: {', '.join(missing)}. Sem isso o webhook não confere quem chama.")
    print(f"WhatsApp do Acauã em http://{host}:{port} (só /health, webhook e /media)")
    print(f"Webhook para o Twilio: {settings.public_url}/api/v1/whatsapp/webhook (POST)")
    uvicorn.run(create_app(settings, somente_whatsapp=True), host=host, port=port)


def cmd_conversa(
    texto: str | None,
    sessao_id: str = "terminal",
    data: str | None = None,
    sem_ia: bool = False,
    nova: bool = False,
    audio: str | None = None,
    falar_resposta: bool = False,
) -> None:
    """Conversa com o agente no terminal (o mesmo agente do WhatsApp). Sem texto: modo interativo."""
    from datetime import date

    from crop_optimizer.agente.nucleo import Agente
    from crop_optimizer.agente.openai_api import OpenAIClient
    from crop_optimizer.agente.sessao import SessaoStore
    from crop_optimizer.agente.voz import falar, transcrever

    store = SessaoStore()
    if nova:
        store.apagar(sessao_id)
    sessao = store.carregar(sessao_id)
    if data:
        sessao.simular = date.fromisoformat(data)
    agente = Agente(client=OpenAIClient(api_key="") if sem_ia else None)

    def turno(pergunta: str) -> None:
        resposta = agente.responder(sessao, pergunta)
        store.salvar(sessao)
        print(f"\nAcauã: {resposta.texto}")
        print(f"  [{resposta.fonte}; ferramentas: {', '.join(resposta.ferramentas) or 'nenhuma'}"
              + (f"; {' | '.join(resposta.observacoes)}" if resposta.observacoes else "") + "]")
        if resposta.uso:
            u = resposta.uso
            print(f"  [tokens: {u['rodadas']} rodada(s), entrada {u['entrada']} ({u['entrada_em_cache']} em cache), "
                  f"saída {u['saida']} ({u['raciocinio']} de raciocínio)]")
        if falar_resposta:
            som = falar(resposta.texto)
            print(f"  [áudio da resposta ({som.provider}): {som.path}]")
        print()

    if audio:
        path = Path(audio)
        mime = {".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
                ".wav": "audio/wav"}.get(path.suffix.lower(), "audio/ogg")
        texto = transcrever(path.read_bytes(), mime)
        print(f"Você (áudio transcrito): {texto}")
    if texto:
        turno(texto)
        return
    print("Converse com o Acauã (linha vazia ou 'sair' para terminar).")
    while True:
        try:
            pergunta = input("Você: ").strip()
        except EOFError:
            break
        if not pergunta or pergunta.lower() == "sair":
            break
        turno(pergunta)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="crop-opt",
        description="Motor Estocástico de Resiliência do Sertão",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_elt = subparsers.add_parser("elt", help="Executa pipeline ELT assíncrono (Bronze -> Silver -> Gold Parquet)")
    p_elt.add_argument("--data-dir", default=None)
    p_elt.add_argument("--mode", choices=["offline", "online"], default=None)
    p_elt.add_argument("--include-zarc", action="store_true", help="Baixa a tábua real ZARC para o lakehouse")

    p_zarc = subparsers.add_parser("zarc", help="Pré-baixa a tábua oficial ZARC (MAPA/Embrapa) para cache local")
    p_zarc.add_argument("--data-dir", default=None)
    p_zarc.add_argument("--ibge", nargs="*", default=None, help="Códigos IBGE extras para indexar na Silver")

    p_sim = subparsers.add_parser("simulate", help="Roda benchmark DuckDB + Monte Carlo (10k cenários)")
    p_sim.add_argument("--location", default="petrolina_pe")
    p_sim.add_argument("--scenarios", type=int, default=10_000)
    p_sim.add_argument("--years", type=int, default=5)
    p_sim.add_argument("--delay-days", type=int, default=14)
    p_sim.add_argument("--veranico-days", type=int, default=7)
    p_sim.add_argument("--data-dir", default=None)

    subparsers.add_parser("app", help="Inicia o dashboard interativo Streamlit")

    p_api = subparsers.add_parser("api", help="Inicia API HTTP para Rádio do Tempo, PDF e Webhook Twilio")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8000)

    p_wa = subparsers.add_parser("whatsapp", help="Serve só o webhook do WhatsApp (para expor pelo túnel)")
    p_wa.add_argument("--host", default="127.0.0.1")
    p_wa.add_argument("--port", type=int, default=8000)

    p_conv = subparsers.add_parser("conversa", help="Conversa com o agente do Acauã no terminal")
    p_conv.add_argument("texto", nargs="?", default=None, help="Pergunta; sem ela, abre o modo interativo")
    p_conv.add_argument("--sessao", default="terminal", help="Chave da conversa (no WhatsApp é o número)")
    p_conv.add_argument("--data", default=None, help="Simular outro dia (AAAA-MM-DD), para demonstração")
    p_conv.add_argument("--sem-ia", action="store_true", help="Responder só com as regras, sem a OpenAI")
    p_conv.add_argument("--nova", action="store_true", help="Esquecer a conversa anterior desta sessão")
    p_conv.add_argument("--audio", default=None, help="Arquivo de áudio com a pergunta (.ogg, .mp3, .m4a)")
    p_conv.add_argument("--falar", action="store_true", help="Gerar também o áudio da resposta")

    args = parser.parse_args(argv)
    if args.command == "elt":
        cmd_elt(data_dir=args.data_dir, mode=args.mode, include_zarc=args.include_zarc)
    elif args.command == "zarc":
        cmd_zarc(data_dir=args.data_dir, ibge_codes=args.ibge)
    elif args.command == "simulate":
        cmd_simulate(
            location_id=args.location,
            n_scenarios=args.scenarios,
            horizon_years=args.years,
            delay_days=args.delay_days,
            veranico_days=args.veranico_days,
            data_dir=args.data_dir,
        )
    elif args.command == "app":
        cmd_app()
    elif args.command == "api":
        cmd_api(host=args.host, port=args.port)
    elif args.command == "whatsapp":
        cmd_whatsapp(host=args.host, port=args.port)
    elif args.command == "conversa":
        cmd_conversa(args.texto, args.sessao, args.data, args.sem_ia, args.nova, args.audio, args.falar or bool(args.audio))


if __name__ == "__main__":
    main()
