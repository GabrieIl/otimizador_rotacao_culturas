# Motor Estocástico de Resiliência do Sertão ("Conselheiro de Bolso")

Simulador probabilístico para apoiar o agricultor familiar do Semiárido e técnicos da EMATER/cooperativas na decisão de plantio frente a **atraso das chuvas**, **veranicos** e **ciclos de seca (El Niño/La Niña)** nos próximos **5 anos**.

## Arquitetura do Projeto

1. **Frente de Dados — ETL Assíncrono & Local Data Lakehouse (`ingestion/`, `elt/`, `lakehouse/`)**:
   - Pipelines assíncronos (`asyncio` + `httpx.AsyncClient`) consumindo chuvas de satélite (CHIRPS/GPM via NASA POWER), umidade do solo (SMAP/MODIS via NASA AppEEARS) e janelas ZARC (Embrapa).
   - Armazenamento Medallion (`data/bronze`, `data/silver`, `data/gold`) em Parquet particionado (Hive `location_id` / `year`) e consultas instantâneas via **DuckDB + Polars**.
2. **Frente do Motor Matemático — Simulação de Sobrevivência (`engine/`)**:
   - **Monte Carlo vetorizado em NumPy (10.000 cenários em < 1s)**: focado em **balanço de biomassa** (kg de grão para a família + kg de palhada/forragem para o rebanho) com persistência climática AR(1).
   - Ranqueamento que minimiza a **probabilidade de 2 anos consecutivos de perda total** e gera o **Placar de Sobrevivência em 10**.
   - **Cadeias de Markov do solo (`markov_soil.py`)**: evolução de fertilidade, matéria orgânica e economia de insumos.
3. **Frente de Acessibilidade & Visões Analíticas (`analytics/`, `accessibility/`, `api/`, `app/`)**:
   - **Matriz de Atraso das Chuvas → Semáforo Agrícola**: 🟢 Plante Milho | 🟡 Mude para Sorgo/Caupi | 🔴 Guarde a semente.
   - **Placar de Sobrevivência em 10** + **Balança Comida (🌽) × Forragem (🌿) × Escudo (🛡️)**.
   - **O Rádio do Tempo (Audio-First TTS)**: roteiro regionalizado + síntese de áudio (Offline WAV / Google TTS / OpenAI TTS) pronto para WhatsApp.
   - **Ficha "O Que Não Sabemos" (One-Pager PDF)**: PDF A4 de 1 página exportável para técnicos EMATER/ONGs.
   - **API HTTP + Webhook Twilio WhatsApp (`api/server.py`)**.

## Como Executar

```bash
# 1. Ativar ambiente virtual
source .venv/bin/activate

# 2. Executar pipeline ELT assíncrono (constroi Star Schema Parquet)
python scripts/run_elt.py

# 3. Benchmark DuckDB + 10.000 cenários Monte Carlo (< 5s)
python scripts/run_benchmark.py

# 4. Iniciar interface Streamlit (Conselheiro + Rádio do Tempo + Ficha EMATER)
python scripts/run_app.py

# 5. Iniciar API HTTP / Webhook WhatsApp Twilio
python scripts/run_api.py

# 6. Rodar testes unitários com verificação de cobertura (>= 80%) e linter
pytest --cov=crop_optimizer --cov-report=term-missing
ruff check src tests scripts
```
