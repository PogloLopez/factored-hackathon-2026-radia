# Auditoría de señal

Qué se puede predecir con el dataset real y qué hacemos con eso. Datos de 2026-09-30 y 2026-10-01. Reproducible con `uv run radia-ml audit` (escribe `data/local/reports/signal_audit.json`). El F1 de intención sale de `uv run radia-ml intent` (MLflow, experimento `intent-classifier`).

## En una frase

Ninguna etiqueta del dataset depende de los datos del cliente. Donde hay señal, sale de una sola columna de contexto, y una tabla de tasas sobre esa columna iguala o supera al modelo.

## Cómo se midió

- Para cada etiqueta, un modelo (gradient boosting, validación cruzada) contra un baseline trivial.
- AUC 0.5 es azar. Si el modelo empata con una tabla por una columna, no hay nada que aprender más allá de esa columna.
- Split por cliente cuando aplica. Muestras de 150,000 filas con semilla fija.

## Resultados

| Etiqueta | Tabla | Modelo | Baseline trivial | Lectura |
| --- | --- | --- | --- | --- |
| Cupo asignado | products (C2) | MAE 18,066 USD | Cuantiles por familia: 18,057 USD | Sin señal. Correlación máx. con features: 0.004 |
| Mora > 30 días | products | AUC del buró 0.503 | Sorteo de 9.5 % por producto | Sin señal. Desvío máx. contra el sorteo: 1.3 pts |
| Motivo según el texto | call_transcripts | F1 macro 0.143 | Clase mayoritaria: accuracy 34.5 % | Sin señal. 42 textos distintos en 171,321 llamadas |
| Escalado a supervisor | call_center_interactions | AUC 0.505 | — | Sin señal |
| Transacción rechazada | transactions | AUC 0.500 | — | Sin señal |
| Churn (Closed o Inactive) | customers | AUC 0.502 (techo) | — | Sin señal |
| Resuelto al 1er contacto | call_center_interactions | AUC 0.761 | Tasa por categoría: 0.763 | Solo la categoría |
| Sentimiento negativo | call_center_interactions | AUC 0.765 | Tasa por categoría: 0.765 | Solo la categoría |
| Requiere seguimiento | call_center_interactions | AUC 0.674 | Tasa por categoría: 0.676 | Solo la categoría |
| Conversión de campaña | campaign_sends | AUC 0.623 | Tasa por canal: 0.660 | Solo el canal |

### Lo único con estructura: tasas por categoría del contacto

| Categoría | Resuelto al 1er contacto | Sentimiento negativo | Requiere seguimiento |
| --- | ---: | ---: | ---: |
| Transaccional | 91.5 % | 0 % | 21.9 % |
| Producto | 90.0 % | 19.2 % | 23.8 % |
| Técnico | 69.9 % | 34.9 % | 40.5 % |
| Comercial | 65.9 % | 35.1 % | 43.9 % |
| Retención | 60.8 % | 35.5 % | 48.7 % |
| Queja | **43.7 %** | 34.9 % | **62.7 %** |

Conversión por canal: SMS 1.03 %, Push 0.91 %, Email 0.62 %, Voz y WhatsApp 0 %.

## Otros hallazgos de calidad

- El dataset trae valores en español y con tilde (`México`, `Tarjeta Crédito`). Sin normalizar, Gold excluía a todo México y generaba 0 etiquetas de cupo. Arreglado en la rama `fix/etl-vocabulario-real`.
- Nulos: ingreso 20 % y buró 15 %, no el ~5 % del [[latam_bank_dataset_summary]]. El modelo solo se evalúa sobre clientes con ingreso (sesgo de selección, declarado).
- Revisamos el texto de las transcripciones buscando instrucciones escondidas ("ignora", "actúa como", "apruébame"). Ninguna.

## Qué significa para el concurso

- [[factored_ai_data_hackathon_2026]] pide al menos un componente aprendido evaluado contra un baseline, con etiquetas válidas y sin leakage. Lo cumplimos con el modelo de cupo y lo reportamos con honestidad: no supera a los cuantiles por familia porque la etiqueta es aleatoria.
- Es el riesgo que [[propuesta]] ya anticipaba (sección 11). La política sigue funcionando: no depende de que el modelo gane.
- La auditoría misma es evidencia: muestra rigor, baselines justos y que no forzamos conclusiones.

## Qué hacemos

1. **Componente de ML:** el modelo de cupo contra 3 baselines: múltiplo fijo y múltiplo ajustado (`radia-ml train`), y cuantiles por familia (`radia-ml audit`). Resultado negativo reportado.
2. **Ofertas:** el baseline actual (múltiplo del ingreso) es *peor* que no mirar al cliente. Cambiar el cupo de C6 a la mediana por familia. Decisión de Pablo.
3. **Política de derivación:** usar la tabla de categorías como respaldo con datos. Queja se resuelve al primer contacto solo 44 % y pide seguimiento 63 %: va a humano.
4. **Intención en el chat:** reglas más LLM, evaluadas con los casos held-out. No hay datos para entrenar un clasificador.
5. **No más exploración de etiquetas.** Feature freeze el 2026-10-02.

## Qué hace cada uno

| Persona | Tareas |
| --- | --- |
| Isabella | Sección de evaluación de ML en el reporte con esta auditoría. Model card del modelo de cupo. 1-2 slides con la tabla de resultados |
| Pablo | Revisar y mergear `fix/etl-vocabulario-real` (urgente). Regenerar Gold, puntaje y ofertas con datos reales. Decidir el cupo de C6. Declarar los nulos reales en calidad de datos |
| Edwin | Derivación con la tabla de categorías (Queja a humano). Intención con reglas y LLM. Corrida de evaluación con casos held-out |
| Esteban | Demo con un caso por nivel de atención, incluida una queja derivada con su expediente. Slides con los hallazgos de datos |

## Ramas

- `fix/etl-vocabulario-real`: normalización de vocabulario en Silver. Para mergear.
- `feat/ml-fitted-baseline`: baseline de múltiplo ajustado. CI en verde.
- `feat/ml-intent-classifier`: clasificador de intención. Evidencia negativa, sin señal.
- `feat/ml-auditoria-senal`: `radia-ml audit` y este documento.

Detalle del modelo de cupo en `src/radia/ml/README.md`. Plan general en [[propuesta]] y [[roadmap]].
