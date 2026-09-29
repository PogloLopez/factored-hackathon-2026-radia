"""C2. Etiquetas Gold para los modelos, separadas de las features (C1).

Productor: ETL. Consumidor: modelos.

Cupo (modelo de cupo, C4):
- Una fila por producto de crédito existente. `snapshot_date` es la misma de C1.
- Convertido a USD desde `products.currency` con `daily_exchange_rates`.
- Productos con `credit_limit` nulo o 0 se descartan.
- Hay varias filas por cliente: el split train/test va por `customer_id`.

Mora (modelo de riesgo, C5):
- Universo: clientes con crédito y sin mora mayor a 30 días al corte. Los que ya
  están en mora los corta la política y, si entraran, la etiqueta se filtraría
  por `max_days_past_due` de C1.
- `days_past_due` nulo en un producto de crédito cuenta como 0.
- La etiqueta se mira después de la fecha de corte de las features.
"""

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series

from radia.contracts.common import ProductFamily, values
from radia.contracts.data import validate

CONTRACT_VERSION = "0.1.0"


class GoldLimitLabels(pa.DataFrameModel):
    product_id: Series[str] = pa.Field(nullable=False)
    customer_id: Series[str] = pa.Field(nullable=False)
    snapshot_date: Series[pd.Timestamp] = pa.Field(nullable=False)
    product_family: Series[str] = pa.Field(isin=values(ProductFamily))
    credit_limit_usd: Series[float] = pa.Field(gt=0)

    class Config:
        strict = True
        coerce = True
        unique = ("product_id", "snapshot_date")


class GoldDelinquencyLabels(pa.DataFrameModel):
    customer_id: Series[str] = pa.Field(nullable=False)
    # Las features se calculan con datos hasta esta fecha, la etiqueta se mira después.
    feature_cutoff_date: Series[pd.Timestamp] = pa.Field(nullable=False)
    label_date: Series[pd.Timestamp] = pa.Field(nullable=False)
    delinquent_30p: Series[bool]

    class Config:
        strict = True
        coerce = True
        unique = ("customer_id", "feature_cutoff_date")

    @pa.dataframe_check
    def label_after_cutoff(cls, df: pd.DataFrame) -> pd.Series:
        return df["label_date"] > df["feature_cutoff_date"]


def make_limit_labels(features: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Mock de C2 (cupos) a partir de features C1. Solo para construir código."""
    rng = np.random.default_rng(seed)
    # Una fila por producto de crédito del cliente.
    owners = features.loc[
        features.index.repeat(features["n_credit_products"].clip(lower=0))
    ]
    df = pd.DataFrame(
        {
            "product_id": [f"MOCKP{i:07d}" for i in range(len(owners))],
            "customer_id": owners["customer_id"].to_numpy(),
            "snapshot_date": owners["snapshot_date"].to_numpy(),
            "product_family": rng.choice(
                values(ProductFamily), size=len(owners), p=[0.7, 0.25, 0.05]
            ),
            "credit_limit_usd": rng.lognormal(mean=7.5, sigma=0.8, size=len(owners)),
        }
    )
    return validate(GoldLimitLabels, df)


def make_delinquency_labels(
    features: pd.DataFrame, seed: int = 0, horizon_days: int = 90
) -> pd.DataFrame:
    """Mock de C2 (mora) a partir de features C1. Solo para construir código."""
    rng = np.random.default_rng(seed)
    universe = features[
        (features["n_credit_products"] > 0) & (features["max_days_past_due"] <= 30)
    ]
    cutoff = universe["snapshot_date"]
    df = pd.DataFrame(
        {
            "customer_id": universe["customer_id"].to_numpy(),
            "feature_cutoff_date": cutoff.to_numpy(),
            "label_date": (cutoff + pd.Timedelta(days=horizon_days)).to_numpy(),
            "delinquent_30p": rng.random(len(universe)) < 0.08,
        }
    )
    return validate(GoldDelinquencyLabels, df)
