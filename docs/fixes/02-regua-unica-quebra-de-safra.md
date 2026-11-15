# Fix 2 — Aviso e ranking com o mesmo motor e a mesma régua

**Branch:** `fix/aviso-mesmo-motor` (a partir da `feature/paginas-interativas`)
**Data:** 15/11/2026

## Problema

Em Petrolina, o aviso dizia que o milho "quebra em 8 de cada 10 anos", e o ranking dizia que "Só milho
aguenta 6 de 10 anos". Os dois números pareciam se contradizer. Eles vinham de contas diferentes:

| | Aviso (antes) | Ranking (antes) |
|---|---|---|
| O que contava como perda | colher menos de 65% do normal | faltar comida para a família: colher menos de ~17% do normal (ou pouca comida e pouca forragem juntas) |
| Veranico | o típico (14 dias) **em todo ano** | sorteado dos veranicos reais, só nos anos em que ocorre (~8 de cada 10) |
| Modelo | uma conta simplificada à parte (`views.py`) | o motor completo (ENSO, matéria orgânica, solo) |

Medido no próprio motor, a colheita do milho fica abaixo de 65% do normal em 9 de 10 anos e abaixo de 17%
em 3 de 10. Cada número estava certo dentro da sua régua, mas a tela usava "quebra" e "aguenta" sem dizer qual.
Além disso, aplicar o veranico típico em todo ano deixava o aviso pessimista: sem veranico o risco era 47%; com
ele fixo, 81%.

## Correção

- **Uma régua só:** `config/colheita.yaml`, `quebra_safra.limiar_colheita_relativa: 0.5` (REVISAR AGRÔNOMO).
  Quebra de safra = colher **menos da metade do normal desta terra**.
  - Grãos (milho, caupi, sorgo): conta o grão. Forrageiras perenes (palma, buffel): conta a forragem.
  - Numa rotação, vale a média das culturas do ano (cada uma com a mesma área).
  - "Normal desta terra" = o que a lavoura colhe nesse solo num ano sem falta de água. O fator fixo do solo
    local não conta como quebra. Já o atraso, o veranico, a falta de chuva e a mudança do solo causada pela
    rotação, sim.
- **Um motor só:** o aviso de cada cultura agora roda o mesmo `MonteCarloRotationEngine` do ranking, com a
  cultura plantada sozinha por 1 ano (`harvest_failure_prob`). Ele usa o mesmo solo de hoje (estado, matéria
  orgânica, nitrogênio e fator por cultura) e o veranico sorteado do histórico real.
- **O ranking conta pela mesma régua.** "Colhe em X de 10 anos" = anos sem quebra de safra. O risco mostrado é
  "2 quebras de safra seguidas" (ou "quebra de safra" com horizonte de 1 ano).
- **Textos:** o aviso diz "dá quebra de safra em X de cada 10 anos (colhe menos da metade do normal)". O texto
  da régua sai do config.

## Resultado (Petrolina, 15/11/2026, sem atraso)

| | Antes | Depois |
|---|---|---|
| Aviso do milho | quebra em 8 de 10 | quebra em 6 de 10 |
| Só milho no ranking, 1 ano | aguenta 6 de 10 | colhe em 4 de 10 (= 6 quebras) |
| Caupi / sorgo / palma, aviso | — | 1 / 0 / 0 de 10 |

Com 5 e 10 anos, o "Só milho" colhe em 3 de 10, porque o solo empobrece com o milho todo ano.

## Testes

`tests/test_regua_unica.py`:
- o milho no aviso e o "Só milho" no ranking de 1 ano dão o mesmo número, com e sem atraso;
- a quebra é a colheita relativa abaixo da régua;
- o risco sobe de "sem veranico" para "veranico real sorteado" e para "veranico todo ano";
- o texto da régua vem do config.

## Limite que continua

As rotações com palma colhem em 10 de 10 anos, porque a palma quase nunca quebra e entra na média com o mesmo
peso dos grãos. A régua conta "colheu", não "colheu o que a propriedade precisa". A produção de grãos e de forragem
continua no ranking em kg/ha·ano, para comparar.
