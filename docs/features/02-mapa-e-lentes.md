# Feature 2 — Local da roça no mapa e lentes de satélite

**Status:** implementada na branch `feature/mapa-e-lentes` (criada a partir de `feature/atraso-da-chuva`),
aguardando validação da equipe.
**Data:** 14/11/2026

## Objetivo

1. O usuário indica a **latitude e longitude da roça** (digitando ou clicando no mapa).
2. Uma página nova, **"Satélite"**, com barra de navegação no topo, mostra **lentes** com os dados de
   satélite da NASA sobre o mapa, seguindo o mock "O que o satélite vê na sua roça".
3. O ponto escolhido passa a valer também para o **atraso da chuva e as janelas do ZARC** (Feature 1).

---

## Como era antes

- O app tinha **uma página só**, com abas, e o local era um **selectbox com 4 municípios fixos**
  (Petrolina, Quixadá, Sousa, Irecê).
- Não havia mapa nem camadas de satélite na interface.
- O cálculo da chuva e do ZARC só funcionava para esses 4 municípios.
- O recorte do ZARC na silver era regravado só com os municípios pedidos na hora.

## Decisões tomadas com o time

| Pergunta | Decisão |
|---|---|
| O que o ponto da roça controla? | **Chuva + ZARC** usam o ponto. O Monte Carlo continua com o clima de exemplo do município pré-cadastrado mais próximo, com aviso na tela. |
| Lentes do mock que o GIBS não tem (NDVI de Sentinel-2/Landsat, ECOSTRESS) | Usar **o que o GIBS tem**: NDVI e temperatura da superfície do **MODIS**, com o rótulo da fonte correta. Todas as 5 lentes usam dados da lista oficial de recursos do desafio (ver referências, seção 4.1). |
| Navegação | **Plantio** (o dashboard que já existia, sem mudar o conteúdo) + **Satélite** (nova). |
| Visual escuro do mock | **Fica para o passo 9** (estilo visual final). A página usa o visual padrão do Streamlit. |

## Reaproveitado do repositório "God's Eye View"

O God's Eye View é um globo 3D em JavaScript (Cesium + Google 3D Tiles), então o código não serve para
o nosso app em Streamlit. Trouxemos dois **padrões**:

- **Estado visível de cada camada:** a lente sempre diz o que está mostrando: imagem da data pedida, a
  mais recente (quando a data ainda não tem imagem), dado fixo, ou "sem imagem" (antes do início da
  série ou em falha dela). Nunca mostra uma camada vazia sem explicar.
- **Atribuição por fonte, na tela e no documento:** linha de créditos no rodapé da página e cada fonte
  registrada em [referencias.md](../referencias.md).

---

## O que mudou

### 1. Navegação
- `app/dashboard.py`: `main()` agora monta `st.navigation(..., position="top")` com as páginas
  **Plantio** (`plantio_page`, o conteúdo de antes) e **Satélite** (`app/satellite_page.py`).
  O comando para rodar continua o mesmo.

### 2. Escolher a roça
- Na página Satélite, em "📍 Onde fica a sua roça?":
  - latitude e longitude digitadas (com dica: no Nordeste as duas são negativas);
  - **clique no mapa** preenche as coordenadas;
  - atalhos para os 4 municípios de exemplo;
  - botão **"Usar este ponto"** confirma.
- Ao confirmar, `ingestion/geocode.py` descobre o **município, a UF e o código IBGE**:
  1. geocodificação reversa do **OpenStreetMap (Nominatim)**, no nível de município;
  2. **lista oficial de municípios do IBGE** da UF, comparando o nome sem acentos.
  - Fora do Brasil: erro na tela. Sem município ou sem código: a roça é salva assim mesmo (a chuva
    funciona) e a tela avisa que o ZARC não vai aparecer.
- A roça fica na sessão (`app/state.py`) e é compartilhada entre as páginas.
- `domain/roca.py`: `Roca` (ponto + município) → `LocationSpec` para os cálculos, e
  `nearest_preset()` (distância em linha reta) para escolher o clima de exemplo do Monte Carlo.

### 3. Página Plantio com a roça
- Barra lateral: com roça escolhida mostra "📍 Sua roça: Município/UF (lat, lon)", um botão para voltar aos
  municípios de exemplo e um link para trocar no mapa. Sem roça, continua o seletor de exemplos.
- **Chuva e ZARC** são calculados no ponto da roça (NASA POWER na coordenada; ZARC do município achado).
- Logo abaixo, um aviso: "Daqui para baixo, a simulação usa o clima de exemplo de <município mais perto>
  (a X km). Só a chuva e a janela do ZARC acima são do ponto da sua roça."

### 4. Lentes (NASA GIBS)
Camadas WMTS do GIBS, sem login, sobre a imagem de base Esri World Imagery:

| Lente | Fonte | Camada GIBS | Quadrado | Desde | Cada imagem |
|---|---|---|---|---|---|
| Chuva | GPM IMERG | `IMERG_Precipitation_Rate` | ~10 km | 2000 | 1 dia |
| Água no solo | SMAP (L4, zona das raízes) | `SMAP_L4_Analyzed_Root_Zone_Soil_Moisture` | ~9 km | 2015 | 1 dia |
| Verde da lavoura | MODIS Terra (NDVI) | `MODIS_Terra_L3_NDVI_16Day` | 250 m | 2000 | 16 dias |
| Calor da terra | MODIS Terra (temperatura da superfície, dia) | `MODIS_Terra_L3_Land_Surface_Temp_8Day_Day` | 1 km | 2000 | 8 dias |
| Relevo | SRTM | `SRTM_Color_Index` | ~30 m | fixo (2000) | — |

- **Ano (slider) + mês:** a data pedida é o dia 15 do mês e ano escolhidos (no máximo hoje).
  `ingestion/gibs.py` encaixa essa data na imagem que existe: o dia, a composição de 8/16 dias que a
  contém, a mais recente ou "sem imagem".
- **Mapa:** marcador da roça, mais um **quadrado tracejado do tamanho de um pixel da lente** em volta dela,
  para mostrar que a roça cabe num quadrado só. Os tiles são ampliados além do zoom nativo
  (`maxNativeZoom`), então dá para ver os pixels de verdade.
- **Painel da direita**, como no mock: "Esta lente", "Tamanho de cada quadrado", a **legenda oficial de
  cores do GIBS** e "O que o satélite não vê".
- **Chuva do mês no ponto (lente Chuva):** total do mês escolhido e média de 1991-2020, do NASA POWER
  (a mesma fonte do atraso da chuva).
- O GetCapabilities do GIBS (~6 MB) fica em cache diário em `data/bronze/gibs/`. Os nomes e períodos das
  camadas vêm dele, e não de valores fixos no código.

### 5. Ajustes de dados
- `ingestion/zarc_tabua.py`: o recorte da silver agora **acumula** os municípios já lidos (arquivo
  `*.codigos.json` ao lado). Um município novo dispara uma única releitura do CSV; um município sem
  linhas na tábua não faz reler de novo.
- Novos caches por fonte: `data/bronze/gibs/`, `data/bronze/nominatim/`, `data/bronze/ibge/`.

### 6. Configuração
- `config/lentes.yaml`: lentes (nome, fonte, camada, legenda, textos, tamanho do pixel, zoom) e URL do
  GetCapabilities. Os recursos do desafio que **não** viraram lente estão listados no fim, com o motivo.
- `config/localizacao.yaml`: Nominatim (URL, user-agent genérico, zoom), API do IBGE, caixa do Brasil.
- Dependências novas: `folium` e `streamlit-folium` (constam na lista permitida do CLAUDE.md).

### Arquivos

| Arquivo | Mudança |
|---|---|
| `src/crop_optimizer/app/satellite_page.py` | novo: página Satélite |
| `src/crop_optimizer/app/state.py` | novo: roça na sessão |
| `src/crop_optimizer/analytics/satellite_lenses.py` | novo: estado da lente, pixel, chuva do mês |
| `src/crop_optimizer/ingestion/gibs.py` | novo: catálogo, datas e URLs do GIBS |
| `src/crop_optimizer/ingestion/geocode.py` | novo: coordenada → município/UF/IBGE |
| `src/crop_optimizer/domain/roca.py` | novo: `Roca`, distância, município de exemplo mais perto |
| `src/crop_optimizer/app/dashboard.py` | navegação no topo; Plantio usa a roça |
| `src/crop_optimizer/ingestion/zarc_tabua.py` | recorte acumulativo |
| `config/lentes.yaml`, `config/localizacao.yaml` | novos |
| `tests/test_mapa_lentes.py` | 12 testes novos |
| `pyproject.toml` | `folium`, `streamlit-folium` |

---

## Exemplos verificados

| Situação | Resultado |
|---|---|
| Ponto rural (-9.05, -40.90) | Casa Nova/BA, IBGE 2907202. A chuva firma por volta de 01/fev. ZARC: caupi e sorgo com janela até 28/fev; milho sem indicação. Simulação com o clima de Petrolina (58 km). |
| Coordenada na Espanha (40, -3) | "Essa coordenada fica fora do Brasil." |
| Água no solo, março de 2010 | "Sem imagem de Água no solo em março de 2010: essa série começa em 31/03/2015." |
| Verde da lavoura, novembro de 2026 | "Ainda não há imagem para essa data. Mostrando a mais recente, de 16/10 a 31/10/2026." |
| Relevo, qualquer ano | "Relevo: dado fixo, não muda com o ano." |

Tiles de todas as lentes, imagem de base e as 5 legendas responderam HTTP 200 em 14/11/2026.

## Como testar

```bash
source .venv/bin/activate
pytest tests/test_mapa_lentes.py
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
```

Abra a aba **Satélite**, clique no mapa ou digite um ponto, aperte **Usar este ponto**, troque lente,
ano e mês, depois volte em **Plantio**.

---

## Limitações conhecidas

- **Chuva de um dia (IMERG):** a lente mostra a chuva do dia 15 do mês, que muitas vezes é zero. O GIBS não
  tem acumulado mensal do IMERG. O total do mês vem do NASA POWER, no painel.
- **Água no solo usa o SMAP L4 (modelo + satélite),** não o L3, que é a superfície medida a cada 2-3 dias
  descrita nos recursos do desafio. O L3 tem falhas entre as órbitas e deixaria buracos no mapa.
- **Verde e calor são do MODIS** (250 m e 1 km), não do Sentinel-2/Landsat nem do ECOSTRESS do mock.
- **Relevo do SRTM é de 2000.**
- **Monte Carlo:** continua com o clima sintético do município de exemplo mais perto, mesmo com a roça
  marcada (aviso na tela).
- **Município pelo OpenStreetMap:** depende do cadastro do OSM. Um ponto na divisa pode cair no município
  vizinho.
- **Imagem de base Esri:** usada com atribuição. Antes de qualquer uso comercial, revisar os termos da Esri.
- **Visual:** padrão do Streamlit. O tema escuro do mock fica para o passo 9.

## Pendências

- [ ] Lente HLS (Landsat + Sentinel-2, 30 m): escolher automaticamente a data com imagem sem nuvem.
- [ ] ECOSTRESS via Earthdata Login (conta gratuita): está na lista oficial e no mock.
- [ ] NDVI de 10 m do Sentinel-2 (recurso parceiro da ESA, Copernicus Data Space): o mock pedia.
- [ ] Valor numérico no ponto para as outras lentes (hoje só a chuva tem número).
- [ ] Estilo visual do mock (paleta e fontes do Acauã).
- [ ] Separar Plantio em Plantio / Rotações / Painel completo, como no mock.
