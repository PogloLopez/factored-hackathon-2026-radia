"""Tests de radia.contracts.data.active_offers (C6)."""

import pandas as pd
import pandera.pandas as pa
import pytest

from radia.contracts.common import AttentionLevel, ProductCode, values
from radia.contracts.data import validate
from radia.contracts.data.active_offers import (
    ActiveOffers,
    _is_code_list,
    make_active_offers,
)
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.internal_score import make_internal_scores

ERRORS = (pa.errors.SchemaError, pa.errors.SchemaErrors)
NOT_ELIGIBLE = AttentionLevel.NOT_ELIGIBLE


@pytest.fixture
def scores():
    return make_internal_scores(make_gold_features(n=100, seed=1), seed=1)


@pytest.fixture
def offers(scores):
    return make_active_offers(scores, seed=1)


def _eligible_idx(df):
    return df.index[df["attention_level"] != NOT_ELIGIBLE][0]


def test_mock_valida(offers):
    validate(ActiveOffers, offers)
    assert offers["synthetic_policy"].all()


def test_mock_determinista_por_seed(scores):
    a = make_active_offers(scores, seed=5)
    b = make_active_offers(scores, seed=5)
    c = make_active_offers(scores, seed=6)
    pd.testing.assert_frame_equal(a, b)
    assert not a["attention_level"].equals(c["attention_level"])


def test_una_fila_por_cliente_y_producto(offers, scores):
    n_products = len(values(ProductCode))
    assert len(offers) == len(scores) * n_products
    assert not offers.duplicated(["customer_id", "product_code"]).any()
    assert (offers.groupby("customer_id").size() == n_products).all()


def test_band_nulo_donde_score_nulo(offers):
    mask = offers["score"].isna().to_numpy()
    assert mask.any()
    assert offers["band"].isna().to_numpy().tolist() == mask.tolist()


def test_ttl_days_define_vencimiento(scores):
    df = make_active_offers(scores, ttl_days=3)
    assert ((df["expires_at"] - df["generated_at"]) == pd.Timedelta(days=3)).all()


@pytest.mark.parametrize("delta", [pd.Timedelta(0), pd.Timedelta(days=-1)])
def test_falla_expires_no_posterior(offers, delta):
    df = offers.copy()
    df.loc[0, "expires_at"] = df.loc[0, "generated_at"] + delta
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize("factor", [0.5, 1.5])
def test_falla_offered_fuera_de_rango(offers, factor):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, "offered_limit_usd"] = df.loc[i, "negotiation_min_usd"] * factor
    if factor > 1:
        df.loc[i, "offered_limit_usd"] = df.loc[i, "negotiation_max_usd"] * factor
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize(
    "col", ["negotiation_min_usd", "negotiation_max_usd", "offered_limit_usd"]
)
def test_falla_rango_parcialmente_nulo(offers, col):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, col] = None
    if col == "offered_limit_usd":
        # Sigue siendo elegible pero sin cupo, con rango presente.
        assert df.loc[i, "attention_level"] != NOT_ELIGIBLE
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_not_eligible_con_cupo(offers):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, "attention_level"] = NOT_ELIGIBLE
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_pasa_not_eligible_con_todo_nulo(offers):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, "attention_level"] = NOT_ELIGIBLE
    df.loc[i, ["offered_limit_usd", "negotiation_min_usd", "negotiation_max_usd"]] = (
        None
    )
    validate(ActiveOffers, df)


def test_falla_synthetic_policy_false(offers):
    df = offers.copy()
    df.loc[0, "synthetic_policy"] = False
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize(
    "raw", ["no es json", "{}", '{"a": "b"}', "[1, 2]", '["a", 1]', "null"]
)
def test_falla_reasons_json_invalido(offers, raw):
    df = offers.copy()
    df.loc[0, "reasons_json"] = raw
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_reasons_json_lista_vacia(offers):
    df = offers.copy()
    df.loc[0, "reasons_json"] = "[]"
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_alerts_json_admite_lista_vacia_y_rechaza_invalido(offers):
    df = offers.copy()
    df.loc[0, "alerts_json"] = '["declared_income_mismatch"]'
    validate(ActiveOffers, df)
    df.loc[0, "alerts_json"] = "{}"
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_is_code_list_directo():
    assert _is_code_list('["a", "b"]', allow_empty=False)
    assert _is_code_list("[]", allow_empty=True)
    assert not _is_code_list("[]", allow_empty=False)
    assert not _is_code_list('[""]', allow_empty=True)
    assert not _is_code_list("{", allow_empty=True)
    assert not _is_code_list('{"a": 1}', allow_empty=True)
    assert not _is_code_list(None, allow_empty=True)


def test_mock_sin_score_nunca_es_automatico(offers):
    no_score = offers[offers["score"].isna()]
    assert len(no_score) > 0
    assert (no_score["attention_level"] != AttentionLevel.AUTOMATIC).all()


def test_falla_automatico_sin_score(offers):
    df = offers.copy()
    i = df.index[df["score"].isna()][0]
    df.loc[i, "attention_level"] = AttentionLevel.AUTOMATIC
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize("col", ["score", "band"])
def test_falla_score_y_band_no_nulos_juntos(offers, col):
    df = offers.copy()
    i = df.index[df["score"].notna()][0]
    df.loc[i, col] = None
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_cupo_sin_version_de_modelo(offers):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, "limit_model_version"] = None
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_alternativa_de_producto_valida_y_fuera_de_catalogo(offers):
    df = offers.copy()
    i = df.index[df["offered_limit_usd"].isna()][0]
    df.loc[i, "alternative_product_code"] = ProductCode.CC_BASIC.value
    validate(ActiveOffers, df)
    df.loc[i, "alternative_product_code"] = "CRYPTO"
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_offer_id_duplicado(offers):
    df = offers.copy()
    df.loc[1, "offer_id"] = df.loc[0, "offer_id"]
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_cliente_producto_duplicado(offers):
    df = offers.copy()
    df.loc[1, ["customer_id", "product_code"]] = df.loc[
        0, ["customer_id", "product_code"]
    ].to_numpy()
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize("col", ["product_code", "attention_level"])
def test_falla_enum_invalido(offers, col):
    df = offers.copy()
    df.loc[0, col] = "invalido"
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_columna_extra(offers):
    df = offers.assign(extra=1)
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_automatico_sin_cupo(offers):
    df = offers.copy()
    i = df.index[
        (df["attention_level"] == AttentionLevel.AUTOMATIC) & df["score"].notna()
    ][0]
    df.loc[i, ["offered_limit_usd", "negotiation_min_usd", "negotiation_max_usd"]] = (
        None
    )
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize("col", ["reasons_json", "alerts_json"])
def test_falla_codigo_que_no_es_snake_case(offers, col):
    df = offers.copy()
    df.loc[0, col] = '["Banda alta"]'
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_preferential_es_columna_obligatoria(offers):
    assert "preferential" in offers.columns
    with pytest.raises(ERRORS):
        validate(ActiveOffers, offers.drop(columns="preferential"))


def test_falla_codigo_con_salto_de_linea_final(offers):
    df = offers.copy()
    df.loc[0, "reasons_json"] = '["mock_reason\n"]'
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


def test_falla_alternativa_con_cupo(offers):
    df = offers.copy()
    i = _eligible_idx(df)
    df.loc[i, "alternative_product_code"] = ProductCode.CC_BASIC.value
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)


@pytest.mark.parametrize("col", ["exposure", "snapshot_date"])
def test_trazabilidad_obligatoria(offers, col):
    with pytest.raises(ERRORS):
        validate(ActiveOffers, offers.drop(columns=col))


def test_falla_exposicion_fuera_del_enum(offers):
    df = offers.copy()
    df.loc[0, "exposure"] = "extreme"
    with pytest.raises(ERRORS):
        validate(ActiveOffers, df)
