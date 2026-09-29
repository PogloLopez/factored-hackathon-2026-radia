"""C1. Features Gold por cliente y fecha de corte.

Productor: ETL. Consumidores: modelos, puntaje interno y política.

- Las etiquetas viven en C2, separadas a propósito para evitar leakage.
- Montos en USD. El ingreso del diccionario viene en moneda local y el ETL lo
  convierte con `daily_exchange_rates` a la fecha de corte.
- Solo datos con fecha menor o igual a `snapshot_date`, incluidos los agregados de 6 meses.
- Un cliente sin productos de crédito tiene 0 en saldo, número de productos y
  días de mora, no nulo.
"""

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series

from radia.contracts.common import Country, CustomerStatus, Segment, values
from radia.contracts.data import validate

CONTRACT_VERSION = "0.1.0"

# Features que son consecuencia del cupo asignado. El modelo de cupo (C4) no
# puede usarlas: el cupo se despeja de saldo / utilización. El puntaje y la
# política sí las usan.
LIMIT_MODEL_EXCLUDED_FEATURES = (
    "credit_utilization",
    "total_credit_balance_usd",
    "debt_to_income",
)


class GoldCustomerFeatures(pa.DataFrameModel):
    customer_id: Series[str] = pa.Field(nullable=False)
    snapshot_date: Series[pd.Timestamp] = pa.Field(nullable=False)
    country: Series[str] = pa.Field(isin=values(Country))
    segment: Series[str] = pa.Field(isin=values(Segment))
    customer_status: Series[str] = pa.Field(isin=values(CustomerStatus))
    # El diccionario permite nulos en credit_score e ingreso (~5 % de nulos).
    credit_score: Series[pd.Int64Dtype] = pa.Field(ge=300, le=850, nullable=True)
    tenure_months: Series[int] = pa.Field(ge=0)
    monthly_income_usd: Series[float] = pa.Field(ge=0, nullable=True)
    total_credit_balance_usd: Series[float] = pa.Field(ge=0)
    debt_to_income: Series[float] = pa.Field(ge=0, nullable=True)
    credit_utilization: Series[float] = pa.Field(ge=0, nullable=True)
    avg_monthly_inflow_usd_6m: Series[float] = pa.Field(ge=0, nullable=True)
    # Coeficiente de variación de los ingresos mensuales. Menor es más estable.
    income_stability_6m: Series[float] = pa.Field(ge=0, nullable=True)
    n_credit_products: Series[int] = pa.Field(ge=0)
    max_days_past_due: Series[int] = pa.Field(ge=0)

    class Config:
        strict = True  # una columna nueva exige subir CONTRACT_VERSION
        coerce = True
        unique = ("customer_id", "snapshot_date")


def make_gold_features(
    n: int = 1000, seed: int = 0, snapshot_date: str = "2026-06-17"
) -> pd.DataFrame:
    """Mock que cumple C1. Sirve para construir código, nunca para sacar métricas."""
    rng = np.random.default_rng(seed)
    income = rng.lognormal(mean=7.0, sigma=0.6, size=n)
    balance = rng.gamma(shape=2.0, scale=800.0, size=n)
    credit_score = pd.array(rng.integers(300, 851, size=n), dtype="Int64")
    missing_income = rng.random(n) < 0.05
    credit_score[rng.random(n) < 0.05] = pd.NA
    income[missing_income] = np.nan
    df = pd.DataFrame(
        {
            "customer_id": [f"MOCK{i:06d}" for i in range(n)],
            "snapshot_date": pd.Timestamp(snapshot_date),
            "country": rng.choice(values(Country), size=n),
            "segment": rng.choice(values(Segment), size=n, p=[0.1, 0.25, 0.5, 0.15]),
            "customer_status": rng.choice(
                values(CustomerStatus), size=n, p=[0.85, 0.08, 0.04, 0.03]
            ),
            "credit_score": credit_score,
            "tenure_months": rng.integers(0, 37, size=n),
            "monthly_income_usd": income,
            "total_credit_balance_usd": balance,
            "debt_to_income": balance / income,
            "credit_utilization": rng.uniform(0, 1.2, size=n),
            "avg_monthly_inflow_usd_6m": income * rng.uniform(0.6, 1.2, size=n),
            "income_stability_6m": rng.uniform(0, 1.5, size=n),
            "n_credit_products": rng.integers(0, 5, size=n),
            "max_days_past_due": rng.choice([0, 0, 0, 0, 5, 15, 45, 90], size=n),
        }
    )
    return validate(GoldCustomerFeatures, df)
