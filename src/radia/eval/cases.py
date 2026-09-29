"""Carga de los casos de evaluación (C10) desde `cases/<split>.jsonl`.

- Un caso por línea JSON, validado con `EvalCase`.
- El split del archivo y el del caso deben coincidir.
- `customer_id` es un cliente demo de `DEMO_PROFILES` o nulo (sin sesión).
- Los `case_id` no se repiten dentro del archivo.
"""

from pathlib import Path

from radia.contracts.eval_case import EvalCase, Split
from radia.eval.demo_customers import DEMO_PROFILES

CASES_DIR = Path(__file__).with_name("cases")


def cases_path(split: Split | str) -> Path:
    return CASES_DIR / f"{Split(split).value}.jsonl"


def load_cases(split: Split | str) -> list[EvalCase]:
    """Lee y valida los casos de un split. Falla con la línea del error."""
    split = Split(split)
    path = cases_path(split)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = EvalCase.model_validate_json(line)
        except ValueError as exc:
            raise ValueError(f"{path.name}:{n}: caso inválido: {exc}") from exc
        if case.split != split:
            raise ValueError(f"{path.name}:{n}: split {case.split} en archivo {split}")
        if case.customer_id is not None and case.customer_id not in DEMO_PROFILES:
            raise ValueError(
                f"{path.name}:{n}: customer_id desconocido: {case.customer_id}"
            )
        if case.case_id in seen:
            raise ValueError(f"{path.name}:{n}: case_id repetido: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    return cases
