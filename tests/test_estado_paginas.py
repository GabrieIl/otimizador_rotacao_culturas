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
    html = _build_map((-9.05, -40.9), 25).get_root().render()
    assert '"zoom": 17' in html  # zoom pedido acima do limite é cortado
    assert '"minZoom": 4' in html and '"maxZoom": 17' in html
    assert '"maxBoundsViscosity": 1.0' in html and '"noWrap": true' in html
    block = html[html.index('"maxBounds"') : html.index('"zoom"', html.index('"maxBounds"'))]
    south, west, north, east = (float(x) for x in re.findall(r"-?\d+\.\d+", block))
    box = cfg["limites"]
    assert (south, west, north, east) == (box["sul"], box["oeste"], box["norte"], box["leste"])


_VIEW_APP = textwrap.dedent(
    """
    import streamlit as st
    from crop_optimizer.app.satellite_page import _map_view
    p = st.session_state.get("_teste_ponto", (-9.0, -40.0))
    _map_view(p[0], p[1], st.session_state.pop("_teste_chegou", False))
    """
)


def test_map_view_never_feeds_back_user_view(tmp_path) -> None:
    """O mapa só recebe centro quando o ponto muda; a visão do usuário só vale ao voltar à página."""
    path = tmp_path / "view.py"
    path.write_text(_VIEW_APP, encoding="utf-8")
    at = AppTest.from_file(str(path), default_timeout=30)
    ss = at.session_state
    ss["_teste_chegou"] = True
    at.run()
    assert ss["_mapa_ancora"] == ((-9.0, -40.0), 9) and ss["_mapa_pedido"] is None
    # usuário mexeu no mapa: nada é devolvido ao mapa nesta visita
    ss["_mapa_zoom"], ss["_mapa_centro"] = 13, (-9.3, -40.2)
    at.run()
    assert ss["_mapa_ancora"] == ((-9.0, -40.0), 9) and ss["_mapa_pedido"] is None
    # ponto novo pelos campos: centraliza nele, sem mexer na figura
    ss["_teste_ponto"] = (-6.0, -38.0)
    at.run()
    assert ss["_mapa_pedido"] == [-6.0, -38.0] and ss["_mapa_ancora"][1] == 9
    # ponto novo por clique: não recentraliza
    ss["_teste_ponto"] = ss["_mapa_ponto_clicado"] = (-6.1, -38.1)
    at.run()
    assert ss["_mapa_pedido"] == [-6.0, -38.0]
    # volta à página com o mesmo ponto: reabre na última visão do usuário
    ss["_mapa_zoom"], ss["_mapa_centro"] = 12, (-6.2, -38.3)
    ss["_teste_chegou"] = True
    at.run()
    assert ss["_mapa_ancora"] == ((-6.2, -38.3), 12) and ss["_mapa_pedido"] is None
