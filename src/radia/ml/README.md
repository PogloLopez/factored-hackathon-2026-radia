# ml/

**Dueña: Isabella (Data Scientist).**

EDA, modelo de cupo sugerido (principal), modelo de riesgo como alerta de discrepancia, evaluación y model cards.

## Entrega a otros

- Predicción de cupo con rango de negociación (C4) y estimación de riesgo (C5), según `src/radia/contracts/ml.py`.
- Mientras el modelo real no existe, el resto del equipo usa el baseline (múltiplo fijo del ingreso) con la misma interfaz.

## Baseline

`baseline.py`, `IncomeMultipleBaseline`. Cupo = ingreso mensual × múltiplo por producto. Rango de negociación ±20 %. Sin ingreso, sin predicción. Múltiplos provisionales.

## Reglas

- Antes de D3 se trabaja con mocks que cumplen el contrato o con EDA directo sobre S3. Las métricas sobre mock no cuentan.
- Split por cliente y features calculadas solo con información anterior a `snapshot_date` (sin leakage).
- El modelo de cupo no usa `LIMIT_MODEL_EXCLUDED_FEATURES` de C1 (son consecuencia del cupo).
- Notebooks en `notebooks/<tu-nombre>/`, con salidas limpias antes de commitear. Lo que sirve se pasa a `.py`.
- Experimentos registrados en MLflow. `mlruns/` no se versiona.

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
