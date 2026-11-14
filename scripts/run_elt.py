"""Script utilitário para executar o pipeline ELT (Dia 1)."""

from _bootstrap import ensure_venv

ensure_venv()

from crop_optimizer.cli import cmd_elt  # noqa: E402

if __name__ == "__main__":
    cmd_elt()
