"""C6. Ofertas vigentes: la decisión de la política por cliente y producto.

Productor: job batch del ETL que llama a la política (C7) con C1, C3 y el
modelo de cupo (C4). Consumidores: tools del orquestador y la web.

- Una fila por (cliente, producto) vigente, incluidas las no elegibles, para
  que el chat pueda explicar por qué no hay oferta.
- Política sintética: `synthetic_policy` siempre es verdadero. No son
  decisiones reales de crédito.
- Pasada `expires_at`, la oferta no se usa: el orquestador cae a un fallback
  seguro y nunca inventa una.
- Sin puntaje (datos faltantes) nunca hay resolución automática.
- La exposición no es columna: se deriva del producto con el YAML de la política.
"""

import json

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series

from radia.contracts.common import AttentionLevel, Band, ProductCode, values
from radia.contracts.data import validate

CONTRACT_VERSION = "0.1.0"


def _is_code_list(raw: str, *, allow_empty: bool) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(parsed, list)
        and (allow_empty or len(parsed) > 0)
        and all(isinstance(r, str) and r for r in parsed)
    )


class ActiveOffers(pa.DataFrameModel):
    offer_id: Series[str] = pa.Field(nullable=False, unique=True)
    customer_id: Series[str] = pa.Field(nullable=False)
    product_code: Series[str] = pa.Field(isin=values(ProductCode))
    attention_level: Series[str] = pa.Field(isin=values(AttentionLevel))
    # Nulos si el cliente no tiene puntaje (faltan datos).
    score: Series[pd.Int64Dtype] = pa.Field(ge=150, le=950, nullable=True)
    band: Series[str] = pa.Field(isin=values(Band), nullable=True)
    # Nulos si la oferta no es elegible o no hay predicción de cupo.
    offered_limit_usd: Series[float] = pa.Field(gt=0, nullable=True)
    negotiation_min_usd: Series[float] = pa.Field(gt=0, nullable=True)
    negotiation_max_usd: Series[float] = pa.Field(gt=0, nullable=True)
    # JSON con códigos de la política. Razones: al menos una. Alertas: pueden faltar.
    reasons_json: Series[str] = pa.Field(nullable=False)
    alerts_json: Series[str] = pa.Field(nullable=False)
    # Alternativa de menor exposición para ofrecer cuando no es elegible.
    alternative_product_code: Series[str] = pa.Field(
        isin=values(ProductCode), nullable=True
    )
    policy_version: Series[str] = pa.Field(nullable=False)
    limit_model_version: Series[str] = pa.Field(nullable=True)
    synthetic_policy: Series[bool] = pa.Field(isin=[True])
    generated_at: Series[pd.Timestamp] = pa.Field(nullable=False)
    expires_at: Series[pd.Timestamp] = pa.Field(nullable=False)

    class Config:
        strict = True
        coerce = True
        unique = ("customer_id", "product_code")

    @pa.check("reasons_json", element_wise=True)
    def reasons_are_non_empty_list(cls, raw: str) -> bool:
        return _is_code_list(raw, allow_empty=False)

    @pa.check("alerts_json", element_wise=True)
    def alerts_are_list(cls, raw: str) -> bool:
        return _is_code_list(raw, allow_empty=True)

    @pa.dataframe_check
    def score_and_band_null_together(cls, df: pd.DataFrame) -> pd.Series:
        return df["score"].isna() == df["band"].isna()

    @pa.dataframe_check
    def no_automatic_without_score(cls, df: pd.DataFrame) -> pd.Series:
        return ~(
            df["score"].isna() & (df["attention_level"] == AttentionLevel.AUTOMATIC)
        )

    @pa.dataframe_check
    def limit_has_model_version(cls, df: pd.DataFrame) -> pd.Series:
        return df["offered_limit_usd"].isna() | df["limit_model_version"].notna()

    @pa.dataframe_check
    def expires_after_generated(cls, df: pd.DataFrame) -> pd.Series:
        return df["expires_at"] > df["generated_at"]

    @pa.dataframe_check
    def limit_inside_negotiation_range(cls, df: pd.DataFrame) -> pd.Series:
        lo, mid, hi = (
            df["negotiation_min_usd"],
            df["offered_limit_usd"],
            df["negotiation_max_usd"],
        )
        all_null = lo.isna() & mid.isna() & hi.isna()
        ordered = (lo <= mid) & (mid <= hi)
        return all_null | ordered

    @pa.dataframe_check
    def not_eligible_has_no_limit(cls, df: pd.DataFrame) -> pd.Series:
        not_eligible = df["attention_level"] == AttentionLevel.NOT_ELIGIBLE
        return ~not_eligible | df["offered_limit_usd"].isna()


def make_active_offers(
    scores: pd.DataFrame, seed: int = 0, ttl_days: int = 7
) -> pd.DataFrame:
    """Mock de C6 a partir de C3. Decisiones al azar, no las de la política real."""
    rng = np.random.default_rng(seed)
    rows = scores.merge(
        pd.DataFrame({"product_code": values(ProductCode)}), how="cross"
    )
    n = len(rows)
    level = rng.choice(values(AttentionLevel), size=n)
    level[rows["score"].isna().to_numpy()] = AttentionLevel.ANALYST
    limit = rng.lognormal(mean=7.5, sigma=0.8, size=n)
    limit[level == AttentionLevel.NOT_ELIGIBLE] = np.nan
    generated_at = pd.Timestamp("2026-06-17 06:00")
    df = pd.DataFrame(
        {
            "offer_id": [f"MOCKO{i:08d}" for i in range(n)],
            "customer_id": rows["customer_id"].to_numpy(),
            "product_code": rows["product_code"].to_numpy(),
            "attention_level": level,
            "score": rows["score"].array,
            "band": rng.choice(values(Band), size=n),
            "offered_limit_usd": limit,
            "negotiation_min_usd": limit * 0.8,
            "negotiation_max_usd": limit * 1.2,
            "reasons_json": json.dumps(["mock"]),
            "alerts_json": "[]",
            "alternative_product_code": None,
            "policy_version": "mock-policy-0.0.0",
            "limit_model_version": "mock-limit-0.0.0",
            "synthetic_policy": True,
            "generated_at": generated_at,
            "expires_at": generated_at + pd.Timedelta(days=ttl_days),
        }
    )
    df.loc[df["score"].isna(), "band"] = None
    return validate(ActiveOffers, df)
