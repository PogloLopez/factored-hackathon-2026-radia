"""Baseline oficial del modelo de cupo: un múltiplo fijo del ingreso mensual.

Cumple `LimitModel` (C4), así que también es el sustituto del modelo real: la
política y el job de ofertas funcionan con él desde el primer día. Los
múltiplos son provisionales, igual que los topes de la política.
"""

from types import MappingProxyType

import pandas as pd

from radia.contracts.common import ProductCode
from radia.contracts.ml import LimitPrediction

MULTIPLES = MappingProxyType(
    {
        ProductCode.CC_BASIC: 1.0,
        ProductCode.CC_GOLD: 2.0,
        ProductCode.CC_BLACK: 4.0,
        ProductCode.PERSONAL_LOAN: 6.0,
        ProductCode.MORTGAGE: 60.0,
    }
)
# Ancho del rango de negociación alrededor del cupo sugerido (±20 %).
RANGE = 0.2


class IncomeMultipleBaseline:
    version = "baseline-income-multiple-0.1.0"

    def predict(
        self, features: pd.DataFrame, product_code: ProductCode
    ) -> list[LimitPrediction]:
        """`features` cumple C1. Clientes sin ingreso (o con 0) no reciben predicción."""
        multiple = MULTIPLES[ProductCode(product_code)]
        with_income = features[features["monthly_income_usd"] > 0]
        suggested = with_income["monthly_income_usd"] * multiple
        return [
            LimitPrediction(
                customer_id=customer_id,
                product_code=product_code,
                suggested_limit_usd=value,
                lower_usd=value * (1 - RANGE),
                upper_usd=value * (1 + RANGE),
                model_version=self.version,
            )
            for customer_id, value in zip(
                with_income["customer_id"], suggested, strict=True
            )
        ]
