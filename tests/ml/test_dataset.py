"""Tests de radia.ml.dataset."""

import importlib
import warnings

import pandas as pd
import pandera.errors as pa_errors
import pytest

import radia.contracts.data.gold_features as gold_features_module
import radia.ml.dataset as dataset_module
from radia.contracts.data.gold_features import (
    LIMIT_MODEL_EXCLUDED_FEATURES,
    make_gold_features,
)
from radia.contracts.data.gold_labels import make_limit_labels
from radia.ml.dataset import (
    CATEGORICAL_FEATURES,
    FEATURES,
    GROUP,
    NUMERIC_FEATURES,
    TARGET,
    build_training_table,
    split_by_customer,
    to_model_matrix,
)


@pytest.fixture
def mocks():
    features = make_gold_features(300, seed=1)
    labels = make_limit_labels(features, seed=1)
    return features, labels


def test_features_sin_leakage():
    assert not set(FEATURES) & set(LIMIT_MODEL_EXCLUDED_FEATURES)


def test_tabla_una_fila_por_producto(mocks):
    features, labels = mocks
    table = build_training_table(features, labels)
    assert len(table) == len(labels)
    assert table["product_id"].is_unique
    assert list(table.columns) == [
        "product_id",
        GROUP,
        "snapshot_date",
        *FEATURES,
        TARGET,
    ]


def test_etiqueta_sin_features_del_dueno_se_descarta(mocks):
    features, labels = mocks
    huerfanos = features.iloc[:10]["customer_id"]
    table = build_training_table(features.iloc[10:], labels)
    assert not table[GROUP].isin(huerfanos).any()
    assert len(table) == (~labels[GROUP].isin(huerfanos)).sum()


def test_snapshot_distinto_no_une(mocks):
    _, labels = mocks
    otras = make_gold_features(300, seed=1, snapshot_date="2026-05-17")
    assert build_training_table(otras, labels).empty


def test_features_invalidas_fallan(mocks):
    features, labels = mocks
    with pytest.raises(pa_errors.SchemaError):
        build_training_table(features.drop(columns=["credit_score"]), labels)


def test_matriz_del_modelo(mocks):
    table = build_training_table(*mocks)
    x = to_model_matrix(table)
    assert list(x.columns) == list(FEATURES)
    assert all(x[c].dtype == "float64" for c in NUMERIC_FEATURES)
    for col, cats in CATEGORICAL_FEATURES.items():
        assert list(x[col].cat.categories) == list(cats)
    assert x["credit_score"].isna().any()  # los nulos de C1 pasan como NaN


def test_categorias_fijas_aunque_falte_un_valor(mocks):
    table = build_training_table(*mocks)
    parcial = table[table["country"] == table["country"].iloc[0]]
    x = to_model_matrix(parcial)
    assert len(x["country"].cat.categories) == len(CATEGORICAL_FEATURES["country"])


def test_categoria_desconocida_queda_nula(mocks):
    table = build_training_table(*mocks).head(3).copy()
    table["country"] = "XX"
    assert to_model_matrix(table)["country"].isna().all()


def test_split_sin_clientes_compartidos(mocks):
    table = build_training_table(*mocks)
    train, test = split_by_customer(table)
    assert not set(train[GROUP]) & set(test[GROUP])
    assert len(train) + len(test) == len(table)
    assert not test.empty


def test_split_reproducible_y_semilla_cambia(mocks):
    table = build_training_table(*mocks)
    a = split_by_customer(table, seed=5)[1]
    b = split_by_customer(table, seed=5)[1]
    c = split_by_customer(table, seed=6)[1]
    pd.testing.assert_frame_equal(a, b)
    assert set(a[GROUP]) != set(c[GROUP])


def test_split_respeta_test_size(mocks):
    table = build_training_table(*mocks)
    _, test = split_by_customer(table, test_size=0.3)
    assert test[GROUP].nunique() == pytest.approx(0.3 * table[GROUP].nunique(), abs=2)


def test_split_tabla_vacia_falla(mocks):
    table = build_training_table(*mocks).iloc[0:0]
    with pytest.raises(ValueError):
        split_by_customer(table)


def test_matriz_sin_warnings_con_valores_fuera_de_vocabulario(mocks):
    table = build_training_table(*mocks).head(4).copy()
    valido = table["country"].iloc[0]
    table["country"] = ["XX", valido, None, "YY"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        x = to_model_matrix(table)
    assert x["country"].isna().tolist() == [True, False, True, True]
    assert x["country"].iloc[1] == valido


def test_guarda_de_leakage_lanza_runtime_error(monkeypatch):
    monkeypatch.setattr(
        gold_features_module,
        "LIMIT_MODEL_EXCLUDED_FEATURES",
        (*LIMIT_MODEL_EXCLUDED_FEATURES, "credit_score"),
    )
    try:
        with pytest.raises(RuntimeError, match="leakage"):
            importlib.reload(dataset_module)
    finally:
        monkeypatch.undo()
        importlib.reload(dataset_module)
