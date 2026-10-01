# ml/

**Dueña: Isabella (Data Scientist).**

EDA, modelo de cupo sugerido (principal), modelo de riesgo como alerta de discrepancia, evaluación y model cards.

## Entrega a otros

- Predicción de cupo con rango de negociación (C4) y estimación de riesgo (C5), según `src/radia/contracts/ml.py`.
- Mientras el modelo real no existe, el resto del equipo usa el baseline (múltiplo fijo del ingreso) con la misma interfaz.

## Baseline

`baseline.py`, `IncomeMultipleBaseline`. Cupo = ingreso mensual × múltiplo por producto. Rango de negociación ±20 %. Sin ingreso, sin predicción. Múltiplos provisionales.

## Modelo de cupo

```bash
uv run radia-ml train --mock        # datos mock: prueba el código, las métricas no cuentan
uv run radia-ml train               # Gold real: data/local/gold/{customer_features,limit_labels}.parquet
uv run radia-ml train --seed 1 --test-size 0.25
```

- `dataset.py`. Une C1 y C2 por `customer_id` y `snapshot_date`. Sin `LIMIT_MODEL_EXCLUDED_FEATURES`. Split por cliente.
- `limit_model.py`, `QuantileLimitModel`. Tres gradient boosting cuantiles (0.1, 0.5, 0.9) sobre el log del cupo: piso, sugerido y techo. Cumple `LimitModel` (C4).
- `metrics.py`. MAE, error porcentual (mediana y media), cobertura y ancho del rango. Global y por grupo. Rechaza nulos, infinitos y cupos <= 0.
- `train.py`. Modelo contra baseline sobre las mismas filas de test. Métricas por país, segmento y familia (fairness).
- Train y test solo con productos cuyo dueño tiene ingreso > 0 (C4). Los descartes se registran.

### MLflow

- Experimento `limit-model`. Tracking en `data/local/mlflow.db`, artefactos en `data/local/mlartifacts/`. Nada se versiona.
- Se registran parámetros, métricas `model_*` y `baseline_*`, y un CSV por grupo.
- Ver los runs: `uv run mlflow ui --backend-store-uri sqlite:///data/local/mlflow.db`.

### Limitaciones

- La etiqueta trae la familia, no el nivel de tarjeta. CC_BASIC, CC_GOLD y CC_BLACK reciben la misma predicción y la política la recorta a su tope.
- En la evaluación, el baseline de tarjetas usa el múltiplo de CC_GOLD. Queda registrado como `baseline_card_code`.
- Cobertura nominal del rango: 80 %. Se reporta la real.
- **Con datos reales (2026-09-30) el cupo no tiene señal.** Correlación ~0 con todas las features. El modelo empata con los cuantiles del cupo por familia, sin mirar al cliente (MAE 17.9k vs 18.1k USD). Los cupos parecen uniformes por familia. La mora > 30 días tampoco: sale al azar con ~9.5 % por producto (AUC del puntaje de buró 0.497).

## Clasificador de intención

Componente de ML propuesto porque el cupo y la mora no tienen señal. Del texto del cliente al motivo del contacto.

```bash
uv run radia-etl manifest --tables call_center_interactions,call_transcripts   # solo LIST; Pablo lo aprueba
uv run radia-etl download <manifiesto generado> --approved
uv run radia-etl bronze --tables call_center_interactions,call_transcripts
uv run radia-etl silver --tables call_center_interactions,call_transcripts
uv run radia-ml intent              # --mock para probar el código
```

- `intent.py`. `customer_text` de `call_transcripts` unido a `reason_category` de `call_center_interactions`. Split por cliente.
- Modelo: TF-IDF (palabras y bigramas, sin tildes) + regresión logística.
- Baselines: clase mayoritaria y palabras clave aprendidas de train (log-odds por clase).
- Métricas: accuracy y F1 macro con las clases de train fijas, global y por acento.
- MLflow: experimento `intent-classifier`, métricas `model_*`, `baseline_majority_*`, `baseline_keywords_*`.
- Las tablas de llamadas no entran al default de `radia-etl`: solo con `--tables`.
- **Con datos reales (2026-10-01) no hay señal.** Solo 42 textos distintos en 171,321 transcripciones, casi todos "consultar saldo", con la misma proporción de categorías que el total. Modelo: accuracy 20.0 %, F1 macro 0.143. Palabras clave: 20.2 %, 0.131. Clase mayoritaria: 34.5 %, 0.086. Se conserva como evidencia de evaluación, no como componente del sistema.

## Reglas

- Antes de D3 se trabaja con mocks que cumplen el contrato o con EDA directo sobre S3. Las métricas sobre mock no cuentan.
- Split por cliente y features calculadas solo con información anterior a `snapshot_date` (sin leakage).
- El modelo de cupo no usa `LIMIT_MODEL_EXCLUDED_FEATURES` de C1 (son consecuencia del cupo).
- Notebooks en `notebooks/<tu-nombre>/`, con salidas limpias antes de commitear. Lo que sirve se pasa a `.py`.
- Experimentos registrados en MLflow. `mlruns/` no se versiona.

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
