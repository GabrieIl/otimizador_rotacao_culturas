# Feature 4 — Plantio sem controles manuais e veranico da chuva real

**Status:** implementada na branch `feature/plantio-sem-controles` (a partir da `main` com as Features 1-3).
**Data:** 14/11/2026

## Objetivo

Tirar da página Plantio todos os controles da barra lateral. O app controla os parâmetros por dentro, e o
local vem da roça marcada no mapa. O veranico, que era um controle manual, passa a ser calculado com a
chuva real.

---

## Como era antes

Barra lateral da Plantio:

| Controle | Problema |
|---|---|
| Nome do agricultor (padrão "Seu João") | Desnecessário. O nome padrão aparecia no rádio, no WhatsApp e no PDF. |
| Município de exemplo | Repetia o que a roça no mapa já faz. |
| Data de hoje | Ocupava espaço; só é útil para a demonstração. |
| **Veranico na quadra chuvosa** (0-21 dias, padrão 7) | Somava N dias secos a **todo** ano de **todo** cenário, **em cima** do veranico que o motor já sorteia. Contava o veranico duas vezes, e o sorteio usava o clima sintético. |
| Horizonte (3-5 anos) | Controle global, mas só os painéis da simulação dependem dele. |
| Cenários Monte Carlo (2 mil a 20 mil) | Detalhe técnico, sem uso para o agricultor. |

Com horizonte de 1 ano, o motor troca "2 anos seguidos de perda" por "perder a safra no ano", mas a tela
continuava escrevendo "2 anos seguidos". O rádio dizia "próximos cinco anos" fixo e "a chuva atrasou 0
dias" fora da época.

---

## O que mudou

### 1. Sem barra lateral
- **Local:** linha no topo, "Sua roça: ..." ou "Local: Petrolina/PE (município de exemplo)", com o
  link "Marcar ou trocar a roça no mapa". O município de exemplo é escolhido na Início ou na Satélite.
- **Data:** "Simular outra data", fechado por padrão. Quando a data não é hoje, a página mostra
  "Simulando o dia ...". O CLAUDE.md pede esse controle para a demonstração fora da época de chuva.
- **Nome:** removido. Rádio: "Alô, agricultora e agricultor!"; WhatsApp: "Olá!"; o PDF não imprime o
  campo. `SimulationConfig.farmer_name` agora é vazio por padrão. A API ainda aceita nome, se enviado.
- **Cenários:** fixo em 10.000 (`N_SCENARIOS`).
- **Solo:** resumo por cultura logo abaixo da chuva, com link para a Início.

### 2. Horizonte como filtro dos painéis
- Seção **"Rotações"** com o filtro **Horizonte da simulação: 1 ano | 2 anos | 3 anos | 5 anos**
  (padrão 5). Ele vale para os painéis abaixo: métricas, Balança, placar, rádio, ficha e gráficos.
- O **semáforo** e a matriz atraso x cultura não dependem do horizonte e ficam acima do filtro.
- **Com 1 ano**, os textos dizem "risco de perder a safra no ano" no lugar de "2 anos seguidos" (métricas,
  Balança, gráfico de Pareto, PDF e rádio). Função `loss_risk_label` em `analytics/views.py`.

### 3. Veranico calculado da chuva real
**Veranico** = dias seguidos sem chuva (dia com menos de 1 mm) **depois que a chuva firmou**. É o que
mais quebra safra no semiárido, mesmo em ano de chuva normal no total. É diferente do atraso, que é a chuva
demorar a começar.

- Para cada safra de 1991-2020 em que a chuva firmou (critério da Feature 1), o app mede a **maior
  sequência de dias secos** nos 90 dias seguintes (`engine/rain_onset.py`,
  `build_veranico_climatology`).
- **Veranico** = sequência de **10 dias ou mais**. Parâmetros em `config/chuva.yaml` (`veranico`,
  `# CONFERIR`).
- **No Monte Carlo:** a chance de veranico em cada ano simulado é a proporção observada no local, e o
  tamanho é **sorteado entre os veranicos que de fato aconteceram**. Antes era uma chance sintética, com
  8-18 dias, mais o valor fixo do slider.
- **No semáforo:** a matriz atraso x cultura usa a maior seca típica do local (mediana).
- **Na tela da chuva:** "Veranico: aconteceu em X de cada 10 anos... a maior seca dentro da safra costuma
  durar N dias". Com a safra em andamento, aparece um aviso a partir de 5 dias sem chuva ("Veranico em
  curso: 12 dias seguidos sem chuva" a partir de 10).

Valores reais (NASA POWER, 1991-2020):

| Município | Safras com chuva firme | Veranico (10+ dias) | Maior seca típica | Mais longo |
|---|---|---|---|---|
| Petrolina | 19 de 30 | 8 de cada 10 | 14 dias | 33 dias |
| Irecê | 23 de 30 | 7 de cada 10 | 16 dias | 27 dias |
| Sousa | 30 de 30 | 4 de cada 10 | 7 dias | 33 dias |
| Quixadá | 29 de 30 | 2 de cada 10 | 6 dias | 20 dias |

**Efeito no resultado:** em Petrolina, "Só Milho" passou a perder **4 de cada 10 anos**. Com o sorteio
sintético, perdia 1. O veranico real é mais frequente e mais longo do que o modelo supunha.

### 4. Rádio
- Não diz mais "a chuva atrasou 0 dias". Sem atraso, o motivo vira "pelo histórico de chuva de ...".
- "para os próximos N anos" segue o horizonte escolhido.

### 5. Sem emojis no site
A pedido da equipe, nenhum texto do site tem emoji: títulos, abas, menus, ícones das páginas, métricas,
rótulos de gráfico, mensagem do WhatsApp e tabela de solo por cultura. O que o emoji comunicava virou
palavra:
- **Semáforo:** "SEMÁFORO VERDE — Plante Milho". A palavra continua junto da cor, como o CLAUDE.md exige.
  `TrafficLightLevel.emoji` foi trocado por `TrafficLightLevel.label` ("Verde", "Amarelo", "Vermelho"), e a
  API devolve `label` no lugar de `emoji`.
- **Solo por cultura:** "Milho: atenção · Sorgo: bom".
- **Origem dos dados do solo:** "análise de campo", "mapa/satélite", "típico do semiárido (assumido)".
- Junto, corrigi um bug antigo do WhatsApp: a mensagem trocava todas as vírgulas por pontos ("Olá. *Maria*!").

### Arquivos

| Arquivo | Mudança |
|---|---|
| `src/crop_optimizer/app/dashboard.py` | sem barra lateral; local no topo; data recolhida; horizonte como filtro; semáforo separado da simulação; veranico real |
| `src/crop_optimizer/engine/rain_onset.py` | `VeranicoClimatology`, `build_veranico_climatology`, `current_dry_days` |
| `src/crop_optimizer/analytics/rain_delay.py` | relatório da chuva com veranico e aviso de dias secos |
| `src/crop_optimizer/engine/monte_carlo.py` | tamanho do veranico sorteado do histórico real |
| `src/crop_optimizer/lakehouse/catalog.py` | `SeasonalClimateStats.veranico_lengths` |
| `src/crop_optimizer/analytics/views.py` | `loss_risk_label` |
| `src/crop_optimizer/accessibility/*.py` | saudação sem nome; textos por horizonte; atraso 0 |
| `src/crop_optimizer/app/charts.py` | rótulo do Pareto por horizonte |
| `src/crop_optimizer/domain/models.py` | `farmer_name` vazio por padrão |
| `config/chuva.yaml` | seção `veranico` |
| `tests/test_veranico_plantio.py` | 8 testes novos |

## Como testar

```bash
pytest tests/test_veranico_plantio.py
streamlit run src/crop_optimizer/app/dashboard.py --server.port 8501
```
Na **Plantio**: troque o horizonte em "Rotações" (veja o rótulo mudar em 1 ano). Abra "Simular
outra data" e escolha 05/03/2026.

## Limitações e pendências

- A definição de veranico (10 dias, janela de 90 dias, dia seco < 1 mm) varia na literatura e precisa
  de validação (`# CONFERIR`).
- **Como os dias de veranico viram perda** (coeficiente por dia x sensibilidade da cultura) continua sem
  fonte (`engine/monte_carlo.py`).
- A chance de "perder a safra" ainda vem do clima **sintético** do município de exemplo mais próximo, para a
  chuva total. Só o atraso e o veranico vêm da chuva real.
- A CLI e a API ainda aceitam `veranico_days` e `n_scenarios` manuais (para testes técnicos).
