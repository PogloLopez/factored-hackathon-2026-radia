"""Clientes demo SINTÉTICOS para evaluación y demostración (test fixture).

No son clientes del dataset. Sus filas C1 y C3 se escriben a mano, se validan
con los contratos y C6 sale del job real (`build_offers`) con el baseline de
cupo y la política de reglas. Así cada nivel de atención viene de la política,
no de este archivo.

Cobertura:
- Un cliente por celda de la matriz banda x exposición (12).
- Uno por excepción: excluido inactivo, mora > 30 días, sin ingreso, sin
  puntaje, zona gris y segmento Premium.
- Riesgo alto (discrepancia del modelo de riesgo) no aplica: el job de C6 no
  recibe estimación de riesgo. Se agrega cuando exista el modelo (C5).

Cada perfil fija un producto representativo y el nivel que la política debe
dar para ese producto. Los tests lo verifican contra C6.

PROVISIONAL. Se reemplazan por clientes reales del dataset cuando Pablo
apruebe la descarga. Ver [[propuesta]], sección 6.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import pandas as pd

from radia.backend.policy.engine import RulesPolicy
from radia.contracts.common import (
    AttentionLevel,
    Band,
    Country,
    CustomerStatus,
    Exposure,
    ProductCode,
    Segment,
)
from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.internal_score import InternalScore
from radia.etl.offers import build_offers
from radia.ml.baseline import IncomeMultipleBaseline

FIXTURE_LABEL = "demo-fixture"
SNAPSHOT_DATE = pd.Timestamp("2026-06-17")
SCORE_VERSION = "demo-fixture-0.1.0"
NAN = math.nan


@dataclass(frozen=True)
class DemoProfile:
    """Qué representa un cliente demo y qué nivel se espera para su producto."""

    customer_id: str
    kind: str  # "cell" o "exception"
    label: str
    description: str
    product_code: ProductCode
    expected_level: AttentionLevel
    # Banda y exposición esperadas en C6. Nulas si no aplican (sin puntaje).
    band: Band | None
    exposure: Exposure
    # Hechos del cliente con los que se arman C1 y C3.
    country: Country
    segment: Segment
    status: CustomerStatus
    score: int | None
    credit_score: int | None
    monthly_income_usd: float
    max_days_past_due: int = 0


def _cell(
    n: int,
    band: Band,
    exposure: Exposure,
    product: ProductCode,
    level: AttentionLevel,
    score: int,
    country: Country,
    segment: Segment,
    income: float,
) -> DemoProfile:
    return DemoProfile(
        customer_id=f"DEMO{n:06d}",
        kind="cell",
        label=f"{band}_x_{exposure}",
        description=f"Banda {band}, exposición {exposure} ({product}).",
        product_code=product,
        expected_level=level,
        band=band,
        exposure=exposure,
        country=country,
        segment=segment,
        status=CustomerStatus.ACTIVE,
        score=score,
        credit_score=min(850, max(300, score - 60)),
        monthly_income_usd=income,
    )


B, E, P, L = Band, Exposure, ProductCode, AttentionLevel
C, S = Country, Segment

_PROFILES: list[DemoProfile] = [
    # Celdas de la matriz. Puntajes lejos de la zona gris (umbral ± 15).
    _cell(1, B.EXCELLENT, E.LOW, P.CC_BASIC, L.AUTOMATIC, 905, C.MEXICO, S.PLUS, 2500),
    _cell(
        2,
        B.EXCELLENT,
        E.MEDIUM,
        P.PERSONAL_LOAN,
        L.AUTOMATIC,
        880,
        C.COLOMBIA,
        S.BASIC,
        1800,
    ),
    _cell(
        3,
        B.EXCELLENT,
        E.HIGH,
        P.MORTGAGE,
        L.ANALYST_AND_ADVISOR,
        920,
        C.ARGENTINA,
        S.PLUS,
        3200,
    ),
    _cell(4, B.HIGH, E.LOW, P.CC_BASIC, L.AUTOMATIC, 760, C.MEXICO, S.BASIC, 1200),
    _cell(5, B.HIGH, E.MEDIUM, P.CC_GOLD, L.AUTOMATIC, 790, C.COLOMBIA, S.PLUS, 1500),
    _cell(
        6,
        B.HIGH,
        E.HIGH,
        P.CC_BLACK,
        L.ANALYST_AND_ADVISOR,
        740,
        C.ARGENTINA,
        S.BASIC,
        2100,
    ),
    _cell(7, B.MEDIUM, E.LOW, P.CC_BASIC, L.AUTOMATIC, 620, C.MEXICO, S.STUDENT, 700),
    _cell(
        8, B.MEDIUM, E.MEDIUM, P.PERSONAL_LOAN, L.ANALYST, 640, C.COLOMBIA, S.BASIC, 950
    ),
    _cell(
        9,
        B.MEDIUM,
        E.HIGH,
        P.MORTGAGE,
        L.ANALYST_AND_ADVISOR,
        600,
        C.ARGENTINA,
        S.PLUS,
        1300,
    ),
    _cell(10, B.LOW, E.LOW, P.CC_BASIC, L.ANALYST, 480, C.MEXICO, S.BASIC, 600),
    _cell(
        11,
        B.LOW,
        E.MEDIUM,
        P.PERSONAL_LOAN,
        L.NOT_ELIGIBLE,
        420,
        C.COLOMBIA,
        S.STUDENT,
        500,
    ),
    _cell(
        12, B.LOW, E.HIGH, P.CC_BLACK, L.NOT_ELIGIBLE, 380, C.ARGENTINA, S.BASIC, 800
    ),
    # Excepciones.
    DemoProfile(
        customer_id="DEMO000013",
        kind="exception",
        label="excluded_inactive",
        description="Cliente inactivo. Excluido antes de la matriz.",
        product_code=P.CC_BASIC,
        expected_level=L.NOT_ELIGIBLE,
        band=B.HIGH,
        exposure=E.LOW,
        country=C.MEXICO,
        segment=S.PLUS,
        status=CustomerStatus.INACTIVE,
        score=780,
        credit_score=720,
        monthly_income_usd=1600,
    ),
    DemoProfile(
        customer_id="DEMO000014",
        kind="exception",
        label="days_past_due_above_30",
        description="Mora vigente de 45 días. Excluido antes de la matriz.",
        product_code=P.CC_BASIC,
        expected_level=L.NOT_ELIGIBLE,
        band=B.HIGH,
        exposure=E.LOW,
        country=C.COLOMBIA,
        segment=S.BASIC,
        status=CustomerStatus.ACTIVE,
        score=760,
        credit_score=700,
        monthly_income_usd=1100,
        max_days_past_due=45,
    ),
    DemoProfile(
        customer_id="DEMO000015",
        kind="exception",
        label="missing_income",
        description="Sin ingreso registrado. Sin puntaje ni cupo: va al analista.",
        product_code=P.CC_BASIC,
        expected_level=L.ANALYST,
        band=None,
        exposure=E.LOW,
        country=C.ARGENTINA,
        segment=S.PLUS,
        status=CustomerStatus.ACTIVE,
        score=None,
        credit_score=710,
        monthly_income_usd=NAN,
    ),
    DemoProfile(
        customer_id="DEMO000016",
        kind="exception",
        label="missing_score",
        description="Sin puntaje de buró, así que sin puntaje interno: va al analista.",
        product_code=P.CC_BASIC,
        expected_level=L.ANALYST,
        band=None,
        exposure=E.LOW,
        country=C.MEXICO,
        segment=S.BASIC,
        status=CustomerStatus.ACTIVE,
        score=None,
        credit_score=None,
        monthly_income_usd=1100,
    ),
    DemoProfile(
        customer_id="DEMO000017",
        kind="exception",
        label="score_gray_zone",
        description="Puntaje 708, a 8 puntos del umbral 700: zona gris, va al analista.",
        product_code=P.CC_BASIC,
        expected_level=L.ANALYST,
        band=B.HIGH,
        exposure=E.LOW,
        country=C.COLOMBIA,
        segment=S.BASIC,
        status=CustomerStatus.ACTIVE,
        score=708,
        credit_score=650,
        monthly_income_usd=1400,
    ),
    DemoProfile(
        customer_id="DEMO000018",
        kind="exception",
        label="premium_medium_exposure",
        description="Segmento Premium con exposición media: trato preferencial, asesor.",
        product_code=P.CC_GOLD,
        expected_level=L.ADVISOR,
        band=B.HIGH,
        exposure=E.MEDIUM,
        country=C.ARGENTINA,
        segment=S.PREMIUM,
        status=CustomerStatus.ACTIVE,
        score=810,
        credit_score=760,
        monthly_income_usd=4000,
    ),
]

DEMO_PROFILES: MappingProxyType[str, DemoProfile] = MappingProxyType(
    {p.customer_id: p for p in _PROFILES}
)


def _feature_row(p: DemoProfile) -> dict:
    income = p.monthly_income_usd
    has_income = not math.isnan(income)
    balance = 0.0 if p.max_days_past_due == 0 else 900.0
    return {
        "customer_id": p.customer_id,
        "snapshot_date": SNAPSHOT_DATE,
        "country": p.country.value,
        "segment": p.segment.value,
        "customer_status": p.status.value,
        "credit_score": p.credit_score,
        "tenure_months": 24,
        "monthly_income_usd": income,
        "total_credit_balance_usd": balance,
        "debt_to_income": balance / income if has_income else NAN,
        "credit_utilization": 0.3 if balance else 0.0,
        "avg_monthly_inflow_usd_6m": income * 0.9 if has_income else NAN,
        "income_stability_6m": 0.2 if has_income else NAN,
        "n_credit_products": 1 if balance else 0,
        "max_days_past_due": p.max_days_past_due,
    }


def demo_features() -> pd.DataFrame:
    """Filas C1 de los clientes demo, validadas."""
    df = pd.DataFrame([_feature_row(p) for p in _PROFILES])
    df["credit_score"] = df["credit_score"].astype("Int64")
    return validate(GoldCustomerFeatures, df)


def demo_scores() -> pd.DataFrame:
    """Filas C3 de los clientes demo, validadas. Desglose ficticio de fixture."""
    rows = [
        {
            "customer_id": p.customer_id,
            "snapshot_date": SNAPSHOT_DATE,
            "score": p.score,
            "breakdown_json": "{}"
            if p.score is None
            else json.dumps(
                {"base": 150, FIXTURE_LABEL.replace("-", "_"): p.score - 150}
            ),
            "score_version": SCORE_VERSION,
        }
        for p in _PROFILES
    ]
    df = pd.DataFrame(rows)
    df["score"] = df["score"].astype("Int64")
    return validate(InternalScore, df)


def demo_offers(generated_at: datetime) -> pd.DataFrame:
    """C6 de los clientes demo con el job real, el baseline de cupo y la política."""
    return build_offers(
        demo_features(),
        demo_scores(),
        IncomeMultipleBaseline(),
        RulesPolicy(),
        generated_at,
    )
