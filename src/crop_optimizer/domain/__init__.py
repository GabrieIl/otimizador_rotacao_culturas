"""Modelos e catálogos de domínio do Motor Estocástico de Resiliência do Sertão."""

from crop_optimizer.domain.models import (
    BalancePriority,
    CropSpec,
    LocationSpec,
    MarkovSoilOutput,
    RotationStrategy,
    SeasonSlot,
    SimulationConfig,
    SoilHealthState,
    StrategySimulationResult,
    TrafficLightLevel,
)
from crop_optimizer.domain.presets import (
    DEFAULT_CROPS,
    DEFAULT_LOCATIONS,
    DEFAULT_STRATEGIES,
    crop_map,
    location_map,
)

__all__ = [
    "DEFAULT_CROPS",
    "DEFAULT_LOCATIONS",
    "DEFAULT_STRATEGIES",
    "BalancePriority",
    "CropSpec",
    "LocationSpec",
    "MarkovSoilOutput",
    "RotationStrategy",
    "SeasonSlot",
    "SimulationConfig",
    "SoilHealthState",
    "StrategySimulationResult",
    "TrafficLightLevel",
    "crop_map",
    "location_map",
]
