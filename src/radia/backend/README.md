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

Detalle en [[propuesta]] y [[trabajo_en_paralelo]].
