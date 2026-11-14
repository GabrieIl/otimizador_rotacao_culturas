"""Estado compartilhado entre as páginas (roça, município de exemplo, filtros, zoom do mapa).

O Streamlit apaga o estado de um widget quando a página que o desenha não roda (ex.: ao ir da
Início para a Plantio). Para a escolha valer em todas as páginas, guardamos uma cópia numa chave
própria e devolvemos ao widget antes de desenhá-lo:

    keep("ano_lente", 2026)
    st.slider("Ano", ..., **watch("ano_lente"))   # sem value=/index=: o valor vem da sessão
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from crop_optimizer.domain.roca import Roca

_KEY = "roca"
_STORE = "_guardado_"


def get_roca() -> Roca | None:
    return st.session_state.get(_KEY)


def set_roca(roca: Roca) -> None:
    st.session_state[_KEY] = roca


def clear_roca() -> None:
    st.session_state.pop(_KEY, None)


def keep(key: str, default: Any) -> None:
    """Restaura o valor guardado do widget `key` (ou `default`) antes de desenhá-lo."""
    store = _STORE + key
    if store not in st.session_state:
        st.session_state[store] = st.session_state.get(key, default)
    st.session_state[key] = st.session_state[store]


def _remember(key: str) -> None:
    st.session_state[_STORE + key] = st.session_state[key]


def watch(key: str) -> dict[str, Any]:
    """Argumentos do widget para guardar cada mudança: st.radio(..., **watch("lente"))."""
    return {"key": key, "on_change": _remember, "args": (key,)}


def stored(key: str, default: Any = None) -> Any:
    """Valor guardado, mesmo que o widget não esteja nesta página."""
    return st.session_state.get(_STORE + key, st.session_state.get(key, default))


def store(key: str, value: Any) -> None:
    """Muda o valor guardado (vale na próxima vez que o widget for desenhado).

    Não mexe na chave do próprio widget: se ele já foi desenhado nesta execução, o Streamlit
    não deixa alterar. O `keep` da próxima execução aplica o valor.
    """
    st.session_state[_STORE + key] = value
