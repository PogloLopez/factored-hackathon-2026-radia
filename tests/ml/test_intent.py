"""Tests de radia.ml.intent."""

import numpy as np
import pandas as pd
import pytest
from pandas.errors import MergeError

from radia.ml.intent import (
    LABEL,
    TEXT,
    IntentModel,
    KeywordBaseline,
    MajorityBaseline,
    build_intent_table,
    evaluate_intent,
    intent_metrics,
    make_mock_calls,
)


@pytest.fixture(scope="module")
def tabla() -> pd.DataFrame:
    interactions, transcripts = make_mock_calls(n=600, seed=1)
    return build_intent_table(interactions, transcripts)


def _split(tabla: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    corte = int(len(tabla) * 0.7)
    return tabla.iloc[:corte], tabla.iloc[corte:].reset_index(drop=True)


def _crudo(textos, etiquetas, acentos=None):
    n = len(textos)
    ids = [f"I{i}" for i in range(n)]
    interactions = pd.DataFrame({"interaction_id": ids, "reason_category": etiquetas})
    transcripts = pd.DataFrame(
        {
            "interaction_id": ids,
            "customer_id": [f"C{i}" for i in range(n)],
            "customer_text": textos,
            "detected_accent": acentos or ["Mexican"] * n,
        }
    )
    return interactions, transcripts


# --- build_intent_table ---


def test_tabla_une_por_interaction_id_y_renombra_columnas():
    inter, trans = make_mock_calls(n=50, seed=0)
    tabla = build_intent_table(inter, trans)
    assert len(tabla) == 50
    assert {TEXT, LABEL, "accent", "interaction_id", "customer_id"} <= set(
        tabla.columns
    )
    esperado = inter.set_index("interaction_id")["reason_category"]
    assert (
        tabla[LABEL].to_numpy() == esperado.loc[tabla["interaction_id"]].to_numpy()
    ).all()


def test_tabla_descarta_interacciones_sin_transcripcion():
    inter, trans = make_mock_calls(n=10, seed=0)
    tabla = build_intent_table(inter, trans.iloc[:6])
    assert len(tabla) == 6


def test_tabla_descarta_texto_vacio_o_nulo_y_etiqueta_nula():
    inter, trans = _crudo(
        ["hola", "   ", None, "buen dia", "otro texto"],
        ["A", "A", "A", None, "B"],
    )
    tabla = build_intent_table(inter, trans)
    assert list(tabla[TEXT]) == ["hola", "otro texto"]
    assert list(tabla[LABEL]) == ["A", "B"]
    assert list(tabla.index) == [0, 1]


def test_tabla_acento_faltante_es_unknown():
    inter, trans = _crudo(["uno", "dos"], ["A", "B"], ["Mexican", None])
    tabla = build_intent_table(inter, trans)
    assert list(tabla["accent"]) == ["mexican", "unknown"]


def test_tabla_recorta_espacios_del_texto():
    inter, trans = _crudo(["  hola  "], ["A"])
    assert build_intent_table(inter, trans)[TEXT].iloc[0] == "hola"


def test_tabla_interaction_id_duplicado_en_interactions_falla():
    inter, trans = _crudo(["uno", "dos"], ["A", "B"])
    inter = pd.concat([inter, inter.iloc[[0]]], ignore_index=True)
    with pytest.raises(MergeError):
        build_intent_table(inter, trans)


def test_tabla_acento_se_normaliza_a_minusculas():
    inter, trans = _crudo(["uno", "dos"], ["A", "B"], ["MEXICAN", "Colombian"])
    assert list(build_intent_table(inter, trans)["accent"]) == [
        "mexican",
        "colombian",
    ]


# --- modelos ---


def test_modelo_aprende_el_mock(tabla):
    train, test = _split(tabla)
    modelo = IntentModel().fit(train)
    pred = modelo.predict(test[TEXT])
    assert len(pred) == len(test)
    assert intent_metrics(test[LABEL], pred)["accuracy"] > 0.9


def test_mayoritaria_predice_siempre_la_moda_y_tiene_accuracy_baja(tabla):
    train, test = _split(tabla)
    base = MajorityBaseline().fit(train)
    pred = base.predict(test[TEXT])
    assert set(pred) == {train[LABEL].mode().iloc[0]}
    assert intent_metrics(test[LABEL], pred)["accuracy"] < 0.4


def test_keywords_aprende_el_mock(tabla):
    train, test = _split(tabla)
    base = KeywordBaseline().fit(train)
    pred = base.predict(test[TEXT])
    assert intent_metrics(test[LABEL], pred)["accuracy"] > 0.9
    assert set(base.keywords_) == set(train[LABEL])
    assert all(len(kw) <= base.k for kw in base.keywords_.values())


def test_keywords_sin_coincidencias_predice_la_mayoritaria(tabla):
    train, _ = _split(tabla)
    base = KeywordBaseline().fit(train)
    pred = base.predict(pd.Series(["zzzz qqqq", "xyzxyz"]))
    assert list(pred) == [base.default_, base.default_]
    assert base.default_ == train[LABEL].mode().iloc[0]


@pytest.mark.parametrize("nulo", [np.nan, None])
def test_keywords_predict_tolera_nulos_y_devuelve_la_por_defecto(tabla, nulo):
    train, _ = _split(tabla)
    base = KeywordBaseline().fit(train)
    pred = base.predict(pd.Series([nulo, "quiero una queja", nulo], dtype=object))
    assert pred[0] == base.default_
    assert pred[2] == base.default_
    assert pred[1] == "Complaint"


@pytest.mark.parametrize("frecuente", ["A", "B"])
def test_keywords_empate_gana_la_clase_mas_frecuente_en_train(frecuente):
    otra = "B" if frecuente == "A" else "A"
    # "comun" es keyword de ambas clases; "solo_a"/"solo_b" las distinguen.
    textos = [f"comun solo_{frecuente.lower()}"] * 3 + [f"comun solo_{otra.lower()}"]
    etiquetas = [frecuente] * 3 + [otra]
    inter, trans = _crudo(textos, etiquetas)
    base = KeywordBaseline().fit(build_intent_table(inter, trans))
    assert "comun" in base.keywords_["A"] and "comun" in base.keywords_["B"]
    assert base.priority_[0] == frecuente
    assert list(base.predict(pd.Series(["comun"]))) == [frecuente]


def test_keywords_solo_salen_de_train(tabla):
    train, _ = _split(tabla)
    base = KeywordBaseline().fit(train)
    antes = {k: set(v) for k, v in base.keywords_.items()}
    palabra = "palabrainventadaxyz"
    base.predict(pd.Series([f"{palabra} quiero una queja"]))
    assert base.keywords_ == antes
    assert all(palabra not in kw for kw in base.keywords_.values())
    # Reajustar con train idéntico da las mismas keywords, sin influencia de test.
    assert KeywordBaseline().fit(train).keywords_ == antes


def test_keywords_k_limita_cantidad_por_clase(tabla):
    train, _ = _split(tabla)
    base = KeywordBaseline(k=2).fit(train)
    assert all(len(kw) <= 2 for kw in base.keywords_.values())


# --- métricas ---


def test_metricas_con_valores_a_mano():
    y_true = pd.Series(["A", "A", "B", "B"])
    y_pred = np.array(["A", "B", "B", "B"], dtype=object)
    m = intent_metrics(y_true, y_pred)
    assert m["n"] == 4.0
    assert m["accuracy"] == pytest.approx(0.75)
    # F1 A = 2*1*0.5/1.5 = 2/3; F1 B = 2*(2/3)*1/(5/3) = 0.8
    assert m["f1_macro"] == pytest.approx((2 / 3 + 0.8) / 2)


def test_metricas_vacias_lanzan_value_error():
    with pytest.raises(ValueError, match="sin filas"):
        intent_metrics(pd.Series([], dtype=object), np.array([], dtype=object))


def test_evaluate_intent_devuelve_una_fila_por_acento(tabla):
    _, test = _split(tabla)
    ev = evaluate_intent(test, MajorityBaseline().fit(test).predict(test[TEXT]))
    grupo = ev.by_group["accent"]
    assert set(grupo.index) == set(test["accent"].unique())
    assert len(grupo) == test["accent"].nunique()
    assert grupo.index.name == "accent"
    assert grupo["n"].sum() == len(test)
    assert ev.overall["n"] == len(test)


def test_metricas_labels_fijos_bajan_el_f1_si_falta_una_clase():
    y_true = pd.Series(["A", "A", "B", "B"])
    y_pred = np.array(["A", "A", "B", "B"], dtype=object)
    sin = intent_metrics(y_true, y_pred)
    con = intent_metrics(y_true, y_pred, labels=["A", "B", "C"])
    assert sin["f1_macro"] == pytest.approx(1.0)
    # C no aparece ni en test ni en pred: F1 0 -> (1 + 1 + 0) / 3
    assert con["f1_macro"] == pytest.approx(2 / 3)
    assert con["f1_macro"] < sin["f1_macro"]
    assert con["accuracy"] == sin["accuracy"] == pytest.approx(1.0)


def test_evaluate_intent_pasa_labels_a_global_y_por_grupo():
    test = pd.DataFrame(
        {
            LABEL: ["A", "B", "A", "B"],
            "accent": ["mexican", "mexican", "colombian", "colombian"],
        }
    )
    pred = np.array(["A", "B", "A", "B"], dtype=object)
    sin = evaluate_intent(test, pred)
    con = evaluate_intent(test, pred, labels=["A", "B", "C"])
    assert sin.overall["f1_macro"] == pytest.approx(1.0)
    assert con.overall["f1_macro"] == pytest.approx(2 / 3)
    grupo = con.by_group["accent"]
    assert grupo["f1_macro"].to_numpy() == pytest.approx([2 / 3, 2 / 3])
    assert sin.by_group["accent"]["f1_macro"].to_numpy() == pytest.approx([1, 1])
