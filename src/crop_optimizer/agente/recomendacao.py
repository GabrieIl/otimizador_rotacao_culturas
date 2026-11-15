"""O que plantar hoje: ordena as culturas com o que o Acauã já calcula, para o chatbot aconselhar uma ação.

Não é agronomia nova: só junta, numa ordem explícita, os dados que a página Plantio já mostra.

Critério (na ordem):
1. o aviso de hoje: "Pode plantar" < "Arriscado" < esperar (chuva ou janela);
2. a janela oficial: aberta (ou cultura perene, sem janela no ZARC) antes da que ainda vai abrir; entre as que
   vão abrir, a que abre primeiro;
3. a menor quebra de safra com o atraso de hoje (clima de exemplo);
4. quanto a lavoura aguenta sem chuva na floração perto do veranico típico daqui (menos dias faltando, melhor);
5. a nota do solo para a cultura.
Culturas com "Não plante", "Não plante agora" ou "Fora da janela" saem da ordem e vão para "evitar".

Sem finalidade, a recomendação sai separada para grãos (comida) e para forragem (rebanho): uma cultura perene de
pasto quase nunca tem janela fechada nem quebra de safra, e ficaria sempre em primeiro numa lista só.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from crop_optimizer.analytics.rain_delay import fmt_date
from crop_optimizer.config import load_yaml_config
from crop_optimizer.domain.crop_registry import crop_info, is_irrigated
from crop_optimizer.domain.presets import crop_map

FINALIDADES = ("graos", "forragem")
_GROUP = {"verde": 0, "amarelo": 1, "espera": 2, "vermelho": 3, "rega": 4}

CRITERIO = (
    "aviso de hoje (pode plantar, depois arriscado, depois esperar); janela oficial aberta ou que abre primeiro; "
    "menor quebra de safra; quanto aguenta sem chuva perto do veranico típico; solo"
)


def serve_para(crop_id: str) -> list[str]:
    """Para que a cultura serve no motor: grãos (comida), forragem (rebanho) ou rega (irrigada)."""
    if is_irrigated(crop_id):
        return ["rega"]
    crop = crop_map().get(crop_id)
    info = crop_info(crop_id)
    min_forage = float(load_yaml_config("conversa")["recomendacao"]["forragem_minima_t_ha"])
    out = []
    has_food_spec = crop is not None and crop.food_fraction > 0 and crop.base_yield_ton_ha > 0
    if has_food_spec or info.get("grupo") in ("graos", "raizes"):
        out.append("graos")
    if crop is not None and crop.forage_yield_ton_ha >= min_forage:
        out.append("forragem")
    return out


@dataclass(frozen=True, slots=True)
class Opcao:
    crop_id: str
    nome: str
    nivel: str  # verde | amarelo | espera | vermelho
    palavra: str
    motivo: str
    quebra_de_10: int
    quebra_pct: float  # sem arredondar, para desempatar
    janela_estado: str | None  # aberta | ainda_nao_abriu | fechou | sem_indicacao | None (perene)
    janela_abre: date | None
    janela_fecha: date | None
    aguenta_dias: int | None  # None = guarda água na planta (palma) ou sem dado de água
    veranico_tipico: int | None
    nota_solo: float
    aptidao_solo: str

    def chave(self, hoje: date) -> tuple:
        if self.janela_estado in (None, "aberta"):
            wait = 0
        elif self.janela_estado == "ainda_nao_abriu" and self.janela_abre is not None:
            wait = max(0, (self.janela_abre - hoje).days)
        else:
            wait = 999
        gap = 0 if self.aguenta_dias is None or self.veranico_tipico is None else max(
            0, self.veranico_tipico - self.aguenta_dias)
        return (_GROUP[self.nivel], wait, self.quebra_pct, gap, -self.nota_solo)

    def resumo(self) -> dict:
        out: dict = {
            "cultura": self.nome,
            "id": self.crop_id,
            "serve_para": serve_para(self.crop_id),
            "aviso": self.palavra,
            "quebra_de_safra": f"{self.quebra_de_10} de cada 10 anos",
            "solo": self.aptidao_solo,
        }
        if self.janela_estado is None:
            out["janela_oficial"] = "não se aplica (cultura perene, o ZARC não dá janela anual)"
        elif self.janela_estado == "aberta":
            out["janela_oficial"] = f"aberta até {fmt_date(self.janela_fecha)}"
        elif self.janela_estado == "ainda_nao_abriu":
            out["janela_oficial"] = f"abre em {fmt_date(self.janela_abre)}"
        if self.aguenta_dias is not None:
            out["aguenta_sem_chuva_dias"] = self.aguenta_dias
        return out


def _action(top: Opcao) -> str:
    name = top.nome.lower()
    if top.nivel == "verde":
        return f"pode plantar {name} hoje"
    if top.nivel == "amarelo":
        return f"plantar hoje é arriscado; a opção menos arriscada é {name}"
    if top.palavra == "Espere a janela abrir":
        return f"espere: a primeira janela oficial a abrir é a de {name}, em {fmt_date(top.janela_abre)}"
    return f"espere a chuva firmar; quando firmar, a primeira opção é {name}"


def _rank(opcoes: list[Opcao], hoje: date, finalidade: str, quantas: int) -> tuple[list[Opcao], list[Opcao]]:
    pool = [o for o in opcoes if finalidade in serve_para(o.crop_id)]
    ordem = sorted((o for o in pool if o.nivel != "vermelho"), key=lambda o: o.chave(hoje))
    return ordem[:quantas], [o for o in pool if o.nivel == "vermelho"]


def recomendar(opcoes: list[Opcao], hoje: date, finalidade: str | None = None, quantas: int = 3) -> dict:
    """O que plantar hoje, por finalidade (grãos e forragem, ou só a pedida), em dados prontos para o chatbot."""
    wanted = [finalidade] if finalidade else list(FINALIDADES)
    out: dict = {"criterio": CRITERIO, "por_finalidade": {}, "evitar": []}
    actions, seen_avoid = [], set()
    for fin in wanted:
        ordem, evitar = _rank(opcoes, hoje, fin, quantas)
        label = "para grãos" if fin == "graos" else "para forragem do rebanho"
        out["por_finalidade"][fin] = {
            "o_que_fazer_hoje": _action(ordem[0]) if ordem else "nenhuma cultura indicada aqui agora",
            "ordem": [o.resumo() for o in ordem],
        }
        actions.append(f"{label}, {out['por_finalidade'][fin]['o_que_fazer_hoje']}")
        for o in evitar:
            if o.crop_id not in seen_avoid:
                seen_avoid.add(o.crop_id)
                out["evitar"].append({"cultura": o.nome, "aviso": o.palavra, "motivo": o.motivo})
    out["o_que_fazer_hoje"] = "; ".join(actions).capitalize() + "."
    return out
