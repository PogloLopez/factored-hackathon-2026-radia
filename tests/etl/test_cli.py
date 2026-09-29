"""Tests de la CLI del ETL. Settings sin archivo de entorno y S3 simulado con moto."""

import tempfile
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from radia.config import Settings
from radia.etl import cli

runner = CliRunner()


@pytest.fixture
def settings(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp, mock_aws():
        s = Settings(
            _env_file=None,
            s3_bucket_name="test-bucket",
            aws_default_region="us-east-1",
            data_dir=Path(tmp),
        )
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket="test-bucket")
        c.put_object(Bucket="test-bucket", Key="data/customers.csv", Body=b"id\nC1\n")
        monkeypatch.setattr(cli, "get_settings", lambda: s)
        yield s


def test_manifest_imprime_resumen_y_guarda(settings):
    result = runner.invoke(cli.app, ["manifest", "--tables", "customers"])
    assert result.exit_code == 0, result.output
    assert "customers" in result.output
    assert list(settings.manifest_dir.glob("manifest_*.json"))


def test_manifest_rechaza_tablas_fuera_de_alcance(settings):
    result = runner.invoke(cli.app, ["manifest", "--tables", "digital_events"])
    assert result.exit_code != 0


def test_download_exige_aprobacion(settings):
    runner.invoke(cli.app, ["manifest", "--tables", "customers"])
    path = next(settings.manifest_dir.glob("manifest_*.json"))
    result = runner.invoke(cli.app, ["download", str(path)])
    assert result.exit_code != 0
    assert not settings.raw_dir.exists()


def test_download_aprobado_baja_una_vez(settings):
    runner.invoke(cli.app, ["manifest", "--tables", "customers"])
    path = next(settings.manifest_dir.glob("manifest_*.json"))
    first = runner.invoke(cli.app, ["download", str(path), "--approved"])
    assert first.exit_code == 0, first.output
    assert "Descargados: 1" in first.output
    second = runner.invoke(cli.app, ["download", str(path), "--approved"])
    assert "Descargados: 0" in second.output


def test_sin_bucket_falla(monkeypatch):
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, s3_bucket_name=None)
    )
    result = runner.invoke(cli.app, ["manifest"])
    assert result.exit_code != 0


def test_bronze_y_silver_por_cli(raw_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: raw_settings)
    result = runner.invoke(cli.app, ["bronze", "--tables", "customers,products"])
    assert result.exit_code == 0, result.output
    assert (raw_settings.data_dir / "bronze" / "products.parquet").exists()
    result = runner.invoke(cli.app, ["silver", "--tables", "customers,products"])
    assert result.exit_code == 0, result.output
    assert "customers" in result.output
    assert (raw_settings.data_dir / "quality" / "products.json").exists()


def test_bronze_rechaza_tablas_sin_spec(raw_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: raw_settings)
    result = runner.invoke(cli.app, ["bronze", "--tables", "campaign_sends"])
    assert result.exit_code != 0


def test_gold_y_score_por_cli(silver_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: silver_settings)
    result = runner.invoke(cli.app, ["gold", "--snapshot", "2026-06-17"])
    assert result.exit_code == 0, result.output
    assert "Corte: 2026-06-17" in result.output
    assert "customer_features" in result.output
    assert (silver_settings.data_dir / "gold" / "limit_labels.parquet").exists()
    result = runner.invoke(cli.app, ["score"])
    assert result.exit_code == 0, result.output
    # C3 y C4 no tienen credit_score o ingreso.
    assert "4 clientes, 2 sin puntaje" in result.output
    assert (silver_settings.data_dir / "gold" / "internal_score.parquet").exists()


def test_score_sin_gold_falla(silver_settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: silver_settings)
    result = runner.invoke(cli.app, ["score"])
    assert result.exit_code != 0
