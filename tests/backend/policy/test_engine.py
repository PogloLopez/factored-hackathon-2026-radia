"""Tests de radia.backend.policy.engine (C7).

La matriz esperada se escribe a mano desde [[propuesta]], sección 4, y no se
lee del YAML: si alguien cambia el YAML sin cambiar la propuesta, esto falla.
"""

import pytest

from radia.backend.policy.engine import RulesPolicy
from radia.contracts.common import AttentionLevel as L
from radia.contracts.common import Band, Exposure, ProductCode
from radia.contracts.ml import LimitPrediction, RiskEstimate
from radia.contracts.policy import (
    CustomerRequest,
    EligibilityPolicy,
    PolicyDecision,
    PolicyInput,
)

POLICY = RulesPolicy()

# Puntajes lejos de todo umbral (550, 700, 850) para no caer en zona gris.
SCORE = {Band.EXCELLENT: 920, Band.HIGH: 775, Band.MEDIUM: 625, Band.LOW: 300}
PRODUCT = {
    Exposure.LOW: ProductCode.CC_BASIC,
    Exposure.MEDIUM: ProductCode.PERSONAL_LOAN,
    Exposure.HIGH: ProductCode.MORTGAGE,
}
MATRIX = {
    Band.EXCELLENT: {Exposure.LOW: L.AUTOMATIC, Exposure.MEDIUM: L.AUTOMATIC},
    Band.HIGH: {Exposure.LOW: L.AUTOMATIC, Exposure.MEDIUM: L.AUTOMATIC},
    Band.MEDIUM: {Exposure.LOW: L.AUTOMATIC, Exposure.MEDIUM: L.ANALYST},
    Band.LOW: {
        Exposure.LOW: L.ANALYST,
        Exposure.MEDIUM: L.NOT_ELIGIBLE,
        Exposure.HIGH: L.NOT_ELIGIBLE,
    },
}
for _band in (Band.EXCELLENT, Band.HIGH, Band.MEDIUM):
    MATRIX[_band][Exposure.HIGH] = L.ANALYST_AND_ADVISOR


def prediction(product=ProductCode.CC_GOLD, suggested=400.0, lower=300.0, upper=450.0):
    return LimitPrediction(
        customer_id="c1",
        product_code=product,
        suggested_limit_usd=suggested,
        lower_usd=lower,
        upper_usd=upper,
        model_version="limit-v1",
    )


def make_input(
    product=ProductCode.CC_GOLD,
    request: dict | None = None,
    with_prediction=True,
    **over,
) -> PolicyInput:
    base = {
        "customer_id": "c1",
        "customer_status": "Active",
        "segment": "Plus",
        "max_days_past_due": 0,
        "monthly_income_usd": 3000.0,
        "score": 775,
        "limit_prediction": prediction(product) if with_prediction else None,
        "request": CustomerRequest(product_code=product, **(request or {})),
    }
    return PolicyInput(**{**base, **over})


def decide(**kwargs) -> PolicyDecision:
    return POLICY.decide(make_input(**kwargs))


# --- Interfaz e invariantes ------------------------------------------------


def test_satisfies_protocol():
    policy: EligibilityPolicy = POLICY
    assert policy.version == "synthetic-policy-0.1.0"


def test_decision_carries_version_and_is_synthetic():
    d = decide()
    assert d.policy_version == POLICY.version
    assert d.synthetic_policy is True
    assert d.customer_id == "c1"
    assert d.product_code == ProductCode.CC_GOLD


def test_deterministic():
    inp = make_input(request={"customer_requests_human": True}, score=560)
    first = POLICY.decide(inp)
    assert all(POLICY.decide(inp) == first for _ in range(20))
    assert RulesPolicy().decide(inp) == first


def test_codes_are_snake_case():
    d = decide(
        score=560,
        segment="Premium",
        monthly_income_usd=None,
        request={"customer_requests_human": True, "requested_amount_usd": 9999.0},
    )
    for code in d.reasons + d.alerts:
        assert code == code.lower()
        assert " " not in code


# --- Matriz: una prueba por celda ------------------------------------------


@pytest.mark.parametrize(
    ("band", "exposure"),
    [(b, e) for b in Band for e in Exposure],
    ids=lambda v: str(v),
)
def test_matrix_cell(band, exposure):
    product = PRODUCT[exposure]
    expected = MATRIX[band][exposure]
    d = decide(product=product, score=SCORE[band])
    assert d.band == band
    assert d.exposure == exposure
    assert d.attention_level == expected
    assert f"band_{band}" in d.reasons
    assert f"exposure_{exposure}" in d.reasons
    if expected == L.NOT_ELIGIBLE:
        assert d.offered_limit_usd is None
    else:
        assert d.offered_limit_usd == 400.0
        assert d.limit_model_version == "limit-v1"


# --- Exclusiones -------------------------------------------------------------


@pytest.mark.parametrize("status", ["Inactive", "Suspended", "Closed"])
def test_status_exclusion(status):
    d = decide(customer_status=status, score=920)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert f"customer_status_{status.lower()}" in d.reasons
    assert d.offered_limit_usd is None
    assert d.alternative_product_code is None


def test_days_past_due_exclusion():
    d = decide(max_days_past_due=31, score=920)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert "days_past_due_above_limit" in d.reasons


def test_days_past_due_at_limit_is_not_excluded():
    d = decide(max_days_past_due=30, score=920)
    assert d.attention_level == L.AUTOMATIC


def test_both_exclusions_listed():
    d = decide(customer_status="Suspended", max_days_past_due=60)
    assert d.reasons[:2] == ["customer_status_suspended", "days_past_due_above_limit"]


def test_exclusion_with_human_request_goes_to_advisor_without_limit():
    d = decide(
        customer_status="Closed",
        request={"customer_disputes_rejection": True, "customer_requests_human": True},
    )
    assert d.attention_level == L.ADVISOR
    assert "customer_requests_human" in d.reasons
    assert d.offered_limit_usd is None
    assert d.alternative_product_code is None


def test_exclusion_preferential_alone_stays_not_eligible():
    d = decide(customer_status="Suspended", segment="Premium")
    assert d.attention_level == L.NOT_ELIGIBLE
    assert "preferential_segment_exposure" in d.alerts


def test_alternative_is_never_the_requested_product():
    # Banda baja pide CC_BASIC por encima del tope: la exposición sube a media.
    d = decide(
        score=400,
        product=ProductCode.CC_BASIC,
        request={"requested_amount_usd": 600.0},
    )
    assert d.attention_level == L.NOT_ELIGIBLE
    assert d.alternative_product_code != ProductCode.CC_BASIC


def test_exclusion_without_score():
    d = decide(customer_status="Inactive", score=None)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert d.score is None and d.band is None


# --- Datos faltantes -------------------------------------------------------


def test_missing_score_goes_to_analyst():
    d = decide(score=None, product=ProductCode.CC_BASIC)
    assert d.attention_level == L.ANALYST
    assert "missing_data" in d.reasons
    assert "missing_score" in d.reasons
    assert d.score is None and d.band is None


def test_missing_income_goes_to_analyst():
    d = decide(monthly_income_usd=None, score=920)
    assert d.attention_level == L.ANALYST
    assert "missing_data" in d.reasons
    assert "missing_income" in d.reasons


def test_missing_score_and_income_single_missing_data():
    d = decide(score=None, monthly_income_usd=None)
    assert d.reasons.count("missing_data") == 1


def test_missing_income_keeps_matrix_not_eligible():
    d = decide(monthly_income_usd=None, score=300, product=ProductCode.MORTGAGE)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert "missing_income" in d.alerts


# --- Excepciones al analista ---------------------------------------------


@pytest.mark.parametrize("score", [535, 550, 565, 685, 715, 835, 865])
def test_gray_zone_goes_to_analyst(score):
    d = decide(score=score, product=ProductCode.CC_BASIC)
    assert d.attention_level == L.ANALYST
    assert "score_in_gray_zone" in d.reasons


@pytest.mark.parametrize("score", [534, 566, 684, 716, 834, 866])
def test_outside_gray_zone(score):
    d = decide(score=score, product=ProductCode.CC_BASIC)
    assert "score_in_gray_zone" not in d.reasons


def test_declared_income_mismatch_goes_to_analyst():
    d = decide(score=920, request={"declared_monthly_income_usd": 3601.0})
    assert d.attention_level == L.ANALYST
    assert "declared_income_mismatch" in d.reasons


def test_declared_income_within_tolerance():
    d = decide(score=920, request={"declared_monthly_income_usd": 3600.0})
    assert d.attention_level == L.AUTOMATIC


def test_declared_income_lower_also_counts():
    d = decide(score=920, request={"declared_monthly_income_usd": 2000.0})
    assert "declared_income_mismatch" in d.reasons


def test_risk_discrepancy_goes_to_analyst():
    risk = RiskEstimate(customer_id="c1", prob_delinquent_30p=0.35, model_version="r1")
    d = decide(score=920, risk_estimate=risk)
    assert d.attention_level == L.ANALYST
    assert "risk_model_discrepancy" in d.reasons


def test_low_risk_does_not_escalate():
    risk = RiskEstimate(customer_id="c1", prob_delinquent_30p=0.34, model_version="r1")
    assert decide(score=920, risk_estimate=risk).attention_level == L.AUTOMATIC


# --- Excepciones al asesor -------------------------------------------------


def test_requests_human_goes_to_advisor():
    d = decide(score=920, request={"customer_requests_human": True})
    assert d.attention_level == L.ADVISOR
    assert "customer_requests_human" in d.reasons
    assert d.offered_limit_usd == 400.0


def test_dispute_goes_to_advisor():
    d = decide(score=920, request={"customer_disputes_rejection": True})
    assert d.attention_level == L.ADVISOR
    assert "customer_disputes_rejection" in d.reasons


def test_dispute_of_matrix_not_eligible_goes_to_advisor_without_limit():
    d = decide(
        score=300,
        product=ProductCode.PERSONAL_LOAN,
        request={"customer_disputes_rejection": True},
    )
    assert d.attention_level == L.ADVISOR
    assert d.offered_limit_usd is None
    assert d.alternative_product_code == ProductCode.CC_BASIC


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        (ProductCode.CC_BASIC, L.AUTOMATIC),
        (ProductCode.CC_GOLD, L.ADVISOR),
        (ProductCode.MORTGAGE, L.ANALYST_AND_ADVISOR),
    ],
)
def test_premium_with_medium_or_high_exposure(product, expected):
    d = decide(score=920, segment="Premium", product=product)
    assert d.attention_level == expected
    assert d.preferential is True
    has_reason = "preferential_segment_exposure" in d.reasons
    assert has_reason == (product != ProductCode.CC_BASIC)


def test_preferential_only_for_premium():
    assert decide(segment="Plus").preferential is False
    assert decide(segment="Premium").preferential is True


def test_analyst_and_advisor_combine():
    d = decide(score=560, request={"customer_requests_human": True})
    assert d.attention_level == L.ANALYST_AND_ADVISOR
    assert "score_in_gray_zone" in d.reasons
    assert "customer_requests_human" in d.reasons


def test_exception_never_lowers_level():
    # Medio x alta ya es analista y asesor; pedir humano no lo baja a asesor.
    d = decide(
        score=625,
        product=ProductCode.MORTGAGE,
        request={"customer_requests_human": True},
    )
    assert d.attention_level == L.ANALYST_AND_ADVISOR


def test_analyst_exception_does_not_rescue_matrix_not_eligible():
    # Zona gris bajo 550 con exposición media: sigue no elegible.
    d = decide(score=545, product=ProductCode.CC_GOLD)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert "score_in_gray_zone" in d.alerts


# --- Exposición y monto pedido ---------------------------------------------


def test_requested_amount_above_cap_raises_exposure():
    d = decide(
        score=625, product=ProductCode.CC_BASIC, request={"requested_amount_usd": 501.0}
    )
    assert d.exposure == Exposure.MEDIUM
    assert d.attention_level == L.ANALYST
    assert "requested_amount_above_product_max" in d.reasons


def test_requested_amount_at_cap_keeps_exposure():
    d = decide(
        score=625, product=ProductCode.CC_BASIC, request={"requested_amount_usd": 500.0}
    )
    assert d.exposure == Exposure.LOW


def test_small_requested_amount_never_lowers_exposure():
    d = decide(
        score=625, product=ProductCode.MORTGAGE, request={"requested_amount_usd": 10.0}
    )
    assert d.exposure == Exposure.HIGH
    assert d.attention_level == L.ANALYST_AND_ADVISOR


def test_requested_amount_on_high_stays_high():
    d = decide(product=ProductCode.CC_BLACK, request={"requested_amount_usd": 1e9})
    assert d.exposure == Exposure.HIGH


# --- Cupo --------------------------------------------------------------------


def test_limit_capped_to_product_max():
    inp = make_input(
        product=ProductCode.CC_BASIC,
        score=920,
        limit_prediction=prediction(ProductCode.CC_BASIC, 800.0, 600.0, 1000.0),
    )
    d = POLICY.decide(inp)
    assert d.attention_level == L.AUTOMATIC
    assert d.offered_limit_usd == 500.0
    assert d.negotiation_min_usd == 500.0
    assert d.negotiation_max_usd == 500.0
    assert "limit_capped_to_product_max" in d.alerts


def test_only_upper_capped_keeps_order():
    inp = make_input(
        product=ProductCode.CC_BASIC,
        score=920,
        limit_prediction=prediction(ProductCode.CC_BASIC, 450.0, 300.0, 900.0),
    )
    d = POLICY.decide(inp)
    assert (d.negotiation_min_usd, d.offered_limit_usd, d.negotiation_max_usd) == (
        300.0,
        450.0,
        500.0,
    )


def test_limit_within_cap_untouched():
    d = decide(score=920)
    assert (d.negotiation_min_usd, d.offered_limit_usd, d.negotiation_max_usd) == (
        300.0,
        400.0,
        450.0,
    )
    assert "limit_capped_to_product_max" not in d.alerts


def test_missing_prediction_turns_automatic_into_analyst():
    d = decide(score=920, with_prediction=False)
    assert d.attention_level == L.ANALYST
    assert "missing_limit_prediction" in d.reasons
    assert d.offered_limit_usd is None


def test_missing_prediction_on_human_level_is_alert():
    d = decide(
        score=920, with_prediction=False, request={"customer_requests_human": True}
    )
    assert d.attention_level == L.ADVISOR
    assert "missing_limit_prediction" in d.alerts
    assert d.offered_limit_usd is None


def test_not_eligible_has_no_limit_and_offers_alternative():
    d = decide(score=300, product=ProductCode.MORTGAGE)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert d.offered_limit_usd is None
    assert d.limit_model_version is None
    assert d.alternative_product_code == ProductCode.CC_BASIC


def test_no_alternative_for_eligible():
    assert decide(score=920).alternative_product_code is None


def test_no_automatic_without_score_or_limit():
    cases = [
        make_input(score=None),
        make_input(with_prediction=False, score=920),
        make_input(monthly_income_usd=None, score=920),
    ]
    for inp in cases:
        assert POLICY.decide(inp).attention_level != L.AUTOMATIC


def test_preferencial_no_rescata_un_no_elegible():
    # Banda baja con exposición media: la matriz dice no elegible.
    d = decide(score=400, segment="Premium", product=ProductCode.CC_GOLD)
    assert d.attention_level == L.NOT_ELIGIBLE
    assert d.preferential is True
    assert d.offered_limit_usd is None


def test_preferencial_con_disputa_si_va_al_asesor():
    d = decide(
        score=400,
        segment="Premium",
        product=ProductCode.CC_GOLD,
        request={"customer_disputes_rejection": True},
    )
    assert d.attention_level == L.ADVISOR
    assert "preferential_segment_exposure" not in d.reasons
