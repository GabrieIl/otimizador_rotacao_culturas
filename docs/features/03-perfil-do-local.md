# Feature 3 — Perfil do local e limitação do solo por cultura

**Status:** implementada na branch `feature/perfil-do-local` (a partir da `main` com as Features 1 e 2),
aguardando validação. **Os valores agronômicos precisam de revisão de agrônomo** (ver abaixo).
**Data:** 14/11/2026

## Objetivo

1. Nova página inicial **"Início"** com o resumo do local: chuva, solo, relevo e janelas do ZARC.
2. **Solo pelos dados de satélite/mapa** (SoilGrids, SRTM), com **ajuste por análise de campo** para quem tiver.
3. A "condição do solo" deixa de ser uma só e passa a ser **por cultura**: o mesmo solo pode ser bom para o
   feijão-caupi e crítico para o milho.
4. O Monte Carlo passa a usar esse resultado. O seletor manual "Condição Atual do Solo" sai.

---

## Como era antes

- Na barra lateral da Plantio havia um seletor **"Condição Atual do Solo"** com 5 opções (Crítico,
  Degradado, Equilibrado, Fértil, Regenerativo).
- Cada estado tinha um multiplicador de produtividade fixo (0,72 a 1,15), aplicado **igual a todas as
  culturas** (`engine/markov_soil.py`, `STATE_YIELD_MULTIPLIER`).
- A matéria orgânica (2,2%) e o nitrogênio (55 kg/ha) iniciais eram **fixos**, sem relação com o estado
  escolhido. "Crítico" começava com a mesma matéria orgânica de "Fértil".
- Nenhum número tinha fonte. Não havia dado de solo do local.

---

## O que mudou

### 1. Navegação
`Início` (nova, padrão) · `Plantio` · `Satélite`. O local é o mesmo nas três: a roça marcada no mapa ou o
município de exemplo escolhido (seletor compartilhado).

### 2. Perfil do local (página Início)
- **Números do topo:** chuva média do ano (1991-2020, NASA POWER), data em que a chuva costuma firmar,
  altitude e classe de relevo, mais uma linha com a situação da chuva hoje.
- **"O solo é bom para quê?":** tabela por cultura (situação, índice 0-100, o que mais limita, efeito na
  simulação), com o porquê de cada fator.
- **Solo e relevo:** tabela com valor, classe oficial, **de onde veio** (🧪 análise de campo, 🛰️
  mapa/satélite, 📍 típico do semiárido, assumido) e faixa provável do mapa.
- **"🧪 Tenho análise de solo":** formulário com os campos do laudo (argila, areia, M.O., pH, P e K
  Mehlich-1, V%, CTC, declividade). Fica salvo em `data/campo/<local>.json`, só na máquina, e o valor de
  campo sempre vence o do mapa.
- **Janelas do ZARC** por cultura.

### 3. De onde vem cada atributo

| Atributo | Fonte sem análise | Observação |
|---|---|---|
| Argila, areia, pH, CTC | **SoilGrids 2.0** (ISRIC), 250 m, camada 0-20 cm (5/10/5 cm de 0-5/5-15/15-30) | Com faixa de incerteza (quantis 5% e 95%) |
| Matéria orgânica | SoilGrids, carbono orgânico x 1,724 | Fator da fonte oficial (Alvarez V. et al., 1999) |
| Nitrogênio disponível | N total do SoilGrids x taxa de mineralização | Vai para o Monte Carlo; REVISAR AGRÔNOMO |
| Altitude e declividade | **SRTM** via Terrain Tiles (AWS), método de Horn, mediana de 9 pixels de ~38 m | |
| Fósforo, potássio, V% | **nenhum satélite estima** → valor típico do semiárido, **assumido** | Só a análise de campo mede |

- **Área urbana ou água** (o SoilGrids não tem valor): o app usa o ponto com dado mais próximo, a 3 km
  (norte, sul, leste ou oeste), e avisa. Os municípios de exemplo usam a sede, que é urbana, então isso
  sempre acontece com eles.

### 4. Limitação do solo por cultura (antiga "Feature 4")
Em `analytics/soil_suitability.py`, com todos os parâmetros em `config/aptidao.yaml`:

1. **Classes oficiais da análise de solo** (Alvarez V. et al., 1999 – 5ª Aproximação): M.O., P por teor de
   argila, K, V%, CTC e pH.
2. **7 fatores por cultura**, no estilo do Sistema de Avaliação da Aptidão Agrícola (Ramalho Filho &
   Beek, Embrapa): nitrogênio (pela M.O.), fósforo, potássio, bases (V%), acidez (pH contra a faixa da
   cultura no FAO Ecocrop), água retida (textura) e erosão (relevo, com proteção das perenes).
3. Cada fator vira um **grau** (nenhuma, ligeira, moderada, forte, muito forte) cruzando a classe do solo
   com a **exigência da cultura**. Exemplo: o feijão-caupi tem exigência de N "nula" porque fixa o próprio
   nitrogênio (Embrapa, Circular Técnica 87).
4. Grau → **nota de Sys et al. (1991)**: 1,0 / 0,90 / 0,725 / 0,50 / 0,20, o meio de cada faixa.
5. **Índice** = nota mínima x raiz(produto das demais) x 100 (método da raiz quadrada). Classes S1 > 75
   (🟢 Bom), S2 50-75 (🟡 Atenção), S3 25-50 (🟠 Restrito), N < 25 (🔴 Crítico).
6. **Fator para o Monte Carlo** = índice local ÷ índice do **solo típico do semiárido**, entre 0,40 e
   1,25. A produtividade base das culturas já representa a roça típica da região, então o solo só mexe
   no que for melhor ou pior que o típico.
7. **Atributo assumido é neutro:** se o P não tem análise, o fator fósforo usa o mesmo grau do solo
   típico. Sem isso, a argila do mapa mudaria a classe de um P que ninguém mediu.

### 5. Monte Carlo
- `SimulationConfig.soil_crop_factors` (fator por cultura) multiplica grãos e forragem.
- O estado da cadeia de Markov continua evoluindo com a rotação, mas o efeito dele virou **relativo ao
  estado de hoje**. Antes um estado ruim penalizava todas as culturas igualmente; agora a penalidade
  absoluta vem do fator por cultura, e o Markov mostra se a rotação melhora ou piora o solo ao longo dos
  anos.
- Estado inicial do Markov = o estado cuja meta de M.O. é a mais próxima da M.O. do local (coerência da
  dinâmica). M.O. e N iniciais vêm do perfil.
- Com a configuração padrão (estado Equilibrado, sem fatores), o resultado é idêntico ao de antes.

### Arquivos

| Arquivo | Mudança |
|---|---|
| `config/aptidao.yaml` | novo: classes, exigências, notas, solo típico, fontes de dados |
| `src/crop_optimizer/analytics/soil_suitability.py` | novo: limitação por cultura, índice, fator, N e estado iniciais |
| `src/crop_optimizer/domain/soil_profile.py` | novo: perfil com origem de cada valor, análise de campo |
| `src/crop_optimizer/ingestion/soilgrids.py` | novo: SoilGrids 0-20 cm, cache, ponto vizinho |
| `src/crop_optimizer/ingestion/terrain.py` | novo: altitude e declividade (Terrain Tiles/SRTM) |
| `src/crop_optimizer/app/home_page.py` | novo: página Início |
| `src/crop_optimizer/app/common.py` | novo: carregamentos compartilhados e seletor de exemplo |
| `src/crop_optimizer/app/navigation.py` | novo: links entre páginas |
| `src/crop_optimizer/app/dashboard.py` | Início como padrão; seletor de solo removido; perfil → simulação |
| `src/crop_optimizer/engine/monte_carlo.py` | fator por cultura; efeito do Markov relativo |
| `src/crop_optimizer/domain/models.py` | `SimulationConfig.soil_crop_factors` |
| `tests/test_perfil_solo.py` | 17 testes novos |

---

## Exemplos verificados (14/11/2026)

| Local | Solo (mapa) | Resultado |
|---|---|---|
| Petrolina, Quixadá, Sousa (ponto a 3 km da sede) | M.O. 1,3-1,9% (baixo), textura média, pH bom, plano | Milho 🟡 59 (limita N), caupi 🟡 72 (P assumido), sorgo 🟢 85, palma 🟢 77, buffel 🟢 100. Fator 1,00 (igual ao típico). |
| Irecê (3 km da sede) | argila 35% (argilosa), M.O. 2,6% (médio), pH 7,2 | Milho 🟡 62 (fator 1,06), caupi 🟡 69 (0,95) |
| Quixadá rural (-5,05, -39,10) | declividade 12,6% (ondulado) | Sorgo perde por erosão (fator 0,81); palma e buffel sofrem menos |
| Petrolina + análise (P 3, M.O. 0,6) | P e M.O. muito baixos | Milho 🟠 34 (−43%), caupi 🟡 50 (limita P, **não** N), buffel 🟢 85 |

Petrolina, Quixadá e Sousa saem com o mesmo índice porque, sem análise, os valores do mapa caem nas mesmas
classes oficiais. É o limite de detalhe do mapa de 250 m: a análise de campo é o que diferencia.

## Como testar

```bash
pytest tests/test_perfil_solo.py
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
```
Abra **Início**, troque o município de exemplo, abra "🧪 Tenho análise de solo", ponha P = 3 e salve.
Depois veja a **Plantio**: a barra lateral mostra o solo por cultura e a simulação já usa os fatores.

---

## ⚠️ Precisa de revisão de agrônomo

Tudo marcado `# REVISAR AGRÔNOMO` em `config/aptidao.yaml` (e 1 linha em `domain/soil_profile.py`).
Principais pontos:

1. **Exigência de cada cultura** (N, P, K, bases, água, proteção contra erosão): definida pela equipe a
   partir da literatura. A única exigência com fonte direta é "N nula" para o caupi.
2. **Faixa de pH** de sorgo, palma e buffel. Milho e caupi vêm do FAO Ecocrop.
3. **Tabelas de grau** (classe x sensibilidade → grau) e graus por textura e relevo.
4. **Solo típico do semiárido**, que é a base do fator relativo. Muda todos os fatores.
5. **Nitrogênio disponível** (5% de N na M.O., densidade 1,4, 2% de mineralização ao ano).
6. **CTC do SoilGrids em cmol/kg** tratada como cmolc/dm³.
7. **Textura "arenosa"** aproximada como areia − argila ≥ 70%.

## Limitações conhecidas

- O SoilGrids é um **mapa estimado** (250 m), não uma medição: a faixa de incerteza é larga (ex.: M.O.
  de 0,2% a 3,0% em Casa Nova).
- **Fósforo, potássio e V%** sem análise ficam neutros. Justo com quem não tem análise, mas esconde o fator
  que mais limita no semiárido (P).
- **Não considera** salinidade, profundidade do solo, pedregosidade, drenagem nem histórico de manejo.
- Ainda não usa a tendência do verde (NDVI) x chuva para detectar degradação: depende de uma conta no
  NASA Earthdata (AppEEARS).
- O Monte Carlo ainda usa o clima sintético do município de exemplo mais próximo.
