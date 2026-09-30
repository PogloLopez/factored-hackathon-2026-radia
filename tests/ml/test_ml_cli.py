"""Tests de la CLI de ML. Settings apuntan a tmp_path; MLflow usa sqlite temporal."""

import pytest
from typer.testing import CliRunner

from radia.config import Settings
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.etl.gold import gold_path
from radia.etl.offers import write_parquet
from radia.ml import cli

runner = CliRunner()


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    return s


def _uri(tmp_path):
    return f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"


def test_train_mock_imprime_modelo_baseline_y_aviso(settings, tmp_path):
    result = runner.invoke(
        cli.app, ["train", "--mock", "--tracking-uri", _uri(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "model" in result.output
    assert "baseline" in result.output
    assert "(mock)" in result.output
    assert "Aviso: datos mock" in result.output


def test_train_sin_gold_falla_y_sugiere_radia_etl_gold(settings, tmp_path):
    result = runner.invoke(cli.app, ["train", "--tracking-uri", _uri(tmp_path)])
    assert result.exit_code != 0
    assert "radia-etl gold" in " ".join(result.output.split())
    assert not (tmp_path / "mlflow.db").exists()


def test_train_con_gold_parcial_falla(settings, tmp_path):
    features = make_gold_features(n=200, seed=0)
    write_parquet(features, gold_path(settings, "customer_features"))
    result = runner.invoke(cli.app, ["train", "--tracking-uri", _uri(tmp_path)])
    assert result.exit_code != 0
    assert "limit_labels" in " ".join(result.output.split())


def test_train_con_gold_usa_data_source_gold(settings, tmp_path):
    features = make_gold_features(n=2000, seed=0)
    labels = make_limit_labels(features, seed=0)
    write_parquet(features, gold_path(settings, "customer_features"))
    write_parquet(labels, gold_path(settings, "limit_labels"))
    result = runner.invoke(
        cli.app, ["train", "--tracking-uri", _uri(tmp_path), "--seed", "1"]
    )
    assert result.exit_code == 0, result.output
    assert "(gold)" in result.output
    assert "Aviso: datos mock" not in result.output
    assert (tmp_path / "mlflow.db").exists()


def test_train_sin_tracking_uri_crea_mlflow_db_en_data_dir(settings):
    result = runner.invoke(cli.app, ["train", "--mock"])
    assert result.exit_code == 0, result.output
    assert (settings.data_dir / "mlflow.db").exists()


@pytest.mark.parametrize("size", ["0", "1", "1.5", "-0.2"])
def test_train_rechaza_test_size_fuera_de_rango(settings, tmp_path, size):
    result = runner.invoke(
        cli.app,
        ["train", "--mock", "--test-size", size, "--tracking-uri", _uri(tmp_path)],
    )
    assert result.exit_code != 0
    assert "test-size" in " ".join(result.output.split())


def test_train_guarda_artefactos_en_data_dir(settings, tmp_path):
    result = runner.invoke(
        cli.app, ["train", "--mock", "--tracking-uri", _uri(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    csvs = list((settings.data_dir / "mlartifacts").rglob("*.csv"))
    assert csvs, "los CSV por grupo deberían quedar en data_dir/mlartifacts"
