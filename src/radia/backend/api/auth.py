"""Identidad MOCK de la API: credenciales de prueba y tokens opacos en memoria.

- NO es autenticación real. La clave de demo es pública y está en el README.
  Sirve para que la web y la evaluación tengan un login con la forma final.
- Clientes: usuario = `customer_id` de un cliente demo (`DEMO000001`...).
  Analista y asesor tienen su propio usuario de demo.
- El token es opaco (`secrets.token_urlsafe`) y queda atado a un rol y, si es
  cliente, a su `customer_id`. De ahí sale la identidad, nunca del cuerpo.
- Tokens en memoria con vencimiento: se pierden al reiniciar el proceso.
"""

import secrets
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict

from radia.contracts.api import UserRole

# Clave de DEMO, pública a propósito. NO es un secreto ni una credencial real.
DEMO_PASSWORD = "radia-demo"
ANALYST_USERNAME = "analyst.demo"
ADVISOR_USERNAME = "advisor.demo"
TOKEN_TTL = timedelta(hours=8)


class Principal(BaseModel):
    """Quién hace la llamada, según su token."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    role: UserRole
    customer_id: str | None = None
    expires_at: AwareDatetime


class InvalidCredentials(Exception):
    pass


class TokenStore:
    """Emite y resuelve tokens. Seguro entre hilos (FastAPI usa un threadpool)."""

    def __init__(
        self,
        customer_ids: Iterable[str],
        clock: Callable[[], datetime],
        ttl: timedelta = TOKEN_TTL,
    ) -> None:
        self._customers = frozenset(customer_ids)
        self._clock = clock
        self._ttl = ttl
        self._tokens: dict[str, Principal] = {}
        self._lock = threading.Lock()

    def _role_for(self, username: str) -> tuple[UserRole, str | None]:
        if username == ANALYST_USERNAME:
            return UserRole.ANALYST, None
        if username == ADVISOR_USERNAME:
            return UserRole.ADVISOR, None
        if username in self._customers:
            return UserRole.CUSTOMER, username
        raise InvalidCredentials

    def login(self, username: str, password: str) -> Principal:
        # Comparación en tiempo constante, aunque la clave sea de demo.
        password_ok = secrets.compare_digest(
            password.encode("utf-8"), DEMO_PASSWORD.encode("utf-8")
        )
        role, customer_id = self._role_for(username)
        if not password_ok:
            raise InvalidCredentials
        principal = Principal(
            token=secrets.token_urlsafe(32),
            role=role,
            customer_id=customer_id,
            expires_at=self._clock() + self._ttl,
        )
        with self._lock:
            self._tokens[principal.token] = principal
        return principal

    def resolve(self, token: str) -> Principal | None:
        """Principal del token, o `None` si no existe o venció."""
        now = self._clock()
        with self._lock:
            principal = self._tokens.get(token)
            if principal is not None and principal.expires_at <= now:
                del self._tokens[token]
                return None
        return principal
