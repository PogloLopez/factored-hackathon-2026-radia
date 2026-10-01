"""CLI de ML: `uv run radia-ml --help`."""

import json
from typing import Annotated

import mlflow
import typer

from radia.config import Settings, get_settings
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.etl.gold import gold_path
from radia.etl.offers import read_parquet
from radia.etl.silver import silver_path
from radia.ml.intent import make_mock_calls, run_intent_experiment
from radia.ml.signal_audit import AUDITS, run_audit
from radia.ml.train import run_experiment

app = typer.Typer(no_args_is_help=True, help="Modelos de Radia.")

EXPERIMENT = "limit-model"


def _use_experiment(settings: Settings, tracking_uri: str | None, name: str) -> None:
    """Tracking en data/local y experimento activo, creado con artefactos locales."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(
        tracking_uri or f"sqlite:///{(settings.data_dir / 'mlflow.db').as_posix()}"
    )
    # Los artefactos van a data/local (no versionado), no a ./mlruns del repo.
    experiment = mlflow.get_experiment_by_name(name)
    # MLflow borra en suave: el experimento sigue existiendo y no se puede usar.
    if experiment is not None and experiment.lifecycle_stage == "deleted":
        raise typer.BadParameter(
            f"el experimento {name} está borrado en MLflow. Restáuralo con "
            f"`uv run mlflow experiments restore -x {experiment.experiment_id}`"
        )
    if experiment is None:
        artifacts = (settings.data_dir / "mlartifacts").resolve()
        mlflow.create_experiment(name, artifact_location=artifacts.as_uri())
    mlflow.set_experiment(name)


@app.callback()
def main() -> None:
    """Modelos de Radia."""


@app.command()
def train(
    mock: Annotated[
        bool, typer.Option(help="Datos mock de C1 y C2. Las métricas no cuentan.")
    ] = False,
    seed: int = 0,
    test_size: float = 0.2,
    tracking_uri: Annotated[
        str | None,
        typer.Option(
            help="Por defecto sqlite en data/local/mlflow.db (no versionado)."
        ),
    ] = None,
) -> None:
    """Entrena el modelo de cupo, lo compara con el baseline y lo registra en MLflow."""
    if not 0 < test_size < 1:
        raise typer.BadParameter("--test-size debe estar entre 0 y 1, sin incluirlos")
    settings = get_settings()
    if mock:
        features = make_gold_features(n=5000, seed=seed)
        labels = make_limit_labels(features, seed=seed)
        source = "mock"
    else:
        paths = {
            name: gold_path(settings, name)
            for name in ("customer_features", "limit_labels")
        }
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            raise typer.BadParameter(
                f"falta Gold: {missing}. Corre `radia-etl gold` o usa --mock"
            )
        features = read_parquet(paths["customer_features"])
        labels = read_parquet(paths["limit_labels"])
        source = "gold"

    _use_experiment(settings, tracking_uri, EXPERIMENT)
    with mlflow.start_run(run_name=f"{source}-seed{seed}") as run:
        _, evaluations = run_experiment(
            features, labels, seed=seed, test_size=test_size, data_source=source
        )
    for name, ev in evaluations.items():
        shown = ", ".join(f"{k}={v:,.3f}" for k, v in ev.overall.items())
        typer.echo(f"{name:15} {shown}")
    typer.echo(f"Run MLflow: {run.info.run_id} ({source})")
    if mock:
        typer.echo("Aviso: datos mock. Estas métricas no se reportan.")


INTENT_EXPERIMENT = "intent-classifier"
INTENT_TABLES = ("call_center_interactions", "call_transcripts")


@app.command()
def intent(
    mock: Annotated[
        bool, typer.Option(help="Llamadas mock. Las métricas no cuentan.")
    ] = False,
    seed: int = 0,
    test_size: float = 0.2,
    tracking_uri: Annotated[
        str | None,
        typer.Option(
            help="Por defecto sqlite en data/local/mlflow.db (no versionado)."
        ),
    ] = None,
) -> None:
    """Entrena el clasificador de intención, lo compara con dos baselines y lo registra."""
    if not 0 < test_size < 1:
        raise typer.BadParameter("--test-size debe estar entre 0 y 1, sin incluirlos")
    settings = get_settings()
    if mock:
        interactions, transcripts = make_mock_calls(n=5000, seed=seed)
        source = "mock"
    else:
        paths = [silver_path(settings, t) for t in INTENT_TABLES]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise typer.BadParameter(
                f"falta Silver: {missing}. Corre `radia-etl silver --tables "
                f"{','.join(INTENT_TABLES)}` o usa --mock"
            )
        interactions, transcripts = (read_parquet(p) for p in paths)
        source = "silver"

    _use_experiment(settings, tracking_uri, INTENT_EXPERIMENT)
    with mlflow.start_run(run_name=f"{source}-seed{seed}") as run:
        evaluations = run_intent_experiment(
            interactions,
            transcripts,
            seed=seed,
            test_size=test_size,
            data_source=source,
        )
    for name, ev in evaluations.items():
        shown = ", ".join(f"{k}={v:,.3f}" for k, v in ev.overall.items())
        typer.echo(f"{name:17} {shown}")
    typer.echo(f"Run MLflow: {run.info.run_id} ({source})")
    if mock:
        typer.echo("Aviso: datos mock. Estas métricas no se reportan.")


@app.command()
def audit(
    only: Annotated[
        str | None,
        typer.Option(
            help=f"Chequeos separados por coma. Opciones: {','.join(AUDITS)}."
        ),
    ] = None,
) -> None:
    """Auditoría de señal: qué etiquetas se pueden predecir. Escribe un JSON."""
    names = [n.strip() for n in only.split(",") if n.strip()] if only else None
    unknown = set(names or []) - set(AUDITS)
    if unknown:
        raise typer.BadParameter(f"chequeos desconocidos: {sorted(unknown)}")
    settings = get_settings()
    results = run_audit(settings, names)
    out = settings.data_dir / "reports" / "signal_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, result in results.items():
        typer.echo(f"{name:13} {json.dumps(result, ensure_ascii=False)[:160]}")
    typer.echo(f"Reporte: {out}")
