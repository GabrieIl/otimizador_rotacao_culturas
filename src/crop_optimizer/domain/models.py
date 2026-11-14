"""Modelos de domínio agronômicos, climáticos, biomassa e resiliência do Sertão."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum

import numpy as np
from pydantic import BaseModel, Field


class SeasonSlot(StrEnum):
    """Janelas sazonais dentro de um ano agrícola."""

    SAFRA = "safra"
    SAFRINHA = "safrinha"
    COBERTURA = "cobertura"


class TrafficLightLevel(StrEnum):
    """Semáforo Agrícola para tradução acessível do risco climático."""

    VERDE = "verde"
    AMARELO = "amarelo"
    VERMELHO = "vermelho"

    @property
    def emoji(self) -> str:
        return {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}[self.value]

    @property
    def guidance(self) -> str:
        return {
            "verde": "Plante Milho",
            "amarelo": "Mude para Sorgo/Caupi",
            "vermelho": "Guarde a semente, risco extremo",
        }[self.value]


class BalancePriority(StrEnum):
    """Prioridade escolhida pelo agricultor na Balança Comida x Forragem x Risco."""

    EQUILIBRADO = "equilibrado"
    COMIDA = "comida"
    FORRAGEM = "forragem"
    ESCUDO = "escudo"


class SoilHealthState(int, Enum):
    """Estados discretos da Cadeia de Markov para saúde do solo."""

    CRITICO = 0
    DEGRADADO = 1
    EQUILIBRADO = 2
    FERTIL = 3
    REGENERATIVO = 4

    @property
    def label(self) -> str:
        labels = {
            0: "Crítico",
            1: "Degradado",
            2: "Equilibrado",
            3: "Fértil",
            4: "Regenerativo",
        }
        return labels[self.value]


class LocationSpec(BaseModel):
    """Município / microrregião produtora monitorada."""

    location_id: str
    name: str
    state: str
    ibge_code: str | None = None
    biome: str
    latitude: float
    longitude: float
    soil_type: str = "Tipo 2 (Franco-Arenoso)"
    frost_prone: bool = False
    is_semiarid: bool = True
    rainy_season_start_doy: int = 15
    veranico_risk_base: float = 0.30


class CropSpec(BaseModel):
    """Parâmetros agronômicos, de biomassa (comida/forragem) e econômicos de uma cultura."""

    crop_id: str
    name: str
    slot: SeasonSlot
    cycle_days: int
    base_yield_ton_ha: float
    base_price_brl_ton: float
    price_volatility: float
    direct_cost_brl_ha: float
    nitrogen_demand_kg_ha: float
    nitrogen_fixation_kg_ha: float = 0.0
    organic_matter_delta_pct: float = 0.0
    drought_sensitivity: float = 1.0
    frost_sensitivity: float = 0.5
    is_cover_crop: bool = False
    food_fraction: float = 1.0
    forage_yield_ton_ha: float = 1.0
    forage_drought_resilience: float = 0.70


class RotationStrategy(BaseModel):
    """Sequência anual de culturas repetida no horizonte de planejamento."""

    strategy_id: str
    name: str
    short_name: str = ""
    description: str
    annual_sequence: list[str] = Field(
        description="Lista ordenada de crop_id executada por ano agrícola"
    )
    tags: list[str] = Field(default_factory=list)


class SimulationConfig(BaseModel):
    """Parâmetros de execução da simulação estocástica de sobrevivência."""

    location_id: str = "petrolina_pe"
    horizon_years: int = Field(default=5, ge=1, le=10)
    n_scenarios: int = Field(default=10_000, ge=100, le=100_000)
    initial_soil_state: SoilHealthState = SoilHealthState.EQUILIBRADO
    initial_nitrogen_kg_ha: float = 55.0
    initial_organic_matter_pct: float = 2.2
    safra_delay_days: int = Field(default=0, ge=0, le=45)
    veranico_days: int = Field(default=0, ge=0, le=30)
    fertilizer_price_brl_kg_n: float = 6.20
    discount_rate: float = 0.085
    family_food_target_kg_year: float = 600.0
    herd_forage_target_kg_year: float = 2_400.0
    farmer_name: str = "Seu João"
    seed: int = 42


@dataclass(slots=True)
class MarkovSoilOutput:
    """Trajetórias vetorizadas da Cadeia de Markov do solo (shape: n_scenarios x n_steps+1)."""

    states: np.ndarray
    nitrogen_kg_ha: np.ndarray
    organic_matter_pct: np.ndarray
    fertilizer_savings_brl_ha: np.ndarray
    yield_multiplier: np.ndarray


@dataclass(slots=True)
class StrategySimulationResult:
    """Resultado consolidado de Monte Carlo (Sobrevivência, Biomassa e Finanças)."""

    strategy: RotationStrategy
    npv_profit_brl_ha: np.ndarray
    annual_profit_brl_ha: np.ndarray
    annual_food_kg_ha: np.ndarray
    annual_forage_kg_ha: np.ndarray
    soil_output: MarkovSoilOutput
    step_labels: list[str]
    expected_npv_brl_ha: float
    profit_std_brl_ha: float
    cvar_95_brl_ha: float
    prob_loss: float
    expected_food_kg_ha_year: float
    expected_forage_kg_ha_year: float
    prob_two_consecutive_losses: float
    prob_herd_collapse: float
    survival_score_of_10: int
    loss_years_of_10: int
    food_score: float
    forage_score: float
    shield_score: float
    final_soil_score_mean: float
    final_soil_score_std: float
    total_fertilizer_savings_mean: float
    execution_ms: float
    is_pareto_optimal: bool = False
    metadata: dict[str, float] = field(default_factory=dict)
