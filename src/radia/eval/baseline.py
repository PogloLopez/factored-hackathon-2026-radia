"""Baseline del sistema: asistente ingenuo sin política ni permisos.

Ver [[propuesta]], sección 5: "chat con LLM que recibe los datos del cliente y
responde libremente, sin reglas ni tools. Va a aprobar cuando se le presione".

Simulación determinista, SIN LLM real:
- Entiende igual que Radia (mismo `FakeLanguageModel.classify`). Así la
  diferencia medida es la capa de control, no la comprensión.
- Sus datos son las filas C6 del cliente pegadas en el prompt al abrir el chat:
  no revisa vigencia, no sabe si la fuente se cayó, ignora la sesión vencida.
- Sin permisos dentro del chat: si el mensaje nombra otro cliente, lee sus
  datos.
- "Aprueba" solo ante intención real de solicitud o aprobación: intent
  `apply_product` o un pedido explícito ("apruébame", "emite", "solicítala",
  "dame la ..."). Un "Sí, confirmo" suelto, declarar el ingreso o una
  inyección sin pedido no alcanzan. Dice que registró la solicitud por lo
  pedido o por el cupo, sin confirmación, sin mirar el nivel de atención y sin
  verificar nada. Si no hay oferta, inventa un cupo con el ingreso.
- No escala por diseño: a quien pide un humano le dice que llame a la
  sucursal. Su `handoff_missed` se lee así, no como error de comprensión.
- Justo con él: misma puerta de autenticación que la API (sin sesión rechaza
  igual que Radia), aclara lo ambiguo y redirige lo no soportado, como haría
  un LLM general.

Produce la misma evidencia (`CaseRun`) que el runner y se juzga con las mismas
métricas.
"""

import math
import re
import time
from collections.abc import Sequence

from radia.backend.agent.llm import (
    ChatMessage,
    FakeLanguageModel,
    Intent,
    Role,
    Understanding,
)
from radia.backend.agent.tools import Offer, utc_now
from radia.contracts.common import ProductCode
from radia.contracts.eval_case import EvalCase
from radia.contracts.trace import Outcome, TurnTrace
from radia.eval.demo_customers import DEMO_PROFILES
from radia.eval.evidence import ActionRecord, CaseRun, DataRead, SystemName
from radia.eval.runner import CURRENCY_BY_COUNTRY, EvalRunner, reject_without_session

BASELINE_MODEL = "baseline-naive-sim-0.1.0"
BASELINE_PROMPT = "baseline-prompt-0.1.0"
# Cupo inventado cuando no hay oferta: múltiplo del ingreso (o un fijo).
INVENTED_INCOME_MULTIPLE = 3.0
INVENTED_DEFAULT_USD = 1000.0
# Pedido explícito de solicitud o aprobación: imperativos y verbos de pedido.
# Sin "confirmo" ni "registrado" sueltos: no piden aprobar nada.
PRESSURE = re.compile(
    r"\b(?:"
    r"apru[eé]b(?:a|ame|alo|ala|en|enme|enlo|enla)"
    r"|aprob[aá](?:me|lo|la)?|aprobarme"
    r"|aprov(?:e|ar)|approve"
    r"|autoriz(?:o|a|ame|ar)"
    r"|em[ií]t(?:e|a|eme|ela|elo|ir)"
    r"|registr(?:a|á|ame|ala|alo|en|enla)"
    r"|d[aá]me\s+(?:el|la|un|una|mi)|d[eé]mel[oa]"
    r"|solic[ií]t(?:a|á|ar|arla|arlo|ala|alo|en|enla|enlo|o)"
    r")\b",
    re.IGNORECASE,
)
CUSTOMER_TOKEN = re.compile(r"\bDEMO\d{6}\b", re.IGNORECASE)


class NaiveAssistant:
    """Asistente ingenuo determinista. Misma evidencia que el runner."""

    def __init__(self, runner: EvalRunner) -> None:
        # El runner da la verdad de terreno y las filas C6 de la demo.
        self.runner = runner
        self.understanding = FakeLanguageModel()

    def run(self, cases: Sequence[EvalCase], run_index: int = 0) -> list[CaseRun]:
        return [self.run_case(case, run_index) for case in cases]

    def run_case(self, case: EvalCase, run_index: int = 0) -> CaseRun:
        if case.customer_id is None:
            # Misma puerta de autenticación que la API y que Radia.
            return reject_without_session(
                case, run_index, SystemName.BASELINE, BASELINE_MODEL, BASELINE_PROMPT
            )
        history: list[ChatMessage] = []
        traces: list[TurnTrace] = []
        reads: list[DataRead] = []
        actions: list[ActionRecord] = []
        focus: ProductCode | None = None
        elapsed = 0.0
        for index, turn in enumerate(case.turns):
            started = time.perf_counter()
            u = self.understanding.classify(turn.content, history)
            focus = u.product_code or focus
            target = _mentioned_customer(turn.content, u) or case.customer_id
            rows = self._rows(target, case)
            if target is not None and rows:
                reads.append(
                    DataRead(turn_index=index, customer_id=target, source="prompt")
                )
            outcome, sources, reference = Outcome.ANSWERED, [], None
            if u.intent == Intent.UNSUPPORTED:
                outcome = Outcome.REDIRECTED
            elif _pressured(turn.content, u) and target is not None:
                offer = _pick(rows, u.product_code or focus)
                reference = f"BASE-{case.case_id}-{index}"
                actions.append(
                    ActionRecord(
                        turn_index=index,
                        customer_id=target,
                        reference=reference,
                        offer_id=offer.offer_id if offer else None,
                        product_code=offer.product_code if offer else focus,
                        amount_usd=_granted(u, offer, target),
                        stored=False,
                    )
                )
                outcome = Outcome.ACTION_COMPLETED
                sources = [f"active_offers:{offer.offer_id}"] if offer else []
            elif u.intent == Intent.AMBIGUOUS:
                outcome = Outcome.CLARIFICATION
            elif rows:
                # Consulta: responde con todos los cupos que tiene en el prompt.
                sources = [f"active_offers:{o.offer_id}" for o in rows]
            ms = (time.perf_counter() - started) * 1000
            elapsed += ms
            traces.append(
                TurnTrace(
                    trace_id=f"TRC-BASE-{case.case_id}-{index}",
                    session_id=f"BASE-{case.case_id}",
                    turn_index=index,
                    timestamp=utc_now(),
                    customer_id=case.customer_id,
                    eval_case_id=case.case_id,
                    intent=u.intent.value,
                    outcome=outcome,
                    sources=sources,
                    llm_model=BASELINE_MODEL,
                    prompt_version=BASELINE_PROMPT,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    latency_ms=ms,
                    application_reference=reference,
                )
            )
            history.append(ChatMessage(role=Role.CUSTOMER, content=turn.content))
        return CaseRun(
            system=SystemName.BASELINE,
            run_index=run_index,
            case_id=case.case_id,
            customer_id=case.customer_id,
            traces=traces,
            data_reads=reads,
            actions=actions,
            offers=self.runner.offer_facts(case.customer_id, case.inject_failure),
            latency_ms=elapsed,
        )

    def _rows(self, customer_id: str | None, case: EvalCase) -> list[Offer]:
        if customer_id is None or customer_id not in DEMO_PROFILES:
            return []
        return self.runner.offer_rows(customer_id, case.inject_failure)


def _mentioned_customer(text: str, u: Understanding) -> str | None:
    """Cliente nombrado en el chat. El ingenuo le cree sin verificar."""
    token = CUSTOMER_TOKEN.search(text)
    if token:
        return token.group(0).upper()
    return u.other_customer_id


def _pressured(text: str, u: Understanding) -> bool:
    """Intención real de solicitud o aprobación."""
    return u.intent == Intent.APPLY_PRODUCT or bool(PRESSURE.search(text))


def _pick(rows: Sequence[Offer], product: ProductCode | None) -> Offer | None:
    if product is None:
        return None
    return next((o for o in rows if o.product_code == product), None)


def _granted(u: Understanding, offer: Offer | None, customer_id: str) -> float:
    """Lo que el ingenuo "aprueba": lo pedido, el cupo o un cupo inventado."""
    profile = DEMO_PROFILES.get(customer_id)
    if u.amount is not None:
        if u.amount_in_usd or profile is None:
            return u.amount
        return u.amount * CURRENCY_BY_COUNTRY[profile.country][1]
    if offer is not None and offer.offered_limit_usd:
        return offer.offered_limit_usd
    income = profile.monthly_income_usd if profile else math.nan
    if math.isnan(income):
        return INVENTED_DEFAULT_USD
    return income * INVENTED_INCOME_MULTIPLE
