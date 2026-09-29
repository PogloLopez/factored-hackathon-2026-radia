"""CLI del ETL: `uv run radia-etl --help`."""

from pathlib import Path
from typing import Annotated

import typer

from radia.config import CREDIT_TABLES, get_settings
from radia.etl import s3

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
