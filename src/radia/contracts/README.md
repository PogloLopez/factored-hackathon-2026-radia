# contracts/

Carpeta **compartida**. Aquí vivirá la forma de todo lo que una pieza le entrega a otra.
Hoy vacía. Borradores y explicación en [[trabajo_en_paralelo]].

| ID | Archivo | Productor | Consumidor |
| --- | --- | --- | --- |
| C1 | `data/gold_features.py` | Pablo | Isabella, puntaje |
| C2 | `data/gold_labels.py` | Pablo | Isabella |
| C3 | `data/internal_score.py` | Pablo | Edwin, bandeja del analista |
| C4, C5 | `ml.py` | Isabella | Política, job de ofertas |
| C6 | `data/active_offers.py` | Pablo (job que llama a la política) | Tools de Edwin, carrusel |
| C7 | `policy.py` + `src/radia/backend/policy/rules_v0.yaml` | Edwin | Job de ofertas, orquestador |
| C8 | `api.py` | Edwin | Esteban |
| C9 | `handoff.py` | Edwin | Esteban |
| C10 | `eval_case.py` | Todos | Isabella, Edwin |
| C11 | `trace.py` | Edwin | Pablo, Isabella |

## Reglas

- D1 cada productor pasa su borrador a código y lo revisa con su consumidor. D2 se congelan como v1.
- Cualquier cambio entra por PR que toca solo el contrato y sube `CONTRACT_VERSION`. Aprueban productor y consumidor.
- Cambio compatible (agregar campo opcional) sube la versión menor. Cambio que rompe (renombrar, borrar, cambiar tipo) se acuerda en la reunión diaria y sube la versión mayor.
- Cada contrato con su prueba.
