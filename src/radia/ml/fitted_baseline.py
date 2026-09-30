"""Baseline fuerte del cupo: múltiplo del ingreso ajustado con train, por familia.

El baseline oficial (`baseline.py`) usa múltiplos fijos a mano. Este aprende de
train el cociente `cupo / ingreso` de cada familia:

- Cupo sugerido: mediana del cociente × ingreso.
- Rango: percentiles del cociente (por defecto 10 y 90) × ingreso, la misma
  cobertura nominal que el modelo (80 %). Así la comparación es pareja.

Si el modelo no le gana a este baseline, las features no aportan más que el ingreso.
"""

from typing import Self

import numpy as np
import pandas as pd

from radia.contracts.common import ProductCode
from radia.contracts.ml import LimitPrediction
from radia.ml.dataset import TARGET
from radia.ml.limit_model import QUANTILES


class FittedIncomeMultipleBaseline:
    version = "baseline-fitted-income-multiple-0.1.0"

    def __init__(self, quantiles: tuple[float, float, float] = QUANTILES) -> None:
        low, mid, high = quantiles
        if not 0 < low < mid < high < 1:
            raise ValueError("se exige 0 < piso < sugerido < techo < 1")
        self.quantiles = quantiles
        # familia -> (múltiplo piso, sugerido, techo)
        self.multiples: dict[str, tuple[float, float, float]] = {}

    def fit(self, table: pd.DataFrame) -> Self:
        """`table` sale de `build_training_table`. Solo usa filas con ingreso > 0."""
        rows = table[table["monthly_income_usd"] > 0]
        if rows.empty:
            raise ValueError("sin filas con ingreso > 0 para ajustar el baseline")
        # Un cupo 0 deja múltiplos en 0 y LimitPrediction (gt=0) falla después.
        limits = rows[TARGET].to_numpy(dtype="float64")
        if not (np.isfinite(limits) & (limits > 0)).all():
            raise ValueError("se exigen cupos finitos y > 0")
        ratio = rows[TARGET] / rows["monthly_income_usd"]
        by_family = ratio.groupby(rows["product_family"].astype(str), observed=True)
        self.multiples = {
            family: tuple(float(v) for v in np.quantile(values, self.quantiles))
            for family, values in by_family
        }
        return self

    def predict_table(self, table: pd.DataFrame) -> pd.DataFrame:
        """`lower`, `pred` y `upper` en USD, en el orden de `table`."""
        if not self.multiples:
            raise RuntimeError("el baseline no está ajustado")
        family = table["product_family"].astype(str)
        unknown = sorted(set(family) - set(self.multiples))
        if unknown:
            raise ValueError(f"familias sin múltiplo ajustado: {unknown}")
        income = table["monthly_income_usd"]
        low, mid, high = (
            family.map({f: m[i] for f, m in self.multiples.items()}) * income
            for i in range(3)
        )
        return pd.DataFrame(
            {"lower": low, "pred": mid, "upper": high}, index=table.index
        )

    def predict(
        self, features: pd.DataFrame, product_code: ProductCode
    ) -> list[LimitPrediction]:
        """Cumple `LimitModel` (C4). Clientes sin ingreso (o con 0) no reciben predicción."""
        code = ProductCode(product_code)
        with_income = features[features["monthly_income_usd"] > 0]
        if with_income.empty:
            return []
        out = self.predict_table(with_income.assign(product_family=code.family.value))
        return [
            LimitPrediction(
                customer_id=customer_id,
                product_code=code,
                suggested_limit_usd=row.pred,
                lower_usd=row.lower,
                upper_usd=row.upper,
                model_version=self.version,
            )
            for customer_id, row in zip(
                with_income["customer_id"], out.itertuples(), strict=True
            )
        ]
