"""Cálculos do Acauã sem Streamlit: a mesma cadeia da página Plantio, para o agente e a API.

Cada passo repete o que `app/dashboard.py` e `app/common.py` fazem, com os mesmos parâmetros,
para a resposta no WhatsApp bater com a tela. Se a página mudar o cálculo, mude aqui também
(ver tests/test_agente_ferramentas.py, que compara as duas).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache

import polars as pl

from crop_optimizer.analytics import agua, build_planting_window_risk_matrix
from crop_optimizer.analytics.crop_advice import CropVerdict, crop_verdict, irrigated_verdict
from crop_optimizer.analytics.rain_delay import (
    CropWindowStatus,
    RainDelayReport,
    ZarcStatusReport,
    build_rain_delay_report,
    fetch_location_zarc,
    seasonal_stats_from_rain_series,
)
from crop_optimizer.analytics.soil_suitability import (
    CropSuitability,
    available_nitrogen_kg_ha,
    evaluate,
    initial_markov_state,
    texture_class,
)
from crop_optimizer.config import get_settings, load_yaml_config
from crop_optimizer.domain.crop_registry import is_irrigated, is_perennial, ordered_ids
from crop_optimizer.domain.models import (
    LocationSpec,
    RotationStrategy,
    SimulationConfig,
    SoilHealthState,
    StrategySimulationResult,
)
from crop_optimizer.domain.presets import crop_map
from crop_optimizer.domain.soil_profile import SoilProfile, build_profile, load_field_data
from crop_optimizer.elt.pipeline import CropLakehouseEltPipeline
from crop_optimizer.engine import MonteCarloRotationEngine, compute_pareto_frontier
from crop_optimizer.engine.candidates import candidate_strategies, current_strategy
from crop_optimizer.engine.rain_onset import season_start_for
from crop_optimizer.ingestion.power_temperature import (
    TemperatureUnavailable,
    fetch_temperature_series,
)
from crop_optimizer.ingestion.rain_history import RainDataUnavailable, fetch_rain_series
from crop_optimizer.ingestion.soilgrids import SoilGridsUnavailable, fetch_soilgrids_nearby
from crop_optimizer.ingestion.terrain import TerrainUnavailable, terrain_at
from crop_optimizer.lakehouse.catalog import LakehouseCatalog, SeasonalClimateStats

# mesmos valores da página Plantio (app/dashboard.py)
DELAY_GRID = [0, 7, 14, 21, 28, 35]
N_SCENARIOS = 10_000
DEFAULT_VERANICO_DAYS = 7  # sem chuva firme no histórico, a página usa 7 dias


def _crop_names() -> dict[str, str]:
    return {k: str(v["nome"]) for k, v in load_yaml_config("aptidao")["culturas"].items()}


CROP_IDS = [c for c in ordered_ids() if c in _crop_names()] + [c for c in _crop_names() if c not in ordered_ids()]
DEFAULT_RISK_PCT = 50.0  # cultura sem linha na matriz: a página assume 50%
HORIZONS = [1, 2, 3, 5, 10]  # anos à frente do ranking das rotações
TOP_ROTATIONS = 5  # rotações mostradas no ranking (mais a de hoje)

RainOverride = tuple[str, float, float, float, float]

_catalog_lock = threading.Lock()  # DuckDB: uma consulta por vez (a API atende em threads)


@lru_cache(maxsize=1)
def _catalog() -> LakehouseCatalog:
    settings = get_settings()
    catalog = LakehouseCatalog(settings)
    if not catalog.is_ready():
        CropLakehouseEltPipeline(settings).run()
    return catalog


# --- chuva e solo (dado real) -------------------------------------------------

@lru_cache(maxsize=64)
def _rain_report_cached(
    location_json: str, as_of: date, soil_group: str | None = None, cycle_code: str | None = None
) -> RainDelayReport:
    return build_rain_delay_report(
        LocationSpec.model_validate_json(location_json),
        as_of,
        soil_group=soil_group,
        cycle_code=cycle_code,
    )


def rain_report(
    location: LocationSpec, as_of: date, soil_group: str | None = None, cycle_code: str | None = None
) -> RainDelayReport:
    """Atraso da chuva + janelas ZARC. Levanta RainDataUnavailable se não houver chuva real."""
    return _rain_report_cached(location.model_dump_json(), as_of, soil_group, cycle_code)


@lru_cache(maxsize=64)
def _site_layers(lat: float, lon: float):
    warnings: list[str] = []
    try:
        soil, moved = fetch_soilgrids_nearby(lat, lon)
    except SoilGridsUnavailable as exc:
        soil, moved = None, None
        warnings.append(f"Mapa de solo indisponível: {exc}")
    if moved:
        warnings.append(f"O mapa de solo não tem valor no ponto exato; usamos o ponto com dado mais próximo, {moved}.")
    elif soil is not None and not soil:
        warnings.append("O mapa de solo não tem valor nesse ponto nem a 3 km dele (área urbana ou água).")
    try:
        terrain = terrain_at(lat, lon)
    except TerrainUnavailable as exc:
        terrain = None
        warnings.append(f"Relevo indisponível: {exc}")
    return soil, terrain, tuple(warnings)


def soil_profile(location: LocationSpec) -> SoilProfile:
    """Perfil do solo: análise de campo > mapa (SoilGrids + SRTM) > valor típico (igual à Início)."""
    soil, terrain, warnings = _site_layers(round(location.latitude, 4), round(location.longitude, 4))
    return build_profile(soil, terrain, load_field_data(location.location_id), list(warnings))


# --- risco por cultura e rotações (clima sintético do município de exemplo) ---

@dataclass(frozen=True, slots=True)
class VeranicoArgs:
    probability: float | None
    lengths: tuple[int, ...]
    typical_days: int

    @classmethod
    def from_report(cls, report: RainDelayReport | None) -> VeranicoArgs:
        v = report.veranico if report is not None else None
        if v is not None and v.seasons_with_onset:
            return cls(round(v.probability, 3), v.veranico_lengths, v.typical_longest)
        return cls(None, (), DEFAULT_VERANICO_DAYS)


def _rain_override(location: LocationSpec, exemplo_id: str, veranico: VeranicoArgs) -> RainOverride | None:
    """Calibração NASA POWER do ponto para o motor (igual a app/dashboard.py)."""
    try:
        series = fetch_rain_series(location, today=date.today())
    except RainDataUnavailable:
        return None
    with _catalog_lock:
        base_stats = _catalog().get_seasonal_climate_stats(exemplo_id)
    pt_stats = seasonal_stats_from_rain_series(
        series, base_stats, veranico_prob=veranico.probability, veranico_lengths=veranico.lengths
    )
    if pt_stats.location_id != series.location_id:
        return None
    return (
        pt_stats.location_id,
        pt_stats.safra_rain_mean_mm,
        pt_stats.safra_rain_std_mm,
        pt_stats.safrinha_rain_mean_mm,
        pt_stats.safrinha_rain_std_mm,
    )


def _climate_stats(
    exemplo_id: str, veranico: VeranicoArgs, rain_override: RainOverride | None = None
) -> SeasonalClimateStats:
    with _catalog_lock:
        stats = _catalog().get_seasonal_climate_stats(exemplo_id)
    if rain_override is not None:
        pt_id, safra_mean, safra_std, safrinha_mean, safrinha_std = rain_override
        stats = replace(
            stats,
            location_id=pt_id,
            safra_rain_mean_mm=safra_mean,
            safra_rain_std_mm=safra_std,
            safrinha_rain_mean_mm=safrinha_mean,
            safrinha_rain_std_mm=safrinha_std,
        )
    if veranico.probability is None:
        return stats
    return replace(stats, veranico_prob=veranico.probability, veranico_lengths=veranico.lengths)


def _soil_config(exemplo_id: str, soil: SoilInputs) -> SimulationConfig:
    """Motor com o solo de hoje: a mesma configuração no aviso e no ranking (como na página)."""
    return SimulationConfig(
        location_id=exemplo_id,
        n_scenarios=N_SCENARIOS,
        initial_soil_state=SoilHealthState(soil.initial_state),
        initial_organic_matter_pct=soil.om_pct,
        initial_nitrogen_kg_ha=soil.n_kg_ha,
        soil_crop_factors=dict(soil.factors),
        veranico_days=0,  # o veranico vem do sorteio com o histórico real
    )


@lru_cache(maxsize=32)
def risk_matrix(
    exemplo_id: str,
    safra_delay_days: int,
    veranico: VeranicoArgs,
    soil: SoilInputs,
    rain_override: RainOverride | None = None,
) -> pl.DataFrame:
    """Matriz atraso x cultura do aviso: o mesmo motor e a mesma régua de quebra do ranking."""
    return build_planting_window_risk_matrix(
        _climate_stats(exemplo_id, veranico, rain_override),
        delay_days_grid=sorted({*DELAY_GRID, safra_delay_days}),
        n_samples=N_SCENARIOS,
        config=_soil_config(exemplo_id, soil),
    )


def crop_failure_pct(matrix: pl.DataFrame, crop_id: str, delay_days: int) -> float | None:
    row = matrix.filter((pl.col("crop_id") == crop_id) & (pl.col("delay_days") == delay_days))
    return float(row["failure_prob_pct"][0]) if row.height else None


@dataclass(frozen=True, slots=True)
class SoilInputs:
    initial_state: int
    om_pct: float
    n_kg_ha: float
    factors: tuple[tuple[str, float], ...]

    @classmethod
    def from_profile(cls, profile: SoilProfile, suitability: list[CropSuitability]) -> SoilInputs:
        return cls(
            int(initial_markov_state(profile.get("mo_pct"))),
            round(profile.get("mo_pct"), 2),
            round(available_nitrogen_kg_ha(profile), 1),
            tuple(sorted((c.crop_id, round(c.yield_factor, 3)) for c in suitability)),
        )


@lru_cache(maxsize=512)
def _simulate_one(
    strategy_key: tuple[str, str, str, tuple[str, ...]],
    config_json: str,
    exemplo_id: str,
    veranico: VeranicoArgs,
    rain_override: RainOverride | None = None,
) -> StrategySimulationResult:
    """Uma rotação em cache; trocar restrições reutiliza as combinações já simuladas."""
    strategy_id, name, description, crops_seq = strategy_key
    strategy = RotationStrategy(
        strategy_id=strategy_id,
        name=name,
        short_name=name,
        description=description,
        annual_sequence=list(crops_seq),
    )
    config = SimulationConfig.model_validate_json(config_json)
    with _catalog_lock:
        lake_crops = {c.crop_id: c for c in _catalog().load_crops()}
    crops = {**crop_map(), **lake_crops}
    return MonteCarloRotationEngine(crops_catalog=crops).simulate_strategy(
        strategy, _climate_stats(exemplo_id, veranico, rain_override), config
    )


@lru_cache(maxsize=64)
def simulate_rotations(
    exemplo_id: str,
    horizon_years: int,
    safra_delay_days: int,
    veranico: VeranicoArgs,
    soil: SoilInputs,
    rain_override: RainOverride | None = None,
    required: tuple[str, ...] = (),
    excluded: tuple[str, ...] = (),
    current_crops: tuple[str, ...] = (),
) -> list[StrategySimulationResult]:
    """10.000 cenários das rotações candidatas + jeito de hoje, com os mesmos parâmetros da página Plantio."""
    current = current_strategy(list(current_crops))
    candidates = candidate_strategies(list(required), list(excluded))
    same_as_current = {tuple(sorted(current.annual_sequence))}
    candidates = [c for c in candidates if tuple(sorted(c.annual_sequence)) not in same_as_current]
    config_json = _soil_config(exemplo_id, soil).model_copy(
        update={"horizon_years": horizon_years, "safra_delay_days": safra_delay_days}
    ).model_dump_json()
    results = [
        _simulate_one(
            (strat.strategy_id, strat.short_name or strat.name, strat.description, tuple(strat.annual_sequence)),
            config_json,
            exemplo_id,
            veranico,
            rain_override,
        )
        for strat in [current, *candidates]
    ]
    compute_pareto_frontier(results, criterion="two_year_loss")
    return results


# --- pacote completo para um local e uma data --------------------------------

@dataclass(slots=True)
class Panorama:
    """Tudo o que a página Plantio mostra, para um local e uma data."""

    location: LocationSpec
    exemplo_id: str
    as_of: date
    report: RainDelayReport | None
    zarc: ZarcStatusReport
    rain_error: str | None
    profile: SoilProfile
    suitability: list[CropSuitability]
    safra_delay_days: int
    veranico: VeranicoArgs
    soil: SoilInputs
    matrix: pl.DataFrame
    soil_group: str
    cycle_code: str | None
    rain_override: RainOverride | None

    def risk_pct(self, crop_id: str) -> float:
        pct = crop_failure_pct(self.matrix, crop_id, self.safra_delay_days)
        return DEFAULT_RISK_PCT if pct is None else pct

    def window(self, crop_id: str) -> CropWindowStatus | None:
        """Janela do ZARC; cultura do ZARC sem janela no município vira "sem indicação" (como na página)."""
        window = next((cw for cw in self.zarc.crop_windows if cw.crop_id == crop_id), None)
        zarc_crops = set(load_yaml_config("zarc")["culturas"])
        if crop_id in zarc_crops and window is None and self.zarc.zarc_error is None:
            window = CropWindowStatus(crop_id, None, "sem_indicacao")
        return window

    def verdict(
        self,
        crop_id: str,
        water: dict[str, tuple[agua.HoldDays, agua.SoilWaterToday | None, agua.IrrigationPlan | None]] | None = None,
    ) -> CropVerdict:
        """O aviso do Acauã para a cultura (o mesmo da página Plantio)."""
        if is_irrigated(crop_id):
            resolved_water = water if water is not None else self.water()
            plan = resolved_water[crop_id][2] if resolved_water is not None and crop_id in resolved_water else None
            return irrigated_verdict(crop_id, _crop_names().get(crop_id, crop_id), plan)
        status = self.report.status if self.report is not None else None
        return crop_verdict(crop_id, self.risk_pct(crop_id), status, self.window(crop_id), self.safra_delay_days)

    def rotations(
        self,
        horizon_years: int,
        required: tuple[str, ...] = (),
        excluded: tuple[str, ...] = (),
        current_crops: tuple[str, ...] = (),
    ) -> list[StrategySimulationResult]:
        return simulate_rotations(
            self.exemplo_id,
            horizon_years,
            self.safra_delay_days,
            self.veranico,
            self.soil,
            self.rain_override,
            required,
            excluded,
            current_crops,
        )

    def water(
        self,
    ) -> dict[str, tuple[agua.HoldDays, agua.SoilWaterToday | None, agua.IrrigationPlan | None]] | None:
        """Água da roça por cultura (dias que aguenta, água no solo hoje e plano de rega), como na página.

        None se a chuva ou a temperatura do NASA POWER não estiverem disponíveis.
        """
        try:
            return water_by_crop(self.location, self.as_of, self.profile, tuple(CROP_IDS))
        except (RainDataUnavailable, TemperatureUnavailable):
            return None


def panorama(
    location: LocationSpec,
    exemplo_id: str,
    as_of: date,
    *,
    soil_group: str | None = None,
    cycle_code: str | None = None,
) -> Panorama:
    profile = soil_profile(location)
    eff_soil_group = soil_group or texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    suitability = evaluate(profile)
    try:
        report = rain_report(location, as_of, soil_group=eff_soil_group, cycle_code=cycle_code)
    except RainDataUnavailable as exc:
        report, rain_error, delay = None, str(exc), 0
        zarc = fetch_location_zarc(
            location,
            season_start_for(as_of, 1),
            as_of,
            soil_group=eff_soil_group,
            cycle_code=cycle_code,
        )
    else:
        rain_error, delay = None, report.motor_delay_days
        zarc = ZarcStatusReport(
            crop_windows=report.crop_windows,
            zarc_safra=report.zarc_safra,
            zarc_error=report.zarc_error,
            decendios_by_crop=report.decendios_by_crop,
            soil_group=report.soil_group,
            cycle_code=report.cycle_code,
        )
    veranico = VeranicoArgs.from_report(report)
    soil = SoilInputs.from_profile(profile, suitability)
    rain_override = _rain_override(location, exemplo_id, veranico)
    return Panorama(
        location=location,
        exemplo_id=exemplo_id,
        as_of=as_of,
        report=report,
        zarc=zarc,
        rain_error=rain_error,
        profile=profile,
        suitability=suitability,
        safra_delay_days=delay,
        veranico=veranico,
        soil=soil,
        matrix=risk_matrix(exemplo_id, delay, veranico, soil, rain_override),
        soil_group=eff_soil_group,
        cycle_code=cycle_code,
        rain_override=rain_override,
    )


# --- água da roça (NASA POWER chuva + temperatura, FAO-56) --------------------

@lru_cache(maxsize=32)
def _water_cached(location_json: str, as_of: date, texture_group: str, depth_m: float | None,
                  crop_ids: tuple[str, ...]):
    location = LocationSpec.model_validate_json(location_json)
    today = max(as_of, date.today())
    rain = fetch_rain_series(location, today=today)
    temp = fetch_temperature_series(location, today=today)
    n = min(rain.dates.size, temp.dates.size)
    dates, precip = rain.dates[:n], rain.precip_mm[:n]
    et0 = agua.daily_et0(temp.dates[:n], temp.tmax_c[:n], temp.tmin_c[:n], location.latitude)
    clim = agua.et0_climatology(dates, et0)
    ref = rain_report(location, as_of).status.reference
    cad = agua.cad_mm_per_m(texture_group)
    out = {}
    for crop_id in crop_ids:
        crop = agua.crop_water(crop_id)
        hold = agua.hold_days(crop_id, cad, agua.critical_et0(dates, et0, ref, crop), depth_m)
        plan = (
            agua.irrigation_plan(crop_id, cad, clim, as_of, is_perennial(crop_id), depth_m)
            if is_irrigated(crop_id)
            else None
        )
        out[crop_id] = (hold, agua.soil_water_today(dates, precip, et0, cad, crop_id, as_of, depth_m), plan)
    return out


def water_by_crop(location: LocationSpec, as_of: date, profile: SoilProfile, crop_ids: tuple[str, ...]):
    """O mesmo cálculo de app/common.py:water_by_crop, sem Streamlit."""
    texture_group = texture_class(profile.get("areia_pct"), profile.get("argila_pct"))
    return _water_cached(location.model_dump_json(), as_of, texture_group, profile.depth_m, crop_ids)
