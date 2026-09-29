"""C2. Etiquetas Gold para los modelos, separadas de las features (C1).

Productor: ETL. Consumidor: modelos.
- Cupo asignado por producto de crédito existente (modelo de cupo, C4).
- Mora mayor a 30 días después de la fecha de corte de las features (riesgo, C5).
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
    owners = features[features["n_credit_products"] > 0]
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
    cutoff = features["snapshot_date"]
    df = pd.DataFrame(
        {
            "customer_id": features["customer_id"].to_numpy(),
            "feature_cutoff_date": cutoff.to_numpy(),
            "label_date": (cutoff + pd.Timedelta(days=horizon_days)).to_numpy(),
            "delinquent_30p": rng.random(len(features)) < 0.08,
        }
    )
    return validate(GoldDelinquencyLabels, df)
