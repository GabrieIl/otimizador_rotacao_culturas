# Feature 1 — Atraso da chuva

**Status:** implementada na branch `feature/atraso-da-chuva`, aguardando validação da equipe.
**Data:** 14/11/2026

## Objetivo

1. Identificar e validar qual referência o sistema usava para "atraso da chuva".
2. Usar dados de satélite/reanálise para obter o histórico de chuva de cada local.
3. Calcular o atraso automaticamente: referência × chuva observada no local.
4. Mostrar na interface a situação real da safra atual, sem o usuário configurar dias de atraso.

---

## Como era antes

### Interface
- O atraso era um **slider manual** na barra lateral: "Atraso das Chuvas (dias)", de 0 a 35, padrão 14
  (`app/dashboard.py`).
- O número não era medido contra nenhuma data. Era uma hipótese que o usuário escolhia.

### Referência de início da chuva
- Cada município tinha um campo fixo `rainy_season_start_doy` (dia do ano) em `domain/presets.py`:

  | Município | Valor fixo | Data |
  |---|---|---|
  | Petrolina/PE | 15 | 15/jan |
  | Quixadá/CE | 32 | 01/fev |
  | Sousa/PB | 25 | 25/jan |
  | Irecê/BA | 315 | 11/nov |

- **Nenhuma fonte citada.** Esse valor não era usado no atraso; só alimentava as janelas do "ZARC".

### ZARC
- `ingestion/embrapa_zarc.py` **não consultava o ZARC**. Ele gerava janelas a partir da data fixa acima
  (`início + 28 dias` para milho, `+ 42` para as outras culturas etc.).

### Clima
- O modo padrão (`CROP_OPT_INGESTION_MODE=offline`) **gera chuva sintética** a partir de perfis fixos
  (`ingestion/nasa_power.py`, `_generate_calibrated_series`). No modo online, uma falha da API também
  caía no sintético sem aviso na tela.

### Efeito do atraso no motor
- `engine/monte_carlo.py::_delay_and_veranico_penalty` transforma os dias de atraso em estresse e teto de
  produtividade com coeficientes sem fonte (tolerância de 5 dias, `0.011 * atraso + 0.00022 * atraso²` etc.).
  **Esta feature não mexeu nisso:** só trocou de onde vem o número de dias.

---

## O que mudou

### 1. Validação da referência
Comparamos as datas fixas com o histórico real (NASA POWER 1991-2020) e com o ZARC oficial 2026/2027:

| Município | Fixo antigo | Mediana real (critério de Sivakumar) | Anos sem chuva firme (1991-2020) | Janelas ZARC sequeiro 2026/27 |
|---|---|---|---|---|
| Petrolina/PE | 15/jan | **11/fev** | 11 de 30 | caupi 21/jan–20/fev · sorgo 11/jan–28/fev · **milho: sem indicação** |
| Quixadá/CE | 01/fev | **25/jan** | 1 de 30 | milho 11/fev–31/mar · caupi 21/jan–20/abr · sorgo 01/fev–20/mai |
| Sousa/PB | 25/jan | **17/jan** | 0 de 30 | milho 21/jan–10/mar · caupi 21/jan–20/abr · sorgo 21/jan–30/abr |
| Irecê/BA | 11/nov | **06/dez** | 7 de 30 | sorgo 21/nov–20/fev · **milho e caupi: sem indicação** |

Conclusões:
- As datas fixas estavam a 1-4 semanas do observado e não tinham fonte. Foram substituídas pelo cálculo.
- A primeira janela do ZARC abre, nos 4 municípios, dentro da faixa em que a chuva firma em metade dos anos
  (P25 a P75 do satélite): as duas fontes concordam.
- **O ZARC não indica milho de sequeiro em Petrolina e Irecê.** O semáforo antigo mandava "Plante Milho"
  nesses locais.

### 2. Fonte de chuva real com cache por fonte
- Novo `ingestion/rain_history.py`: baixa `PRECTOTCORR` do NASA POWER **sem fallback sintético**. Se a API
  falhar e não houver cache, levanta `RainDataUnavailable` e a tela mostra o erro.
- Cache em `data/bronze/nasa_power/`, com o JSON original:
  - histórico fechado (1991 até 31/12 de dois anos atrás): baixado uma única vez;
  - trecho recente (1º/jan do ano anterior até hoje): no máximo uma vez por dia.

### 3. Tábua oficial do ZARC
- Novo `ingestion/zarc_tabua.py`: lê o CSV de dados abertos do MAPA (baixado manualmente) de
  `data/bronze/zarc/`, filtra os municípios do catálogo e o manejo sequeiro, e grava o recorte em formato
  longo em `data/silver/zarc/`. Depois disso o app não precisa reler os 248 MB.
- Calcula a janela por cultura (união dos solos e ciclos), mesmo quando ela cruza a virada do ano
  (ex.: Irecê, nov–fev).

### 4. Motor do atraso
- Novo `engine/rain_onset.py`:
  - `detect_onset`: primeiro dia em que a chuva "firmou" (critério de Sivakumar, 1988);
  - `hydro_year_start_month`: o ano hidrológico começa no mês seguinte ao mais seco da normal;
  - `build_reference`: data de início em cada safra de 1991-2020, mediana e quartis. **Anos sem chuva firme
    entram como "depois de qualquer data" (censura), não são descartados**;
  - `assess_season`: situação da safra atual em uma data.
- Estados possíveis:

  | Estado | Quando | Atraso |
  |---|---|---|
  | `antes_da_epoca` | ainda não firmou e a data normal não chegou | 0 |
  | `atrasada` | passou da data normal e não firmou | hoje − normal (cresce a cada dia) |
  | `firmando` | caiu chuva suficiente, mas ainda não fecharam os 30 dias sem veranico longo | início − normal |
  | `firmou` | início confirmado | início − normal (negativo = adiantada) |
  | `sem_referencia` | em mais da metade dos anos a chuva não firmou | 0 |

- O atraso enviado ao Monte Carlo é cortado em 0-45 dias (limite de `SimulationConfig`).

### 5. Interface
- O slider de atraso foi **removido**. No lugar entrou **"Data de hoje"** (padrão: hoje), para simular outras
  épocas na demonstração.
- Nova seção no topo, "🌧️ Chuva da safra AAAA/AAAA em <município>":
  - frase simples com a situação (ex.: "A chuva está atrasada 14 dias... Nos anos em que atrasou assim, ela
    ainda firmou em 5 de cada 10");
  - métricas: quando firmou, data normal, atraso, atraso usado na simulação;
  - origem dos dados e critério usado, em uma legenda;
  - janela oficial do ZARC por cultura: ✅ aberta (faltam N dias), ⏳ ainda não abriu, 🚫 fechou,
    ⛔ sem indicação.
- O resto da tela (semáforo, placar, rádio, ficha) recebe o atraso calculado.

### 6. Configuração e estrutura
- `config/chuva.yaml`: limiares do critério, período de referência, URL do POWER, limite do motor.
  Valores marcados `# CONFERIR`.
- `config/zarc.yaml`: arquivo e safra do ZARC, manejo, mapeamento cultura do motor → nome na tábua.
- `config.py`: `load_yaml_config()` e `LakehousePaths.bronze_source(<fonte>)`.
- `LocationSpec.ibge_code` (códigos conferidos na própria tábua do ZARC).
- Dependência nova: `pyyaml` (consta na lista permitida do CLAUDE.md).
- O CLAUDE.md agora fala em `data/bronze/<fonte>/` no lugar de `data/raw/` (uma subpasta por fonte).

### Arquivos

| Arquivo | Mudança |
|---|---|
| `src/crop_optimizer/ingestion/rain_history.py` | novo |
| `src/crop_optimizer/ingestion/zarc_tabua.py` | novo |
| `src/crop_optimizer/engine/rain_onset.py` | novo |
| `src/crop_optimizer/analytics/rain_delay.py` | novo: junta chuva + referência + ZARC e gera as frases |
| `src/crop_optimizer/app/dashboard.py` | slider removido, data de hoje e seção da chuva |
| `src/crop_optimizer/config.py` | leitor de YAML e subpastas da bronze |
| `src/crop_optimizer/domain/models.py`, `presets.py` | `ibge_code` |
| `config/chuva.yaml`, `config/zarc.yaml` | novos |
| `tests/test_rain_onset.py` | 10 testes novos |
| `pyproject.toml` | `pyyaml` |

---

## Como ficou: exemplos reais

| Município e data | O que a tela diz |
|---|---|
| Irecê, 14/11/2026 | Ainda não é tempo. Normal: 06/dez. 54 mm desde 01/set. Atraso 0. |
| Irecê, 20/12/2025 | Atrasada 14 dias. Nos anos em que atrasou assim, ainda firmou em 5 de cada 10. |
| Irecê, 20/01/2026 | Caiu chuva boa em 02/jan, 27 dias depois do normal. ZARC: só o sorgo com janela aberta (31 dias). |
| Sousa, 20/01/2026 | Atrasada 3 dias. ZARC: milho, caupi e sorgo abrem em 21/jan. |
| Petrolina, 05/03/2026 | Caiu chuva boa em 23/fev, 12 dias depois do normal. |

## Como testar

```bash
source .venv/bin/activate
pytest tests/test_rain_onset.py
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
```

Na barra lateral, troque o município e a "Data de hoje" (ex.: 20/12/2025 em Irecê).

Para trocar a safra do ZARC: baixe o CSV novo para `data/bronze/zarc/` e atualize `arquivo` e `safra` em
`config/zarc.yaml`.

---

## Limitações conhecidas

- **Resolução:** o NASA POWER tem uns 50 km por pixel. É chuva da região, não do roçado.
- **Reanálise, não satélite direto:** `PRECTOTCORR` vem do MERRA-2 (e do GEOS-IT no trecho recente),
  corrigido com dados de pluviômetro. Não é medição direta de satélite como o IMERG ou o CHIRPS.
- **Latência:** os últimos ~3 dias vêm como `-999` (sem dado). A tela mostra até quando há dado.
- **ZARC sem solo e ciclo:** sem o dicionário de dados, os códigos `Cod_Solo` e `Cod_Ciclo` não foram
  traduzidos. A janela mostrada é a união de todos os solos e ciclos.
- **Critério não calibrado para o semiárido:** os limiares de Sivakumar vêm da África Ocidental. Precisam
  de revisão de agronomia (`# CONFERIR`).

## Pendências

- [ ] Revisão de agronomia/meteorologia dos limiares em `config/chuva.yaml`.
- [ ] Baixar o dicionário de dados do ZARC e permitir escolher o tipo de solo.
- [ ] O Rádio do Tempo e o WhatsApp dizem "atrasou 0 dias" quando ainda não é época.
- [ ] O semáforo e o Monte Carlo ainda usam o clima sintético do modo offline. Só o atraso é real.
- [ ] A CLI (`--delay-days`) e a API (`safra_delay_days`) ainda recebem o atraso à mão.
- [ ] Trocar o falso `EmbrapaZarcSource` pela tábua real.
- [ ] Conferir as datas com o CHIRPS (satélite + estações, ~5 km).
