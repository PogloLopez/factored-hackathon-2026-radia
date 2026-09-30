"""Tabla de entrenamiento del modelo de cupo: features C1 unidas a etiquetas C2.

- Una fila por producto de crédito existente (etiqueta de C2) con las features
  del dueño en la misma `snapshot_date`.
- Sin `LIMIT_MODEL_EXCLUDED_FEATURES`: saldo, utilización y deuda sobre ingreso
  se despejan del cupo, usarlas sería leakage.
- El split va por `customer_id`: un cliente con varios productos queda entero
  en train o en test.
"""

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit

from radia.contracts.common import (
    Country,
    CustomerStatus,
    ProductFamily,
    Segment,
    values,
)
from radia.contracts.data import validate
from radia.contracts.data.gold_features import (
    LIMIT_MODEL_EXCLUDED_FEATURES,
    GoldCustomerFeatures,
)
from radia.contracts.data.gold_labels import GoldLimitLabels

TARGET = "credit_limit_usd"
GROUP = "customer_id"

NUMERIC_FEATURES = (
    "credit_score",
    "tenure_months",
    "monthly_income_usd",
    "avg_monthly_inflow_usd_6m",
    "income_stability_6m",
    "n_credit_products",
    "max_days_past_due",
)
# Categorías fijas desde los enums: train y test codifican igual aunque a un
# split le falte algún valor.
CATEGORICAL_FEATURES = {
    "country": values(Country),
    "segment": values(Segment),
    "customer_status": values(CustomerStatus),
    "product_family": values(ProductFamily),
}
FEATURES = NUMERIC_FEATURES + tuple(CATEGORICAL_FEATURES)

assert not set(FEATURES) & set(LIMIT_MODEL_EXCLUDED_FEATURES)


def build_training_table(features: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Une C1 y C2 validados. Una etiqueta sin features del dueño se descarta."""
    features = validate(GoldCustomerFeatures, features)
    labels = validate(GoldLimitLabels, labels)
    table = labels.merge(features, on=["customer_id", "snapshot_date"], how="inner")
    return table[["product_id", GROUP, "snapshot_date", *FEATURES, TARGET]]


def to_model_matrix(table: pd.DataFrame) -> pd.DataFrame:
    """Solo las columnas del modelo, numéricas en float y categóricas con categorías fijas."""
    x = pd.DataFrame(index=table.index)
    for col in NUMERIC_FEATURES:
        x[col] = pd.to_numeric(table[col], errors="coerce").astype("float64")
    for col, categories in CATEGORICAL_FEATURES.items():
        x[col] = pd.Categorical(table[col], categories=categories)
    return x


def split_by_customer(
    table: pd.DataFrame, test_size: float = 0.2, seed: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train y test sin clientes compartidos."""
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_idx, test_idx = next(splitter.split(table, groups=table[GROUP]))
    return table.iloc[train_idx], table.iloc[test_idx]
