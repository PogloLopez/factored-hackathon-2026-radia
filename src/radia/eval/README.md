# eval/

Carpeta **compartida**. Dueños del harness: Isabella y Edwin. Autores de casos: todo el equipo.

## Qué hay

- `demo_customers.py`. Clientes demo **sintéticos** (`DEMO000001`...), etiquetados como test fixture.
  - Uno por celda de la matriz banda x exposición y uno por excepción (inactivo, mora > 30, sin ingreso, sin puntaje, zona gris, Premium).
  - C1 y C3 escritos a mano. C6 sale del job real (`build_offers`) con el baseline de cupo y la política.
  - `DEMO_PROFILES` dice qué representa cada cliente y qué nivel espera para su producto.
  - Se reemplazan por clientes reales cuando se apruebe la descarga.
- `cases/dev.jsonl` y `cases/heldout.jsonl`. Casos C10, uno por línea. Contrato en `radia.contracts.eval_case`.
- `cases.py`. `load_cases(split)` valida cada caso y que su `customer_id` exista en `DEMO_PROFILES` (o sea nulo, sin sesión).

## Cómo se agrega un caso

1. Elegir split antes de escribirlo. No se cambia después.
2. Una línea JSON en el archivo del split. `case_id` único: prefijo de categoría y número (dev 001-099, heldout 101+).
3. `customer_id` de `DEMO_PROFILES`, o nulo para probar acceso sin sesión.
4. `expected`: `attention_level` si la política lo fija; `must` y `must_not` con `Behavior`.
5. En `notes`, el producto y lo que el caso prueba.
6. `uv run pytest tests/eval` en verde.

## Regla del heldout

- Se escribe **antes** de ajustar prompts.
- **Nunca** se usa para ajustar prompts, reglas ni umbrales. Solo para reportar.
- Redacción distinta a dev: paráfrasis, errores de tipeo, mezcla de idiomas. Un test lo verifica.
- Si un caso heldout se usó para ajustar, pasa a dev y se escribe otro.

## Métricas

Del enunciado ([[factored_ai_data_hackathon_2026]]). Resolución automática segura, contención, calidad del handoff, resultados inseguros con denominador, latencia p50 y p95, costo por caso y por resolución. Tres corridas por configuración. Ver [[propuesta]], sección 5.
