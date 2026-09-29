"""C7. Política de elegibilidad: entrada, decisión e interfaz.

Productor: `radia.backend.policy` (función pura, reglas versionadas en YAML).
Consumidores: job de ofertas (C6) y orquestador.

- La política es sintética. No toma decisiones reales de crédito.
- Lo que el cliente dice en el chat (`CustomerRequest`) nunca cambia el
  puntaje ni el cupo. Solo puede activar excepciones hacia un humano, p. ej. un
  ingreso declarado distinto al registrado manda el caso al analista.
- Razones y alertas son códigos en snake_case que la conversación traduce a
  texto. La conversación no inventa razones.
"""

from typing import Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radia.contracts.common import (
    AttentionLevel,
    Band,
    CustomerStatus,
    Exposure,
    ProductCode,
    Segment,
)
from radia.contracts.ml import LimitPrediction, RiskEstimate

CONTRACT_VERSION = "0.1.0"

_FROZEN = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class CustomerRequest(BaseModel):
    """Lo que pide el cliente. Dato no verificado."""

    model_config = _FROZEN

    product_code: ProductCode
    requested_amount_usd: float | None = Field(default=None, gt=0)
    declared_monthly_income_usd: float | None = Field(default=None, ge=0)
    customer_requests_human: bool = False
    customer_disputes_rejection: bool = False


class PolicyInput(BaseModel):
    """Hechos verificados del cliente (C1, C3, C4, C5) más su solicitud."""

    model_config = _FROZEN

    customer_id: str = Field(min_length=1)
    customer_status: CustomerStatus
    segment: Segment
    max_days_past_due: int = Field(ge=0)
    monthly_income_usd: float | None = Field(default=None, ge=0)
    score: int | None = Field(default=None, ge=150, le=950)
    limit_prediction: LimitPrediction | None = None
    risk_estimate: RiskEstimate | None = None
    request: CustomerRequest

    @model_validator(mode="after")
    def check_same_customer_and_product(self) -> Self:
        pred = self.limit_prediction
        if pred and (
            pred.customer_id != self.customer_id
            or pred.product_code != self.request.product_code
        ):
            raise ValueError("limit_prediction no corresponde al cliente o producto")
        if self.risk_estimate and self.risk_estimate.customer_id != self.customer_id:
            raise ValueError("risk_estimate no corresponde al cliente")
        return self


class PolicyDecision(BaseModel):
    model_config = _FROZEN

    customer_id: str = Field(min_length=1)
    product_code: ProductCode
    attention_level: AttentionLevel
    band: Band | None
    exposure: Exposure
    offered_limit_usd: float | None = Field(default=None, gt=0)
    negotiation_min_usd: float | None = Field(default=None, gt=0)
    negotiation_max_usd: float | None = Field(default=None, gt=0)
    reasons: list[str] = Field(min_length=1)
    alerts: list[str] = Field(default_factory=list)
    policy_version: str = Field(min_length=1)
    synthetic_policy: Literal[True] = True

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        limits = (
            self.negotiation_min_usd,
            self.offered_limit_usd,
            self.negotiation_max_usd,
        )
        if self.attention_level == AttentionLevel.NOT_ELIGIBLE and any(
            v is not None for v in limits
        ):
            raise ValueError("una decisión no elegible no ofrece cupo")
        if any(v is None for v in limits) and any(v is not None for v in limits):
            raise ValueError("cupo y rango de negociación van juntos o no van")
        lo, mid, hi = limits
        if mid is not None and not lo <= mid <= hi:
            raise ValueError("se exige negotiation_min <= offered <= negotiation_max")
        return self


class EligibilityPolicy(Protocol):
    version: str

    def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        """Función pura: misma entrada, misma decisión."""
        ...
