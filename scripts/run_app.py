"""Script utilitário para iniciar a interface Streamlit (Dia 3)."""

import sys

from _bootstrap import ensure_venv

ensure_venv()

from crop_optimizer.cli import cmd_app  # noqa: E402

if __name__ == "__main__":
    cmd_app(sys.argv[1:])
