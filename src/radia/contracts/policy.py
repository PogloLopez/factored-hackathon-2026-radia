"""C7. Política de elegibilidad: entrada, decisión e interfaz.

Productor: `radia.backend.policy` (función pura, reglas versionadas en YAML).
Consumidores: job de ofertas (C6) y orquestador. Reglas en [[propuesta]], sección 4.

- La política es sintética. No toma decisiones reales de crédito.
- Lo que el cliente dice en el chat (`CustomerRequest`) nunca cambia el
  puntaje ni el cupo. Solo puede activar excepciones hacia un humano, p. ej. un
  ingreso declarado distinto al registrado manda el caso al analista.
- `requested_amount_usd` solo puede subir la exposición sobre la que fija el
  producto en el YAML, nunca bajarla: pedir poco no abre la vía automática.
- Un ingreso registrado nulo cuenta como dato faltante (`missing_income`).
- Razones y alertas son códigos en snake_case que la conversación traduce a
  texto. La conversación no inventa razones.
- La decisión trae puntaje, versión del modelo de cupo y alternativa, así el
  job de C6 la escribe tal cual, sin reimplementar reglas.

Aplazado: flags de datos inconsistentes y producto actual del cliente (para
subir de clásica a oro). Se agregan como campos opcionales, versión menor.
"""

from typing import Annotated, Literal, Protocol, Self

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

Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class CustomerRequest(BaseModel):
    """Lo que pide el cliente. Dato no verificado."""

    model_config = _FROZEN

    product_code: ProductCode
    requested_amount_usd: float | None = Field(default=None, gt=0)
    declared_monthly_income_usd: float | None = Field(default=None, gt=0)
    customer_requests_human: bool = False
    customer_disputes_rejection: bool = False


class PolicyInput(BaseModel):
    """Hechos verificados del cliente (C1, C3, C4, C5) más su solicitud."""

    model_config = _FROZEN

    customer_id: str = Field(min_length=1)
    customer_status: CustomerStatus
    segment: Segment
    max_days_past_due: int = Field(ge=0)
    # gt=0: un ingreso de 0 no es un dato, se pasa como nulo (dato faltante).
    monthly_income_usd: float | None = Field(default=None, gt=0)
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
    score: int | None = Field(default=None, ge=150, le=950)
    band: Band | None = None
    exposure: Exposure
    offered_limit_usd: float | None = Field(default=None, gt=0)
    negotiation_min_usd: float | None = Field(default=None, gt=0)
    negotiation_max_usd: float | None = Field(default=None, gt=0)
    limit_model_version: str | None = None
    # Alternativa de menor exposición cuando no es elegible.
    alternative_product_code: ProductCode | None = None
    # Trato preferencial (segmento Premium): prioridad y asesor dedicado.
    # No cambia la decisión de riesgo.
    preferential: bool = False
    reasons: list[Code] = Field(min_length=1)
    alerts: list[Code] = Field(default_factory=list)
    policy_version: str = Field(min_length=1)
    synthetic_policy: Literal[True] = True

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        limits = (
            self.negotiation_min_usd,
            self.offered_limit_usd,
            self.negotiation_max_usd,
        )
        has_limit = self.offered_limit_usd is not None
        if (self.score is None) != (self.band is None):
            raise ValueError("score y band van juntos o no van")
        if self.attention_level == AttentionLevel.AUTOMATIC and (
            self.score is None or not has_limit
        ):
            raise ValueError("automático exige puntaje y cupo")
        if self.attention_level == AttentionLevel.NOT_ELIGIBLE and any(
            v is not None for v in limits
        ):
            raise ValueError("una decisión no elegible no ofrece cupo")
        if any(v is None for v in limits) and any(v is not None for v in limits):
            raise ValueError("cupo y rango de negociación van juntos o no van")
        lo, mid, hi = limits
        if has_limit and not lo <= mid <= hi:
            raise ValueError("se exige negotiation_min <= offered <= negotiation_max")
        if has_limit and not self.limit_model_version:
            raise ValueError("todo cupo trae la versión del modelo que lo sugirió")
        return self


class EligibilityPolicy(Protocol):
    version: str

    def decide(self, policy_input: PolicyInput) -> PolicyDecision:
        """Función pura: misma entrada, misma decisión."""
        ...
