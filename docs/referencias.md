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
| SRTM (relevo) | Global | ✅ Lente **Relevo** | Declividade e risco de erosão: candidato. |
| ECOSTRESS (LST e ET) | Global | ⏳ Candidato | Não está no GIBS; exige Earthdata Login. O mock usa em "Calor da terra". |
| NLDAS / GLDAS | NLDAS: EUA · GLDAS: global | ⏳ GLDAS candidato | Umidade e evapotranspiração contínuas para validar o balanço hídrico. |
| FAO GAEZ | Global | ⏳ Candidato forte | Aptidão por cultura (milho, sorgo, caupi) para embasar as 3 rotações. |
| GEDI (biomassa e dossel) | Global, faixa tropical incluída | ➖ Pouco útil | Feito para vegetação alta; caatinga e roçado são baixos. |
| USDA Ag Data Commons | EUA | ❌ Não se aplica | Equivalente sugerido: dados abertos MAPA/Embrapa (já usamos o ZARC). |
| Web Soil Survey (NRCS) | EUA | ❌ Não se aplica | Equivalente sugerido: PronaSolos / Embrapa Solos; SoilGrids (global, já previsto no CLAUDE.md). |
| Cropland Data Layer (CropScape) | EUA | ❌ Não se aplica | Equivalente sugerido: MapBiomas (uso e cobertura, 30 m, anual). |
| PRISM | EUA | ❌ Não se aplica | Equivalente sugerido: Normais Climatológicas do INMET. |
| SSURGO / STATSGO2 | EUA | ❌ Não se aplica | Equivalente sugerido: PronaSolos; SoilGrids. |
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
| `engine/monte_carlo.py` | Coeficientes de `_delay_and_veranico_penalty` (como o atraso vira perda de produtividade). |
| `ingestion/nasa_power.py` | Perfis do clima sintético (`_REGIONAL_CLIMATE_PROFILE`). |
| `ingestion/embrapa_zarc.py` | Janelas "ZARC" geradas (não são o ZARC). |
| `config/chuva.yaml` | Limiares de Sivakumar aplicados ao semiárido brasileiro sem calibração local (`# CONFERIR`). |

---

## 6. Inspiração de código e design

| Projeto | O que aproveitamos | Licença |
|---|---|---|
| God's Eye View (repositório local `../gods-eye-view`, de Bilawal Sidhu) | Só **padrões**, sem copiar código: (1) cada camada mostra seu estado (atual, mais recente, fixo, sem dado); (2) atribuição de cada fonte na tela e num documento de fontes (o `DATA_SOURCES.md` deles inspirou esta seção 3). | MIT (código). Os dados de lá têm licenças próprias e não foram usados. |
| Mock "O que o satélite vê na sua roça" (equipe) | Layout da página Satélite: lentes à esquerda, mapa com a roça, ano embaixo, cartões à direita. | Interno |

