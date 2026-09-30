"""Tests de las specs declarativas de tablas."""

import pytest

from radia.contracts.common import Country, ProductFamily, values
from radia.etl.tables import TABLES, select_tables


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
