"""C4 y C5. Predicciones de los modelos hacia la política.

Productor: modelos (`radia.ml`). Consumidores: política (C7) y job de ofertas (C6).

- C4. Cupo sugerido con su rango de negociación. La política lo recorta a sus
  topes. Un cliente sin ingreso no recibe predicción: la política lo toma como
  dato faltante y manda el caso al analista.
- C5. Probabilidad de mora mayor a 30 días. Alerta de discrepancia contra el
  puntaje determinístico. Fuera del alcance mínimo: la política funciona sin ella.
"""

from typing import Protocol, Self

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from radia.contracts.common import ProductCode

CONTRACT_VERSION = "0.1.0"


class LimitPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    customer_id: str = Field(min_length=1)
    product_code: ProductCode
    suggested_limit_usd: float = Field(gt=0)
    lower_usd: float = Field(gt=0)  # piso del rango de negociación del asesor
    upper_usd: float = Field(gt=0)  # techo del rango de negociación del asesor
    model_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_range(self) -> Self:
        if not self.lower_usd <= self.suggested_limit_usd <= self.upper_usd:
            raise ValueError("se exige lower_usd <= suggested_limit_usd <= upper_usd")
        return self


class RiskEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    customer_id: str = Field(min_length=1)
    prob_delinquent_30p: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1)


class LimitModel(Protocol):
    """Interfaz del modelo de cupo. El baseline de múltiplo de ingreso la cumple."""

    version: str

    def predict(
        self, features: pd.DataFrame, product_code: ProductCode
    ) -> list[LimitPrediction]:
        """`features` cumple C1. Omite a los clientes sin ingreso."""
        ...


class RiskModel(Protocol):
    version: str

    def predict(self, features: pd.DataFrame) -> list[RiskEstimate]:
        """`features` cumple C1."""
        ...
