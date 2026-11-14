# Fix 1 — Seleção entre páginas e zoom do mapa

**Branch:** `fix/mapa-zoom-e-selecao` (a partir da `main` com as Features 1-4)
**Data:** 14/11/2026

## Problemas

1. **A seleção não ficava marcada entre as páginas.** O Streamlit apaga o estado de um widget quando a
   página que o desenha não roda. Ao ir da Início para a Plantio, o município de exemplo voltava para
   Petrolina. Na volta à Satélite, a lente, o ano e o mês também voltavam ao padrão. Os botões de exemplo da
   Satélite só moviam o ponto no mapa e não mudavam o local das outras páginas.
2. **Zoom demais deixava o mapa sem imagem.** A imagem de base (Esri World Imagery) só existe até o zoom
   17 no semiárido. Do 18 em diante o servidor devolve o quadro "Map data not yet available" (testado em
   Casa Nova, Quixadá e Irecê).
3. **O zoom mudava sozinho.** Cada lente tinha um zoom próprio, e trocar a lente, o ano ou o ponto
   reconstruía o mapa no zoom da lente.
4. **Zoom de menos mostrava o mapa-múndi repetido.**

## Correções

- `app/state.py`: `keep(chave, padrão)` + `watch(chave)` guardam o valor de cada widget numa chave própria
  da sessão e o devolvem antes de desenhar. Também `stored()` e `store()` para ler e mudar a escolha de
  outra página. Aplicado em:
  - município de exemplo (Início);
  - lente, ano, mês, latitude e longitude (Satélite);
  - data simulada e horizonte (Plantio).
- **Um só "local em uso"** para as três páginas: a roça confirmada ou o município de exemplo. Os botões de
  exemplo da Satélite agora escolhem o município para todas as páginas (`select_example`). A Satélite mostra
  "Local em uso: ..." e o ponto do mapa acompanha a escolha feita na Início.
- **Mapa** (`config/lentes.yaml`, seção `mapa`):
  - zoom de **4** (Brasil inteiro) a **17** (último nível com imagem);
  - mapa preso à caixa do Brasil (`maxBounds` com viscosidade 1), sem repetir o planeta (`noWrap`,
    `worldCopyJump: false`).
- **Zoom e posição estáveis** (segunda versão, depois de a primeira deixar o mapa "indo e voltando"):
  - **Causa do vaivém:** a primeira versão devolvia ao mapa, a cada execução, o centro e o zoom que ele
    tinha acabado de informar. O componente `streamlit-folium` chama `setView` sempre que esses valores
    mudam, então o mapa era puxado para uma posição um pouco antiga enquanto o usuário ainda arrastava ou
    dava zoom.
  - **Como funciona agora:**
    - A figura do mapa (só a imagem de base e os limites) fica **fixa durante a visita à página**. Se a
      figura muda, o componente recria o mapa e perde o zoom.
    - Lente, quadrado do pixel e marcador vão pelo `feature_group_to_add`, que o componente troca **sem
      recriar** o mapa. Trocar lente, ano ou mês não mexe na visão.
    - O app só envia um centro ao mapa quando o **ponto muda** pelos campos de coordenada ou por um exemplo:
      recentraliza e mantém o zoom. Ponto escolhido por **clique** não recentraliza. O zoom **nunca** é
      enviado.
    - O zoom e o centro informados pelo mapa são guardados só para **reabrir na mesma visão** quando o usuário
      volta à página. Se o ponto mudou em outra página, abre no ponto novo com o mesmo zoom.
    - Cada página chama `arrived()` (em `app/state.py`) para o app saber quando o usuário chegou de outra
      página.
- O campo `zoom` de cada lente foi removido de `config/lentes.yaml`.

## Testes

`tests/test_estado_paginas.py`: valor de widget sobrevive à troca de página; mudança feita em outra página
vale na volta; limites de zoom e caixa do Brasil no mapa gerado; a visão do usuário nunca é devolvida ao
mapa durante a visita (só centro quando o ponto muda, e não por clique).

O fluxo Início → Plantio → Satélite → Início também foi verificado com um app de teste que só desenha uma
página por vez: o município, a lente, o ano, o mês, o horizonte, a data e o zoom se mantiveram. **O mapa
não foi testado num navegador.** O comportamento do zoom dinâmico depende do componente
`streamlit-folium` no navegador.
