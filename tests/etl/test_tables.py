"""Tests de las specs declarativas de tablas."""

import unicodedata

import pytest
from pydantic import ValidationError

from radia.contracts.common import Country, ProductFamily, values
from radia.etl.tables import TABLES, TableSpec, select_tables


def test_specs_consistentes():
    for spec in TABLES.values():
        assert set(spec.primary_key) <= spec.columns.keys()
        if spec.order_by:
            assert spec.order_by in spec.columns
        for fk in spec.foreign_keys:
            assert fk.column in spec.columns
            assert fk.ref_column in TABLES[fk.ref_table].columns


def test_dimensiones_antes_que_hechos():
    names = list(TABLES)
    assert names.index("customers") < names.index("products")
    assert names.index("products") < names.index("transactions")


def test_select_tables_respeta_orden_y_rechaza_desconocidas():
    assert [t.name for t in select_tables("transactions, customers")] == [
        "customers",
        "transactions",
    ]
    assert len(select_tables(None)) == len(TABLES)
    with pytest.raises(ValueError, match="campaign_sends"):
        select_tables("campaign_sends")


def test_value_map_claves_y_destinos_en_el_vocabulario_de_contratos():
    assert TABLES["customers"].value_map.keys() == {"country"}
    assert TABLES["products"].value_map.keys() == {"product_type"}
    assert TABLES["customers"].value_map["country"] == {"México": "Mexico"}
    assert set(TABLES["products"].value_map["product_type"]) == {
        "Tarjeta Crédito",
        "Préstamo Personal",
        "Préstamo Hipotecario",
    }
    for spec in TABLES.values():
        assert spec.value_map.keys() <= spec.columns.keys()
    assert set(TABLES["customers"].value_map["country"].values()) <= set(
        values(Country)
    )
    assert set(TABLES["products"].value_map["product_type"].values()) <= set(
        values(ProductFamily)
    )


def _spec_con_value_map(value_map):
    base = TABLES["customers"]
    return TableSpec.model_validate({**base.model_dump(), "value_map": value_map})


def test_value_map_sobre_columna_inexistente_falla_nombrandola():
    with pytest.raises(ValidationError, match="columna_fantasma"):
        _spec_con_value_map({"columna_fantasma": {"a": "b"}})


def test_value_map_claves_nfd_quedan_en_nfc():
    nfd = unicodedata.normalize("NFD", "México")
    assert nfd != "México"
    spec = _spec_con_value_map({"country": {nfd: "Mexico"}})
    assert list(spec.value_map["country"]) == ["México"]


def test_value_map_vacio_falla_nombrando_la_columna():
    with pytest.raises(ValidationError, match="country"):
        TableSpec.model_validate(
            TABLES["customers"].model_dump() | {"value_map": {"country": {}}}
        )
