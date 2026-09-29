"""CLI del ETL: `uv run radia-etl --help`."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from radia.config import CREDIT_TABLES, get_settings
from radia.etl import s3
from radia.etl.bronze import build_bronze
from radia.etl.gold import build_features, build_limit_labels, gold_path
from radia.etl.offers import run_offers_job
from radia.etl.score import DEFAULT_WEIGHTS, build_score
from radia.etl.silver import build_silver
from radia.etl.tables import TableSpec, select_tables

app = typer.Typer(no_args_is_help=True, help="Pipeline de datos de Radia.")


def _mb(n: int) -> str:
    return f"{n / 1_000_000:,.1f} MB"


def _require_bucket() -> str:
    bucket = get_settings().s3_bucket_name
    if not bucket:
        raise typer.BadParameter(
            "falta S3_BUCKET_NAME en el entorno (ver .env.example)"
        )
    return bucket


@app.command()
def manifest(
    tables: Annotated[str, typer.Option(help="Tablas separadas por coma.")] = ",".join(
        CREDIT_TABLES
    ),
) -> None:
    """Lista las claves de las tablas pedidas (solo LIST) y guarda el manifiesto."""
    settings = get_settings()
    bucket = _require_bucket()
    names = tuple(t.strip() for t in tables.split(",") if t.strip())
    unknown = set(names) - set(CREDIT_TABLES)
    if unknown:
        raise typer.BadParameter(f"tablas fuera del alcance de crédito: {unknown}")
    result = s3.build_manifest(
        s3.make_client(settings), bucket, settings.s3_prefix, names
    )
    path = s3.save_manifest(result, settings.manifest_dir)
    for table, row in sorted(result.summary().items()):
        typer.echo(f"{table:24} {row['objects']:>7} objetos  {_mb(row['bytes']):>12}")
    typer.echo(
        f"{'TOTAL':24} {len(result.entries):>7} objetos  {_mb(result.total_bytes):>12}"
    )
    typer.echo(f"Manifiesto: {path}")


@app.command()
def download(
    manifest_path: Annotated[Path, typer.Argument(help="Manifiesto aprobado.")],
    approved: Annotated[
        bool,
        typer.Option("--approved", help="Confirma que Pablo aprobó este manifiesto."),
    ] = False,
) -> None:
    """Descarga una sola vez lo pendiente del manifiesto a data/local/raw/."""
    if not approved:
        raise typer.BadParameter(
            "la descarga exige --approved: Pablo revisa el manifiesto antes (checkpoint)"
        )
    settings = get_settings()
    result = s3.load_manifest(manifest_path)
    pending = s3.pending_entries(result, settings.raw_dir)
    typer.echo(
        f"Pendientes: {len(pending)} objetos, {_mb(sum(e.size_bytes for e in pending))}"
    )
    done = s3.download(
        s3.make_client(settings),
        result,
        settings.raw_dir,
        settings.s3_max_concurrency,
    )
    typer.echo(f"Descargados: {len(done)}")


def _specs(tables: str | None) -> list[TableSpec]:
    try:
        return select_tables(tables)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


TablesOption = Annotated[
    str | None,
    typer.Option(help="Tablas separadas por coma. Por defecto, todas las de Silver."),
]


@app.command()
def bronze(tables: TablesOption = None) -> None:
    """Reconstruye Bronze (parquet sin tipar) desde data/local/raw/."""
    settings = get_settings()
    con = duckdb.connect()
    for spec in _specs(tables):
        path = build_bronze(spec, settings, con)
        typer.echo(f"{spec.name:24} {path}")


@app.command()
def silver(tables: TablesOption = None) -> None:
    """Construye Silver y el reporte de calidad desde Bronze."""
    settings = get_settings()
    con = duckdb.connect()
    for spec in _specs(tables):
        r = build_silver(spec, settings, con)
        typer.echo(
            f"{r.table:24} in={r.rows_in:>9} out={r.rows_out:>9} "
            f"dup={r.exact_duplicates_removed} viejas={r.stale_versions_removed} "
            f"cast={sum(r.cast_failures.values())} huerfanos={r.orphans}"
        )
    typer.echo(f"Reportes: {settings.data_dir / 'quality'}")


@app.command()
def gold(
    snapshot: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help="Fecha de corte. Por defecto, la última transacción en Silver.",
        ),
    ] = None,
) -> None:
    """Construye features (C1) y etiquetas de cupo (C2) desde Silver."""
    settings = get_settings()
    cutoff = snapshot.date() if snapshot else None
    features = build_features(settings, cutoff)
    snapshot_date = (
        features["snapshot_date"].iloc[0].date() if len(features) else cutoff
    )
    labels = build_limit_labels(settings, snapshot_date)
    typer.echo(f"Corte: {snapshot_date}")
    typer.echo(f"{'customer_features':24} {len(features):>9} filas")
    typer.echo(f"{'limit_labels':24} {len(labels):>9} filas")
    typer.echo(f"Gold: {gold_path(settings, 'customer_features').parent}")


@app.command()
def score(
    weights: Annotated[
        Path, typer.Option(help="YAML de pesos. Los v0 son provisionales.")
    ] = DEFAULT_WEIGHTS,
) -> None:
    """Calcula el puntaje interno (C3) desde las features Gold."""
    settings = get_settings()
    scores = build_score(settings, weights)
    valid = scores["score"].dropna()
    typer.echo(
        f"{scores['score_version'].iloc[0] if len(scores) else '-'}: "
        f"{len(scores)} clientes, {scores['score'].isna().sum()} sin puntaje"
    )
    if len(valid):
        typer.echo(f"Mediana {valid.median():.0f}, rango {valid.min()} a {valid.max()}")
    typer.echo(f"Salida: {gold_path(settings, 'internal_score')}")


@app.command()
def offers() -> None:
    """Materializa las ofertas vigentes (C6) desde C1 y C3 con la política (C7)."""
    try:
        path = run_offers_job(get_settings())
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Ofertas: {path}")
