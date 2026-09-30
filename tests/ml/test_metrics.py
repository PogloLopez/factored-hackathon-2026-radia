"""Tests de radia.ml.metrics."""

import pandas as pd
import pytest

from radia.ml.metrics import limit_metrics, metrics_by_group


def _results() -> pd.DataFrame:
    # Errores absolutos 10, 50, 0 -> APE 0.10, 0.25, 0.0
    return pd.DataFrame(
        {
            "y_true": [100.0, 200.0, 400.0],
            "pred": [110.0, 150.0, 400.0],
            "lower": [90.0, 160.0, 380.0],
            "upper": [120.0, 190.0, 420.0],
        }
    )


def test_metricas_calculadas_a_mano():
    m = limit_metrics(_results())
    assert m["n"] == 3.0
    assert m["mae_usd"] == pytest.approx(20.0)
    assert m["median_ape"] == pytest.approx(0.10)
    assert m["mean_ape"] == pytest.approx(0.35 / 3)
    # 100 y 400 caen dentro del rango; 200 queda fuera de [160, 190]
    assert m["coverage"] == pytest.approx(2 / 3)
    # anchos relativos: 30/110, 30/150 = 0.2, 40/400 = 0.1 -> mediana 0.2
    assert m["median_width_pct"] == pytest.approx(0.2)


def test_prediccion_perfecta():
    df = pd.DataFrame(
        {"y_true": [100.0], "pred": [100.0], "lower": [100.0], "upper": [100.0]}
    )
    m = limit_metrics(df)
    assert m["mae_usd"] == 0.0
    assert m["median_ape"] == 0.0
    assert m["coverage"] == 1.0
    assert m["median_width_pct"] == 0.0


def test_los_limites_del_rango_cuentan_como_cubiertos():
    df = pd.DataFrame(
        {
            "y_true": [100.0, 200.0],
            "pred": [100.0, 200.0],
            "lower": [100.0, 150.0],
            "upper": [120.0, 200.0],
        }
    )
    assert limit_metrics(df)["coverage"] == 1.0


def test_columnas_faltantes():
    df = _results().drop(columns=["lower", "upper"])
    with pytest.raises(ValueError, match=r"faltan columnas: \['lower', 'upper'\]"):
        limit_metrics(df)


def test_dataframe_vacio():
    with pytest.raises(ValueError, match="sin filas"):
        limit_metrics(_results().iloc[0:0])


def test_columnas_extra_se_ignoran():
    df = _results().assign(country="MX")
    assert limit_metrics(df)["n"] == 3.0


def test_por_grupo_una_fila_por_categoria():
    df = pd.concat(
        [
            _results().assign(country="MX"),
            pd.DataFrame(
                {
                    "y_true": [100.0],
                    "pred": [120.0],
                    "lower": [130.0],
                    "upper": [150.0],
                    "country": ["CO"],
                }
            ),
        ],
        ignore_index=True,
    )
    out = metrics_by_group(df, "country")
    assert list(out.index) == ["CO", "MX"]  # ordenado
    assert out.index.name == "country"
    assert out.loc["MX", "mae_usd"] == pytest.approx(20.0)
    assert out.loc["MX", "n"] == 3.0
    assert out.loc["CO", "mae_usd"] == pytest.approx(20.0)
    assert out.loc["CO", "median_ape"] == pytest.approx(0.2)
    assert out.loc["CO", "coverage"] == 0.0  # 100 < lower=130
    assert out.loc["CO", "median_width_pct"] == pytest.approx(20 / 120)


def test_por_grupo_categorico_omite_categorias_sin_filas():
    df = _results().assign(
        country=pd.Categorical(["MX", "MX", "MX"], categories=["MX", "CO", "AR"])
    )
    out = metrics_by_group(df, "country")
    assert list(out.index) == ["MX"]


def test_por_grupo_columna_inexistente():
    with pytest.raises(KeyError):
        metrics_by_group(_results(), "country")


@pytest.mark.parametrize("col", ["y_true", "pred", "lower", "upper"])
def test_nulos_en_columnas_de_metricas(col):
    df = _results()
    df.loc[0, col] = None
    with pytest.raises(ValueError, match="hay nulos en y_true, pred, lower o upper"):
        limit_metrics(df)


@pytest.mark.parametrize("col", ["y_true", "pred"])
@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_y_true_y_pred_deben_ser_positivos(col, bad):
    df = _results()
    df.loc[1, col] = bad
    with pytest.raises(ValueError, match="y_true y pred deben ser > 0"):
        limit_metrics(df)


def test_lower_mayor_que_upper():
    df = _results()
    df.loc[2, "lower"] = 500.0  # upper=420
    with pytest.raises(ValueError, match=r"lower <= upper"):
        limit_metrics(df)


def test_lower_igual_a_upper_es_valido():
    df = _results()
    df.loc[0, ["lower", "upper"]] = 100.0
    assert limit_metrics(df)["n"] == 3.0


def test_por_grupo_nulos_en_la_columna_by():
    df = _results().assign(country=["MX", None, "CO"])
    with pytest.raises(ValueError, match="hay nulos en country"):
        metrics_by_group(df, "country")


def test_por_grupo_propaga_validacion_de_entrada():
    df = _results().assign(country="MX")
    df.loc[0, "y_true"] = 0.0
    with pytest.raises(ValueError, match="y_true y pred deben ser > 0"):
        metrics_by_group(df, "country")
