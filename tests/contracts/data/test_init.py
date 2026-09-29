"""Tests de radia.contracts.data.validate."""

import pandas as pd
import pandera.pandas as pa
import pytest

from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures, make_gold_features

ERRORS = (pa.errors.SchemaError, pa.errors.SchemaErrors)


def test_validate_devuelve_dataframe_valido():
    df = make_gold_features(n=20)
    out = validate(GoldCustomerFeatures, df)
    assert isinstance(out, pd.DataFrame)
    assert len(out) == 20


def test_validate_resetea_indice():
    df = make_gold_features(n=10)
    df.index = range(100, 110)
    out = validate(GoldCustomerFeatures, df)
    assert list(out.index) == list(range(10))


def test_validate_no_muta_el_original():
    df = make_gold_features(n=10)
    df.index = range(100, 110)
    validate(GoldCustomerFeatures, df)
    assert list(df.index) == list(range(100, 110))


def test_validate_indice_duplicado_valido_no_se_cae():
    df = make_gold_features(n=10)
    df.index = [0] * 10
    assert len(validate(GoldCustomerFeatures, df)) == 10


def test_validate_indice_duplicado_con_datos_invalidos_lanza_error_pandera():
    df = pd.concat([make_gold_features(n=5), make_gold_features(n=5)])
    assert df.index.has_duplicates
    # customer_id duplicado: error real de pandera, no ValueError.
    with pytest.raises(ERRORS) as exc:
        validate(GoldCustomerFeatures, df)
    assert not isinstance(exc.value, ValueError) or isinstance(exc.value, ERRORS)
