"""CLI de la evaluación: `uv run radia-eval --help`.

Siempre con `FakeLanguageModel`: sin red ni gasto. Correr con Groq real es
checkpoint de Pablo y no se expone aquí.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from radia.config import get_settings
from radia.contracts.eval_case import Split
from radia.eval.cases import load_cases
from radia.eval.evidence import SystemName
from radia.eval.report import evaluate, write_outputs

app = typer.Typer(no_args_is_help=True, help="Evaluación de Radia contra el baseline.")


@app.callback()
def main() -> None:
    """Evaluación offline sobre los casos C10."""


@app.command()
def run(
    split: Annotated[Split, typer.Option(help="Casos a correr.")] = Split.HELDOUT,
    runs: Annotated[int, typer.Option(min=1, help="Corridas por configuración.")] = 3,
    out_dir: Annotated[
        Path | None,
        typer.Option(help="Carpeta de salida. Por defecto data_dir/eval/<fecha>."),
    ] = None,
) -> None:
    """Corre Radia y el baseline; escribe results.jsonl y report.md."""
    started_at = datetime.now(UTC)
    cases = load_cases(split)
    if out_dir is None:
        out_dir = get_settings().data_dir / "eval" / f"{started_at:%Y%m%dT%H%M%SZ}"
    evaluation = evaluate(cases, runs=runs)
    results_path, report_path = write_outputs(
        evaluation, out_dir, split.value, started_at
    )
    for system in SystemName:
        m = evaluation.metrics(system)
        typer.echo(
            f"{system.value:9} pasan {m.passed}  inseguros {m.unsafe_cases}  "
            f"resolución automática segura {m.safe_auto_resolution}"
        )
    typer.echo(f"Resultados: {results_path}")
    typer.echo(f"Reporte: {report_path}")
