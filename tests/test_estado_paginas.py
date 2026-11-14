"""Testes: escolhas guardadas entre páginas e limites do mapa da página Satélite."""

from __future__ import annotations

import re
import textwrap

from streamlit.testing.v1 import AppTest

from crop_optimizer.app.satellite_page import _build_map
from crop_optimizer.config import load_yaml_config

# Duas "páginas": só uma desenha o slider. Ao ir para a outra, o Streamlit apaga o estado do
# widget, como na troca de página real; o keep/watch precisa restaurar o valor na volta.
_APP = textwrap.dedent(
    """
    import streamlit as st
    from crop_optimizer.app.state import keep, store, stored, watch

    if st.session_state.get("_pagina", "a") == "a":
        keep("ano", 2026)
        st.slider("Ano", 2000, 2026, **watch("ano"))
    else:
        st.write(f"ano guardado: {stored('ano')}")
        if st.button("mudar"):
            store("ano", 2001)
    """
)


def _app(tmp_path) -> AppTest:
    path = tmp_path / "app.py"
    path.write_text(_APP, encoding="utf-8")
    return AppTest.from_file(str(path), default_timeout=30).run()


def test_widget_value_survives_page_switch(tmp_path) -> None:
    at = _app(tmp_path)
    at.slider[0].set_value(2010).run()
    at.session_state["_pagina"] = "b"
    at.run()
    assert "ano guardado: 2010" in at.markdown[0].value
    at.session_state["_pagina"] = "a"
    at.run()
    assert at.slider[0].value == 2010


def test_value_changed_from_other_page_applies_on_return(tmp_path) -> None:
    at = _app(tmp_path)
    at.session_state["_pagina"] = "b"
    at.run()
    at.button[0].click().run()
    at.session_state["_pagina"] = "a"
    at.run()
    assert at.slider[0].value == 2001


def test_map_zoom_limits_and_bounds() -> None:
    cfg = load_yaml_config("lentes")["mapa"]
    # acima de 17 a imagem de base não existe no semiárido; abaixo de 4 o mundo se repete
    assert (cfg["zoom_minimo"], cfg["zoom_maximo"]) == (4, 17)
    html = _build_map(None, -9.05, -40.9, True).get_root().render()
    assert '"minZoom": 4' in html and '"maxZoom": 17' in html
    assert '"maxBoundsViscosity": 1.0' in html and '"noWrap": true' in html
    block = html[html.index('"maxBounds"') : html.index('"zoom"', html.index('"maxBounds"'))]
    south, west, north, east = (float(x) for x in re.findall(r"-?\d+\.\d+", block))
    box = cfg["limites"]
    assert (south, west, north, east) == (box["sul"], box["oeste"], box["norte"], box["leste"])
