"""Tests de radia.ml.train."""

import mlflow
import numpy as np
import pandas as pd
import pytest

from radia.contracts.common import ProductCode
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.ml.baseline import MULTIPLES, RANGE, IncomeMultipleBaseline
from radia.ml.dataset import TARGET, build_training_table, split_by_customer
from radia.ml.train import (
    BASELINE_CODE,
    GROUPS,
    baseline_results,
    evaluate,
    run_experiment,
)


@pytest.fixture(autouse=True)
def mlflow_aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")


@pytest.fixture
def mocks():
    features = make_gold_features(400, seed=1)
    labels = make_limit_labels(features, seed=1)
    return features, labels


def _run(features, labels, **kwargs):
    with mlflow.start_run() as run:
        model, evaluations = run_experiment(features, labels, **kwargs)
    return run, model, evaluations


def test_baseline_results_valores_a_mano_por_familia():
    test = pd.DataFrame(
        {
            "product_family": ["Credit Card", "Personal Loan", "Mortgage"],
            "monthly_income_usd": [1000.0, 1000.0, 1000.0],
        },
        index=[5, 7, 9],
    )
    out = baseline_results(test)
    assert list(out.index) == [5, 7, 9]
    # tarjeta usa CC_GOLD (x2), préstamo x6, hipoteca x60
    assert out["pred"].tolist() == pytest.approx([2000.0, 6000.0, 60000.0])
    assert out["lower"].tolist() == pytest.approx([1600.0, 4800.0, 48000.0])
    assert out["upper"].tolist() == pytest.approx([2400.0, 7200.0, 72000.0])


def test_baseline_results_tarjeta_usa_cc_gold():
    assert BASELINE_CODE["Credit Card"] == ProductCode.CC_GOLD
    test = pd.DataFrame(
        {"product_family": ["Credit Card"], "monthly_income_usd": [500.0]}
    )
    out = baseline_results(test)
    assert out["pred"].iloc[0] == 500.0 * MULTIPLES[ProductCode.CC_GOLD]
    assert out["upper"].iloc[0] == pytest.approx(out["pred"].iloc[0] * (1 + RANGE))


def test_baseline_results_familia_desconocida_falla():
    test = pd.DataFrame({"product_family": ["otra"], "monthly_income_usd": [100.0]})
    with pytest.raises(ValueError, match="otra"):
        baseline_results(test)


def test_evaluate_devuelve_overall_y_by_group_con_las_tres_claves():
    test = pd.DataFrame(
        {
            TARGET: [1000.0, 2000.0, 3000.0, 4000.0],
            "country": ["MX", "MX", "CO", "CO"],
            "segment": ["a", "b", "a", "b"],
            "product_family": ["Credit Card"] * 4,
        }
    )
    preds = pd.DataFrame(
        {
            "pred": [1000.0, 2000.0, 3000.0, 4000.0],
            "lower": [900.0, 1800.0, 2700.0, 3600.0],
            "upper": [1100.0, 2200.0, 3300.0, 4400.0],
        },
        index=test.index,
    )
    ev = evaluate(test, preds)
    assert ev.overall["n"] == 4.0
    assert ev.overall["mae_usd"] == 0.0
    assert ev.overall["coverage"] == 1.0
    assert set(ev.by_group) == set(GROUPS) == {"country", "segment", "product_family"}
    assert list(ev.by_group["country"].index) == ["CO", "MX"]
    assert ev.by_group["country"]["n"].tolist() == [2.0, 2.0]


def test_evaluate_prediccion_no_positiva_falla():
    test = pd.DataFrame(
        {TARGET: [1000.0], "country": ["MX"], "segment": ["a"], "product_family": ["x"]}
    )
    preds = pd.DataFrame({"pred": [0.0], "lower": [0.0], "upper": [0.0]})
    with pytest.raises(ValueError, match="> 0"):
        evaluate(test, preds)


def test_run_experiment_registra_params_y_metricas(mocks):
    features, labels = mocks
    run, model, evaluations = _run(features, labels, seed=3, test_size=0.25)
    data = mlflow.get_run(run.info.run_id).data
    assert data.params["data_source"] == "mock"
    assert data.params["seed"] == "3"
    assert data.params["test_size"] == "0.25"
    assert data.params["model_version"] == model.version
    assert data.params["baseline_version"] == IncomeMultipleBaseline.version
    assert {"n_train", "n_test", "quantiles"} <= set(data.params)
    for name in ("model", "baseline"):
        for key, value in evaluations[name].overall.items():
            assert data.metrics[f"{name}_{key}"] == pytest.approx(value)
    assert set(evaluations) == {"model", "baseline"}


def test_run_experiment_registra_tablas_por_grupo(mocks):
    features, labels = mocks
    run, _, _ = _run(features, labels)
    artifacts = {
        a.path
        for a in mlflow.MlflowClient().list_artifacts(run.info.run_id, "by_group")
    }
    esperados = {f"by_group/{n}_{g}.csv" for n in ("model", "baseline") for g in GROUPS}
    assert artifacts == esperados


def test_run_experiment_data_source_personalizado(mocks):
    features, labels = mocks
    run, _, _ = _run(features, labels, data_source="gold")
    assert mlflow.get_run(run.info.run_id).data.params["data_source"] == "gold"


def test_modelo_y_baseline_tienen_el_mismo_n(mocks):
    features, labels = mocks
    run, _, ev = _run(features, labels)
    assert ev["model"].overall["n"] == ev["baseline"].overall["n"]
    n_test = int(mlflow.get_run(run.info.run_id).data.params["n_test"])
    assert ev["model"].overall["n"] == n_test
    for g in GROUPS:
        assert ev["model"].by_group[g]["n"].sum() == n_test
        assert ev["baseline"].by_group[g]["n"].sum() == n_test


def test_el_test_excluye_ingreso_cero_o_nulo(mocks):
    features, labels = mocks
    features = features.copy()
    features.loc[features.index[:150:2], "monthly_income_usd"] = 0.0
    features.loc[features.index[1:150:2], "monthly_income_usd"] = np.nan
    table = build_training_table(features, labels)
    _, test = split_by_customer(table, test_size=0.2, seed=0)
    esperado = int((test["monthly_income_usd"] > 0).sum())
    assert esperado < len(test)
    run, _, ev = _run(features, labels, seed=0, test_size=0.2)
    assert ev["model"].overall["n"] == esperado
    assert int(mlflow.get_run(run.info.run_id).data.params["n_test"]) == esperado


@pytest.mark.parametrize("ingreso", [0.0, np.nan])
def test_error_si_ningun_producto_de_test_tiene_ingreso(mocks, ingreso):
    features, labels = mocks
    features = features.assign(monthly_income_usd=ingreso)
    with mlflow.start_run(), pytest.raises(ValueError, match="ingreso > 0"):
        run_experiment(features, labels)


def test_run_experiment_sin_run_activo_falla(mocks):
    with pytest.raises(RuntimeError, match="run activo"):
        run_experiment(*mocks)
    assert mlflow.active_run() is None


def test_train_descarta_sin_ingreso_y_registra_descartes(mocks):
    features, labels = mocks
    features = features.copy()
    features.loc[features.index[:40], "monthly_income_usd"] = 0.0
    run, _, _ = _run(features, labels)
    params = mlflow.get_run(run.info.run_id).data.params
    dropped = int(params["n_train_dropped_no_income"]) + int(
        params["n_test_dropped_no_income"]
    )
    assert dropped > 0
    total = build_training_table(features, labels)
    assert int(params["n_train"]) + int(params["n_test"]) + dropped == len(total)


def test_run_experiment_registra_tarjeta_del_baseline(mocks):
    run, _, _ = _run(*mocks)
    params = mlflow.get_run(run.info.run_id).data.params
    assert params["baseline_card_code"] == "CC_GOLD"
