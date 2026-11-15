# Referências do projeto

Toda fonte de dado e todo método usado no código entra aqui, com **link**, **o que é** e **onde é usado**.
Ao adicionar uma referência, preencha a coluna "Conferido": diga se a citação foi checada na fonte original
ou se ainda falta conferir.

Índice:
1. [Métodos científicos usados](#1-métodos-científicos-usados)
2. [Métodos avaliados e não adotados](#2-métodos-avaliados-e-não-adotados)
3. [Bases de dados usadas](#3-bases-de-dados-usadas)
4. [Bases de dados candidatas (ainda não usadas)](#4-bases-de-dados-candidatas-ainda-não-usadas)
5. [Valores sem fonte no código](#5-valores-sem-fonte-no-código)
6. [Inspiração de código e design](#6-inspiração-de-código-e-design)

---

## 1. Métodos científicos usados

### 1.1 Sivakumar (1988): início agronômico da estação chuvosa

| | |
|---|---|
| **Citação** | SIVAKUMAR, M. V. K. Predicting rainy season potential from the onset of rains in Southern Sahelian and Sudanian climatic zones of West Africa. *Agricultural and Forest Meteorology*, v. 42, n. 4, p. 295–305, 1988. |
| **DOI** | 10.1016/0168-1923(88)90039-1 |
| **Acesso** | Repositório ICRISAT: <https://oar.icrisat.org/1436> |
| **O que diz** | A estação chuvosa começa no primeiro dia, após uma data inicial, com ≥ 20 mm acumulados em 3 dias e sem período seco > 7 dias nos 30 dias seguintes. Mostra que o início das chuvas prevê a duração da estação de cultivo. |
| **Onde usamos** | `src/crop_optimizer/engine/rain_onset.py` → `detect_onset()`; limiares em `config/chuva.yaml` (`inicio_chuva`). |
| **Para quê** | Definir em que dia a chuva "firmou" em cada safra, histórica e atual, e daí o atraso. |
| **Adaptações nossas** | Dia seco = < 1 mm; dia sem dado conta como seco; procura até 240 dias após o início do ano hidrológico; quando os 30 dias de verificação ainda não terminaram, o início é marcado como provisório ("firmando"). |
| **Conferido** | Revista, volume e páginas conferidos por busca. DOI ainda não conferido na página da editora. Os limiares vieram de trabalhos que citam o artigo; falta ler o original. |

### 1.2 Normal climatológica 1991-2020 (OMM)

| | |
|---|---|
| **Citação** | WORLD METEOROLOGICAL ORGANIZATION. *WMO Guidelines on the Calculation of Climate Normals*. WMO-No. 1203. Genebra: WMO, 2017. |
| **O que diz** | O período padrão de referência climática é de 30 anos, atualizado a cada década. O vigente é 1991-2020. |
| **Onde usamos** | `config/chuva.yaml` → `referencia.ano_inicio` / `ano_fim`; `engine/rain_onset.py` → `build_reference()`. |
| **Para quê** | Escolher os anos que definem a data "normal" de início da chuva. |
| **Conferido** | ❌ Citação de memória, falta conferir. O INMET usa o mesmo período nas normais 1991-2020: <https://portal.inmet.gov.br/normais>. |

### 1.3 Estatística: mediana com anos censurados

| | |
|---|---|
| **O que é** | Os anos em que a chuva nunca firmou entram como valor infinito ("depois de qualquer data") no cálculo de mediana e quartis. Usa-se o quantil pela inversa da CDF empírica (`numpy.quantile(..., method="inverted_cdf")`). |
| **Onde usamos** | `engine/rain_onset.py` → `_censored_quantile()`. |
| **Por quê** | Descartar os anos secos faria a chuva parecer mais pontual. Em Petrolina, descartá-los daria normal em 04/jan; mantê-los dá 11/fev. |
| **Referência formal** | Tratamento padrão de dados censurados à direita. Falta citar uma referência de estatística/climatologia. |

### 1.3b Veranico (sequência seca dentro da estação chuvosa)

| | |
|---|---|
| **O que é** | Período de dias seguidos sem chuva (ou com chuva insignificante) no meio da estação chuvosa. |
| **Definição usada** | Maior sequência de dias com < 1 mm nos 90 dias depois que a chuva firmou (critério de Sivakumar, seção 1.1); veranico se ≥ 10 dias. |
| **Fonte da definição** | ⚠️ A literatura brasileira usa limiares diferentes (5, 7, 10 ou 15 dias, e "dia seco" < 1 mm, < 2 mm ou < 5 mm). Os nossos valores são de trabalho, `# CONFERIR` em `config/chuva.yaml`. O próprio critério de Sivakumar usa veranico > 7 dias em 30 para validar o início. Falta citar uma referência regional (ex.: estudos de veranico no semiárido nordestino com dados do INMET/FUNCEME). |
| **Onde no código** | `engine/rain_onset.py` → `build_veranico_climatology`, `current_dry_days`; `engine/monte_carlo.py` (sorteio do tamanho); `analytics/rain_delay.py` (aviso). |

### 1.4 Interpretação de análise de solo: Alvarez V. et al. (1999), 5ª Aproximação

| | |
|---|---|
| **Citação** | ALVAREZ V., V. H. et al. Interpretação dos resultados das análises de solos. In: RIBEIRO, A. C.; GUIMARÃES, P. T. G.; ALVAREZ V., V. H. (ed.). *Recomendações para o uso de corretivos e fertilizantes em Minas Gerais: 5ª aproximação*. Viçosa: CFSEMG, 1999. |
| **Onde conferimos** | Tabelas 1, 2 e 3 reproduzidas em FREIRE, F. M. et al. *Fertilidade de solos: interpretação de resultados de análise do solo*. Embrapa Milho e Sorgo, Sistema de Produção 1 (Cultivo do Milho). <https://ainfo.cnptia.embrapa.br/digital/bitstream/item/27337/1/Fertilidade-de-solos-Interpretacao.pdf> |
| **O que usamos** | Classes (muito baixo a muito bom) de M.O., V%, CTC a pH 7, K Mehlich-1, **P Mehlich-1 por teor de argila** e pH em água (classificação agronômica); fator M.O. = 1,724 x C.O. |
| **Onde no código** | `config/aptidao.yaml` → `classes_analise`, `fator_carbono_para_mo`; `analytics/soil_suitability.py` (`classify`, `phosphorus_class`). |
| **Cuidado** | As classes são de Minas Gerais. Há recomendações regionais do Nordeste (ex.: IPA/PE, 2008) que podem diferir. A edição de 2020 da CFSEMG também mudou as faixas. |
| **Conferido** | ✅ Valores copiados das tabelas do PDF da Embrapa em 14/11/2026. |

### 1.5 Avaliação de aptidão: graus de limitação por fator

| | |
|---|---|
| **Citação** | RAMALHO FILHO, A.; BEEK, K. J. *Sistema de avaliação da aptidão agrícola das terras*. 3. ed. Rio de Janeiro: EMBRAPA-CNPS, 1995. 65 p. |
| **O que usamos** | A ideia: comparar a terra com a exigência do uso, **fator por fator** (fertilidade, água, erosão...), com graus de limitação nulo, ligeiro, moderado, forte e muito forte. |
| **Onde no código** | `analytics/soil_suitability.py` (`_factors`); graus em `config/aptidao.yaml`. |
| **Conferido** | ⚠️ Referência e estrutura conferidas em trabalhos que aplicam o método. Os **limites de cada grau** no nosso código **não** vêm do manual: são da equipe (REVISAR AGRÔNOMO). |

### 1.6 Notas por grau e índice: Sys et al. (1991)

| | |
|---|---|
| **Citação** | SYS, C.; VAN RANST, E.; DEBAVEYE, J. *Land Evaluation*, Parts I-II. Ghent: ITC/Ghent University, 1991. (Part III, *Crop requirements*, 1993.) |
| **Onde conferimos** | MOLOUDI, A.; YAGHMAEIAN MAHABADI, N. Quantitative and qualitative land suitability... *Polish Journal of Soil Science*, v. 52, n. 2, 2019. DOI: 10.17951/pjss/2019.52.2.195. |
| **O que usamos** | Notas: sem limitação 1,0-0,95; ligeira 0,95-0,85; moderada 0,85-0,60; forte 0,60-0,40; muito forte 0,40-0 (usamos o meio de cada faixa). Classes do índice: S1 > 75, S2 50-75, S3 25-50, N < 25. Índice pelo **método da raiz quadrada** (Khidir, 1986, citado no mesmo artigo): nota mínima x raiz(produto das demais) x 100. |
| **Onde no código** | `config/aptidao.yaml` → `notas_grau`, `classes_indice`; `analytics/soil_suitability.py` → `land_index`. |
| **Conferido** | ✅ Faixas e classes conferidas no artigo de 2019, que cita Sys et al. O livro original não foi consultado. |

### 1.7 Exigências das culturas

| Cultura | O que tem fonte | Fonte | O resto |
|---|---|---|---|
| Milho | pH ótimo 5-7, absoluto 4,5-8,5 | FAO Ecocrop, *Zea mays* (<https://ecocrop.apps.fao.org/ecocrop/srv/en/dataSheet?id=2175>) | REVISAR AGRÔNOMO |
| Feijão-caupi | pH ótimo 5,5-7,5, absoluto 4,3-8,8 | FAO Ecocrop, *Vigna unguiculata* | REVISAR AGRÔNOMO |
| Feijão-caupi | **não depende de N do solo** (fixa N com *Bradyrhizobium*) | Embrapa Amazônia Ocidental, Circular Técnica 87: a inoculação sem N mineral rendeu o mesmo que a ureia (<https://www.infoteca.cnptia.embrapa.br/infoteca/bitstream/doc/1148068/1/CircTec87.pdf>) | — |
| Sorgo | pH tolerado 4,3-8,7; prefere levemente ácido | FAO Ecocrop, *Sorghum bicolor* (página da cultura) | Faixa ótima: REVISAR AGRÔNOMO |
| Palma forrageira | não vai bem em solo ácido ou salino; exigente em K, Ca e Mg; não tolera encharcamento | Cartilha do Projeto Propaga Palma (UFV) (<https://projetopropagapalma.ufv.br/wp-content/uploads/2022/04/Cartilhas_3.pdf>); material Embrapa (<https://www.infoteca.cnptia.embrapa.br/infoteca/bitstream/doc/534153/1/MidiaPalmaForrageira.pdf>) | Faixas numéricas: REVISAR AGRÔNOMO |
| Capim-buffel | — | — | Tudo: REVISAR AGRÔNOMO |
| Solo típico do semiárido | "solos arenosos e de baixa fertilidade" (qualitativo) | Embrapa, *Nutrição mineral, calagem e adubação da palma forrageira* (<https://www.infoteca.cnptia.embrapa.br/infoteca/bitstream/doc/1143032/1/NUTRICAO-MINERAL-CALAGEM-E-ADUBACAO.pdf>) | Valores: REVISAR AGRÔNOMO |

### 1.8 Classes de relevo e textura

**Classe textural (triângulo textural):** regras do triângulo USDA (Soil Survey Manual; calculadora de textura
do NRCS), as mesmas usadas pela SBCS, com os nomes em português do *Manual de descrição e coleta de solo no
campo*. Código: `analytics/soil_texture.py`. ❌ Regras escritas de memória e conferidas por testes com
exemplos; falta conferir no manual.


| | |
|---|---|
| **Relevo** | Plano 0-3%, suave ondulado 3-8, ondulado 8-20, forte ondulado 20-45, montanhoso 45-75, escarpado > 75. SANTOS, R. D. et al. *Manual de descrição e coleta de solo no campo*. SBCS/Embrapa. ⚠️ Faixas conferidas em trabalho que as reproduz (<https://journals.ufrpe.br/index.php/BJAS/article/download/4004/482484244>), não no manual. |
| **Textura** | Grupamentos do SiBCS: arenosa (areia e areia franca), média, argilosa (35-60% de argila), muito argilosa (> 60%). SANTOS, H. G. et al. *Sistema Brasileiro de Classificação de Solos*. 5. ed. Embrapa, 2018. ❌ Citação de memória. "Arenosa" foi aproximada como areia − argila ≥ 70% (REVISAR AGRÔNOMO). |
| **Declividade** | Método de Horn (janela 3x3): HORN, B. K. P. Hill shading and the reflectance map. *Proceedings of the IEEE*, v. 69, n. 1, 1981. ❌ Citação de memória. |

### 1.9 FAO-56: ET0, água disponível e dias que a lavoura aguenta

ALLEN, R. G.; PEREIRA, L. S.; RAES, D.; SMITH, M. *Crop evapotranspiration: guidelines for computing crop
water requirements*. FAO Irrigation and Drainage Paper 56. Roma: FAO, 1998.
<https://www.fao.org/4/x0490e/x0490e00.htm>

| Onde | O quê |
|---|---|
| `analytics/agua.py` | Ra pela latitude e dia do ano (eq. 21), ET0 de Hargreaves (eq. 52), TAW = CAD x Zr (eq. 82), RAW = p x TAW (eq. 83), Ks e balanço de um reservatório (cap. 8). Teste: Ra do exemplo 8 (20° S, 3/set = 32,2 MJ m⁻² dia⁻¹). |
| `config/agua.yaml` | Kc (tabela 12), Zr e p (tabela 22), fases (tabela 11) de milho, caupi e sorgo; "pastagem extensiva" para o buffel. `# CONFERIR` |

HARGREAVES, G. H.; SAMANI, Z. A. Reference crop evapotranspiration from temperature. *Applied Engineering
in Agriculture*, v. 1, n. 2, p. 96-99, 1985. ❌ Citação de memória (a FAO-56 reproduz a equação).

---

## 2. Métodos avaliados e não adotados

### 2.1 Liebmann & Marengo (2001) / Liebmann et al. (2007): anomalia acumulada

| | |
|---|---|
| **Citação** | LIEBMANN, B.; MARENGO, J. A. Interannual variability of the rainy season and rainfall in the Brazilian Amazon Basin. *Journal of Climate*, v. 14, 2001. LIEBMANN, B. et al. Onset and end of the rainy season in South America in observations and the ECHAM 4.5 atmospheric general circulation model. *Journal of Climate*, v. 20, 2007. |
| **Acesso** | <https://www.ldeo.columbia.edu/~suzana/papers/liebmann_etal_jclim.pdf> |
| **O que diz** | Início da estação = dia do mínimo da curva A(d) = Σ (chuva diária − média anual). |
| **Por que não usamos** | Testado com a chuva do NASA POWER (análise exploratória de 14/11/2026). Ano a ano no semiárido, nos anos secos o mínimo cai no fim da janela e o desvio-padrão passou de 100 dias, contra 26-43 dias do critério de Sivakumar. Serve para a média de longo prazo, não para o atraso de cada ano. |
| **Conferido** | ❌ Volume e páginas não conferidos. |

### 2.2 Contexto regional

| | |
|---|---|
| **Citação** | SPARACINO, J.; ARGIBAY, D. S.; ESPINDOLA, G. Long-term (35 years) rainy and dry season characterization in semiarid Northeastern Brazil. *Revista Brasileira de Meteorologia*, 2021. DOI: 10.1590/0102-77863630138. |
| **Acesso** | <https://www.scielo.br/j/rbmet/a/wnJMXG9LspR78p3wtddZWNm/?lang=en> |
| **Uso** | Só contexto: aplica anomalia acumulada a séries diárias do semiárido nordestino e mostra que o fim da estação varia mais que o início. Não está no código. |
| **Conferido** | Título e DOI vieram de busca. Falta ler o artigo. |

---

## 3. Bases de dados usadas

### 3.1 NASA POWER: chuva diária (`PRECTOTCORR`)

| | |
|---|---|
| **Quem é a fonte** | NASA Langley Research Center, projeto POWER (Prediction Of Worldwide Energy Resources). |
| **Site / documentação** | <https://power.larc.nasa.gov/> · <https://power.larc.nasa.gov/docs/> |
| **Endpoint usado** | `GET https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR&community=AG&longitude={lon}&latitude={lat}&start=AAAAMMDD&end=AAAAMMDD&format=JSON` |
| **Versão da API** | POWER Daily API v2.10.3, segundo o cabeçalho da resposta em 14/11/2026. |
| **O que tem** | Precipitação total corrigida, em mm/dia, por dia, no horário local (LST). Valor ausente = `-999`. Cobre 1981 até ~3 dias atrás. |
| **Origem do dado** | Reanálise **MERRA-2** no histórico (cabeçalho `"sources": ["MERRA2"]`) e **MERRA-2 + GEOS-IT** no trecho recente. A chuva do MERRA-2 é corrigida com produtos de pluviômetro. Ver Reichle et al. (2017) abaixo. |
| **Resolução** | Grade do MERRA-2, ~0,5° × 0,625° (~50 km). |
| **Onde usamos** | `src/crop_optimizer/ingestion/rain_history.py` → `fetch_rain_series()`. Parâmetros em `config/chuva.yaml` (`nasa_power`). |
| **Cache local** | `data/bronze/nasa_power/<local>_PRECTOTCORR_<inicio>_<fim>.json` (resposta original). |
| **Agradecimento pedido pela NASA** | "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program." |
| **Conferido** | Endpoint, parâmetros, unidades, fill value e fontes conferidos nas respostas reais. Texto de agradecimento de memória: conferir no site. |

Referência da correção de chuva do MERRA-2:

| | |
|---|---|
| **Citação** | REICHLE, R. H. et al. Land surface precipitation in MERRA-2. *Journal of Climate*, v. 30, n. 5, p. 1643–1664, 2017. DOI: 10.1175/JCLI-D-16-0570.1. |
| **Conferido** | DOI, revista, volume e páginas conferidos por busca. |

Referência geral do MERRA-2 (a conferir): GELARO, R. et al. The Modern-Era Retrospective Analysis for
Research and Applications, Version 2 (MERRA-2). *Journal of Climate*, v. 30, 2017.
DOI: 10.1175/JCLI-D-16-0758.1. ❌ Não conferido.

### 3.2 ZARC: Tábua de Risco (MAPA / Embrapa)

| | |
|---|---|
| **Quem é a fonte** | Ministério da Agricultura e Pecuária (MAPA), Secretaria de Política Agrícola. A metodologia é da Embrapa, no Programa Nacional de Zoneamento Agrícola de Risco Climático. |
| **Conjunto de dados** | <https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico> |
| **Arquivo usado** | "Tábua de risco - Safra 2026/2027": `dados-abertos-tabua-de-risco-safra-2026-2027.csv`, atualizado no portal em 13/11/2026. <https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/139e5a60-1f43-4cc8-aeab-a35dbbf816c0/download/dados-abertos-tabua-de-risco-safra-2026-2027.csv> |
| **Dicionário de dados** | <https://dados.agricultura.gov.br/dataset/6d3d141c-885e-41a4-ab7f-dc8ff323b96f/resource/bebb0ebb-bc75-460c-b900-a7a1ebd87bee/download/dicionario-de-dados-tabua-de-risco-2026.pdf> (**ainda não baixado**) |
| **Licença** | Creative Commons Attribution, segundo o portal. |
| **O que tem** | CSV com `;`, UTF-8 com BOM, ~248 MB, 1.127.969 linhas. Cada linha é uma combinação cultura × município (`geocodigo` IBGE) × solo (`Cod_Solo`) × ciclo (`Cod_Ciclo`) × manejo (`Nome_Outros_Manejos`: Sequeiro/Irrigado), com a portaria (`Portaria`) e 36 colunas `dec1`..`dec36`. Cada coluna traz o risco de plantar naquele decêndio: `20`, `30`, `40` (%) ou `0` (não indicado). Decêndio 1 = 01-10/jan. |
| **Como é obtido** | **Download manual** (o portal derruba conexões de clientes automáticos). O arquivo fica intacto em `data/bronze/zarc/`. |
| **Onde usamos** | `src/crop_optimizer/ingestion/zarc_tabua.py` → `load_zarc_table()` e `zarc_windows_for()`; `analytics/rain_delay.py` → janelas por cultura na tela. Configuração em `config/zarc.yaml`. Recorte em `data/silver/zarc/`. |
| **Página do programa** | Manual do Gestor ZARC: <https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/documentos/ManualdoGestorZARCV1.1.pdf/@@download/file> |

Portarias da safra 2026/2027 que valem para os nossos municípios (manejo sequeiro):

| Município | Cultura | Portaria |
|---|---|---|
| Petrolina/PE | Feijão Caupi | Port. 131 de 26/05/2026 |
| Petrolina/PE | Sorgo Forrageiro | Port. 307 de 23/07/2026 |
| Quixadá/CE | Feijão Caupi | Port. 121 de 26/05/2026 |
| Quixadá/CE | Milho 1ª Safra | Port. 218 de 10/07/2026 |
| Quixadá/CE | Sorgo Forrageiro | Port. 297 de 23/07/2026 |
| Sousa/PB | Feijão Caupi | Port. 130 de 26/05/2026 |
| Sousa/PB | Milho 1ª Safra | Port. 227 de 10/07/2026 |
| Sousa/PB | Sorgo Forrageiro | Port. 306 de 23/07/2026 |
| Irecê/BA | Sorgo Forrageiro | Port. 296 de 23/07/2026 |

Petrolina e Irecê não têm "Milho 1ª Safra" em sequeiro, e Irecê não tem "Feijão Caupi". Ou seja, essas
combinações não são indicadas no zoneamento desta safra.

### 3.3 Códigos IBGE dos municípios

| | |
|---|---|
| **Fonte** | Coluna `geocodigo` da tábua do ZARC (código IBGE de 7 dígitos). |
| **Valores** | Petrolina 2611101 · Quixadá 2311306 · Sousa 2516201 · Irecê 2914604 |
| **Onde usamos** | `domain/presets.py` → `LocationSpec.ibge_code`. |

### 3.4 NASA GIBS: imagens das lentes (página Satélite)

| | |
|---|---|
| **Quem é a fonte** | NASA, Global Imagery Browse Services (GIBS), parte do EOSDIS/ESDIS. As mesmas imagens do NASA Worldview. |
| **Site / documentação** | <https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api> · Worldview: <https://worldview.earthdata.nasa.gov/> |
| **Catálogo usado** | GetCapabilities WMTS, EPSG:3857, "best": <https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities> |
| **O que tem** | Tiles PNG/JPEG prontos para mapa web, por camada e data. O catálogo traz nome, grade (zoom máximo nativo), períodos disponíveis e o modelo de URL de cada camada. Legendas oficiais em `https://gibs.earthdata.nasa.gov/legends/<colormap>_H.svg`. |
| **Acesso** | Público, sem login e sem chave. |
| **Onde usamos** | `src/crop_optimizer/ingestion/gibs.py` (catálogo, datas, URLs); `analytics/satellite_lenses.py`; `app/satellite_page.py`; configuração em `config/lentes.yaml`. |
| **Cache local** | `data/bronze/gibs/wmts_epsg3857_best_AAAAMMDD.xml` (um por dia). Os tiles são baixados pelo navegador, sem cache nosso. |
| **Agradecimento sugerido** | "We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS)." ❌ Texto de memória, conferir na documentação do GIBS. |
| **Conferido** | Nomes das camadas, períodos, modelos de URL e legendas conferidos no catálogo e com pedidos reais em 14/11/2026 (HTTP 200). |

Camadas usadas (identificador e título conforme o catálogo do GIBS). O produto de origem de cada uma é
**provável** e precisa ser conferido na página da camada no Worldview:

| Lente | Camada GIBS | Título no catálogo | Grade nativa | Produto de origem provável |
|---|---|---|---|---|
| Chuva | `IMERG_Precipitation_Rate` | Precipitation Rate (IMERG) | Level6 | GPM IMERG (NASA/JAXA), ~0,1° |
| Água no solo | `SMAP_L4_Analyzed_Root_Zone_Soil_Moisture` | Root Zone Soil Moisture (L4, 12z Instantaneous, Model Value-Added, SMAP) | Level6 | SMAP L4 (SPL4SMAU), 9 km |
| Verde da lavoura | `MODIS_Terra_L3_NDVI_16Day` | Vegetation Index (16-Day, MODIS, Terra) | Level9 | MOD13Q1, 250 m |
| Calor da terra | `MODIS_Terra_L3_Land_Surface_Temp_8Day_Day` | Land Surface Temperature (8-Day, Day, MODIS, Terra) | Level7 | MOD11A2, 1 km |
| Relevo | `SRTM_Color_Index` | Digital Elevation Model (Color Index, SRTM) | Level12 | SRTM (NASA/NGA, 2000), ~30 m |

### 3.5 Esri World Imagery: imagem de base do mapa

| | |
|---|---|
| **Quem é a fonte** | Esri, com imagens de Maxar, Earthstar Geographics e outros provedores. |
| **URL de tiles** | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |
| **Atribuição na tela** | "Imagem de base: Esri, Maxar, Earthstar Geographics" |
| **Onde usamos** | `app/satellite_page.py` (`_BASE_TILES`). |
| **Cuidado** | Serve só de fundo visual, sem nenhum cálculo. Revisar os termos de uso da Esri antes de qualquer uso comercial. |

### 3.6 OpenStreetMap Nominatim: município da coordenada

| | |
|---|---|
| **Quem é a fonte** | Fundação OpenStreetMap. Dados © OpenStreetMap contributors, licença ODbL 1.0. |
| **Endpoint** | `GET https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=..&lon=..&zoom=10&addressdetails=1&accept-language=pt-BR` |
| **O que usamos da resposta** | `address.city` / `municipality` / `town` / `village` (nome do município) e `address["ISO3166-2-lvl4"]` (ex.: `BR-PE`). |
| **Regras de uso** | No máximo 1 pedido por segundo, User-Agent identificando o app (usamos um genérico, sem dados pessoais) e cache das respostas. <https://operations.osmfoundation.org/policies/nominatim/> |
| **Onde usamos** | `ingestion/geocode.py`; configuração em `config/localizacao.yaml`; cache em `data/bronze/nominatim/`. |

### 3.7 IBGE: API de localidades (código dos municípios)

| | |
|---|---|
| **Quem é a fonte** | Instituto Brasileiro de Geografia e Estatística (IBGE), serviço de dados. |
| **Endpoint** | `GET https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios` |
| **O que tem** | Lista oficial de municípios da UF, com `id` (código IBGE de 7 dígitos) e `nome`. |
| **Onde usamos** | `ingestion/geocode.py` (nome do OSM → código IBGE, comparando sem acentos); cache em `data/bronze/ibge/municipios_<UF>.json`. |
| **Documentação** | <https://servicodados.ibge.gov.br/api/docs/localidades> |

### 3.8 ISRIC SoilGrids 2.0: solo do ponto

| | |
|---|---|
| **Quem é a fonte** | ISRIC – World Soil Information (Holanda). |
| **Citação** | POGGIO, L. et al. SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty. *SOIL*, v. 7, p. 217-240, 2021. ❌ Citação de memória, conferir. |
| **Endpoint** | `GET https://rest.isric.org/soilgrids/v2.0/properties/query?lon=..&lat=..&property=clay&property=sand&property=silt&property=soc&property=nitrogen&property=phh2o&property=cec&property=bdod&depth=0-5cm&depth=5-15cm&depth=15-30cm&value=mean&value=Q0.05&value=Q0.95` |
| **O que tem** | Mapas globais de 250 m feitos por aprendizado de máquina com perfis de solo e camadas de satélite. Média e quantis 5%/95% por profundidade. Unidades: valor ÷ `d_factor` = unidade-alvo (argila e areia %, soc g/kg, nitrogênio g/kg, pH, cec cmol(c)/kg, bdod kg/dm³). Área urbana e água vêm sem valor. |
| **Como usamos** | Média ponderada 0-20 cm (5/10/5 cm); M.O. = soc/10 x 1,724; sem valor no ponto → ponto a 3 km nas 4 direções, com aviso. |
| **Onde no código** | `ingestion/soilgrids.py`; configuração em `config/aptidao.yaml` (`soilgrids`); cache em `data/bronze/soilgrids/`. |
| **Conferido** | ✅ Respostas reais em 14/11/2026 (Casa Nova, perto de Quixadá); sede de Petrolina sem valor (urbana). |

### 3.8b SoilGrids pelo WCS: solo da região (comparação)

| | |
|---|---|
| **Quem é a fonte** | ISRIC, os mesmos mapas do SoilGrids 2.0 (seção 3.8), pelo serviço de mapas OGC WCS. |
| **Por que WCS** | A API REST tem política de uso justo de **5 chamadas por minuto** (<https://rest.isric.org/>; FAQ <https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_02.html>). O WCS devolve o recorte de uma área inteira em uma chamada por camada. |
| **Endpoint** | `https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID={prop}_{prof}_mean&FORMAT=GEOTIFF_INT16&SUBSET=long(..)&SUBSET=lat(..)&SUBSETTINGCRS=EPSG:4326&OUTPUTCRS=EPSG:4326` |
| **O que usamos** | clay, sand, soc, phh2o, nitrogen, cec em 0-5/5-15/15-30 cm, num quadrado de ±0,25° (~55 km); média 0-20 cm; valor 0 = sem dado. |
| **Onde no código** | `ingestion/soilgrids_wcs.py`; tela em `app/home_page.py` ("Como é o solo daqui"); cache em `data/bronze/soilgrids_wcs/`. |
| **Conferido** | ✅ As 6 camadas responderam em ~1 s (14/11/2026); GeoTIFF int16 lido com o Pillow. |

### 3.9 Terrain Tiles (AWS Open Data): altitude e declividade

| | |
|---|---|
| **Quem é a fonte** | Terrain Tiles da Tilezen/Mapzen, hospedados no AWS Open Data; entre as fontes está o **SRTM** (NASA). |
| **Endpoint** | `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` (sem chave). Página: <https://registry.opendata.aws/terrain-tiles/> |
| **O que tem** | PNG com a altitude codificada: altitude = R x 256 + G + B/256 − 32768 (m). Usamos zoom 12 (~38 m por pixel no equador). |
| **Onde no código** | `ingestion/terrain.py`; cache em `data/bronze/terrain_tiles/`. |
| **Atribuição** | As fontes e licenças de cada dado estão na página do dataset. Falta registrar o texto de atribuição exigido. |
| **Conferido** | ✅ Tile real em 14/11/2026 (Casa Nova: 398 a 489 m no tile). |

### 3.10 NASA POWER: temperatura do ar (`T2M_MAX`, `T2M_MIN`)

| | |
|---|---|
| **Quem é a fonte** | NASA POWER (MERRA-2/GEOS-IT), a mesma API da chuva (seção 3.1). |
| **O que tem** | Temperatura máxima e mínima diária a 2 m, °C, desde 1981; -999 = sem dado. |
| **Onde no código** | `ingestion/power_temperature.py` -> ET0 de Hargreaves em `analytics/agua.py`; cache em `data/bronze/nasa_power/`. |
| **Conferido** | ✅ Petrolina, Quixadá e Sousa em 15/11/2026 (ET0 média de 5,4 a 5,7 mm/dia). |

### 3.11 NASA GIBS: valor da camada no ponto (cor do pixel -> legenda)

| | |
|---|---|
| **Endpoint da imagem** | `https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=<camada>&CRS=EPSG:4326&BBOX=<s,w,n,e>&WIDTH=9&HEIGHT=9&FORMAT=image/png&TIME=<data>` (sem login). Com 1x1 pixel o GIBS devolve transparente; com 9x9, lemos o pixel do meio. |
| **Legenda** | `https://gibs.earthdata.nasa.gov/colormaps/v1.3/<colormap>.xml`: cada cor com a faixa de valor e a unidade. |
| **Camadas usadas** | `SMAP_L4_Analyzed_Root_Zone_Soil_Moisture` (m³/m³, 2015-), `MODIS_Terra_L3_NDVI_16Day` (2000-), `MODIS_Terra_L3_Land_Surface_Temp_8Day_Day` (K, 2000-). |
| **Onde no código** | `ingestion/gibs_values.py` -> `analytics/lens_insights.py`; cache em `data/bronze/gibs_colormaps/` e `data/bronze/gibs_pixels/`. |
| **Alternativa avaliada** | ORNL DAAC MODIS/VIIRS Subsets API (`https://modis.ornl.gov/rst/api/v1/`), sem login, com o valor exato e também o SMAP L3 (`SPL3SMP_E`). Ficou de fora por levar ~50 s por consulta. |
| **Conferido** | ✅ Petrolina em 15/11/2026: SMAP 0,073 m³/m³ (10/nov), NDVI 0,25 (16/out), LST 313,7 K (26/fev/2020). |

### 3.12 MapBiomas (avaliado, não usado)

Cobertura anual (Coleção 8) e Solo (carbono, Coleção 3). O endereço público
`storage.googleapis.com/mapbiomas-public/.../brasil_coverage_2022.tif` devolveu **403** em 15/11/2026, e
listar o bucket pede login (401). Ler GeoTIFF exigiria `rasterio`, fora da lista de dependências. Além disso,
a classificação ano a ano não distingue um pousio curto de pasto, então "anos sem descanso" não se sustenta.

---

## 4. Bases de dados candidatas (ainda não usadas)

| Base | Quem | Link | Por que interessa | Situação |
|---|---|---|---|---|
| CHIRPS | Climate Hazards Center (UCSB) | <https://www.chc.ucsb.edu/data/chirps> | Satélite + estações, ~5 km, muito usado no semiárido. Serviria para conferir as datas do POWER. | Versão final sai uns 45 dias depois. Acesso por ponto via API ClimateSERV ainda não testado. |
| GPM IMERG | NASA | <https://gpm.nasa.gov/data/imerg> | Satélite "puro", atraso de horas. | Exige login no NASA Earthdata. |
| Normais Climatológicas 1991-2020 | INMET | <https://portal.inmet.gov.br/normais> | Chuva mensal e de 10 em 10 dias por estação oficial. Serviria para validar o POWER. | Não achamos CSV para download direto. |
| ECOSTRESS (ECO_L3T_JET / ECO_L4T_ESI) | NASA LP DAAC | <https://cmr.earthdata.nasa.gov/search/concepts/C4057232489-LPCLOUD.html> | Evapotranspiração e estresse hídrico a ~70 m. Está no mock ("Calor da terra"). | Não está no GIBS; exige Earthdata Login. |
| HLS L30/S30 (Landsat + Sentinel-2) | NASA LP DAAC | <https://www.earthdata.nasa.gov/data/catalog/lpcloud-hlsl30-2.0> | Foto de 30 m a cada poucos dias. Está no mock ("Verde da lavoura"). | Está no GIBS (`HLS_*_Nadir_BRDF_Adjusted_Reflectance`), mas cada dia só cobre a faixa de uma passagem. Falta escolher a data com imagem sem nuvem. |
| SMAP L3 Enhanced 9 km (SPL3SMP_E) | NASA NSIDC DAAC | <https://nsidc.org/data/spl3smp_e/versions/6> | Umidade da superfície medida pelo satélite. | No GIBS, com falhas entre órbitas. Usamos o L4 (sem falhas). |
| GRACE/GRACE-FO Mascon | NASA PO.DAAC / JPL | <https://podaac.jpl.nasa.gov/dataset/TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4> | Água subterrânea da região (~300 km), mensal. | No GIBS só até 07/2022. |
| API Agritec (ZARC) | Embrapa AgroAPI | <https://www.agroapi.cnptia.embrapa.br/portal/assets/docs/agritec.pdf> | ZARC por API, com cultivares indicadas. | Precisa de cadastro; grátis até um limite. |

GRACE/GRACE-FO e o SMAP L3 Enhanced vieram de um catálogo não oficial
(<https://spacedata.swapniltamse.com/challenges/field-shift-adapting-farms/>) e **não constam na lista
oficial abaixo**. Ficam só como candidatos.

### 4.1 Recursos oficiais do desafio × o que usamos

Fonte: aba "Resources" do desafio *Field Shift: Adapting Farms with NASA Data*,
<https://www.spaceappschallenge.org/2026/challenges/adapting-farms-with-nasa-data/?tab=resources>
(conteúdo colado pela equipe em 14/11/2026; o site não abriu daqui por um erro de certificado SSL).

A NASA avisa na página que não endossa entidades fora do governo dos EUA e que, em sites de terceiros,
valem os termos de uso de cada site.

**NASA Data & Resources**

| Recurso oficial | Cobertura | No projeto | Observação |
|---|---|---|---|
| SMAP (umidade do solo) | Global | ✅ Lente **Água no solo** (SMAP L4, zona das raízes, via GIBS) | O texto oficial fala da umidade de superfície medida a cada 2-3 dias (L3). Usamos o L4 para o mapa não ficar com faixas vazias entre as órbitas. |
| GPM & IMERG (chuva) | Global | ✅ Lente **Chuva** (IMERG diário via GIBS) | Candidato a conferir o NASA POWER no cálculo do atraso. |
| Landsat e MODIS/VIIRS (refletância, NDVI) | Global | ✅ Lentes **Verde da lavoura** (MODIS NDVI 250 m) e **Calor da terra** (MODIS LST 1 km) | Landsat de 30 m (HLS) ainda pendente. |
| NASA POWER | Global | ✅ **Atraso da chuva** e chuva do mês no ponto | Temperatura e radiação para ET0 (Hargreaves, CLAUDE.md §5.1) ainda não usadas. |
| SRTM (relevo) | Global | ✅ Lente **Relevo** e **declividade** no perfil do local (fator erosão) | Via Terrain Tiles (AWS). |
| ECOSTRESS (LST e ET) | Global | ⏳ Candidato | Não está no GIBS; exige Earthdata Login. O mock usa em "Calor da terra". |
| NLDAS / GLDAS | NLDAS: EUA · GLDAS: global | ⏳ GLDAS candidato | Umidade e evapotranspiração contínuas para validar o balanço hídrico. |
| FAO GAEZ | Global | ⏳ Candidato forte | Aptidão por cultura (milho, sorgo, caupi) para embasar as 3 rotações. |
| GEDI (biomassa e dossel) | Global, faixa tropical incluída | ➖ Pouco útil | Feito para vegetação alta; caatinga e roçado são baixos. |
| USDA Ag Data Commons | EUA | ❌ Não se aplica | Equivalente sugerido: dados abertos MAPA/Embrapa (já usamos o ZARC). |
| Web Soil Survey (NRCS) | EUA | ❌ Não se aplica | **Usamos o SoilGrids** (global, Feature 3). PronaSolos / Embrapa Solos fica como candidato. |
| Cropland Data Layer (CropScape) | EUA | ❌ Não se aplica | Equivalente sugerido: MapBiomas (uso e cobertura, 30 m, anual). |
| PRISM | EUA | ❌ Não se aplica | Equivalente sugerido: Normais Climatológicas do INMET. |
| SSURGO / STATSGO2 | EUA | ❌ Não se aplica | **Usamos o SoilGrids** (Feature 3); PronaSolos candidato. |
| NAIP (foto aérea de 1 m) | EUA | ❌ Não se aplica | A imagem de base Esri cumpre o papel visual. |
| NLCD (cobertura do solo) | EUA | ❌ Não se aplica | Equivalente sugerido: MapBiomas. |
| CoCoRaHS (pluviômetros voluntários) | América do Norte | ❌ Não se aplica | Equivalente sugerido: postos do INMET, da ANA e de órgãos estaduais (FUNCEME, APAC, AESA, INEMA). |
| USGS NWIS (água) | EUA | ❌ Não se aplica | Equivalente sugerido: ANA Hidroweb. |
| USDA AMS Market News (preços) | EUA | ❌ Não se aplica | Equivalente sugerido: CONAB (hoje os preços do app são fixos, ver seção 5). |
| USDA NASS QuickStats (produção) | EUA | ❌ Não se aplica | Equivalente sugerido: IBGE PAM via SIDRA, tabela 5457 (já prevista no CLAUDE.md para validação). |
| OpenET | Oeste dos EUA | ❌ Não se aplica | — |
| USFS LANDFIRE | EUA | ❌ Não se aplica | Equivalente sugerido: MapBiomas. |

**Space Agency Partner Resources**

| Recurso oficial | Cobertura | No projeto | Observação |
|---|---|---|---|
| Copernicus Sentinel-2 (ESA) | Global | ⏳ Candidato | NDVI de 10 m, o que o mock pedia em "Verde da lavoura". Acesso via Copernicus Data Space (conta gratuita). |
| ERA5 (ECMWF) | Global | ⏳ Candidato | Reanálise para conferir a chuva e a temperatura do NASA POWER. |

Os equivalentes brasileiros são **sugestões da equipe**. Ainda não foram baixados nem conferidos.

---

## 5. Valores sem fonte no código

Estes valores estão no sistema **sem referência**. Não apresente como fato até achar uma fonte ou trocar
por cálculo.

| Onde | O quê |
|---|---|
| `domain/presets.py` | Coordenadas dos municípios: falta conferir com o IBGE. |
| `domain/presets.py` | `rainy_season_start_doy` (não é mais usado no atraso; ainda alimenta o falso `EmbrapaZarcSource` e o AppEEARS sintético). |
| `domain/presets.py` | Parâmetros das culturas (produtividade, sensibilidade à seca, preços, custos). |
| `config/aptidao.yaml` | Tudo marcado `# REVISAR AGRÔNOMO`: exigências das culturas, tabelas de grau, solo típico do semiárido, N disponível (ver seção 1.7). |
| `engine/markov_soil.py` | Matrizes de transição e metas de M.O./N por estado. Desde a Feature 3, o multiplicador por estado só age como **mudança relativa** ao estado de hoje. |
| `engine/monte_carlo.py` | Coeficientes de `_delay_and_veranico_penalty` (como o atraso vira perda de produtividade). |
| `ingestion/nasa_power.py` | Perfis do clima sintético (`_REGIONAL_CLIMATE_PROFILE`). |
| `ingestion/embrapa_zarc.py` | Janelas "ZARC" geradas (não são o ZARC). |
| `config/chuva.yaml` | Limiares de Sivakumar aplicados ao semiárido brasileiro sem calibração local (`# CONFERIR`). |
| `config/colheita.yaml` | Régua da quebra de safra: colher menos da metade do normal (REVISAR AGRÔNOMO). |
| `config/agua.yaml` | Parâmetros do buffel e da palma, NDVI de vegetação seca (0,30), limite de 40 °C na floração. |
| `config/lentes.yaml` | Textos do risco de enxurrada por classe de relevo (REVISAR AGRÔNOMO). |
| `domain/presets.py` | Preços e custos usados na **Renda** (não são cotação). |

---

## 6. Inspiração de código e design

### 6.1 Identidade visual

| Item | Origem | Licença / observação |
|---|---|---|
| Logo, ícone, mascote (5 poses) e paleta | Pranchas da marca Acauã, criadas pela equipe (14/11/2026); recortes em `src/crop_optimizer/app/assets/marca/` | Da equipe. Falta a versão em vetor (SVG). |
| Montserrat, Inter, IBM Plex Mono | Google Fonts (<https://fonts.google.com>), carregadas pelo tema do Streamlit | SIL Open Font License 1.1 |
| Contraste mínimo 4,5:1 para texto | WCAG 2.1, critério 1.4.3 (<https://www.w3.org/TR/WCAG21/#contrast-minimum>) | Conferido em `tests/test_identidade_visual.py` |
| Capturas de tela para verificar o visual | Playwright (Chromium headless), instalado fora do projeto | Ferramenta local; não é dependência do app |

### 6.2 Código e padrões

| Projeto | O que aproveitamos | Licença |
|---|---|---|
| God's Eye View (repositório local `../gods-eye-view`, de Bilawal Sidhu) | Só **padrões**, sem copiar código: (1) cada camada mostra seu estado (atual, mais recente, fixo, sem dado); (2) atribuição de cada fonte na tela e num documento de fontes (o `DATA_SOURCES.md` deles inspirou esta seção 3). | MIT (código). Os dados de lá têm licenças próprias e não foram usados. |
| Mock "O que o satélite vê na sua roça" (equipe) | Layout da página Satélite: lentes à esquerda, mapa com a roça, ano embaixo, cartões à direita. | Interno |

