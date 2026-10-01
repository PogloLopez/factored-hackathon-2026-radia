"""Tests de la auditoría de señal con DataFrames sintéticos (sin datos reales)."""

import numpy as np
import pandas as pd
import pytest

from radia.config import Settings
from radia.ml.signal_audit import _categorical, cv_auc, rate_table_auc, run_audit

N = 2000


def _rng():
    return np.random.default_rng(42)


def test_cv_auc_cerca_de_azar_con_etiqueta_independiente():
    rng = _rng()
    x = pd.DataFrame({"a": rng.normal(size=N), "b": rng.normal(size=N)})
    y = pd.Series(rng.random(N) < 0.3)
    assert abs(cv_auc(x, y) - 0.5) < 0.08


def test_cv_auc_cerca_de_uno_con_etiqueta_determinada_por_feature():
    rng = _rng()
    a = rng.normal(size=N)
    x = pd.DataFrame({"a": a, "ruido": rng.normal(size=N)})
    assert cv_auc(x, pd.Series(a > 0)) > 0.95


def test_cv_auc_una_sola_clase_lanza_value_error():
    x = pd.DataFrame({"a": np.arange(50.0)})
    with pytest.raises(ValueError, match="una sola clase"):
        cv_auc(x, pd.Series([True] * 50))


def test_rate_table_auc_alto_cuando_la_etiqueta_depende_del_grupo():
    rng = _rng()
    groups = pd.Series(rng.choice(["a", "b", "c", "d"], size=N))
    p = groups.map({"a": 0.05, "b": 0.3, "c": 0.7, "d": 0.95}).to_numpy()
    y = pd.Series(rng.random(N) < p)
    assert rate_table_auc(groups, y) > 0.7


def test_rate_table_auc_cerca_de_azar_sin_dependencia():
    rng = _rng()
    groups = pd.Series(rng.choice(["a", "b", "c", "d"], size=N))
    y = pd.Series(rng.random(N) < 0.4)
    assert abs(rate_table_auc(groups, y) - 0.5) < 0.08


def test_categorical_agrupa_en_otras_mas_alla_de_250_categorias():
    # 300 categorías: las 250 más frecuentes se conservan, el resto va a OTRAS.
    values = [f"c{i}" for i in range(300) for _ in range(300 - i)]
    out = _categorical(pd.DataFrame({"cat": values}))["cat"]
    assert out.dtype == "category"
    assert out.nunique() == 251
    assert "OTRAS" in set(out)
    assert (out == "OTRAS").sum() == sum(300 - i for i in range(250, 300))


def test_categorical_deja_numericas_intactas_y_no_muta_la_entrada():
    x = pd.DataFrame({"num": [1.0, 2.0, 3.0], "txt": ["a", None, "b"]})
    out = _categorical(x)
    pd.testing.assert_series_equal(out["num"], x["num"])
    assert "NA" in set(out["txt"])
    assert x["txt"].isna().any()


def test_run_audit_anota_error_cuando_falta_silver(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "data")
    names = ["delinquency", "intent", "calls", "transactions", "churn"]
    out = run_audit(s, names)
    assert list(out) == names
    for name in names:
        assert "error" in out[name]
