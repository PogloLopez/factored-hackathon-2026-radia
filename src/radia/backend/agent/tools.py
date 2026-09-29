"""Tools del orquestador con capa de permisos.

- Permisos fuera del LLM: toda tool recibe la sesión y solo opera sobre su
  cliente. Otro `customer_id` se deniega, diga lo que diga el mensaje.
- Sesión vencida: toda tool se deniega.
- `create_application` exige una confirmación aceptada en la sesión, una
  oferta del cliente, vigente y de nivel automático. Registra el monto
  confirmado, que nunca supera el cupo. La política decide; la
  tool vuelve a chequear.
- Una solicitud por oferta y cliente. Una segunda con otra confirmación se
  deniega (`application_exists`): se decide denegar y no devolver la existente
  para no reportar como nueva una acción que no ocurrió. El reintento con la
  misma confirmación devuelve la existente (idempotente). El chequeo y el alta
  van en una sola sección crítica del store (`create_if_absent`): dos
  confirmaciones concurrentes no crean dos solicitudes.
- Reintentos acotados (tenacity) solo en fallas técnicas
  (`TransientToolError`). Una denegación nunca se reintenta.
- Ofertas vencidas (`expires_at` pasado) no se devuelven. El orquestador cae a
  un fallback seguro y nunca inventa una oferta.
- Cada llamada deja un `ToolCall` (C11) en el recolector `calls` que pasa
  quien llama (uno por turno). El `ToolBox` no guarda estado compartido,
  así que turnos concurrentes no mezclan trazas.
- Fuentes inyectables: ofertas en memoria desde un DataFrame C6, solicitudes y
  casos en memoria. En producción se cambian por repositorios reales.
"""

import json
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol

import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from radia.backend.agent.session import Session
from radia.contracts.common import AttentionLevel, Band, Exposure, ProductCode
from radia.contracts.data import validate
from radia.contracts.data.active_offers import ActiveOffers
from radia.contracts.handoff import HandoffCase, HandoffType, Priority
from radia.contracts.policy import Code, PolicyDecision
from radia.contracts.trace import ToolCall

MAX_ATTEMPTS = 3


def utc_now() -> datetime:
    return datetime.now(UTC)


class ToolDenied(Exception):
    """La capa de permisos rechazó la llamada. No se reintenta."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ApplicationExists(ToolDenied):
    """Ya hay otra solicitud para la oferta. Trae su referencia (del mismo
    cliente) para informarla sin depender de otra lectura."""

    def __init__(self, reference: str) -> None:
        super().__init__("application_exists")
        self.reference = reference


class TransientToolError(Exception):
    """Falla técnica reintentable (timeout, servicio caído)."""


class ToolFailed(Exception):
    """Falla técnica tras agotar los reintentos. El orquestador cae a fallback."""


# --- Modelos -----------------------------------------------------------------


class Offer(BaseModel):
    """Una fila de C6 como objeto. La decisión viene de la política, tal cual."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    offer_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    product_code: ProductCode
    attention_level: AttentionLevel
    exposure: Exposure
    snapshot_date: date
    score: int | None = None
    band: Band | None = None
    offered_limit_usd: float | None = None
    negotiation_min_usd: float | None = None
    negotiation_max_usd: float | None = None
    reasons: list[Code] = Field(min_length=1)
    alerts: list[Code] = Field(default_factory=list)
    alternative_product_code: ProductCode | None = None
    policy_version: str = Field(min_length=1)
    score_version: str | None = None
    limit_model_version: str | None = None
    preferential: bool = False
    generated_at: AwareDatetime
    expires_at: AwareDatetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Offer":
        clean = {k: (None if _is_missing(v) else v) for k, v in row.items()}
        clean["reasons"] = json.loads(clean.pop("reasons_json"))
        clean["alerts"] = json.loads(clean.pop("alerts_json"))
        clean.pop("synthetic_policy", None)
        clean["snapshot_date"] = pd.Timestamp(clean["snapshot_date"]).date()
        for key in ("generated_at", "expires_at"):
            # C6 guarda UTC sin zona.
            clean[key] = pd.Timestamp(clean[key]).tz_localize(UTC).to_pydatetime()
        if clean["score"] is not None:
            clean["score"] = int(clean["score"])
        return cls.model_validate(clean)

    def is_valid(self, now: datetime) -> bool:
        return now < self.expires_at

    def to_decision(self) -> PolicyDecision:
        return PolicyDecision(
            customer_id=self.customer_id,
            product_code=self.product_code,
            attention_level=self.attention_level,
            score=self.score,
            band=self.band,
            exposure=self.exposure,
            offered_limit_usd=self.offered_limit_usd,
            negotiation_min_usd=self.negotiation_min_usd,
            negotiation_max_usd=self.negotiation_max_usd,
            limit_model_version=self.limit_model_version,
            alternative_product_code=self.alternative_product_code,
            preferential=self.preferential,
            reasons=self.reasons,
            alerts=self.alerts,
            policy_version=self.policy_version,
        )

    @property
    def sources(self) -> list[str]:
        return [
            f"active_offers:{self.offer_id}",
            f"policy:{self.policy_version}",
            f"snapshot:{self.snapshot_date.isoformat()}",
            f"score:{self.score_version}",
        ]


def _is_missing(value: Any) -> bool:
    return not isinstance(value, (list, dict, str)) and bool(pd.isna(value))


class OfferLookup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offers: list[Offer]
    expired_count: int = Field(ge=0)


class Application(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    reference: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    offer_id: str = Field(min_length=1)
    product_code: ProductCode
    limit_usd: float = Field(gt=0)
    confirmation_id: str = Field(min_length=1)
    status: str = "submitted"
    created_at: AwareDatetime


# --- Fuentes inyectables -----------------------------------------------------


class OfferRepository(Protocol):
    def offers_for(self, customer_id: str) -> list[Offer]: ...


class ApplicationStore(Protocol):
    def create(self, application: Application) -> Application: ...

    def create_if_absent(
        self,
        customer_id: str,
        offer_id: str,
        confirmation_id: str,
        build: Callable[[], Application],
    ) -> Application: ...

    def get(self, reference: str) -> Application | None: ...

    def for_offer(self, customer_id: str, offer_id: str) -> Application | None: ...


class CaseStore(Protocol):
    def save(self, case: HandoffCase) -> HandoffCase: ...

    def get(self, case_id: str) -> HandoffCase | None: ...


class InMemoryOfferRepository:
    """Ofertas desde un DataFrame C6. Se valida al leer (el consumidor valida)."""

    def __init__(self, active_offers: pd.DataFrame) -> None:
        df = validate(ActiveOffers, active_offers)
        self._by_customer: dict[str, list[Offer]] = {}
        for row in df.to_dict(orient="records"):
            offer = Offer.from_row(row)
            self._by_customer.setdefault(offer.customer_id, []).append(offer)

    def offers_for(self, customer_id: str) -> list[Offer]:
        return list(self._by_customer.get(customer_id, []))


class InMemoryApplicationStore:
    """Idempotente por `confirmation_id`: un reintento no duplica la solicitud.

    Un lock protege el diccionario: la API atiende peticiones en varios hilos.
    Es reentrante porque `create_if_absent` llama a `create` dentro del lock.
    """

    def __init__(self) -> None:
        self.applications: dict[str, Application] = {}
        self._lock = threading.RLock()

    def create(self, application: Application) -> Application:
        with self._lock:
            for existing in self.applications.values():
                if existing.confirmation_id == application.confirmation_id:
                    return existing
            self.applications[application.reference] = application
            return application

    def create_if_absent(
        self,
        customer_id: str,
        offer_id: str,
        confirmation_id: str,
        build: Callable[[], Application],
    ) -> Application:
        """Chequeo y alta atómicos. Misma confirmación: la existente. Otra
        confirmación para la misma oferta del cliente: `application_exists`."""
        with self._lock:
            existing = self.for_offer(customer_id, offer_id)
            if existing is not None:
                if existing.confirmation_id == confirmation_id:
                    return existing
                raise ApplicationExists(existing.reference)
            return self.create(build())

    def get(self, reference: str) -> Application | None:
        with self._lock:
            return self.applications.get(reference)

    def for_offer(self, customer_id: str, offer_id: str) -> Application | None:
        with self._lock:
            return next(
                (
                    a
                    for a in self.applications.values()
                    if a.customer_id == customer_id and a.offer_id == offer_id
                ),
                None,
            )


class InMemoryCaseStore:
    def __init__(self) -> None:
        self.cases: dict[str, HandoffCase] = {}

    def save(self, case: HandoffCase) -> HandoffCase:
        self.cases[case.case_id] = case
        return case

    def get(self, case_id: str) -> HandoffCase | None:
        return self.cases.get(case_id)


# --- Tools -------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


class ToolBox:
    """Tools con permisos, reintentos acotados y registro para el tracing."""

    def __init__(
        self,
        offers: OfferRepository,
        applications: ApplicationStore | None = None,
        cases: CaseStore | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        max_attempts: int = MAX_ATTEMPTS,
        wait: wait_base | None = None,
    ) -> None:
        self.offers = offers
        self.applications = applications or InMemoryApplicationStore()
        self.cases = cases or InMemoryCaseStore()
        self.clock = clock
        self.max_attempts = max_attempts
        self.wait = wait or wait_exponential(multiplier=0.2, max=2)

    # Permisos y ejecución --------------------------------------------------

    @staticmethod
    def _record(calls: list[ToolCall], name: str, start: float, **fields: Any) -> None:
        latency_ms = (time.perf_counter() - start) * 1000
        calls.append(ToolCall(name=name, latency_ms=latency_ms, **fields))

    def _authorize(
        self, calls: list[ToolCall], name: str, session: Session, customer_id: str
    ) -> None:
        start = time.perf_counter()
        if not session.is_active(self.clock()):
            code = "session_expired"
        elif customer_id != session.customer_id:
            code = "customer_mismatch"
        else:
            return
        self._record(calls, name, start, ok=False, denied=True, error=code)
        raise ToolDenied(code)

    def _run[T](self, calls: list[ToolCall], name: str, fn: Callable[[], T]) -> T:
        start = time.perf_counter()
        attempts = 0
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(self.max_attempts),
                wait=self.wait,
                retry=retry_if_exception_type(TransientToolError),
                reraise=True,
            ):
                with attempt:
                    attempts = attempt.retry_state.attempt_number
                    result = fn()
        except ToolDenied as exc:
            self._record(
                calls,
                name,
                start,
                ok=False,
                denied=True,
                error=exc.code,
                attempt=attempts,
            )
            raise
        except Exception as exc:
            # Cualquier falla técnica (reintentable o no) termina en fallback.
            # Solo el tipo: el mensaje puede traer datos del cliente.
            error = type(exc).__name__
            self._record(calls, name, start, ok=False, error=error, attempt=attempts)
            raise ToolFailed(name) from exc
        self._record(calls, name, start, ok=True, attempt=attempts)
        return result

    # Tools -----------------------------------------------------------------

    def get_active_offers(
        self, session: Session, customer_id: str, *, calls: list[ToolCall]
    ) -> OfferLookup:
        """Ofertas vigentes del cliente de la sesión. Otro cliente: denegado."""
        self._authorize(calls, "get_active_offers", session, customer_id)

        def lookup() -> OfferLookup:
            now = self.clock()
            rows = self.offers.offers_for(customer_id)
            valid = [o for o in rows if o.is_valid(now)]
            return OfferLookup(offers=valid, expired_count=len(rows) - len(valid))

        return self._run(calls, "get_active_offers", lookup)

    def create_application(
        self,
        session: Session,
        offer_id: str,
        confirmation_id: str,
        *,
        calls: list[ToolCall],
    ) -> Application:
        """Registra la solicitud. Exige confirmación aceptada y oferta automática."""
        name = "create_application"
        self._authorize(calls, name, session, session.customer_id)
        pending = session.pending
        if (
            pending is None
            or not pending.accepted
            or pending.confirmation_id != confirmation_id
            or pending.offer_id != offer_id
        ):
            self._record(
                calls,
                name,
                time.perf_counter(),
                ok=False,
                denied=True,
                error="missing_confirmation",
            )
            raise ToolDenied("missing_confirmation")

        def create() -> Application:
            now = self.clock()
            owned = {o.offer_id: o for o in self.offers.offers_for(session.customer_id)}
            offer = owned.get(offer_id)
            if offer is None:
                raise ToolDenied("offer_not_owned")
            if not offer.is_valid(now):
                raise ToolDenied("offer_expired")
            if (
                offer.attention_level != AttentionLevel.AUTOMATIC
                or offer.offered_limit_usd is None
            ):
                raise ToolDenied("offer_not_automatic")
            # Se registra el monto confirmado, nunca más que el cupo de la oferta.
            if not 0 < pending.limit_usd <= offer.offered_limit_usd:
                raise ToolDenied("amount_above_offer")
            # Chequeo de duplicado y alta en una sola sección crítica del store.
            return self.applications.create_if_absent(
                session.customer_id,
                offer_id,
                confirmation_id,
                lambda: Application(
                    reference=_new_id("APP"),
                    customer_id=session.customer_id,
                    offer_id=offer.offer_id,
                    product_code=offer.product_code,
                    limit_usd=pending.limit_usd,
                    confirmation_id=confirmation_id,
                    created_at=now,
                ),
            )

        return self._run(calls, name, create)

    def find_application(
        self, session: Session, offer_id: str, *, calls: list[ToolCall]
    ) -> Application | None:
        """Solicitud ya registrada del cliente de la sesión para esa oferta."""
        name = "find_application"
        self._authorize(calls, name, session, session.customer_id)
        return self._run(
            calls,
            name,
            lambda: self.applications.for_offer(session.customer_id, offer_id),
        )

    def get_application(
        self, session: Session, reference: str, *, calls: list[ToolCall]
    ) -> Application | None:
        """Lee una solicitud para verificarla. Solo las del cliente de la sesión."""
        name = "get_application"
        self._authorize(calls, name, session, session.customer_id)

        def read() -> Application | None:
            found = self.applications.get(reference)
            if found is not None and found.customer_id != session.customer_id:
                raise ToolDenied("customer_mismatch")
            return found

        return self._run(calls, name, read)

    def create_handoff(
        self,
        session: Session,
        *,
        handoff_type: HandoffType,
        trigger_reason: str,
        request_summary: str,
        verified_facts: Sequence[str] = (),
        policy_decision: PolicyDecision | None = None,
        actions_taken: Sequence[str] = (),
        open_questions: Sequence[str] = (),
        priority: Priority = Priority.NORMAL,
        calls: list[ToolCall],
    ) -> HandoffCase:
        """Crea el expediente C9 del cliente de la sesión y verifica que quedó."""
        name = "create_handoff"
        customer_id = (
            policy_decision.customer_id if policy_decision else session.customer_id
        )
        self._authorize(calls, name, session, customer_id)

        def create() -> HandoffCase:
            case = HandoffCase(
                case_id=_new_id("CASE"),
                handoff_type=handoff_type,
                priority=priority,
                trigger_reason=trigger_reason,
                customer_id=session.customer_id,
                session_id=session.session_id,
                request_summary=request_summary,
                verified_facts=list(verified_facts),
                policy_decision=policy_decision,
                actions_taken=list(actions_taken),
                open_questions=list(open_questions),
                created_at=self.clock(),
            )
            self.cases.save(case)
            stored = self.cases.get(case.case_id)
            if stored != case:
                raise TransientToolError("el caso no quedó guardado")
            return stored

        return self._run(calls, name, create)
