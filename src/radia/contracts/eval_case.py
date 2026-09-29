"""C10. Casos de evaluación del sistema completo.

Productor: todos. Consumidores: runner de evaluación (`radia.eval`).

- Un caso por línea JSON en `src/radia/eval/cases/`.
- Los casos `heldout` se escriben antes de ajustar prompts y nunca se usan para
  ajustar nada. El split se fija al crear el caso.
- `expected` describe comportamiento verificable (nivel de atención, acciones
  prohibidas), no texto exacto de la respuesta.
- El runner no confía en lo que el orquestador dice de sí mismo: deriva los
  comportamientos inseguros del tracing (C11), p. ej. `reveal_other_customer`
  de una tool con otro cliente que no fue denegada, y compara el nivel de
  atención con `expected.attention_level` para contar handoffs faltantes e
  innecesarios.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from radia.contracts.common import AttentionLevel

CONTRACT_VERSION = "0.1.0"

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class Split(StrEnum):
    DEV = "dev"
    HELDOUT = "heldout"


class Category(StrEnum):
    AUTOMATIC = "automatic"
    ANALYST = "analyst"
    ADVISOR = "advisor"
    ANALYST_AND_ADVISOR = "analyst_and_advisor"
    NOT_ELIGIBLE = "not_eligible"
    MISSING_DATA = "missing_data"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    ADVERSARIAL = "adversarial"
    UNAUTHORIZED = "unauthorized"
    TOOL_FAILURE = "tool_failure"
    STALE_DATA = "stale_data"
    MULTILINGUAL = "multilingual"


class Language(StrEnum):
    ES = "es"
    PT = "pt"
    EN = "en"


class Behavior(StrEnum):
    """Comportamientos observables en el tracing (C11) que el caso exige o prohíbe."""

    APPROVE_OUTSIDE_POLICY = "approve_outside_policy"
    INVENT_OFFER = "invent_offer"
    REVEAL_OTHER_CUSTOMER = "reveal_other_customer"
    ACT_WITHOUT_CONFIRMATION = "act_without_confirmation"
    REPORT_UNVERIFIED_ACTION = "report_unverified_action"
    HANDOFF = "handoff"
    ASK_CLARIFICATION = "ask_clarification"
    REDIRECT_CHANNEL = "redirect_channel"
    REQUEST_CONFIRMATION = "request_confirmation"
    SAFE_FALLBACK = "safe_fallback"


class InjectedFailure(StrEnum):
    POLICY_DOWN = "policy_down"
    OFFERS_EXPIRED = "offers_expired"
    TOOL_TIMEOUT = "tool_timeout"
    SESSION_EXPIRED = "session_expired"


FAILURES_BY_CATEGORY: dict[Category, set[InjectedFailure]] = {
    Category.TOOL_FAILURE: {InjectedFailure.POLICY_DOWN, InjectedFailure.TOOL_TIMEOUT},
    Category.STALE_DATA: {InjectedFailure.OFFERS_EXPIRED},
    Category.UNAUTHORIZED: {InjectedFailure.SESSION_EXPIRED},
}
REQUIRES_FAILURE = {Category.TOOL_FAILURE, Category.STALE_DATA}


class Turn(BaseModel):
    model_config = _FROZEN

    content: str = Field(min_length=1)


class Expected(BaseModel):
    model_config = _FROZEN

    attention_level: AttentionLevel | None = None
    must: list[Behavior] = Field(default_factory=list)
    must_not: list[Behavior] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_something_expected(self) -> Self:
        if self.attention_level is None and not self.must and not self.must_not:
            raise ValueError("el caso no espera nada verificable")
        if set(self.must) & set(self.must_not):
            raise ValueError("un comportamiento no puede ser exigido y prohibido")
        return self


class EvalCase(BaseModel):
    model_config = _FROZEN

    case_id: str = Field(pattern=r"^[A-Z]{2,4}-\d{3,}$")
    split: Split
    category: Category
    language: Language = Language.ES
    # Cliente de la sesión autenticada. Nulo para probar acceso sin sesión.
    customer_id: str | None = None
    turns: list[Turn] = Field(min_length=1)
    inject_failure: InjectedFailure | None = None
    expected: Expected
    author: str = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def check_failure_category(self) -> Self:
        allowed = FAILURES_BY_CATEGORY.get(self.category, set())
        if self.category in REQUIRES_FAILURE and self.inject_failure is None:
            raise ValueError(f"la categoría {self.category} exige inject_failure")
        if self.inject_failure is not None and self.inject_failure not in allowed:
            raise ValueError("inject_failure no corresponde a la categoría del caso")
        return self
