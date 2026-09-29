"""Tests de radia.backend.policy.rules: carga y validación del YAML."""

import copy

import pytest
import yaml
from pydantic import ValidationError

from radia.backend.policy.rules import DEFAULT_RULES_PATH, PolicyRules, load_rules
from radia.contracts.common import AttentionLevel, Band, Exposure, ProductCode


def raw_rules() -> dict:
    """El YAML v0 como dict, para mutarlo en cada prueba sin tocar disco."""
    with DEFAULT_RULES_PATH.open(encoding="utf-8") as fh:
        return copy.deepcopy(yaml.safe_load(fh))


def test_v0_yaml_loads():
    rules = load_rules()
    assert rules.synthetic is True
    assert rules.policy_version == "synthetic-policy-0.1.0"
    assert set(rules.products) == set(ProductCode)


def test_v0_yaml_says_it_is_provisional():
    text = DEFAULT_RULES_PATH.read_text(encoding="utf-8")
    assert "PROVISIONAL" in text
    assert "checkpoint de Pablo" in text


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (150, Band.LOW),
        (549, Band.LOW),
        (550, Band.MEDIUM),
        (699, Band.MEDIUM),
        (700, Band.HIGH),
        (849, Band.HIGH),
        (850, Band.EXCELLENT),
        (950, Band.EXCELLENT),
    ],
)
def test_band_for_edges(score, band):
    assert load_rules().band_for(score) == band


def test_band_thresholds():
    assert load_rules().band_thresholds() == [550, 700, 850]


def test_band_with_gap_fails():
    raw = raw_rules()
    raw["bands"]["high"] = [701, 849]
    with pytest.raises(ValidationError, match="contiguas"):
        PolicyRules.model_validate(raw)


def test_overlapping_bands_fail():
    raw = raw_rules()
    raw["bands"]["high"] = [690, 849]
    with pytest.raises(ValidationError, match="contiguas"):
        PolicyRules.model_validate(raw)


def test_bands_must_cover_full_scale():
    raw = raw_rules()
    raw["bands"]["excellent"] = [850, 900]
    with pytest.raises(ValidationError, match="cubrir"):
        PolicyRules.model_validate(raw)


def test_missing_band_fails():
    raw = raw_rules()
    del raw["bands"]["low"]
    with pytest.raises(ValidationError, match="todas las bandas"):
        PolicyRules.model_validate(raw)


def test_inverted_band_fails():
    raw = raw_rules()
    raw["bands"]["low"] = [549, 150]
    with pytest.raises(ValidationError, match="min <= max"):
        PolicyRules.model_validate(raw)


def test_missing_product_fails():
    raw = raw_rules()
    del raw["products"]["MORTGAGE"]
    with pytest.raises(ValidationError, match="productos sin regla"):
        PolicyRules.model_validate(raw)


def test_product_without_cap_fails():
    raw = raw_rules()
    del raw["products"]["CC_GOLD"]["max_limit_usd"]
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(raw)


def test_incomplete_matrix_row_fails():
    raw = raw_rules()
    del raw["matrix"]["medium"]["high"]
    with pytest.raises(ValidationError, match="incompleta"):
        PolicyRules.model_validate(raw)


def test_unknown_attention_level_fails():
    raw = raw_rules()
    raw["matrix"]["low"]["low"] = "maybe"
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(raw)


def test_non_synthetic_fails():
    raw = raw_rules()
    raw["synthetic"] = False
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(raw)


def test_unknown_key_fails():
    raw = raw_rules()
    raw["extra"] = 1
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(raw)


def test_matrix_values_are_attention_levels():
    rules = load_rules()
    for row in rules.matrix.values():
        assert set(row) == set(Exposure)
        assert all(isinstance(level, AttentionLevel) for level in row.values())


def test_rules_are_frozen():
    rules = load_rules()
    with pytest.raises(ValidationError):
        rules.policy_version = "otra"
