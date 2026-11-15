"""Configurações centralizadas e caminhos do Local Data Lakehouse."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env_file(path: Path | None = None) -> list[str]:
    """Carrega KEY=valor do .env da raiz para os.environ, sem sobrescrever o que já está definido.

    Aceita valor com ou sem aspas, ignora linhas vazias e comentários. Devolve as chaves carregadas.
    """
    if path is None and os.getenv("CROP_OPT_LOAD_DOTENV", "1") == "0":
        return []  # testes: nunca usar as chaves reais
    env_path = path or _default_project_root() / ".env"
    if not env_path.is_file():
        return []
    loaded = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


load_env_file()


def config_dir() -> Path:
    """Diretório dos parâmetros agronômicos em YAML (config/ na raiz do projeto)."""
    return Path(os.getenv("CROP_OPT_CONFIG_DIR", _default_project_root() / "config"))


@cache
def load_yaml_config(name: str) -> dict[str, Any]:
    """Lê config/<name>.yaml. Falha alto se o arquivo não existir: parâmetro não se inventa."""
    path = config_dir() / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class LakehousePaths(BaseModel):
    """Estrutura Medallion (Bronze -> Silver -> Gold Star Schema) em Parquet."""

    root: Path = Field(
        default_factory=lambda: Path(os.getenv("CROP_OPT_DATA_DIR", _default_project_root() / "data"))
    )

    @property
    def bronze(self) -> Path:
        return self.root / "bronze"

    def bronze_source(self, source: str) -> Path:
        """Subpasta da bronze com os arquivos originais de uma fonte (cache, nunca apagado pelo ELT)."""
        path = self.bronze / source
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def silver(self) -> Path:
        return self.root / "silver"

    @property
    def gold(self) -> Path:
        return self.root / "gold"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def dim_location(self) -> Path:
        return self.gold / "dim_location.parquet"

    @property
    def dim_crop(self) -> Path:
        return self.gold / "dim_crop.parquet"

    @property
    def dim_zarc_window(self) -> Path:
        return self.gold / "dim_zarc_window.parquet"

    @property
    def dim_market_price(self) -> Path:
        return self.gold / "dim_market_price.parquet"

    @property
    def fact_climate_daily(self) -> Path:
        return self.gold / "fact_climate_daily"

    def ensure_dirs(self) -> None:
        for path in (self.bronze, self.silver, self.gold, self.artifacts, self.fact_climate_daily):
            path.mkdir(parents=True, exist_ok=True)


class Settings(BaseModel):
    """Configurações globais do Motor Estocástico de Resiliência do Sertão."""

    paths: LakehousePaths = Field(default_factory=LakehousePaths)
    ingestion_mode: Literal["offline", "online"] = Field(
        default_factory=lambda: "online"
        if os.getenv("CROP_OPT_INGESTION_MODE", "offline").lower() == "online"
        else "offline"
    )
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    nasa_appeears_base_url: str = "https://appeears.earthdatacloud.nasa.gov/api"
    nasa_appeears_token: str | None = Field(default_factory=lambda: os.getenv("NASA_APPEEARS_TOKEN") or None)
    tts_provider: Literal["offline", "gtts", "openai"] = Field(
        default_factory=lambda: os.getenv("CROP_OPT_TTS_PROVIDER", "offline").lower()  # type: ignore[return-value]
    )
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    twilio_account_sid: str | None = Field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID") or None)
    twilio_auth_token: str | None = Field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN") or None)
    twilio_whatsapp_from: str = Field(
        default_factory=lambda: os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    )
    # URL pública da API (túnel cloudflared): o Twilio baixa o áudio da resposta e assina o webhook com ela
    public_url: str | None = Field(default_factory=lambda: (os.getenv("ACAUA_PUBLIC_URL") or "").rstrip("/") or None)
    default_n_scenarios: int = 10_000
    default_horizon_years: int = 5
    random_seed: int = 42
    discount_rate: float = 0.085


def get_settings(data_dir: str | Path | None = None) -> Settings:
    """Retorna instância configurada de Settings."""
    if data_dir is not None:
        return Settings(paths=LakehousePaths(root=Path(data_dir)))
    return Settings()
