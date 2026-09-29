"""Estado de la API: piezas del orquestador, fuentes y almacenes en memoria.

- Ofertas C6: las de los clientes demo (`demo_offers`) siempre, más las de
  `data_dir/gold/active_offers.parquet` si existe. Solo los demo pueden hacer
  login: así la demo funciona con o sin Gold. El login real con clientes de
  Gold queda para después de la descarga.
- LLM: `FakeLanguageModel` salvo `use_groq` verdadero (gasto: checkpoint de
  Pablo).
- Traces: JSONL en `settings.traces_dir`, salvo que se inyecte otro sink.
- Todo en memoria: casos, sesiones y mensajes se pierden al reiniciar.
"""

import threading
from collections.abc import Callable
from datetime import datetime

import pandas as pd

from radia.backend.agent.llm import FakeLanguageModel, GroqLanguageModel, LanguageModel
from radia.backend.agent.orchestrator import Orchestrator
from radia.backend.agent.session import Currency
from radia.backend.agent.tools import (
    InMemoryCaseStore,
    InMemoryOfferRepository,
    ToolBox,
    utc_now,
)
from radia.backend.agent.tracing import JsonlTraceSink, TraceSink
from radia.backend.api.auth import TokenStore
from radia.config import Settings
from radia.contracts.api import AdvisorMessage
from radia.contracts.common import Country
from radia.etl.offers import OFFERS_FILE
from radia.eval.demo_customers import DEMO_PROFILES, demo_offers

# Moneda local por país y USD por unidad local. Tasas APROXIMADAS y
# PROVISIONALES, solo para leer montos del chat. No salen del dataset: se
# reemplazan por `daily_exchange_rates` cuando la API lea Gold.
COUNTRY_CURRENCY: dict[Country, tuple[Currency, float]] = {
    Country.MEXICO: (Currency.MXN, 0.055),
    Country.COLOMBIA: (Currency.COP, 0.00025),
    Country.ARGENTINA: (Currency.ARS, 0.001),
}


def load_offers(settings: Settings, clock: Callable[[], datetime]) -> pd.DataFrame:
    """C6 de Gold (si existe) más el de los clientes demo.

    Un `offer_id` demo que ya esté en Gold se descarta: Gold manda.
    """
    demo = demo_offers(clock())
    path = settings.data_dir / "gold" / OFFERS_FILE
    if not path.exists():
        return demo
    gold = pd.read_parquet(path)
    extra = demo[~demo["offer_id"].isin(gold["offer_id"])]
    return pd.concat([gold, extra], ignore_index=True)


def build_llm(settings: Settings) -> LanguageModel:
    """Modelo falso por defecto. Groq solo si `use_groq` es verdadero."""
    if settings.use_groq:
        return GroqLanguageModel(settings)
    return FakeLanguageModel()


def session_currency(customer_id: str) -> tuple[Currency | None, float | None]:
    """Moneda y tasa de la sesión según el país del cliente demo."""
    profile = DEMO_PROFILES.get(customer_id)
    if profile is None:
        return None, None
    return COUNTRY_CURRENCY.get(profile.country, (None, None))


class ApiState:
    """Lo que comparten las rutas.

    `lock` cubre secciones cortas: dueño de la sesión, alta de sesión, decisión
    del analista y mensajes del asesor. Nunca envuelve un turno del orquestador:
    cada sesión ya tiene su lock.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        offers: pd.DataFrame | None = None,
        sink: TraceSink | None = None,
        llm: LanguageModel | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.clock = clock
        self.offers = InMemoryOfferRepository(
            offers if offers is not None else load_offers(settings, clock)
        )
        self.cases = InMemoryCaseStore()
        self.tools = ToolBox(self.offers, cases=self.cases, clock=clock)
        self.orchestrator = Orchestrator(
            llm or build_llm(settings),
            self.tools,
            sink or JsonlTraceSink.from_settings(settings),
            clock=clock,
        )
        self.tokens = TokenStore(DEMO_PROFILES.keys(), clock)
        self.advisor_messages: dict[str, list[AdvisorMessage]] = {}
        self.lock = threading.Lock()
