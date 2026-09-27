# Convenciones

- Python 3.13+.
- `uv`, nunca pip: `uv add`, `uv sync`, `uv run`.
- Librería probada > código a mano.
- Ruff como linter y formatter: `uv run ruff check --fix . && uv run ruff format .`
- Tests con pytest en `tests/`, espejo de la ruta del código.
- Contratos entre piezas en `contracts/`. Ver [[Trabajo_en_paralelo]].
- Identificadores en inglés. Comentarios y docs en español.
- Secretos solo en `.env`. Nunca leerlo, imprimirlo ni commitearlo.
- Datos nunca en Git (`data/local/`).
- Cada quien en su carpeta: `data/` Pablo, `ml/` Isabella, `backend/` Edwin, `frontend/` Esteban.
