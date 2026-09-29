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

## Entrega a otros

- Features Gold (C1) y etiquetas (C2) para los modelos.
- Puntaje interno (C3) para la política y la bandeja del analista.
- Tabla de ofertas vigentes (C6), materializada llamando a la política (C7).

## Reglas

- Ningún dato se versiona. Las salidas locales van en `data/local/`, que está en el `.gitignore`.
- Toda tabla Gold se valida contra su contrato antes de publicarse (`radia.contracts.data.validate`).

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
