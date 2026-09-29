"""Job de ofertas vigentes (C6).

Por cada cliente y producto del catálogo arma la entrada de la política (C7)
con hechos verificados de C1 y C3 más la predicción de cupo (C4), y escribe la
decisión tal cual. Las reglas viven solo en la política: aquí no se reimplementan.

- Sin datos del chat: la solicitud solo trae el producto.
- Un ingreso de 0 o nulo en C1 pasa como nulo (dato faltante): C7 exige > 0.
- `generated_at` debe traer zona horaria. Se guarda en UTC: pandera quita la
  zona al validar C6, así que la columna queda en UTC sin zona.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from radia.backend.policy.engine import RulesPolicy
from radia.config import Settings
from radia.contracts.common import CustomerStatus, ProductCode, Segment
from radia.contracts.data import validate
from radia.contracts.data.active_offers import ActiveOffers
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.internal_score import InternalScore
from radia.contracts.ml import LimitModel, LimitPrediction
from radia.contracts.policy import (
    CustomerRequest,
    EligibilityPolicy,
    PolicyDecision,
    PolicyInput,
)
from radia.etl.bronze import sql_literal
from radia.ml.baseline import IncomeMultipleBaseline

FEATURES_FILE = "customer_features.parquet"
SCORES_FILE = "internal_score.parquet"
OFFERS_FILE = "active_offers.parquet"


def _none_if_na(value):
    """NaN o NA de pandas a None; el resto igual."""
    return None if pd.isna(value) else value


def _income(value) -> float | None:
    """Ingreso de C1 para C7: 0 o nulo cuentan como dato faltante."""
    value = _none_if_na(value)
    return float(value) if value is not None and value > 0 else None


def offer_id(customer_id: str, product_code: str, generated_at: datetime) -> str:
    """Id determinista: misma corrida, mismo cliente y producto, mismo id."""
    key = f"{customer_id}|{product_code}|{generated_at.isoformat()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _latest_snapshot(features: pd.DataFrame) -> pd.DataFrame:
    """Última fecha de corte por cliente. C6 tiene una fila por cliente y producto."""
    latest = features.sort_values("snapshot_date").drop_duplicates(
        "customer_id", keep="last"
    )
    return latest.sort_values("customer_id").reset_index(drop=True)


def _row(
    decision: PolicyDecision,
    snapshot_date: pd.Timestamp,
    score_version: str | None,
    generated_at: datetime,
    expires_at: datetime,
) -> dict:
    return {
        "offer_id": offer_id(
            decision.customer_id, decision.product_code.value, generated_at
        ),
        "customer_id": decision.customer_id,
        "product_code": decision.product_code.value,
        "attention_level": decision.attention_level.value,
        "exposure": decision.exposure.value,
        "snapshot_date": snapshot_date,
        "score": decision.score,
        "band": decision.band.value if decision.band else None,
        "offered_limit_usd": decision.offered_limit_usd,
        "negotiation_min_usd": decision.negotiation_min_usd,
        "negotiation_max_usd": decision.negotiation_max_usd,
        "reasons_json": json.dumps(decision.reasons),
        "alerts_json": json.dumps(decision.alerts),
        "alternative_product_code": (
            decision.alternative_product_code.value
            if decision.alternative_product_code
            else None
        ),
        "policy_version": decision.policy_version,
        "score_version": score_version,
        "limit_model_version": decision.limit_model_version,
        "preferential": decision.preferential,
        "synthetic_policy": decision.synthetic_policy,
        "generated_at": generated_at,
        "expires_at": expires_at,
    }


def build_offers(
    features: pd.DataFrame,
    scores: pd.DataFrame,
    limit_model: LimitModel,
    policy: EligibilityPolicy,
    generated_at: datetime,
    ttl_days: int = 7,
) -> pd.DataFrame:
    """Arma C6 desde C1 y C3. Función pura: misma entrada, mismo DataFrame."""
    if generated_at.tzinfo is None:
        raise ValueError("generated_at debe traer zona horaria")
    if ttl_days <= 0:
        raise ValueError("ttl_days debe ser mayor que 0")
    generated_at = generated_at.astimezone(UTC)
    expires_at = generated_at + timedelta(days=ttl_days)

    latest = _latest_snapshot(features)
    facts = latest.merge(
        scores[["customer_id", "snapshot_date", "score", "score_version"]],
        on=["customer_id", "snapshot_date"],
        how="left",
        validate="one_to_one",
    )
    predictions: dict[tuple[str, ProductCode], LimitPrediction] = {
        (p.customer_id, p.product_code): p
        for code in ProductCode
        for p in limit_model.predict(latest, code)
    }

    rows = []
    for fact in facts.itertuples(index=False):
        score = _none_if_na(fact.score)
        for code in ProductCode:
            decision = policy.decide(
                PolicyInput(
                    customer_id=fact.customer_id,
                    customer_status=CustomerStatus(fact.customer_status),
                    segment=Segment(fact.segment),
                    max_days_past_due=int(fact.max_days_past_due),
                    monthly_income_usd=_income(fact.monthly_income_usd),
                    score=int(score) if score is not None else None,
                    limit_prediction=predictions.get((fact.customer_id, code)),
                    request=CustomerRequest(product_code=code),
                )
            )
            rows.append(
                _row(
                    decision,
                    fact.snapshot_date,
                    _none_if_na(fact.score_version),
                    generated_at,
                    expires_at,
                )
            )

    df = pd.DataFrame(rows, columns=list(ActiveOffers.to_schema().columns))
    return validate(ActiveOffers, df)


def _read(path: Path, what: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"falta {what}: {path}. Corre antes el paso que lo produce"
        )
    return read_parquet(path)


def read_parquet(path: Path) -> pd.DataFrame:
    """Lee un parquet con DuckDB (el proyecto no depende de pyarrow)."""
    # Context manager: en Windows una conexión abierta bloquea el archivo.
    with duckdb.connect() as con:
        return con.execute(f"SELECT * FROM {sql_literal(path)}").df()


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Escribe un parquet con DuckDB. Reemplazo atómico, como en Bronze."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    with duckdb.connect() as con:
        con.register("frame", df)
        con.execute(f"COPY frame TO {sql_literal(tmp)} (FORMAT parquet)")
    tmp.replace(path)


def run_offers_job(settings: Settings, generated_at: datetime | None = None) -> Path:
    """Lee C1 y C3 de Gold, decide con la política y escribe C6. Devuelve la ruta."""
    gold = settings.data_dir / "gold"
    features = validate(
        GoldCustomerFeatures, _read(gold / FEATURES_FILE, "features Gold (C1)")
    )
    scores = validate(InternalScore, _read(gold / SCORES_FILE, "puntaje interno (C3)"))
    offers = build_offers(
        features,
        scores,
        IncomeMultipleBaseline(),
        RulesPolicy(),
        generated_at or datetime.now(UTC),
    )
    path = gold / OFFERS_FILE
    write_parquet(offers, path)
    return path
