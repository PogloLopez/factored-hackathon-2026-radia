"""Puntaje interno determinístico (C3) de 150 a 950 desde las features Gold (C1).

Los pesos viven en un YAML validado con pydantic (`ScoreWeights`). Los de
`score_weights_v0.yaml` son provisionales: checkpoint de Pablo, no aprobados.

Cálculo por cliente:
1. Cada componente convierte una feature en puntos, lineal entre dos puntos y
   recortado en los extremos. Un valor nulo recibe `missing_points`.
2. Puntaje = base + suma de puntos, redondeado y recortado a [150, 950]. Los
   pesos deben tener su rango teórico dentro de [150, 950] (se valida al
   cargar), así el recorte no aplana a los mejores ni a los peores clientes.
3. Si falta `credit_score` o `monthly_income_usd`, el puntaje es nulo y el
   desglose queda vacío: la política manda el caso al analista.

Las exclusiones (inactivo, suspendido, mora > 30 días) no se aplican aquí: son
reglas de la política (C7).
"""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radia.config import Settings
from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.internal_score import SCORE_MAX, SCORE_MIN, InternalScore
from radia.etl.bronze import sql_literal
from radia.etl.gold import gold_path, write_parquet

DEFAULT_WEIGHTS = Path(__file__).with_name("score_weights_v0.yaml")
# Sin estas features no se calcula el puntaje.
REQUIRED_FEATURES = ("credit_score", "monthly_income_usd")
# Features numéricas de C1 que puede usar un componente.
SCORABLE_FEATURES = (
    "credit_score",
    "tenure_months",
    "monthly_income_usd",
    "total_credit_balance_usd",
    "debt_to_income",
    "credit_utilization",
    "avg_monthly_inflow_usd_6m",
    "income_stability_6m",
    "n_credit_products",
    "max_days_past_due",
)


class Component(BaseModel):
    """Tramo lineal de `x_low` a `x_high`, recortado fuera de ese rango."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    x_low: float
    x_high: float
    points_low: float
    points_high: float
    missing_points: float

    @field_validator("feature")
    @classmethod
    def feature_in_c1(cls, value: str) -> str:
        if value not in SCORABLE_FEATURES:
            raise ValueError(f"feature no numérica o fuera de C1: {value}")
        return value

    @model_validator(mode="after")
    def increasing_range(self) -> "Component":
        if self.x_low >= self.x_high:
            raise ValueError("x_low debe ser menor que x_high")
        return self

    @property
    def bounds(self) -> tuple[float, float]:
        """Mínimo y máximo de puntos posibles, incluido el valor faltante."""
        pts = (self.points_low, self.points_high, self.missing_points)
        return min(pts), max(pts)

    def points(self, x: pd.Series) -> np.ndarray:
        values = x.to_numpy(dtype="float64", na_value=np.nan)
        pts = np.interp(
            values, [self.x_low, self.x_high], [self.points_low, self.points_high]
        )
        return np.where(np.isnan(values), self.missing_points, pts)


class ScoreWeights(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    score_version: str = Field(min_length=1)
    base: float = Field(ge=SCORE_MIN, le=SCORE_MAX)
    components: dict[str, Component] = Field(min_length=1)

    @property
    def theoretical_range(self) -> tuple[float, float]:
        """Puntaje mínimo y máximo posibles antes del recorte."""
        lows, highs = zip(*(c.bounds for c in self.components.values()), strict=True)
        return self.base + sum(lows), self.base + sum(highs)

    @model_validator(mode="after")
    def range_within_scale(self) -> "ScoreWeights":
        # Si el rango se sale de la escala, el recorte aplana los extremos:
        # todos los mejores (o peores) clientes quedarían con el mismo puntaje.
        low, high = self.theoretical_range
        if low < SCORE_MIN or high > SCORE_MAX:
            raise ValueError(
                f"rango teórico [{low:g}, {high:g}] fuera de [{SCORE_MIN}, {SCORE_MAX}]"
            )
        return self


def load_weights(path: Path = DEFAULT_WEIGHTS) -> ScoreWeights:
    """Lee y valida los pesos. Un YAML inválido lanza `ValidationError`."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ScoreWeights.model_validate(raw)


def compute_scores(features: pd.DataFrame, weights: ScoreWeights) -> pd.DataFrame:
    """Puntaje C3 para `features` (C1). Función pura y determinista."""
    features = validate(GoldCustomerFeatures, features).sort_values(
        ["customer_id", "snapshot_date"], ignore_index=True
    )
    points = {
        name: np.round(c.points(features[c.feature]), 2)
        for name, c in weights.components.items()
    }
    total = weights.base + np.sum(list(points.values()), axis=0)
    scorable = features[list(REQUIRED_FEATURES)].notna().all(axis=1).to_numpy()
    score = pd.array(
        np.clip(np.round(total), SCORE_MIN, SCORE_MAX).astype("int64"), dtype="Int64"
    )
    score[~scorable] = pd.NA
    breakdown = [
        json.dumps(
            {"base": weights.base, **{n: float(p[i]) for n, p in points.items()}}
        )
        if ok
        else "{}"
        for i, ok in enumerate(scorable)
    ]
    out = pd.DataFrame(
        {
            "customer_id": features["customer_id"],
            "snapshot_date": features["snapshot_date"],
            "score": score,
            "breakdown_json": breakdown,
            "score_version": weights.score_version,
        }
    )
    return validate(InternalScore, out)


def build_score(
    settings: Settings, weights_path: Path = DEFAULT_WEIGHTS
) -> pd.DataFrame:
    """Lee C1 de Gold, calcula C3 y lo escribe en `gold/internal_score.parquet`."""
    src = gold_path(settings, "customer_features")
    if not src.exists():
        raise FileNotFoundError(f"falta C1 en {src}: correr antes `radia-etl gold`")
    con = duckdb.connect()
    features = con.execute(f"SELECT * FROM read_parquet({sql_literal(src)})").df()
    features["credit_score"] = features["credit_score"].astype("Int64")
    scores = compute_scores(features, load_weights(weights_path))
    write_parquet(con, scores, gold_path(settings, "internal_score"))
    return scores
