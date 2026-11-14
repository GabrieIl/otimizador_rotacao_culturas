"""Garante execução dentro do .venv do projeto mesmo se chamado com python3 do sistema."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_venv() -> None:
    root = Path(__file__).resolve().parents[1]
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists() and Path(sys.prefix).resolve() != (root / ".venv").resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])
