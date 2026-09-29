# contracts/

Carpeta **compartida**. La forma de todo lo que una pieza le entrega a otra. Solo formas, sin lógica de negocio.
El código es la fuente de verdad. Los borradores de [[trabajo_en_paralelo]] son históricos.

| ID | Archivo | Qué es | Tipo | Productor | Consumidor |
| --- | --- | --- | --- | --- | --- |
| — | `common.py` | Vocabulario: país, segmento, productos, bandas, niveles | enums | — | todos |
| C1 | `data/gold_features.py` | Features Gold por cliente | pandera | ETL | modelos, puntaje, política |
| C2 | `data/gold_labels.py` | Etiquetas de cupo y de mora | pandera | ETL | modelos |
| C3 | `data/internal_score.py` | Puntaje interno 150 a 950 con desglose | pandera | ETL | política, analista |
| C4, C5 | `ml.py` | Predicción de cupo y de riesgo | pydantic | modelos | política, job de ofertas |
| C6 | `data/active_offers.py` | Ofertas vigentes con versión y vencimiento | pandera | job de ofertas | tools, web |
| C7 | `policy.py` | Entrada, decisión e interfaz de la política | pydantic | política | job de ofertas, orquestador |
| C8 | `api.py` | API hacia la web: request y response por endpoint | pydantic | backend | web |
| C9 | `handoff.py` | Expediente de handoff | pydantic | orquestador | analista, asesor |
| C10 | `eval_case.py` | Casos de evaluación | pydantic | todos | runner de evaluación |
| C11 | `trace.py` | Tracing por turno | pydantic | orquestador | métricas, evaluación |

## Cómo se usa

- Tablas: validar con `radia.contracts.data.validate(Modelo, df)`, al escribir y al leer. Resetea el índice porque pandera se cae con índices duplicados en pandas 3.
- Cada contrato de tabla trae su mock (`make_*`). Sirve para construir código, nunca para sacar métricas.
- Invariantes de seguridad en el contrato, no solo en el código: sin puntaje no hay nivel automático, la política siempre es sintética y el modelo de cupo no usa `LIMIT_MODEL_EXCLUDED_FEATURES`.

## Reglas

- Cada archivo tiene su `CONTRACT_VERSION`. v0 (0.x) hasta perfilar los datos reales. Después se congela como v1.
- Cualquier cambio sube `CONTRACT_VERSION`. Compatible (campo opcional): versión menor. Rompe (renombrar, borrar, cambiar tipo): versión mayor.
- Cada contrato con sus pruebas en `tests/contracts/`.
