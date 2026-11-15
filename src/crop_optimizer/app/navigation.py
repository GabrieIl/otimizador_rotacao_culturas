"""Registro das páginas, para uma página poder linkar outra sem importação circular."""

from __future__ import annotations

import streamlit as st

_PAGES: dict[str, st.Page] = {}


def register(name: str, page: st.Page) -> st.Page:
    _PAGES[name] = page
    return page


def link(name: str, label: str, icon: str | None = None) -> None:
    """Link para outra página (some sem erro se a navegação não estiver ativa, ex.: em testes)."""
    page = _PAGES.get(name)
    if page is not None and hasattr(page, "_icon"):
        st.page_link(page, label=label, icon=icon)
