"""Script utilitário para iniciar a API HTTP (Rádio do Tempo, Ficha PDF e Twilio WhatsApp)."""

from _bootstrap import ensure_venv

ensure_venv()

from crop_optimizer.cli import cmd_api  # noqa: E402

if __name__ == "__main__":
    cmd_api()
