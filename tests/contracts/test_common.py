"""Tests de radia.contracts.common."""

import pytest

from radia.contracts.common import (
    AttentionLevel,
    Band,
    Country,
    CustomerStatus,
    Exposure,
    ProductCode,
    ProductFamily,
    Segment,
    values,
)


@pytest.mark.parametrize(
    ("code", "family"),
    [
        (ProductCode.CC_BASIC, ProductFamily.CREDIT_CARD),
        (ProductCode.CC_GOLD, ProductFamily.CREDIT_CARD),
        (ProductCode.CC_BLACK, ProductFamily.CREDIT_CARD),
        (ProductCode.PERSONAL_LOAN, ProductFamily.PERSONAL_LOAN),
        (ProductCode.MORTGAGE, ProductFamily.MORTGAGE),
    ],
)
def test_product_code_family(code, family):
    assert code.family is family


def test_every_product_code_has_a_family():
    for code in ProductCode:
        assert isinstance(code.family, ProductFamily)


def test_family_values_match_products_table():
    assert values(ProductFamily) == ["Credit Card", "Personal Loan", "Mortgage"]


def test_values_returns_plain_strings():
    result = values(Exposure)
    assert result == ["low", "medium", "high"]
    assert all(type(v) is str for v in result)


@pytest.mark.parametrize(
    ("enum", "expected"),
    [
        (Country, ["Mexico", "Colombia", "Argentina"]),
        (Segment, ["Premium", "Plus", "Basic", "Student"]),
        (CustomerStatus, ["Active", "Inactive", "Suspended", "Closed"]),
    ],
)
def test_values_match_data_dictionary(enum, expected):
    assert values(enum) == expected


def test_band_and_attention_values():
    assert values(Band) == ["excellent", "high", "medium", "low"]
    assert values(AttentionLevel) == [
        "automatic",
        "analyst",
        "advisor",
        "analyst_and_advisor",
        "not_eligible",
    ]


def test_strenum_equals_its_string():
    assert Country.MEXICO == "Mexico"
    assert Segment.PREMIUM == "Premium"
    assert CustomerStatus.ACTIVE == "Active"
    assert ProductCode.CC_GOLD == "CC_GOLD"
    assert str(Country.COLOMBIA) == "Colombia"
    assert "Argentina" in list(Country)


def test_invalid_value_raises():
    with pytest.raises(ValueError):
        Country("Chile")


def test_todo_producto_tiene_familia():
    from radia.contracts.common import PRODUCT_FAMILY

    assert set(PRODUCT_FAMILY) == set(ProductCode)
