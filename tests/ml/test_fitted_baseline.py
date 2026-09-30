"""Tests de radia.ml.fitted_baseline."""

import numpy as np
import pandas as pd
import pytest

from radia.contracts.common import ProductCode
from radia.contracts.ml import LimitModel, LimitPrediction
from radia.ml.fitted_baseline import FittedIncomeMultipleBaseline

CC = "Credit Card"
LOAN = "Personal Loan"


def _tabla() -> pd.DataFrame:
    """CC: cocientes 1..5 (ingreso 1000). Préstamo: cocientes 2 y 4 (ingreso 500)."""
    return pd.DataFrame(
        {
            "product_family": [CC] * 5 + [LOAN] * 2,
            "monthly_income_usd": [1000.0] * 5 + [500.0] * 2,
            "credit_limit_usd": [1000.0, 2000, 3000, 4000, 5000, 1000, 2000],
        },
        index=list("abcdefg"),
    )


def test_multiplos_por_familia_a_mano():
    model = FittedIncomeMultipleBaseline().fit(_tabla())
    assert model.multiples[CC] == pytest.approx((1.4, 3.0, 4.6))
    assert model.multiples[LOAN] == pytest.approx((2.2, 3.0, 3.8))
    assert model.multiples[CC] == pytest.approx(
        tuple(np.quantile([1, 2, 3, 4, 5], (0.1, 0.5, 0.9)))
    )


def test_cuantiles_personalizados():
    model = FittedIncomeMultipleBaseline((0.25, 0.5, 0.75)).fit(_tabla())
    assert model.multiples[CC] == pytest.approx((2.0, 3.0, 4.0))


def test_predict_table_ordenado_y_conserva_indice():
    table = _tabla()
    out = FittedIncomeMultipleBaseline().fit(table).predict_table(table)
    assert list(out.index) == list(table.index)
    assert (out["lower"] <= out["pred"]).all()
    assert (out["pred"] <= out["upper"]).all()
    assert out.loc["a", "pred"] == pytest.approx(3000.0)
    assert out.loc["f", "lower"] == pytest.approx(2.2 * 500)
    assert out.loc["f", "upper"] == pytest.approx(3.8 * 500)


def test_ajuste_ignora_ingreso_cero_negativo_o_nan():
    sucia = pd.concat(
        [
            _tabla(),
            pd.DataFrame(
                {
                    "product_family": [CC] * 3,
                    "monthly_income_usd": [0.0, -10.0, np.nan],
                    "credit_limit_usd": [99999.0] * 3,
                }
            ),
        ],
        ignore_index=True,
    )
    model = FittedIncomeMultipleBaseline().fit(sucia)
    assert model.multiples[CC] == pytest.approx((1.4, 3.0, 4.6))


def test_fit_sin_filas_con_ingreso_da_value_error():
    table = _tabla().assign(monthly_income_usd=[0.0, np.nan] * 3 + [-1.0])
    with pytest.raises(ValueError, match="ingreso"):
        FittedIncomeMultipleBaseline().fit(table)


def test_predict_table_sin_fit_da_runtime_error():
    with pytest.raises(RuntimeError, match="ajustado"):
        FittedIncomeMultipleBaseline().predict_table(_tabla())


def test_familia_desconocida_da_value_error_que_la_nombra():
    model = FittedIncomeMultipleBaseline().fit(_tabla())
    nueva = _tabla().assign(product_family="Mortgage")
    with pytest.raises(ValueError, match="Mortgage"):
        model.predict_table(nueva)


@pytest.mark.parametrize(
    "quantiles",
    [(0.5, 0.5, 0.9), (0.9, 0.5, 0.1), (0.0, 0.5, 0.9), (0.1, 0.5, 1.0)],
)
def test_cuantiles_invalidos_dan_value_error(quantiles):
    with pytest.raises(ValueError, match="piso"):
        FittedIncomeMultipleBaseline(quantiles)


def test_predict_cumple_limit_model_y_omite_sin_ingreso():
    model: LimitModel = FittedIncomeMultipleBaseline().fit(_tabla())
    assert model.version.startswith("baseline-")
    features = pd.DataFrame(
        {
            "customer_id": ["C1", "C2", "C3", "C4"],
            "monthly_income_usd": [2000.0, np.nan, 0.0, 1000.0],
        }
    )
    preds = model.predict(features, ProductCode.CC_GOLD)
    assert [p.customer_id for p in preds] == ["C1", "C4"]
    assert all(isinstance(p, LimitPrediction) for p in preds)
    assert preds[0].suggested_limit_usd == pytest.approx(6000.0)
    assert preds[0].lower_usd == pytest.approx(2800.0)
    assert preds[0].upper_usd == pytest.approx(9200.0)
    assert preds[0].product_code == ProductCode.CC_GOLD
    assert preds[0].model_version == model.version


def test_predict_usa_la_familia_del_producto():
    model = FittedIncomeMultipleBaseline().fit(_tabla())
    features = pd.DataFrame({"customer_id": ["C1"], "monthly_income_usd": [1000.0]})
    (pred,) = model.predict(features, "PERSONAL_LOAN")
    assert pred.suggested_limit_usd == pytest.approx(3000.0)
    assert pred.lower_usd == pytest.approx(2200.0)


def test_predict_sin_nadie_con_ingreso_devuelve_lista_vacia():
    model = FittedIncomeMultipleBaseline().fit(_tabla())
    features = pd.DataFrame({"customer_id": ["C1"], "monthly_income_usd": [np.nan]})
    assert model.predict(features, ProductCode.CC_BASIC) == []


@pytest.mark.parametrize("bad", [0.0, -1.0, np.nan, np.inf])
def test_fit_rechaza_cupos_invalidos(bad):
    tabla = _tabla()
    tabla.loc["a", "credit_limit_usd"] = bad
    with pytest.raises(ValueError, match="cupos finitos"):
        FittedIncomeMultipleBaseline().fit(tabla)
