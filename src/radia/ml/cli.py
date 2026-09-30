"""CLI de ML: `uv run radia-ml --help`."""

from typing import Annotated

import mlflow
import typer

from radia.config import get_settings
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.etl.gold import gold_path
from radia.etl.offers import read_parquet
from radia.ml.train import run_experiment

app = typer.Typer(no_args_is_help=True, help="Modelos de Radia.")

EXPERIMENT = "limit-model"


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

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(
        tracking_uri or f"sqlite:///{(settings.data_dir / 'mlflow.db').as_posix()}"
    )
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"{source}-seed{seed}") as run:
        _, evaluations = run_experiment(
            features, labels, seed=seed, test_size=test_size, data_source=source
        )
    for name, ev in evaluations.items():
        shown = ", ".join(f"{k}={v:,.3f}" for k, v in ev.overall.items())
        typer.echo(f"{name:9} {shown}")
    typer.echo(f"Run MLflow: {run.info.run_id} ({source})")
    if mock:
        typer.echo("Aviso: datos mock. Estas métricas no se reportan.")
