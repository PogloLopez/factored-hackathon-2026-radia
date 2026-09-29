# etl/

**Dueño: Pablo (Data Engineer).**

Pipeline Bronze, Silver y Gold sobre el dataset de S3, puntaje interno determinístico y job de ofertas vigentes. Contratos en `src/radia/contracts/` (C1, C2, C3, C6).

## Uso

```bash
uv run radia-etl manifest                 # solo LIST: claves, tamaños y ETags de las tablas de crédito
uv run radia-etl download <manifiesto> --approved   # descarga única de lo pendiente
```

- Configuración en `radia.config.Settings` (pydantic-settings). Variables en `.env.example`.
- Todo acceso al bucket pasa por `s3.py`. El hook bloquea la CLI de AWS sobre S3.
- Descarga idempotente por ETag. Un re-sync solo trae objetos nuevos o cambiados (datos tardíos).
- Concurrencia máxima `S3_MAX_CONCURRENCY` (4 por defecto, tope 8).

## Manifiesto actual (2026-09-29, solo LIST)

| Tabla | Objetos | Tamaño | Formato |
| --- | ---: | ---: | --- |
| transactions | 1097 | 808 MB | CSV diario `year=/month=/day=` |
| campaign_sends | 1083 | 326 MB | CSV diario `year=/month=/day=` |
| products | 1 | 68 MB | CSV |
| customers | 1 | 47 MB | CSV |
| daily_exchange_rates | 1 | 0.8 MB | CSV |
| marketing_campaigns | 1 | 0.03 MB | CSV |
| **Total** | **2184** | **1.25 GB** | |

**Checkpoint pendiente (Pablo):** aprobar la descarga. `campaign_sends` solo sirve al modelo opcional de producto a ofrecer. Sin esa tabla la descarga baja a 924 MB y 1101 objetos.

## Bronze y Silver

```bash
uv run radia-etl bronze                   # raw CSV -> data/local/bronze/<tabla>.parquet
uv run radia-etl silver                   # bronze -> data/local/silver/ + data/local/quality/
uv run radia-etl silver --tables customers,products
```

- Tablas: `customers`, `products`, `daily_exchange_rates`, `transactions`. Specs en `tables.py` (PK, columna de orden, tipos del [[latam_bank_complete_data_dictionary]]).
- **Bronze**: todo como texto, une particiones y esquemas por nombre (una columna nueva no rompe). Agrega `_source_file` y `_ingested_at`. Se reconstruye completo desde raw.
- **Silver**: `TRIM`, `''` a NULL, `TRY_CAST` al tipo de la spec. Descarta filas sin PK, quita duplicados exactos y deja la última versión por PK (`last_updated` o `process_date`; empate: archivo más reciente).
- Orden de construcción: dimensiones antes que hechos, para medir huérfanos.

### Reporte de calidad

Un JSON por tabla en `data/local/quality/` (`QualityReport` en `silver.py`):

- Filas de entrada y salida, PK nulas, duplicados exactos y versiones viejas quitadas.
- Tasa de nulos y fallas de casteo por columna.
- Huérfanos por FK: `products.customer_id`, `transactions.customer_id` y `transactions.product_id`. `null` si la dimensión aún no tiene Silver.
- Columnas de la spec que faltan en raw y columnas nuevas no previstas.

## Entrega a otros

- Features Gold (C1) y etiquetas (C2) para los modelos.
- Puntaje interno (C3) para la política y la bandeja del analista.
- Tabla de ofertas vigentes (C6), materializada llamando a la política (C7).

## Reglas

- Ningún dato se versiona. Las salidas locales van en `data/local/`, que está en el `.gitignore`.
- Toda tabla Gold se valida contra su contrato antes de publicarse (`radia.contracts.data.validate`).

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
