"""Componentes visuais do Acauã (st.components.v2: HTML + CSS + JS próprios, com retorno ao Python).

Todos usam a mesma base de CSS da marca. O JS monta o conteúdo a partir de `data` (montado pelo
próprio app) e escapa todo texto antes de inserir no HTML.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# --- base comum ------------------------------------------------------------------

_BASE_CSS = """
:host { --pet:#163037; --pet2:#2C4A52; --sub:#56676B; --creme:#F2EFEA; --areia:#E8E2D6; --linha:#D9D0BF;
  --terra:#9C6346; --terra-i:#A46B4D; --ocre:#BB9252; --verde:#266F49; --amarelo:#DDA848; --verm:#AA281E;
  --t-verde:#E1ECE4; --t-amarelo:#F6ECD3; --t-verm:#F3DEDB; --t-espera:#E3E7E6;
  font-family: Inter, sans-serif; color: var(--pet); }
* { box-sizing: border-box; }
.disp { font-family: Montserrat, Inter, sans-serif; }
.rot { font-family: 'IBM Plex Mono', monospace; font-size: .7rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--sub); display:flex; align-items:center; gap:1rem; margin:0 0 .35rem 0; }
.rot::before { content:""; width:6px; height:6px; background:var(--ocre); box-shadow: 8px -5px 0 0 var(--ocre); flex:none; }
.pill { display:inline-flex; align-items:center; border-radius:999px; padding:.15rem .6rem; font-size:.78rem; font-weight:600; white-space:nowrap; }
.tone-verde { background:var(--t-verde); color:var(--verde); }
.tone-amarelo { background:var(--t-amarelo); color:#8A5E12; }
.tone-vermelho { background:var(--t-verm); color:var(--verm); }
.tone-espera, .tone-neutro { background:var(--t-espera); color:var(--pet2); }
.ico svg { width:100%; height:100%; display:block; }
.grupo { font-family: 'IBM Plex Mono', monospace; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase;
  color:var(--sub); margin:.7rem .2rem .25rem .2rem; }
.grupo:first-child { margin-top:.1rem; }
button { font-family: Inter, sans-serif; }
@media (prefers-reduced-motion: no-preference) { .anim { transition: all 160ms ease-out; } }
"""

_JS_HELPERS = """
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function withGroups(items, render) {
  let last = null;
  return items.map((it) => {
    const head = it.group && it.group !== last ? `<p class="grupo">${esc(it.group)}</p>` : '';
    last = it.group || last;
    return head + render(it);
  }).join('');
}
function rootOf(parentElement) {
  let root = parentElement.querySelector('.acaua-root');
  if (!root) { root = document.createElement('div'); root.className = 'acaua-root'; parentElement.appendChild(root); }
  return root;
}
"""


def _current(key: str, field: str, fallback: Any) -> Any:
    """Valor que o usuário acabou de escolher (o Streamlit grava na sessão antes de rodar o script).

    Desenhar com ele evita mostrar a escolha antiga na execução disparada pelo próprio clique.
    """
    state = st.session_state.get(key)
    if state is not None and field in state and state[field] is not None:
        return state[field]
    return fallback


def _component(name: str, css: str, js_body: str):
    return st.components.v2.component(
        f"acaua_{name}", css=_BASE_CSS + css, js=_JS_HELPERS + js_body, isolate_styles=True
    )


# --- 1. cards de cultura (seleção) ------------------------------------------------

_CARDS = _component(
    "cards_cultura",
    """
.lista { display:flex; flex-direction:column; gap:.5rem; max-height:640px; overflow-y:auto; padding-right:.35rem; }
.card { display:flex; align-items:center; gap:.85rem; width:100%; text-align:left; cursor:pointer;
  background:rgba(255,255,255,.45); border:1px solid var(--linha); border-radius:.8rem; padding:.7rem .9rem; color:var(--pet); }
.card:hover { background:rgba(255,255,255,.8); }
.card.sel { background:#fff; border-color:var(--terra); box-shadow: inset 4px 0 0 var(--terra); }
.card .ico { width:44px; height:44px; flex:none; }
.card .nome { font-family: Montserrat, Inter, sans-serif; font-weight:700; font-size:1rem; flex:1; }
""",
    """
export default function(component) {
  const { data, setStateValue, parentElement } = component;
  const root = rootOf(parentElement);
  const sel = data.selected;
  root.innerHTML = '<div class="lista">' + withGroups(data.items, (it) => `
    <button class="card anim ${it.id === sel ? 'sel' : ''}" data-id="${esc(it.id)}" aria-pressed="${it.id === sel}">
      <span class="ico">${it.icon}</span><span class="nome">${esc(it.name)}</span>
      <span class="pill tone-${esc(it.tone)}">${esc(it.status)}</span></button>`) + '</div>';
  const selBtn = root.querySelector('.card.sel');
  if (selBtn) { const lista = root.querySelector('.lista'); lista.scrollTop = Math.max(0, selBtn.offsetTop - lista.offsetTop - 60); }
  root.querySelectorAll('.card').forEach((b) => { b.onclick = () => setStateValue('selected', b.dataset.id); });
}
""",
)


def crop_cards(items: list[dict], selected: str, key: str) -> str:
    """Lista vertical de culturas; devolve a cultura escolhida."""
    current = _current(key, "selected", selected)
    _CARDS(data={"items": items, "selected": current}, key=key, default={"selected": current},
           on_selected_change=lambda: None)
    return current


# --- 2. card grande de uma cultura --------------------------------------------------

_HERO = _component(
    "cultura_destaque",
    """
.hero { background:#fff; border:1px solid var(--linha); border-radius:1rem; padding:1.5rem 1.6rem; }
.topo { display:flex; gap:1.25rem; align-items:center; }
.topo .ico { width:112px; height:112px; flex:none; }
h2 { font-family: Montserrat, Inter, sans-serif; font-size:2rem; font-weight:800; margin:.1rem 0 .3rem 0; line-height:1.1; }
.veredito { font-family: Montserrat, Inter, sans-serif; font-weight:800; font-size:1.35rem; margin:.2rem 0; }
.v-verde { color:var(--verde); } .v-amarelo { color:#8A5E12; } .v-vermelho { color:var(--verm); } .v-espera, .v-neutro { color:var(--pet2); }
.texto { font-size:1rem; line-height:1.5; margin:.5rem 0 0 0; }
.nota { display:flex; align-items:baseline; gap:.5rem; margin-top:1rem; }
.nota .num { font-family: Montserrat, Inter, sans-serif; font-weight:800; font-size:2.4rem; }
.nota .de { color:var(--sub); }
.barra { height:8px; background:var(--areia); border-radius:4px; overflow:hidden; margin:.35rem 0 1rem 0; }
.barra span { display:block; height:100%; border-radius:4px; }
.f-verde { background:var(--verde); } .f-amarelo { background:var(--amarelo); } .f-vermelho { background:var(--verm); } .f-espera, .f-neutro { background:var(--pet2); }
.secao { margin-top:1.1rem; }
ul { list-style:none; padding:0; margin:.4rem 0 0 0; display:flex; flex-direction:column; gap:.45rem; }
li { display:flex; gap:.6rem; align-items:flex-start; font-size:.92rem; line-height:1.4; }
li .pill { flex:none; min-width:6.4rem; justify-content:center; }
.reqs { display:grid; grid-template-columns: repeat(auto-fill,minmax(150px,1fr)); gap:.5rem; margin-top:.5rem; }
.req { background:var(--creme); border-radius:.6rem; padding:.5rem .7rem; }
.req b { display:block; font-size:.75rem; color:var(--sub); font-weight:500; }
.req span { font-weight:600; }
.rodape { color:var(--sub); font-size:.82rem; margin-top:1rem; }
.agua { margin-top:1.2rem; padding-top:1rem; border-top:1px solid var(--areia); }
.dias { display:grid; grid-template-columns: minmax(9rem, auto) 1fr; gap:.45rem .8rem; align-items:center; margin:.5rem 0 .2rem 0; }
.dias .lab { font-size:.86rem; color:var(--pet2); }
.dias .trilho { height:22px; background:var(--areia); border-radius:4px; position:relative; }
.dias .trilho span { position:absolute; left:0; top:0; bottom:0; border-radius:4px; display:flex; align-items:center;
  justify-content:flex-end; padding-right:.45rem; color:#fff; font-weight:700; font-size:.8rem; min-width:2.6rem; }
.b-veranico { background:var(--pet); } .b-ok { background:var(--verde); } .b-curto { background:var(--verm); } .b-neutro { background:var(--pet2); }
.frase { font-size:.95rem; line-height:1.45; margin:.45rem 0 0 0; }
.tanque { height:14px; background:var(--areia); border-radius:7px; position:relative; margin:.5rem 0 .3rem 0; }
.tanque .agua-hoje { position:absolute; left:0; top:0; bottom:0; border-radius:7px; background:var(--pet2); }
.tanque .normal { position:absolute; top:-4px; bottom:-4px; width:2px; background:var(--terra); }
.legenda { font-size:.78rem; color:var(--sub); }
@media (max-width: 640px) { .topo .ico { width:72px; height:72px; } h2 { font-size:1.6rem; } .dias { grid-template-columns: 1fr; } }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const d = data;
  const score = d.score == null ? '' : `
    <div class="nota"><span class="num disp">${esc(Math.round(d.score))}</span><span class="de">de 100 · ${esc(d.score_label)}</span></div>
    <div class="barra"><span class="f-${esc(d.tone)}" style="width:${Math.max(3, Math.min(100, d.score))}%"></span></div>`;
  const reqs = (d.reqs || []).map((r) => `<div class="req"><b>${esc(r.k)}</b><span>${esc(r.v)}</span></div>`).join('');
  const fat = (d.factors || []).map((f) => `<li><span class="pill tone-${esc(f.tone)}">${esc(f.grau)}</span><span><b>${esc(f.label)}.</b> ${esc(f.reason)}</span></li>`).join('');
  root.innerHTML = `<div class="hero">
    <div class="topo"><div class="ico">${d.icon}</div><div>
      <p class="rot">${esc(d.eyebrow)}</p><h2>${esc(d.title)}</h2>
      <p class="veredito v-${esc(d.tone)}">${esc(d.verdict)}</p></div></div>
    ${d.text ? `<p class="texto">${esc(d.text)}</p>` : ''}
    ${score}
    ${reqs ? `<div class="secao"><p class="rot">O que esta cultura precisa</p><div class="reqs">${reqs}</div></div>` : ''}
    ${fat ? `<div class="secao"><p class="rot">${esc(d.factors_title || 'Fator por fator')}</p><ul>${fat}</ul></div>` : ''}
    ${agua(d.agua)}
    ${d.foot ? `<p class="rodape">${esc(d.foot)}</p>` : ''}
  </div>`;
}

function agua(a) {
  if (!a) return '';
  const max = Math.max(1, ...(a.bars || []).map((b) => b.days || 0)) * 1.1;
  const bars = (a.bars || []).map((b) => `<span class="lab">${esc(b.label)}</span>
    <div class="trilho"><span class="b-${esc(b.tone)}" style="width:${Math.max(6, 100 * (b.days || 0) / max)}%">${esc(b.days)} d</span></div>`).join('');
  const solo = a.solo ? `<div class="secao"><p class="rot">${esc(a.solo.title)}</p>
    <div class="tanque" role="img" aria-label="${esc(a.solo.text)}"><span class="agua-hoje" style="width:${Math.max(2, 100 * a.solo.fill)}%"></span>
      ${a.solo.normal == null ? '' : `<span class="normal" style="left:${100 * a.solo.normal}%"></span>`}</div>
    <p class="legenda">Barra: água no solo hoje · traço: o normal desta data</p>
    <p class="frase">${esc(a.solo.text)}</p></div>` : '';
  return `<div class="agua"><p class="rot">${esc(a.title)}</p>
    ${bars ? `<div class="dias">${bars}</div>` : ''}
    ${a.phrase ? `<p class="frase">${esc(a.phrase)}</p>` : ''}
    ${solo}</div>`;
}
""",
)


def crop_hero(data: dict[str, Any], key: str) -> None:
    _HERO(data=data, key=key)


# --- 3. seletor de cultura (combobox com ícones) ------------------------------------

_COMBO = _component(
    "combo_cultura",
    """
.combo { position:relative; max-width:520px; }
.atual { display:flex; align-items:center; gap:.8rem; width:100%; background:#fff; border:1px solid var(--linha);
  border-radius:.8rem; padding:.6rem .9rem; cursor:pointer; color:var(--pet); text-align:left; }
.atual:hover, .atual[aria-expanded="true"] { border-color:var(--terra); }
.ico { width:38px; height:38px; flex:none; }
.nome { font-family: Montserrat, Inter, sans-serif; font-weight:700; font-size:1.05rem; flex:1; }
.seta { width:10px; height:10px; border-right:2px solid var(--pet); border-bottom:2px solid var(--pet); transform: rotate(45deg); margin:0 .3rem .25rem 0; }
.aberto .seta { transform: rotate(-135deg); margin-bottom:-.2rem; }
.opcoes { display:none; margin-top:.4rem; background:#fff; border:1px solid var(--linha); border-radius:.8rem; padding:.35rem;
  max-height:440px; overflow-y:auto; }
.aberto .opcoes { display:block; }
.op { display:flex; align-items:center; gap:.8rem; width:100%; background:none; border:none; border-radius:.6rem;
  padding:.5rem .6rem; cursor:pointer; color:var(--pet); text-align:left; }
.op:hover, .op:focus { background:var(--creme); outline:none; }
.op.sel { background:var(--creme); }
.op .ico { width:30px; height:30px; }
.op .nome { font-size:.95rem; }
""",
    """
export default function(component) {
  const { data, setStateValue, parentElement } = component;
  const root = rootOf(parentElement);
  const cur = data.items.find((i) => i.id === data.selected) || data.items[0];
  root.innerHTML = `<div class="combo">
    <button class="atual" aria-haspopup="listbox" aria-expanded="false">
      <span class="ico">${cur.icon}</span><span class="nome">${esc(cur.name)}</span>
      <span class="pill tone-${esc(cur.tone)}">${esc(cur.status)}</span><span class="seta"></span></button>
    <div class="opcoes" role="listbox">${withGroups(data.items, (it) => `
      <button class="op ${it.id === cur.id ? 'sel' : ''}" role="option" data-id="${esc(it.id)}">
        <span class="ico">${it.icon}</span><span class="nome">${esc(it.name)}</span>
        <span class="pill tone-${esc(it.tone)}">${esc(it.status)}</span></button>`)}</div></div>`;
  const combo = root.querySelector('.combo'), btn = root.querySelector('.atual');
  btn.onclick = () => { const open = !combo.classList.contains('aberto'); combo.classList.toggle('aberto', open); btn.setAttribute('aria-expanded', open); };
  root.querySelectorAll('.op').forEach((o) => { o.onclick = () => { combo.classList.remove('aberto'); setStateValue('selected', o.dataset.id); }; });
}
""",
)


def crop_combo(items: list[dict], selected: str, key: str) -> str:
    current = _current(key, "selected", selected)
    _COMBO(data={"items": items, "selected": current}, key=key, default={"selected": current},
           on_selected_change=lambda: None)
    return current


# --- 4. calendário de chuva -------------------------------------------------------

_CALENDAR = _component(
    "calendario_chuva",
    """
.meses { display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap:1.1rem 1.4rem; }
.mes h4 { font-family: Montserrat, Inter, sans-serif; font-size:.9rem; font-weight:700; margin:0 0 .35rem 0; text-transform: capitalize; }
.grade { display:grid; grid-template-columns: repeat(7, 1fr); gap:3px; }
.sem { font-size:.62rem; color:var(--sub); text-align:center; padding-bottom:2px; font-family:'IBM Plex Mono', monospace; }
.dia { position:relative; aspect-ratio:1/1; border-radius:5px; display:flex; align-items:center; justify-content:center; }
.dia .n { position:absolute; top:1px; left:3px; font-size:.55rem; color:rgba(22,48,55,.55); }
.dia.futuro .n { color:rgba(22,48,55,.35); }
.dia.sem_dado { background-image: repeating-linear-gradient(45deg, rgba(22,48,55,.08) 0 2px, transparent 2px 5px) !important; }
.gota { width:62%; height:62%; border-radius:50%; background:var(--pet); display:flex; align-items:center; justify-content:center; }
.gota.m { width:76%; height:76%; } .gota.g { width:90%; height:90%; }
.gota::after { content:""; width:28%; height:48%; border-right:2px solid #fff; border-bottom:2px solid #fff; transform: translateY(-12%) rotate(45deg); }
.dia.veranico { box-shadow: inset 0 -4px 0 0 rgba(170,40,30,.75); }
.dia.inicio { outline: 2.5px solid var(--verde); outline-offset: 1px; }
.dia.normal { outline: 2px dashed var(--pet); outline-offset: 1px; }
.dia.hoje { outline: 2.5px solid var(--terra); outline-offset: 1px; }
.legenda { display:flex; flex-wrap:wrap; gap:.6rem 1.4rem; margin-top:1rem; font-size:.8rem; color:var(--pet2); align-items:center; }
.leg { display:flex; align-items:center; gap:.45rem; }
.sw { width:18px; height:18px; border-radius:4px; display:inline-flex; align-items:center; justify-content:center; }
.escala { display:flex; gap:2px; }
.escala span { width:14px; height:14px; border-radius:3px; }
@media (max-width: 640px) { .meses { grid-template-columns: 1fr 1fr; gap:.9rem .8rem; } .dia .n { font-size:.48rem; } .grade { gap:2px; } }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const bg = (p) => `rgba(22,48,55,${(0.04 + 0.46 * p).toFixed(3)})`;
  const semana = ['D','S','T','Q','Q','S','S'];
  const meses = data.meses.map((m) => {
    const vazios = Array(m.offset).fill('<span></span>').join('');
    const dias = m.dias.map((d) => {
      const cls = ['dia', d.s, ...d.m].join(' ');
      const chance = Math.round(d.p * 10);
      let tip = `${d.d} ${m.titulo}: chove neste dia em ${chance} de cada 10 anos`;
      if (d.s === 'chuva' || d.s === 'seco') tip += ` · choveu ${d.mm} mm`;
      if (d.s === 'sem_dado') tip += ' · sem dado ainda';
      if (d.m.includes('inicio')) tip += ' · a chuva firmou';
      if (d.m.includes('normal')) tip += ' · início normal da chuva';
      if (d.m.includes('veranico')) tip += ' · veranico';
      let gota = '';
      if (d.s === 'chuva') { const t = d.mm >= 25 ? 'g' : (d.mm >= 10 ? 'm' : ''); gota = `<span class="gota ${t}"></span>`; }
      return `<span class="${esc(cls)}" title="${esc(tip)}" style="background:${bg(d.p)}"><span class="n">${d.d}</span>${gota}</span>`;
    }).join('');
    return `<div class="mes"><h4>${esc(m.titulo)}</h4><div class="grade">${semana.map((s) => `<span class="sem">${s}</span>`).join('')}${vazios}${dias}</div></div>`;
  }).join('');
  const esc5 = [0.1,0.3,0.5,0.7,0.9].map((p) => `<span style="background:${bg(p)}"></span>`).join('');
  const L = data.legenda || {};
  root.innerHTML = `<div class="meses">${meses}</div>
   <div class="legenda">
     <span class="leg"><span class="escala">${esc5}</span>chance de chover no dia (${esc(L.periodo || '1991-2020')}): de pouca a muita</span>
     <span class="leg"><span class="sw" style="background:rgba(22,48,55,.1)"><span class="gota" style="width:70%;height:70%"></span></span>choveu (maior = mais chuva)</span>
     ${L.veranico ? '<span class="leg"><span class="sw" style="box-shadow: inset 0 -4px 0 0 rgba(170,40,30,.75); background:rgba(22,48,55,.1)"></span>veranico</span>' : ''}
     ${L.inicio ? '<span class="leg"><span class="sw" style="outline:2.5px solid #266F49"></span>a chuva firmou</span>' : ''}
     ${L.normal ? '<span class="leg"><span class="sw" style="outline:2px dashed #163037"></span>início normal</span>' : ''}
     <span class="leg"><span class="sw" style="outline:2.5px solid #9C6346"></span>hoje</span>
   </div>`;
}
""",
)


def rain_calendar(months: list[dict], legend: dict, key: str) -> None:
    _CALENDAR(data={"meses": months, "legenda": legend}, key=key)


# --- 5. comparação do solo com a região -----------------------------------------------

_SOIL = _component(
    "solo_regiao",
    """
.linhas { display:flex; flex-direction:column; gap:1.25rem; }
.l { display:grid; grid-template-columns: minmax(150px, 1.1fr) 2.2fr; gap:1.5rem; align-items:center; }
.cab b { font-family: Montserrat, Inter, sans-serif; font-size:1rem; display:block; }
.cab .val { font-family: Montserrat, Inter, sans-serif; font-weight:800; font-size:1.5rem; }
.cab .classe { margin-left:.4rem; }
.cab .fonte { display:block; font-size:.74rem; color:var(--sub); margin-top:.15rem; font-family:'IBM Plex Mono', monospace; }
.regua { position:relative; height:34px; margin-top:6px; }
.trilho { position:absolute; left:0; right:0; top:14px; height:6px; background:var(--areia); border-radius:3px; }
.faixa { position:absolute; top:12px; height:10px; background:rgba(22,48,55,.22); border-radius:5px; }
.med { position:absolute; top:8px; width:2px; height:18px; background:var(--pet); }
.ponto { position:absolute; top:7px; width:20px; height:20px; margin-left:-10px; border-radius:50%; background:var(--terra-i); border:3px solid #fff; box-shadow:0 0 0 1px var(--terra-i); }
.extremos { display:flex; justify-content:space-between; font-size:.7rem; color:var(--sub); font-family:'IBM Plex Mono', monospace; }
.frase { font-size:.85rem; color:var(--pet2); margin-top:.15rem; }
.sem { font-size:.85rem; color:var(--sub); background:var(--creme); border-radius:.6rem; padding:.55rem .75rem; }
@media (max-width: 640px) { .l { grid-template-columns: 1fr; gap:.4rem; } }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const linhas = data.rows.map((r) => {
    let direita = `<div class="sem">${esc(r.note || 'Sem comparação regional para este dado.')}</div>`;
    if (r.scale) {
      const s = r.scale, span = (s.high - s.low) || 1;
      const pos = (v) => Math.max(0, Math.min(100, (v - s.low) / span * 100));
      direita = `<div><div class="regua">
          <div class="trilho"></div>
          <div class="faixa" style="left:${pos(s.p10)}%; width:${Math.max(1, pos(s.p90) - pos(s.p10))}%"></div>
          <div class="med" style="left:${pos(s.p50)}%"></div>
          <div class="ponto" style="left:${pos(s.local)}%" title="${esc(r.value_txt)}"></div></div>
        <div class="extremos"><span>${esc(s.low_txt)}</span><span>região: ${esc(s.p50_txt)} no meio</span><span>${esc(s.high_txt)}</span></div>
        <div class="frase">${esc(s.phrase)}</div></div>`;
    }
    return `<div class="l"><div class="cab"><b>${esc(r.label)}</b>
        <span class="val">${esc(r.value_txt)}</span><span class="pill tone-${esc(r.tone)} classe">${esc(r.class_txt)}</span>
        <span class="fonte">${esc(r.source_txt)}</span></div>${direita}</div>`;
  }).join('');
  root.innerHTML = `<div class="linhas">${linhas}</div>`;
}
""",
)


def soil_compare(rows: list[dict], key: str) -> None:
    _SOIL(data={"rows": rows}, key=key)


# --- 6. janela oficial do ZARC (ano em decêndios) ----------------------------------------

_ZARC = _component(
    "janela_zarc",
    """
.box { background:#fff; border:1px solid var(--linha); border-radius:1rem; padding:1.2rem 1.3rem; }
.estado { font-family: Montserrat, Inter, sans-serif; font-weight:700; font-size:1.15rem; margin:.2rem 0 .8rem 0; }
.linha { position:relative; display:grid; grid-template-columns: repeat(36, 1fr); gap:2px; margin-top:22px; }
.c { height:30px; border-radius:3px; background:var(--areia); }
.r20 { background:#9CC3AC; } .r30 { background:#EDD39B; } .r40 { background:#E6BDB8; }
.meses { display:grid; grid-template-columns: repeat(12, 1fr); margin-top:4px; font-size:.68rem; color:var(--sub); font-family:'IBM Plex Mono', monospace; text-transform: capitalize; }
.hoje { position:absolute; top:-22px; transform: translateX(-50%); display:flex; flex-direction:column; align-items:center; font-size:.68rem; color:var(--terra); font-weight:600; }
.hoje::after { content:""; width:2px; height:44px; background:var(--terra); margin-top:2px; }
.leg { display:flex; flex-wrap:wrap; gap:.4rem 1rem; margin-top:.9rem; font-size:.78rem; color:var(--pet2); }
.leg span { display:inline-flex; align-items:center; gap:.35rem; }
.leg i { width:14px; height:14px; border-radius:3px; display:inline-block; }
.nao { color:var(--pet2); font-size:.95rem; line-height:1.5; }
.fonte { color:var(--sub); font-size:.74rem; margin-top:.7rem; font-family:'IBM Plex Mono', monospace; }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const d = data;
  if (!d.has_window) {
    root.innerHTML = `<div class="box"><p class="rot">Janela oficial de plantio</p><p class="estado">${esc(d.state_txt)}</p><p class="nao">${esc(d.detail)}</p><p class="fonte">${esc(d.source)}</p></div>`;
    return;
  }
  const cells = d.decendios.map((r, i) => `<span class="c ${r ? 'r' + r : ''}" title="${esc(d.labels[i])}${r ? ' · risco ' + r + '%' : ' · não indicado'}"></span>`).join('');
  const hoje = d.today_pos == null ? '' : `<span class="hoje" style="left:${d.today_pos}%">hoje</span>`;
  root.innerHTML = `<div class="box"><p class="rot">Janela oficial de plantio · ZARC</p>
    <p class="estado">${esc(d.state_txt)}</p>
    <div class="linha">${hoje}${cells}</div>
    <div class="meses">${['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'].map((m) => `<span>${m}</span>`).join('')}</div>
    <div class="leg"><span><i class="r20"></i>risco de 20%</span><span><i class="r30"></i>30%</span><span><i class="r40"></i>40%</span><span><i style="background:#E8E2D6"></i>não indicado</span></div>
    <p class="fonte">${esc(d.source)}</p></div>`;
}
""",
)


def zarc_window(data: dict[str, Any], key: str) -> None:
    _ZARC(data=data, key=key)


# --- 7. risco por atraso da chuva (cultura escolhida) ---------------------------------------

_DELAY = _component(
    "risco_atraso",
    """
.box { background:#fff; border:1px solid var(--linha); border-radius:1rem; padding:1.2rem 1.3rem; }
.cols { display:grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap:.6rem; align-items:end; height:170px; margin-top:.6rem; }
.col { display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%; gap:.3rem; }
.bar { width:100%; max-width:64px; border-radius:6px 6px 2px 2px; display:flex; align-items:flex-start; justify-content:center;
  font-family: Montserrat, Inter, sans-serif; font-weight:700; font-size:.82rem; padding-top:.3rem; min-height:26px; }
.b-verde { background:#BFD6C7; } .b-amarelo { background:#F1DDB0; } .b-vermelho { background:#E6BDB8; }
.col.agora .bar { box-shadow: 0 0 0 2.5px var(--terra); }
.lab { font-size:.74rem; color:var(--sub); text-align:center; font-family:'IBM Plex Mono', monospace; }
.col.agora .lab { color:var(--terra); font-weight:600; }
.frase { font-size:.92rem; color:var(--pet2); margin:.2rem 0 0 0; }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const cols = data.points.map((p) => `<div class="col ${p.current ? 'agora' : ''}">
      <div class="bar b-${esc(p.tone)}" style="height:${Math.max(16, p.of10 * 10)}%" title="${esc(p.label)}: quebra em ${p.of10} de cada 10 anos">${p.of10}/10</div>
      <div class="lab">${esc(p.label)}${p.current ? '<br>agora' : ''}</div></div>`).join('');
  root.innerHTML = `<div class="box"><p class="rot">${esc(data.title)}</p><p class="frase">${esc(data.phrase)}</p><div class="cols">${cols}</div></div>`;
}
""",
)


def delay_risk(data: dict[str, Any], key: str) -> None:
    _DELAY(data=data, key=key)


# --- 8. ranking das rotações ------------------------------------------------------------

_RANK = _component(
    "ranking_rotacoes",
    """
.lista { display:flex; flex-direction:column; gap:.7rem; }
.item { display:grid; grid-template-columns: 3rem 1fr auto; gap:1rem; align-items:center; background:rgba(255,255,255,.55);
  border:1px solid var(--linha); border-radius:.9rem; padding:.9rem 1.1rem; }
.item.top { background:#fff; box-shadow: inset 4px 0 0 var(--terra); }
.item.aberto { border-color:var(--terra); }
.pos { font-family: Montserrat, Inter, sans-serif; font-weight:800; font-size:1.9rem; color:var(--pet); text-align:center; }
.nome { font-family: Montserrat, Inter, sans-serif; font-weight:700; font-size:1.02rem; margin:0 0 .4rem 0; }
.chips { display:flex; flex-wrap:wrap; gap:.4rem .9rem; font-size:.85rem; color:var(--pet2); }
.chips b { color:var(--pet); }
.nota { height:6px; background:var(--areia); border-radius:3px; margin-top:.55rem; max-width:340px; }
.nota span { display:block; height:100%; border-radius:3px; background:var(--pet); }
.det { background:none; border:1.5px solid var(--terra); color:var(--terra); border-radius:.55rem; padding:.45rem .9rem;
  font-weight:600; cursor:pointer; white-space:nowrap; }
.det:hover, .item.aberto .det { background:var(--terra); color:#fff; }
@media (max-width: 640px) { .item { grid-template-columns: 2.2rem 1fr; } .det { grid-column: 1 / -1; } }
""",
    """
export default function(component) {
  const { data, setStateValue, parentElement } = component;
  const root = rootOf(parentElement);
  root.innerHTML = '<div class="lista">' + data.items.map((it, i) => `
    <div class="item ${i === 0 ? 'top' : ''} ${it.id === data.detail ? 'aberto' : ''}">
      <div class="pos">${i + 1}</div>
      <div><p class="nome">${esc(it.name)}</p>
        <div class="chips"><span>colhe em <b>${it.aguenta} de 10 anos</b></span><span>${esc(it.risco)}</span>
          <span>grãos <b>${esc(it.graos)}</b></span><span>forragem <b>${esc(it.forragem)}</b></span>
          ${it.renda ? `<span>renda <b>${esc(it.renda)}</b></span>` : ''}
          ${it.seca ? `<span>${esc(it.seca)}</span>` : ''}</div>
        <div class="nota" title="nota ${Math.round(it.nota)} de 100 para a prioridade escolhida"><span style="width:${Math.max(2, Math.min(100, it.nota))}%"></span></div></div>
      <button class="det anim" data-id="${esc(it.id)}">${it.id === data.detail ? 'Fechar' : 'Detalhar'}</button></div>`).join('') + '</div>';
  root.querySelectorAll('.det').forEach((b) => { b.onclick = () => setStateValue('detail', b.dataset.id === data.detail ? '' : b.dataset.id); });
}
""",
)


def rotation_ranking(items: list[dict], detail: str, key: str) -> str:
    current = _current(key, "detail", detail)
    _RANK(data={"items": items, "detail": current}, key=key, default={"detail": current},
          on_detail_change=lambda: None)
    return current


# --- 9. terreno (solo e relevo) -------------------------------------------------------------

_TERRAIN = _component(
    "terreno",
    """
.tipo { background:#fff; border:1px solid var(--linha); border-radius:1rem; padding:1.2rem 1.4rem; margin-bottom:1rem; }
.tipo h3 { font-family: Montserrat, Inter, sans-serif; font-size:1.45rem; font-weight:800; margin:.15rem 0 .35rem 0; }
.tipo p { margin:0; color:var(--pet2); line-height:1.5; }
.grade { display:grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap:1rem; }
.cartao { background:rgba(255,255,255,.55); border:1px solid var(--linha); border-radius:.9rem; padding:1rem 1.1rem; }
.cartao .v { font-family: Montserrat, Inter, sans-serif; font-weight:800; font-size:1.5rem; margin:.1rem 0 .2rem 0; }
.cartao .s { color:var(--pet2); font-size:.85rem; line-height:1.45; }
.cartao .f { color:var(--sub); font-size:.72rem; margin-top:.5rem; font-family:'IBM Plex Mono', monospace; }
.gran { display:flex; height:16px; border-radius:5px; overflow:hidden; margin:.5rem 0 .35rem 0; }
.gran span { display:block; height:100%; }
.gl { display:flex; gap:.9rem; font-size:.75rem; color:var(--pet2); flex-wrap:wrap; }
.gl i { width:10px; height:10px; display:inline-block; border-radius:2px; margin-right:.3rem; }
.esc { position:relative; display:flex; gap:2px; margin:.6rem 0 .3rem 0; }
.esc span { flex:1; height:12px; border-radius:3px; background:var(--areia); }
.esc span.on { background:var(--pet); }
.esc-l { display:flex; justify-content:space-between; font-size:.66rem; color:var(--sub); font-family:'IBM Plex Mono', monospace; }
""",
    """
export default function(component) {
  const { data, parentElement } = component;
  const root = rootOf(parentElement);
  const d = data;
  const g = d.gran;
  const cards = d.cards.map((c) => {
    let extra = '';
    if (c.kind === 'gran') {
      extra = `<div class="gran"><span style="width:${g.areia}%;background:#BB9252"></span><span style="width:${g.silte}%;background:#A46B4D"></span><span style="width:${g.argila}%;background:#163037"></span></div>
        <div class="gl"><span><i style="background:#BB9252"></i>areia ${g.areia.toFixed(0)}%</span><span><i style="background:#A46B4D"></i>silte ${g.silte.toFixed(0)}%</span><span><i style="background:#163037"></i>argila ${g.argila.toFixed(0)}%</span></div>`;
    }
    if (c.kind === 'escala') {
      extra = `<div class="esc">${c.steps.map((s, i) => `<span class="${i === c.on ? 'on' : ''}" title="${esc(s)}"></span>`).join('')}</div>
        <div class="esc-l"><span>${esc(c.steps[0])}</span><span>${esc(c.steps[c.steps.length - 1])}</span></div>`;
    }
    return `<div class="cartao"><p class="rot">${esc(c.label)}</p><p class="v">${esc(c.value)}</p>${extra}<p class="s">${esc(c.text)}</p><p class="f">${esc(c.source)}</p></div>`;
  }).join('');
  root.innerHTML = `<div class="tipo"><p class="rot">Tipo de terreno</p><h3>${esc(d.tipo)}</h3><p>${esc(d.tipo_txt)}</p></div><div class="grade">${cards}</div>`;
}
""",
)


def terrain_panel(data: dict[str, Any], key: str) -> None:
    _TERRAIN(data=data, key=key)
