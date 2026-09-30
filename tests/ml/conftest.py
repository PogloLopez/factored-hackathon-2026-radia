"""MLflow aislado por test: sqlite y artefactos en tmp_path, nunca en el repo."""

import mlflow
import pytest


@pytest.fixture(autouse=True)
def mlflow_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    # Subcarpeta propia: los tests de la CLI revisan tmp_path/mlflow.db.
    root = tmp_path / "_mlflow"
    root.mkdir()
    mlflow.set_tracking_uri(f"sqlite:///{(root / 'tracking.db').as_posix()}")
    # Experimento propio: MLflow recuerda el activo entre tests y, si viene de
    # otra base, falla con "No Experiment with id=...".
    name = "tests"
    mlflow.create_experiment(name, artifact_location=(root / "art").as_uri())
    mlflow.set_experiment(name)
    yield
    while mlflow.active_run():
        mlflow.end_run()
