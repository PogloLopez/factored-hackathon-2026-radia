"""C3. Puntaje interno determinístico de 150 a 950 por cliente.

Productor: ETL. Consumidores: política (C7) y bandeja del analista.
Las bandas no viven aquí: sus umbrales son de la política.
"""

import json

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.typing.pandas import Series

from radia.contracts.data import validate

CONTRACT_VERSION = "0.1.0"

SCORE_MIN = 150
SCORE_MAX = 950


def _is_breakdown(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict) and all(
        isinstance(k, str) and isinstance(v, int | float) and not isinstance(v, bool)
        for k, v in parsed.items()
    )


class InternalScore(pa.DataFrameModel):
    customer_id: Series[str] = pa.Field(nullable=False)
    snapshot_date: Series[pd.Timestamp] = pa.Field(nullable=False)
    # Nulo si faltan datos para calcularlo. La política lo manda al analista.
    score: Series[pd.Int64Dtype] = pa.Field(ge=SCORE_MIN, le=SCORE_MAX, nullable=True)
    # JSON {componente: puntos}. Es la explicación que ve el analista y el cliente.
    breakdown_json: Series[str] = pa.Field(nullable=False)
    score_version: Series[str] = pa.Field(nullable=False)

    class Config:
        strict = True
        coerce = True
        unique = ("customer_id", "snapshot_date")

    @pa.check("breakdown_json", element_wise=True)
    def breakdown_is_json_dict(cls, raw: str) -> bool:
        return _is_breakdown(raw)


def make_internal_scores(features: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Mock de C3 a partir de features C1. Puntajes al azar, no el cálculo real."""
    rng = np.random.default_rng(seed)
    n = len(features)
    score = pd.array(rng.integers(SCORE_MIN, SCORE_MAX + 1, size=n), dtype="Int64")
    score[features["monthly_income_usd"].isna().to_numpy()] = pd.NA
    breakdown = [
        "{}"
        if pd.isna(s)
        else json.dumps({"credit_score": int(s) - SCORE_MIN, "base": SCORE_MIN})
        for s in score
    ]
    df = pd.DataFrame(
        {
            "customer_id": features["customer_id"].to_numpy(),
            "snapshot_date": features["snapshot_date"].to_numpy(),
            "score": score,
            "breakdown_json": breakdown,
            "score_version": "mock-0.0.0",
        }
    )
    return validate(InternalScore, df)
