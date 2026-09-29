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

## Gold

```bash
uv run radia-etl gold                          # corte = última transacción en Silver
uv run radia-etl gold --snapshot 2026-06-17
```

- DuckDB sobre `silver/*.parquet`. Solo datos con fecha ≤ corte.
- `gold/customer_features.parquet` (C1) y `gold/limit_labels.parquet` (C2, cupo en USD por producto de crédito con cupo > 0). Validados con su contrato antes de escribir.
- USD con la tasa más reciente ≤ corte. Moneda del ingreso por país: MXN, COP, ARS. Saldos y cupos por `products.currency`.
- Crédito = Credit Card, Personal Loan, Mortgage. Saldo, número de productos y utilización: solo `Active`. Mora: todo crédito no `Closed`.
- Ingresos 6 meses: depósitos `Approved` con `amount_usd > 0`. Seis meses hacia atrás desde el corte; un mes sin depósitos cuenta 0.
- Clientes con país, segmento o estado fuera del vocabulario, sin registro o registrados después del corte quedan fuera (se avisa en el log).
- `credit_score` fuera de 300 a 850 se trata como nulo.
- Etiqueta de mora (C5): **no se implementa**. El modelo de riesgo está fuera del alcance mínimo.

### Supuestos a verificar con los datos reales

- Dirección de la tasa: `usd = monto * exchange_rate` para `moneda -> USD`. Si solo hay `USD -> moneda`, se usa la inversa.
- `customers` y `products` son la foto actual: segmento, saldo y mora no se reconstruyen a un corte pasado. Limitación declarada.
- `current_balance` positivo = deuda. Negativo se toma como 0.
- Valores exactos de `transaction_type`, `transaction_status` y `product_status` (mayúsculas, espacios).

## Puntaje interno

```bash
uv run radia-etl score                         # pesos v0
uv run radia-etl score --weights otro.yaml
```

- C3 de 150 a 950 en `gold/internal_score.parquet`. Determinista.
- Pesos en `score_weights_v0.yaml`, validados con pydantic (`ScoreWeights`, inmutable).
- **Pesos provisionales. Checkpoint de Pablo: no aprobados.**
- Componentes lineales y recortados: buró (mayor peso), deuda sobre ingreso, estabilidad de ingresos, antigüedad, mora y uso del cupo.
- Puntaje = base + puntos, recortado a [150, 950]. `breakdown_json` guarda los puntos por componente.
- Sin `credit_score` o sin ingreso: puntaje nulo y desglose `{}`. La política lo manda al analista.
- Las exclusiones (inactivo, mora > 30 días) viven en la política, no aquí. Ver [[propuesta]].

## Ofertas vigentes (C6)

```bash
uv run radia-etl offers                   # gold/customer_features + gold/internal_score -> gold/active_offers.parquet
```

- Código en `offers.py`. `build_offers` es pura: misma entrada, mismo DataFrame.
- Una fila por cliente × producto del catálogo, incluidas las no elegibles.
- Usa la última fecha de corte de C1 por cliente y el puntaje de C3 de esa fecha.
- Cupo: `IncomeMultipleBaseline` (C4). Decisión: `RulesPolicy` (C7), escrita tal cual. Aquí no hay reglas.
- Sin datos del chat: la solicitud solo trae el producto.
- Ingreso 0 o nulo en C1 pasa como dato faltante (la política lo manda al analista).
- `generated_at` con zona, guardado en UTC sin zona. Vence a los 7 días (`ttl_days`).
- `offer_id`: hash de cliente, producto y `generated_at`. Cambia en cada corrida.
- Parquet con DuckDB: el proyecto no depende de pyarrow.
- Si falta un insumo, el job falla con la ruta que falta.

## Entrega a otros

- Features Gold (C1) y etiquetas (C2) para los modelos.
- Puntaje interno (C3) para la política y la bandeja del analista.
- Tabla de ofertas vigentes (C6), materializada llamando a la política (C7).

## Reglas

- Ningún dato se versiona. Las salidas locales van en `data/local/`, que está en el `.gitignore`.
- Toda tabla Gold se valida contra su contrato antes de publicarse (`radia.contracts.data.validate`).

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
