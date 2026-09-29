# backend/

**Dueño: Edwin (AI Engineer).**

API, orquestador (máquina de estados con LLM), servicio de política sintética, tools con permisos, guardrails, handoffs y tracing.

## Primeras entregas

- Reglas v0 de la política (borrador en [[trabajo_en_paralelo]], momento 3).
- Stub de la API con respuestas fijas, para que el frontend avance desde el D1 (endpoints en [[trabajo_en_paralelo]], momento 4).

## Reglas

- El LLM nunca produce ni modifica una decisión de política.
- El `customer_id` sale del token de sesión, nunca del texto del chat.
- Toda acción requiere confirmación explícita del cliente y se verifica antes de reportarla.
- Al reemplazar el stub por la lógica real, la forma de las respuestas no cambia.

## Política de elegibilidad (C7)

`policy/engine.py`: `RulesPolicy` cumple `EligibilityPolicy` de `radia.contracts.policy`. Función pura: misma entrada, misma decisión.
`policy/rules_v0.yaml`: bandas, topes, matriz y umbrales. `policy/rules.py` lo valida al cargar.

```python
from radia.backend.policy.engine import RulesPolicy

decision = RulesPolicy().decide(policy_input)
```

Orden de las reglas:

1. Exclusiones: cliente no activo o mora vigente > 30 días. No elegible y sin cupo. Si pide humano o disputa, va al asesor (sin cupo).
2. Exposición: la del producto. Un monto pedido sobre el tope la sube un nivel. Nunca la baja.
3. Nivel base: matriz banda × exposición. Sin puntaje, analista (`missing_data`).
4. Excepciones: al analista (ingreso nulo, zona gris, ingreso declarado distinto, riesgo alto) y al asesor (pide humano, disputa, Premium con exposición media o alta). Solo suben el nivel.
5. Cupo: predicción recortada al tope del producto. Sin predicción, automático pasa a analista.
6. No elegible: sin cupo, con alternativa de menor exposición si la matriz la permite.

Números provisionales: todos los del YAML son checkpoint de Pablo, sin aprobar. Ver [[propuesta]], sección 4.

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
