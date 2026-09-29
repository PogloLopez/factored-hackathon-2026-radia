"""Tests de las specs declarativas de tablas."""

import pytest

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
