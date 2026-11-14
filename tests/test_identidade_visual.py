"""Testes da identidade visual: tema, contraste, arquivos da marca e componentes."""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crop_optimizer.app import theme
from crop_optimizer.app.theme import ASSETS, COLORS

ROOT = Path(__file__).resolve().parents[1]


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted([_lum(a), _lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_streamlit_theme_matches_palette() -> None:
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    assert cfg["primaryColor"] == COLORS.terracota
    assert cfg["backgroundColor"] == COLORS.creme
    assert cfg["textColor"] == COLORS.petroleo
    assert cfg["greenColor"] == COLORS.verde and cfg["redColor"] == COLORS.vermelho
    assert cfg["headingFont"].startswith("Montserrat") and cfg["font"].startswith("Inter")


@pytest.mark.parametrize(
    ("fg", "bg"),
    [
        (COLORS.petroleo, COLORS.creme),  # texto
        (COLORS.texto_suave, COLORS.creme),  # legendas e rótulos
        ("#FFFFFF", COLORS.terracota),  # botão primário e faixa de chamada
        (COLORS.verde, COLORS.creme),  # "Pode plantar"
        ("#8A5E12", COLORS.creme),  # "Arriscado"
        (COLORS.vermelho, COLORS.creme),  # "Não plante agora"
    ],
)
def test_text_contrast_is_aa(fg: str, bg: str) -> None:
    assert contrast(fg, bg) >= 4.5


def test_brand_assets_exist() -> None:
    names = {p.name for p in ASSETS.glob("*.png")}
    assert {"logo_marca.png", "logo_completo.png", "icone.png"} <= names
    assert {"mascote_broto.png", "mascote_canto.png", "mascote_asas.png", "mascote_satelite.png"} <= names


def test_css_has_tokens_motion_guard_and_no_emoji() -> None:
    css = theme._css()
    for token in ("--acaua-petroleo", "--acaua-creme", "--acaua-terracota", "--acaua-ocre"):
        assert token in css
    assert "prefers-reduced-motion: no-preference" in css  # animações só para quem não pediu menos movimento
    assert css.count("@keyframes") <= 1
    assert not any(0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF for ch in css)


_APP = textwrap.dedent(
    """
    import streamlit as st
    from crop_optimizer.app import theme
    theme.inject()
    for level in ("verde", "amarelo", "vermelho"):
        theme.status_card(level, f"detalhe {level}")
    theme.divider()
    """
)


def test_status_cards_render_word_for_each_level(tmp_path) -> None:
    path = tmp_path / "app.py"
    path.write_text(_APP, encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=30).run()
    assert not at.exception
    html = " ".join(el.proto.body for el in at.get("html"))
    for word in ("Pode plantar", "Arriscado", "Não plante agora"):
        assert word in html
