"""Modelo de cupo sugerido (C4) con rango de negociación por cuantiles.

Tres gradient boosting con pérdida cuantil sobre el logaritmo del cupo: el
cuantil bajo es el piso del rango, la mediana el cupo sugerido y el alto el
techo. El logaritmo no cambia los cuantiles (es monótono) y estabiliza cupos
que van de cientos a cientos de miles de USD.

Cumple `LimitModel`, así que reemplaza al baseline sin tocar a los consumidores.

Limitación: la etiqueta (C2) trae la familia del producto, no el nivel de la
tarjeta. CC_BASIC, CC_GOLD y CC_BLACK reciben la misma predicción y la política
la recorta al tope de cada nivel.
"""

from typing import Self

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from radia.contracts.common import ProductCode
from radia.contracts.ml import LimitPrediction
from radia.ml.dataset import TARGET, to_model_matrix

# Cuantiles de (piso, sugerido, techo). 0.1-0.9: rango nominal del 80 %.
QUANTILES = (0.1, 0.5, 0.9)


class QuantileLimitModel:
    version = "limit-quantile-gbm-0.1.0"

    def __init__(
        self,
        quantiles: tuple[float, float, float] = QUANTILES,
        seed: int = 0,
        max_iter: int = 300,
        learning_rate: float = 0.05,
    ) -> None:
        low, mid, high = quantiles
        if not 0 < low < mid < high < 1:
            raise ValueError("se exige 0 < piso < sugerido < techo < 1")
        self.quantiles = quantiles
        self._models = [
            HistGradientBoostingRegressor(
                loss="quantile",
                quantile=q,
                max_iter=max_iter,
                learning_rate=learning_rate,
                categorical_features="from_dtype",
                random_state=seed,
            )
            for q in quantiles
        ]
        self._fitted = False

    def fit(self, table: pd.DataFrame) -> Self:
        """`table` sale de `build_training_table`. Cupos en USD, todos > 0 (C2)."""
        x = to_model_matrix(table)
        y = np.log(table[TARGET].to_numpy(dtype="float64"))
        for model in self._models:
            model.fit(x, y)
        self._fitted = True
        return self

    def predict_table(self, table: pd.DataFrame) -> pd.DataFrame:
        """`lower`, `pred` y `upper` en USD, en el orden de `table`."""
        if not self._fitted:
            raise RuntimeError("el modelo no está entrenado")
        x = to_model_matrix(table)
        raw = np.column_stack([m.predict(x) for m in self._models])
        # Los cuantiles se entrenan por separado y pueden cruzarse: se ordenan.
        low, mid, high = np.exp(np.sort(raw, axis=1)).T
        return pd.DataFrame(
            {"lower": low, "pred": mid, "upper": high}, index=table.index
        )

    def predict(
        self, features: pd.DataFrame, product_code: ProductCode
    ) -> list[LimitPrediction]:
        """`features` cumple C1. Clientes sin ingreso (o con 0) no reciben predicción."""
        code = ProductCode(product_code)
        with_income = features[features["monthly_income_usd"] > 0]
        if with_income.empty:
            return []
        table = with_income.assign(product_family=code.family.value)
        out = self.predict_table(table)
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
