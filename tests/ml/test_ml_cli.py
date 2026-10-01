"""Tests de la CLI de ML. Settings apuntan a tmp_path; MLflow usa sqlite temporal."""

import json
import re

import pytest
from typer.testing import CliRunner

from radia.config import Settings
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.etl.gold import gold_path
from radia.etl.offers import write_parquet
from radia.etl.silver import silver_path
from radia.ml import cli
from radia.ml.intent import make_mock_calls

runner = CliRunner()

# En GitHub Actions Typer colorea (ANSI) y enmarca los errores en un recuadro
# que parte el texto al ancho de la terminal. Se compara sin nada de eso.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NOISE = re.compile(r"[\s│─╭╮╰╯|+]")


def _contains(output: str, text: str) -> bool:
    plain = _NOISE.sub("", _ANSI.sub("", output))
    return _NOISE.sub("", text) in plain


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
    assert _contains(result.output, "radia-etl gold")
    assert not (tmp_path / "mlflow.db").exists()


def test_train_con_gold_parcial_falla(settings, tmp_path):
    features = make_gold_features(n=200, seed=0)
    write_parquet(features, gold_path(settings, "customer_features"))
    result = runner.invoke(cli.app, ["train", "--tracking-uri", _uri(tmp_path)])
    assert result.exit_code != 0
    assert _contains(result.output, "limit_labels")


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
    assert _contains(result.output, "test-size")


def test_train_guarda_artefactos_en_data_dir(settings, tmp_path):
    result = runner.invoke(
        cli.app, ["train", "--mock", "--tracking-uri", _uri(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    csvs = list((settings.data_dir / "mlartifacts").rglob("*.csv"))
    assert csvs, "los CSV por grupo deberían quedar en data_dir/mlartifacts"


def test_train_con_experimento_borrado_explica_como_restaurar(settings, tmp_path):
    import mlflow

    uri = _uri(tmp_path)
    assert (
        runner.invoke(cli.app, ["train", "--mock", "--tracking-uri", uri]).exit_code
        == 0
    )
    mlflow.set_tracking_uri(uri)
    mlflow.delete_experiment(
        mlflow.get_experiment_by_name(cli.EXPERIMENT).experiment_id
    )
    result = runner.invoke(cli.app, ["train", "--mock", "--tracking-uri", uri])
    assert result.exit_code != 0
    assert _contains(result.output, "restore")


# --- intent ---


def test_intent_mock_imprime_tres_lineas_y_aviso(settings, tmp_path):
    result = runner.invoke(
        cli.app, ["intent", "--mock", "--tracking-uri", _uri(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    lineas = result.output.splitlines()
    for nombre in ("model ", "baseline_majority", "baseline_keywords"):
        assert any(line.startswith(nombre) for line in lineas), result.output
    assert "(mock)" in result.output
    assert "Aviso: datos mock" in result.output


def test_intent_sin_silver_falla_y_sugiere_radia_etl_silver(settings, tmp_path):
    result = runner.invoke(cli.app, ["intent", "--tracking-uri", _uri(tmp_path)])
    assert result.exit_code != 0
    assert _contains(result.output, "radia-etl silver")
    assert not (tmp_path / "mlflow.db").exists()


def test_intent_con_silver_usa_data_source_silver(settings, tmp_path):
    inter, trans = make_mock_calls(n=800, seed=0)
    write_parquet(inter, silver_path(settings, "call_center_interactions"))
    write_parquet(trans, silver_path(settings, "call_transcripts"))
    result = runner.invoke(cli.app, ["intent", "--tracking-uri", _uri(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "(silver)" in result.output
    assert "Aviso: datos mock" not in result.output
    assert (tmp_path / "mlflow.db").exists()


@pytest.mark.parametrize("size", ["0", "1", "1.5", "-0.2"])
def test_intent_rechaza_test_size_fuera_de_rango(settings, tmp_path, size):
    result = runner.invoke(
        cli.app,
        ["intent", "--mock", "--test-size", size, "--tracking-uri", _uri(tmp_path)],
    )
    assert result.exit_code != 0
    assert _contains(result.output, "test-size")


def test_audit_only_desconocido_se_rechaza(settings):
    result = runner.invoke(cli.app, ["audit", "--only", "xxx"])
    assert result.exit_code != 0
    assert _contains(result.output, "chequeos desconocidos")


def test_audit_sin_silver_sale_0_y_escribe_reporte_con_error(settings):
    result = runner.invoke(cli.app, ["audit", "--only", "intent"])
    assert result.exit_code == 0, result.output
    report = settings.data_dir / "reports" / "signal_audit.json"
    assert report.exists()
    assert "error" in json.loads(report.read_text(encoding="utf-8"))["intent"]
