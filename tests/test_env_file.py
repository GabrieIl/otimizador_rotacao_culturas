"""Leitura do .env (chaves locais)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from crop_optimizer.config import load_env_file


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in ("ACAUA_T_PLAIN", "ACAUA_T_DQ", "ACAUA_T_SQ", "ACAUA_T_EXPORT", "ACAUA_T_KEEP", "ACAUA_T_EMPTY"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_load_env_file_parses_values(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comentário\n"
        "\n"
        "ACAUA_T_PLAIN=sk-abc=123\n"
        'ACAUA_T_DQ="com aspas"\n'
        "ACAUA_T_SQ='simples'\n"
        "export ACAUA_T_EXPORT=x\n"
        "ACAUA_T_EMPTY=\n"
        "linha sem igual\n",
        encoding="utf-8",
    )
    loaded = load_env_file(env)
    assert os.environ["ACAUA_T_PLAIN"] == "sk-abc=123"
    assert os.environ["ACAUA_T_DQ"] == "com aspas"
    assert os.environ["ACAUA_T_SQ"] == "simples"
    assert os.environ["ACAUA_T_EXPORT"] == "x"
    assert os.environ["ACAUA_T_EMPTY"] == ""
    assert set(loaded) == {"ACAUA_T_PLAIN", "ACAUA_T_DQ", "ACAUA_T_SQ", "ACAUA_T_EXPORT", "ACAUA_T_EMPTY"}


def test_load_env_file_keeps_existing_and_missing_file(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ACAUA_T_KEEP", "do shell")
    env = tmp_path / ".env"
    env.write_text("ACAUA_T_KEEP=do arquivo\n", encoding="utf-8")
    assert load_env_file(env) == []
    assert os.environ["ACAUA_T_KEEP"] == "do shell"
    assert load_env_file(tmp_path / "nao_existe.env") == []


def test_tests_never_load_real_dotenv() -> None:
    assert os.environ["CROP_OPT_LOAD_DOTENV"] == "0"
    assert load_env_file() == []
