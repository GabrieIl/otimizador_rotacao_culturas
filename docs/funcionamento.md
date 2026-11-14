# Como o sistema funciona — guia da equipe

Este guia explica o que o app faz, de onde vem cada informação, em que se baseia e o que ainda é
provisório. As citações completas estão em [referencias.md](referencias.md). O histórico de cada
feature está em [features/](features/).

> **Regra da casa:** o app **apoia** o agricultor e o técnico local, não decide por eles. Toda informação
> mostrada precisa ter fonte real ou aviso visível de que é exemplo.

---

## 1. O que o app responde

1. **"Posso plantar agora?"** Como está a chuva desta safra comparada a um ano normal, e se a janela oficial
   de plantio de cada cultura está aberta.
2. **"Qual roça aguenta mais?"** Comparação de rotações (só milho, milho + caupi, sorgo + caupi + palma...)
   por risco de perda, comida e forragem nos próximos anos.

---

## 2. O que é real e o que ainda é provisório

Leia esta tabela antes de apresentar qualquer número.

| Informação | Fonte | Situação |
|---|---|---|
| Chuva diária usada no **atraso da chuva** | NASA POWER (`PRECTOTCORR`) | ✅ **Real**, baixada e em cache |
| Data normal de início da chuva | calculada da chuva real de 1991-2020 | ✅ **Real** (critério de Sivakumar, 1988) |
| Janelas oficiais de plantio | Tábua de risco do ZARC (MAPA/Embrapa), safra 2026/2027 | ✅ **Real**, CSV oficial |
| Clima usado no **Monte Carlo e no semáforo** | `NasaPowerClient` em modo `offline` | ⚠️ **Sintético** (perfis fixos por município) |
| Umidade do solo / NDVI | `NasaAppeearsClient` em modo `offline` | ⚠️ **Sintético** (sem token do AppEEARS) |
| Preços e custos | `B3MarketDataSource` | ⚠️ **Valores fixos** em `domain/presets.py`, sem consulta |
| Parâmetros das culturas | `domain/presets.py` | ⚠️ Hipóteses da equipe, sem revisão de agronomia |
| Penalidade do atraso e do veranico na produtividade | `engine/monte_carlo.py` | ⚠️ Coeficientes sem fonte |
| Janelas do "ZARC" dentro do ELT (`EmbrapaZarcSource`) | gerado a partir de datas fixas | ❌ **Falso**: não usar; substituir pela tábua real |

Hoje só a seção **"🌧️ Chuva da safra"** é toda baseada em dado real. O semáforo e o placar recebem o atraso
real, mas o resto do clima deles ainda é sintético.

---

## 3. Caminho dos dados

```
Fonte externa                   data/bronze/<fonte>/        data/silver/              App
──────────────                  (arquivo original, cache)   (recorte/limpeza)
NASA POWER API ───────────────► nasa_power/*.json ─────────────────────────────────► atraso da chuva
CSV ZARC (download manual) ───► zarc/*.csv ───────────────► zarc/*.parquet ────────► janelas por cultura
Geradores sintéticos (ELT) ───► *.parquet ────────────────► climate_enriched ──────► gold ─► Monte Carlo
```

- **Bronze** guarda o arquivo exatamente como veio da fonte, **uma subpasta por fonte**. É cache: se o
  arquivo existe, não baixa de novo. O ELT não apaga essas subpastas.
- **Silver** guarda recortes e limpezas (ex.: só os nossos municípios do ZARC).
- **Gold** guarda as tabelas prontas que o Monte Carlo consulta via DuckDB.
- `data/` está no `.gitignore`. Os dados não vão para o git; cada pessoa baixa os seus.

---

## 4. Atraso da chuva: como funciona e por que dá para confiar

### 4.1 De onde vem a chuva
- **NASA POWER**, parâmetro `PRECTOTCORR` (precipitação corrigida, mm/dia), comunidade `AG`.
- O POWER usa a reanálise **MERRA-2** no histórico e **GEOS-IT** no trecho recente. Reanálise é um modelo
  atmosférico que assimila observações de satélite e de superfície. A chuva do MERRA-2 é corrigida com
  produtos de pluviômetro (Reichle et al., 2017).
- **Por que essa fonte:** é da NASA (tema do desafio), gratuita, sem login, cobre de 1981 até ~3 dias atrás
  em qualquer ponto, e a API respondeu em menos de 1 s nos testes.
- **Cuidados:** pixel de ~50 km (chuva da região, não do roçado) e os últimos ~3 dias vêm como `-999`.

### 4.2 Quando a chuva "firma"
Chuva isolada não serve para plantar. Se vier um veranico logo depois, a semente morre. Por isso usamos o
**critério agronômico de Sivakumar (1988)**, muito usado em regiões semiáridas:

> A estação começa no **primeiro dia com pelo menos 20 mm somados em 3 dias**, desde que **nos 30 dias
> seguintes não haja um veranico de mais de 7 dias** (dia com menos de 1 mm conta como seco).

- A procura começa no **início do ano hidrológico**: o mês seguinte ao mais seco da normal (set em
  Petrolina e Irecê, out em Quixadá e Sousa). Assim a estação de Irecê, que vai de nov a abr, não fica
  partida na virada do ano.
- Os limiares estão em `config/chuva.yaml`, marcados `# CONFERIR`.

**Por que não usamos o método de Liebmann e Marengo:** ele é o mais citado para o Brasil, e o testamos.
Ele procura o mínimo da anomalia acumulada de chuva. Funciona bem para a média de longo prazo, mas, ano a
ano no semiárido, nos anos secos a data cai no fim da janela e o desvio passou de 100 dias. Para atraso
ano a ano, o critério agronômico é mais estável (desvio de 26 a 43 dias).

### 4.3 Qual é o "normal"
- Para cada safra de **1991 a 2020** (normal climatológica da OMM) calculamos o dia em que a chuva firmou.
- **Normal = mediana** dessas 30 datas. Mostramos também a faixa em que cai metade dos anos (P25 a P75).
- **Anos em que a chuva nunca firmou não são descartados:** entram como "depois de qualquer data". Se
  fossem descartados, a chuva pareceria mais pontual do que é. Em Petrolina isso move o normal de 04/jan para
  11/fev, porque lá a chuva não firmou em 11 de 30 anos.

### 4.4 Atraso da safra atual
| Situação | O que significa | Atraso |
|---|---|---|
| Ainda não é tempo | não firmou e a data normal ainda não chegou | 0 |
| Atrasada | passou da data normal e não firmou | hoje − normal (cresce a cada dia) |
| Caiu chuva boa (firmando) | já caiu chuva suficiente, mas os 30 dias sem veranico longo ainda não fecharam | início − normal |
| Firmou | início confirmado | início − normal (negativo = adiantada) |

Quando está atrasada, também dizemos: **"nos anos em que atrasou assim, ela ainda firmou em X de cada 10"**.
São os anos de 1991-2020 que, nesta mesma altura, ainda estavam esperando chuva.

O atraso vai para o Monte Carlo cortado entre 0 e 45 dias.

### 4.5 Janela oficial do ZARC
- O **ZARC** (Zoneamento Agrícola de Risco Climático) é a referência oficial do MAPA, feita pela Embrapa. É a
  base do Proagro e do seguro rural. Para cada município, cultura, tipo de solo e ciclo, diz em quais
  **decêndios** (blocos de 10 dias, 36 por ano) o plantio tem risco de perda de até 20%, 30% ou 40%.
- O que não aparece na tábua **não é indicado** (risco acima de 40% ou não zoneado).
- No app mostramos, por cultura, a união dos solos e ciclos: ✅ aberta (faltam N dias), ⏳ ainda não abriu,
  🚫 fechou, ⛔ sem indicação.
- **Por que isso fecha a conta:** o ZARC diz *até quando* é seguro plantar, e o satélite diz *se a chuva já
  chegou* neste ano. Juntos respondem "posso plantar agora?".

### 4.6 As duas fontes concordam
Nos 4 municípios, a primeira janela do ZARC abre **dentro da faixa em que a chuva firma em metade dos anos**
(P25 a P75), medida pelo satélite:

| Município | Faixa normal do satélite (P25 – mediana – P75) | Primeira janela ZARC |
|---|---|---|
| Petrolina | 30/dez – 11/fev – (não firmou em mais de 1 de cada 4 anos) | 11/jan (sorgo) |
| Quixadá | 12/jan – 25/jan – 18/fev | 21/jan (caupi) |
| Sousa | 06/jan – 17/jan – 12/fev | 21/jan (milho, caupi, sorgo) |
| Irecê | 18/nov – 06/dez – 21/mar | 21/nov (sorgo) |

Duas fontes independentes (reanálise da NASA e zoneamento da Embrapa) apontando a mesma época é o principal
argumento de que o cálculo está no lugar certo. A janela do ZARC pode abrir antes da mediana porque indica
quando o plantio *pode* começar com risco aceitável, não o dia típico em que a chuva firma.

---

## 5. Como ler a tela

- **Barra lateral → "Data de hoje":** o atraso é calculado para essa data. Troque para mostrar outra
  época (o demo acontece fora da estação). Ex.: Irecê em 20/12/2025 mostra chuva atrasada.
- **"🌧️ Chuva da safra":** frase principal, quatro números (quando firmou, normal, atraso, atraso usado na
  simulação), fonte e critério na legenda, e janelas do ZARC.
- **Semáforo e placar (abaixo):** usam o atraso calculado, mas o clima de fundo ainda é sintético (seção 2).

---

## 6. Como mexer

| Quero... | Faça |
|---|---|
| Ajustar o critério de chuva firme | edite `config/chuva.yaml` (mantenha `# CONFERIR` até um humano validar) |
| Trocar a safra do ZARC | baixe o novo CSV em [dados.agricultura.gov.br](https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico) para `data/bronze/zarc/`, atualize `arquivo` e `safra` em `config/zarc.yaml` e apague `data/silver/zarc/` |
| Mapear outra cultura no ZARC | `culturas:` em `config/zarc.yaml` (o nome deve ser igual a `Nome_cultura` na tábua) |
| Adicionar município | `DEFAULT_LOCATIONS` em `domain/presets.py` (lat, lon, `ibge_code`) e rode `python scripts/run_elt.py` |
| Forçar novo download da chuva | apague o JSON em `data/bronze/nasa_power/` |

Comandos:

```bash
source .venv/bin/activate
python scripts/run_elt.py                                   # monta o lakehouse
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
pytest                                                      # testes
ruff check src tests scripts                                # lint
```

---

## 7. Regras da equipe para dados

1. **Nunca inventar dados.** Se uma API falhar, mostrar o erro. Valor sintético só com aviso visível
   ("DADOS DE EXEMPLO").
2. **Todo parâmetro agronômico fica em `config/`**, com `# CONFERIR` até alguém de agronomia validar.
3. **Toda fonte e todo método citado vai para [referencias.md](referencias.md)**, com link e onde é usado
   no código.
4. **Download vai para `data/bronze/<fonte>/`** sem alteração, e não se baixa de novo se o arquivo existir.

---

## 8. Limites que precisamos dizer em voz alta

- A chuva é da região (~50 km), não do roçado.
- O ZARC mostrado é a união de solos e ciclos. A janela exata depende do solo e da cultivar do agricultor.
- O critério de "chuva firme" veio da África Ocidental e ainda não foi calibrado para o semiárido brasileiro.
- O modelo não vê fertilidade, pragas, preço, mão de obra nem a chuva do próximo mês. A previsão sazonal
  não faz parte do cálculo.
