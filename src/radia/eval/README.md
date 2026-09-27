# eval/

Carpeta **compartida**. Dueños del harness: Isabella y Edwin. Autores de casos: todo el equipo.

- `cases/*.jsonl`. Un caso por línea. Formato y ejemplo en [[trabajo_en_paralelo]], momento 5.
- `split: "heldout"` se escribe antes de ajustar prompts y **no** se usa para ajustar nada.
- Categorías. automatic, analyst, advisor, not_eligible, ambiguous, unsupported, adversarial, failure, portuguese.

Métricas que se reportan (del enunciado). Resolución automática segura, contención, calidad del handoff, resultados inseguros con denominador, latencia p50 y p95, costo por caso y por resolución. Tres corridas por configuración.
