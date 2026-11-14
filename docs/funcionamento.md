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
| Chuva diária usada no **atraso da chuva** | NASA POWER (`PRECTOTCORR`) | **Real**, baixada e em cache |
| Data normal de início da chuva | calculada da chuva real de 1991-2020 | **Real** (critério de Sivakumar, 1988) |
| Janelas oficiais de plantio | Tábua de risco do ZARC (MAPA/Embrapa), safra 2026/2027 | **Real**, CSV oficial |
| Município da roça (a partir da coordenada) | OpenStreetMap (Nominatim) + lista de municípios do IBGE | **Real**, consultado e em cache |
| Imagens das lentes (chuva, água no solo, verde, calor, relevo) | NASA GIBS (IMERG, SMAP L4, MODIS, SRTM) | **Real**, tiles oficiais |
| Imagem de base do mapa | Esri World Imagery | Real (terceiro, com atribuição) |
| Solo do local (argila, areia, M.O., pH, CTC) | ISRIC SoilGrids 2.0 (mapa de 250 m) ou análise de campo | **Real** (mapa estimado, com faixa de incerteza) |
| Altitude e declividade | SRTM via Terrain Tiles (AWS) | **Real** |
| Fósforo, potássio e V% sem análise | valor típico do semiárido | **Assumido** e neutro (não pesa a favor nem contra) |
| Exigência de cada cultura e graus de limitação | `config/aptidao.yaml` | Classes de análise com fonte; exigências **a revisar por agrônomo** |
| Clima usado no **Monte Carlo e no semáforo** | `NasaPowerClient` em modo `offline` | **Sintético** (perfis fixos por município) |
| Umidade do solo / NDVI | `NasaAppeearsClient` em modo `offline` | **Sintético** (sem token do AppEEARS) |
| Preços e custos | `B3MarketDataSource` | **Valores fixos** em `domain/presets.py`, sem consulta |
| Parâmetros das culturas | `domain/presets.py` | Hipóteses da equipe, sem revisão de agronomia |
| Penalidade do atraso e do veranico na produtividade | `engine/monte_carlo.py` | Coeficientes sem fonte |
| Janelas do "ZARC" dentro do ELT (`EmbrapaZarcSource`) | gerado a partir de datas fixas | **Falso**: não usar; substituir pela tábua real |

Hoje a seção **"Chuva da safra"** (página Plantio) e a página **Satélite** são todas baseadas em dado
real. O semáforo e o placar recebem o atraso real, mas o resto do clima deles ainda é sintético e vem do
**município de exemplo** mais próximo, mesmo quando a roça foi marcada no mapa.

---

## 3. Caminho dos dados

```
Fonte externa                   data/bronze/<fonte>/        data/silver/              App
──────────────                  (arquivo original, cache)   (recorte/limpeza)
NASA POWER API ───────────────► nasa_power/*.json ─────────────────────────────────► atraso da chuva, chuva do mês
CSV ZARC (download manual) ───► zarc/*.csv ───────────────► zarc/*.parquet ────────► janelas por cultura
NASA GIBS GetCapabilities ────► gibs/*.xml (1 por dia) ───────────────────────────► datas e URLs das lentes
NASA GIBS tiles ──────────────────────────────────────────────────────────────────► mapa (direto no navegador)
Nominatim + IBGE ─────────────► nominatim/, ibge/*.json ───────────────────────────► município da roça
ISRIC SoilGrids ──────────────► soilgrids/*.json ────────────────────────────────► solo do local (Início)
Terrain Tiles (SRTM) ─────────► terrain_tiles/*.png ─────────────────────────────► altitude e declividade
Análise de campo (usuário) ───► data/campo/<local>.json ─────────────────────────► vale mais que o mapa
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

### 4.7 Veranico
**Veranico** = dias seguidos sem chuva **depois que a chuva firmou**. Quebra a safra mesmo em ano de chuva
normal no total, principalmente se pega a floração do milho. É diferente do atraso, que é a chuva demorar a
começar.
- Em cada safra de 1991-2020 com chuva firme, medimos a maior sequência de dias secos (< 1 mm) nos 90 dias
  seguintes. Veranico = 10 dias ou mais (`config/chuva.yaml`, `# CONFERIR`).
- O Monte Carlo usa a **chance observada** no local e **sorteia o tamanho entre os veranicos que
  aconteceram**. Petrolina: 8 de cada 10 anos (até 33 dias); Quixadá: 2 de cada 10.
- Na safra em andamento, a Plantio avisa a partir de 5 dias seguidos sem chuva.
- Não existe mais controle manual de veranico (antes era um slider que somava dias a todo ano).

### 4.5 Janela oficial do ZARC
- O **ZARC** (Zoneamento Agrícola de Risco Climático) é a referência oficial do MAPA, feita pela Embrapa. É a
  base do Proagro e do seguro rural. Para cada município, cultura, tipo de solo e ciclo, diz em quais
  **decêndios** (blocos de 10 dias, 36 por ano) o plantio tem risco de perda de até 20%, 30% ou 40%.
- O que não aparece na tábua **não é indicado** (risco acima de 40% ou não zoneado).
- No app mostramos, por cultura, a união dos solos e ciclos: aberta (faltam N dias), ainda não abriu,
  fechou, sem indicação.
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

## 5. Página Satélite: a roça no mapa e as lentes

### 5.1 Marcar a roça
- Latitude e longitude digitadas (do GPS do celular, por exemplo) ou um clique no mapa. Depois,
  **"Usar este ponto"**.
- O município vem de dois passos: o **OpenStreetMap** diz o nome do município e a UF daquela coordenada, e a
  **lista oficial do IBGE** dá o código de 7 dígitos. Esse código liga a roça à tábua do ZARC.
- A roça vale para as duas páginas. Na Plantio, **a chuva e o ZARC passam a ser do ponto da roça**. A
  simulação (Monte Carlo) continua com o clima de exemplo do município pré-cadastrado mais perto, e a tela
  diz qual e a quantos km.

### 5.2 O que cada lente mostra
| Lente | Satélite / produto | Quadrado | O que ajuda a ver |
|---|---|---|---|
| Chuva | GPM IMERG (NASA/JAXA) | ~10 km | onde choveu num dia |
| Água no solo | SMAP L4 (satélite + modelo) | ~9 km | terra seca ou úmida na zona das raízes |
| Verde da lavoura | MODIS Terra, NDVI de 16 dias | 250 m | lavoura, caatinga verde ou seca, área irrigada |
| Calor da terra | MODIS Terra, temperatura da superfície de dia, 8 dias | 1 km | chão quente que seca a planta |
| Relevo | SRTM (2000) | ~30 m | baixios e serras |

- **Ano + mês:** a lente mostra a imagem que cobre o dia 15 daquele mês. Se ainda não existe, mostra a mais
  recente e avisa. Se a série ainda não tinha começado (SMAP antes de 2015), diz isso em vez de mostrar
  um mapa vazio.
- **Quadrado tracejado em volta da roça** = tamanho de um pixel da lente. É a melhor forma de explicar ao
  agricultor que o satélite enxerga a região, não o roçado.
- **Por que dá para confiar:** as imagens são as oficiais da NASA (GIBS/EOSDIS), as mesmas do NASA
  Worldview. Os nomes das camadas e as datas disponíveis são lidos do catálogo do GIBS todo dia, não
  escritos à mão.
- **Alinhado com o desafio:** as 5 lentes e o NASA POWER estão na lista oficial "NASA Data & Resources" do
  desafio (SMAP, GPM IMERG, MODIS, SRTM, POWER). O cruzamento completo, inclusive com os recursos que só
  cobrem os EUA, está em [referencias.md](referencias.md), seção 4.1.
- **Diferenças em relação ao mock:** o GIBS não tem NDVI de Sentinel-2/Landsat nem ECOSTRESS. Usamos o MODIS
  e o rótulo diz isso. Os detalhes estão em [features/02-mapa-e-lentes.md](features/02-mapa-e-lentes.md).

---

## 6. Página Início: perfil do local e solo por cultura

### 6.1 Por que "por cultura"
A criticidade do solo depende do que se vai plantar. Pouca matéria orgânica (pouco nitrogênio) pesa muito
no milho e nada no feijão-caupi, que fixa o próprio nitrogênio. Areia, que segura pouca água, pesa no milho
e pouco no sorgo. Por isso o app não tem mais **uma** condição do solo: cada cultura é comparada com o solo,
**fator por fator**, e **o fator mais fraco manda**. É a lógica da avaliação de aptidão agrícola da Embrapa
(Ramalho Filho & Beek) e da FAO (Sys et al.).

### 6.2 Passo a passo
1. **Atributos do solo**, por ordem de prioridade: análise de campo → mapa SoilGrids/SRTM → valor típico
   do semiárido (assumido). A tela mostra a origem de cada um.
2. **Classe oficial** de cada atributo (Alvarez V. et al., 1999). O fósforo depende da argila: 8 mg/dm³ é
   "muito baixo" em solo arenoso e "médio" em solo argiloso.
3. **Grau de limitação** = classe do solo x exigência da cultura (`config/aptidao.yaml`).
4. **Nota** por grau (Sys) e **índice** 0-100 pelo método da raiz quadrada: Bom > 75, Atenção 50-75,
   Restrito 25-50, Crítico < 25.
5. **Na simulação:** o índice é comparado com o do solo típico do semiárido. Igual ao típico = fator 1,0;
   melhor ou pior muda a colheita simulada daquela cultura.

### 6.3 Como explicar para o agricultor
- "O mapa de satélite dá uma ideia do solo da região. **A análise de solo da sua roça vale mais**:
  se tiver, coloque aqui."
- "Fósforo, potássio e cálcio/magnésio **nenhum satélite mede**. Sem análise, a gente assume o típico da
  região."
- "O que mais atrapalha cada cultura" é o que vale corrigir primeiro (adubo, calcário, curva de nível...),
  sempre com o técnico.

### 6.4 O que ainda é provisório
As exigências das culturas, as tabelas de grau e o solo típico estão marcados `# REVISAR AGRÔNOMO`. As
classes da análise de solo e as notas de Sys têm fonte conferida (ver [referencias.md](referencias.md),
seções 1.4 a 1.8). Detalhes em [features/03-perfil-do-local.md](features/03-perfil-do-local.md).

---

## 7. Como ler a tela

- **Identidade visual:** cores, fontes, o elemento "pixel" e o mascote estão descritos em
  [features/05-identidade-visual.md](features/05-identidade-visual.md). Para mexer no visual, use
  `src/crop_optimizer/app/theme.py` e `.streamlit/config.toml`, e reinicie o servidor.
- **Início, de cima para baixo:** sua roça (município, latitude, longitude e o botão para configurar/editar),
  a chuva do ano x média (seta verde/vermelha) e o calendário de chuva, o solo do lugar comparado com a região,
  o solo por cultura (cards + destaque) e o terreno. Detalhes em
  [features/06-paginas-interativas.md](features/06-paginas-interativas.md).
- **Plantio ("O que devo plantar agora?"):** seletor de cultura com a janela oficial do ZARC, o aviso da cultura
  (Pode plantar / Arriscado / Não plante / Espere) e o risco por atraso. Depois o porquê (calendário da safra,
  início da chuva e veranicos), o ranking das rotações (1 a 10 anos, conforme a prioridade, com "Detalhar") e a
  ficha técnica. "Simular outra data" fica no rodapé (só para testes).

- **Barra de navegação no topo:** **Início** (perfil do local e solo por cultura), **Plantio** (chuva, ZARC,
  semáforo, placar, rádio, ficha) e **Satélite** (mapa e lentes).
- **Plantio não tem barra lateral.** O local vem da roça marcada no mapa (ou do município de exemplo escolhido
  na Início/Satélite). "Simular outra data", no topo e fechado, troca o dia usado no cálculo da chuva
  (útil para a demonstração fora da época). Ex.: Irecê em 20/12/2025 mostra chuva atrasada.
- **Horizonte da simulação** (1, 2, 3 ou 5 anos) é um filtro em "Rotações" e vale só para os painéis
  da simulação. Com 1 ano, o risco mostrado é "perder a safra no ano", não "2 anos seguidos".
- **"Chuva da safra":** frase principal, quatro números (quando firmou, normal, atraso, atraso usado na
  simulação), fonte e critério na legenda, e janelas do ZARC.
- **Semáforo e placar (abaixo):** usam o atraso calculado, mas o clima de fundo ainda é sintético (seção 2).

---

## 8. Como mexer

| Quero... | Faça |
|---|---|
| Ajustar o critério de chuva firme | edite `config/chuva.yaml` (mantenha `# CONFERIR` até um humano validar) |
| Trocar a safra do ZARC | baixe o novo CSV em [dados.agricultura.gov.br](https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico) para `data/bronze/zarc/`, atualize `arquivo` e `safra` em `config/zarc.yaml` e apague `data/silver/zarc/` |
| Mapear outra cultura no ZARC | `culturas:` em `config/zarc.yaml` (o nome deve ser igual a `Nome_cultura` na tábua) |
| Adicionar município | `DEFAULT_LOCATIONS` em `domain/presets.py` (lat, lon, `ibge_code`) e rode `python scripts/run_elt.py` |
| Forçar novo download da chuva | apague o JSON em `data/bronze/nasa_power/` |
| Mudar textos ou camadas das lentes | `config/lentes.yaml` (confira o nome da camada no GetCapabilities do GIBS) |
| Mudar os limites de zoom ou a área do mapa | `config/lentes.yaml`, seção `mapa` (acima do zoom 17 a imagem de base some) |
| Forçar nova leitura do catálogo do GIBS | apague o XML do dia em `data/bronze/gibs/` |
| Ajustar exigências das culturas e graus de limitação | `config/aptidao.yaml` (linhas `# REVISAR AGRÔNOMO`) |
| Apagar a análise de campo de um local | botão "Apagar análise salva" na Início, ou o JSON em `data/campo/` |

Comandos:

```bash
source .venv/bin/activate
python scripts/run_elt.py                                   # monta o lakehouse
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
pytest                                                      # testes
ruff check src tests scripts                                # lint
```

---

## 9. Regras da equipe para dados

1. **Nunca inventar dados.** Se uma API falhar, mostrar o erro. Valor sintético só com aviso visível
   ("DADOS DE EXEMPLO").
2. **Todo parâmetro agronômico fica em `config/`**, com `# CONFERIR` até alguém de agronomia validar.
3. **Toda fonte e todo método citado vai para [referencias.md](referencias.md)**, com link e onde é usado
   no código.
4. **Download vai para `data/bronze/<fonte>/`** sem alteração, e não se baixa de novo se o arquivo existir.

---

## 10. Limites que precisamos dizer em voz alta

- A chuva é da região (~50 km), não do roçado. As lentes vão de ~10 km (chuva) a ~30 m (relevo).
- O ZARC mostrado é a união de solos e ciclos. A janela exata depende do solo e da cultivar do agricultor.
- O critério de "chuva firme" veio da África Ocidental e ainda não foi calibrado para o semiárido brasileiro.
- O modelo não vê fertilidade, pragas, preço, mão de obra nem a chuva do próximo mês. A previsão sazonal
  não faz parte do cálculo.
