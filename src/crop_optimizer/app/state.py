"""Estado compartilhado entre as páginas (a roça escolhida no mapa)."""

from __future__ import annotations

import streamlit as st

from crop_optimizer.domain.roca import Roca

_KEY = "roca"


def get_roca() -> Roca | None:
    return st.session_state.get(_KEY)


def set_roca(roca: Roca) -> None:
    st.session_state[_KEY] = roca


def clear_roca() -> None:
    st.session_state.pop(_KEY, None)
