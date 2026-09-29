"""Reglas versionadas de la política sintética (C7).

Carga `rules_v0.yaml` y lo valida con pydantic. Si el YAML tiene un hueco en
las bandas, un producto sin tope o una celda de la matriz vacía, falla al
cargar, no a mitad de una conversación.
"""

from itertools import pairwise
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from radia.contracts.common import (
    AttentionLevel,
    Band,
    CustomerStatus,
    Exposure,
    ProductCode,
    Segment,
)

SCORE_MIN = 150
SCORE_MAX = 950

DEFAULT_RULES_PATH = Path(__file__).with_name("rules_v0.yaml")

# Orden de menor a mayor exposición. Lo usa el motor para subir un nivel.
EXPOSURE_ORDER: tuple[Exposure, ...] = (Exposure.LOW, Exposure.MEDIUM, Exposure.HIGH)

_FROZEN = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Exclusions(BaseModel):
    model_config = _FROZEN

    customer_status_not_in: list[CustomerStatus] = Field(min_length=1)
    max_current_days_past_due: int = Field(ge=0)


class ProductRule(BaseModel):
    model_config = _FROZEN

    exposure: Exposure
    max_limit_usd: float = Field(gt=0)


class AnalystOverrides(BaseModel):
    model_config = _FROZEN

    score_gray_zone_points: int = Field(ge=0)
    declared_income_differs_pct: float = Field(ge=0)
    prob_delinquent_30p_gte: float = Field(ge=0, le=1)


class AdvisorOverrides(BaseModel):
    model_config = _FROZEN

    preferential_segments: list[Segment]
    preferential_exposure_in: list[Exposure]


class Overrides(BaseModel):
    model_config = _FROZEN

    to_analyst: AnalystOverrides
    to_advisor: AdvisorOverrides


class PolicyRules(BaseModel):
    model_config = _FROZEN

    policy_version: str = Field(min_length=1)
    synthetic: Literal[True]
    exclusions: Exclusions
    bands: dict[Band, tuple[int, int]]
    products: dict[ProductCode, ProductRule]
    matrix: dict[Band, dict[Exposure, AttentionLevel]]
    overrides: Overrides

    @model_validator(mode="after")
    def check_bands(self) -> Self:
        if set(self.bands) != set(Band):
            raise ValueError("bands debe traer todas las bandas")
        ranges = sorted(self.bands.values())
        if any(lo > hi for lo, hi in ranges):
            raise ValueError("cada banda exige min <= max")
        if ranges[0][0] != SCORE_MIN or ranges[-1][1] != SCORE_MAX:
            raise ValueError(f"las bandas deben cubrir {SCORE_MIN} a {SCORE_MAX}")
        for (_, prev_hi), (lo, _) in pairwise(ranges):
            if lo != prev_hi + 1:
                raise ValueError("las bandas deben ser contiguas, sin huecos ni cruces")
        return self

    @model_validator(mode="after")
    def check_catalog_and_matrix(self) -> Self:
        missing = set(ProductCode) - set(self.products)
        if missing:
            raise ValueError(f"productos sin regla: {sorted(missing)}")
        if set(self.matrix) != set(Band):
            raise ValueError("la matriz debe traer todas las bandas")
        for band, row in self.matrix.items():
            if set(row) != set(Exposure):
                raise ValueError(f"la fila {band} de la matriz está incompleta")
        return self

    def band_for(self, score: int) -> Band:
        """Banda del puntaje. Las bandas cubren 150 a 950, así que siempre hay una."""
        for band, (lo, hi) in self.bands.items():
            if lo <= score <= hi:
                return band
        raise ValueError(f"puntaje fuera de escala: {score}")

    def band_thresholds(self) -> list[int]:
        """Umbrales entre bandas: el mínimo de cada banda salvo la más baja."""
        return sorted(lo for lo, _ in self.bands.values() if lo != SCORE_MIN)


def load_rules(path: Path = DEFAULT_RULES_PATH) -> PolicyRules:
    """Lee y valida un YAML de reglas."""
    with path.open(encoding="utf-8") as fh:
        return PolicyRules.model_validate(yaml.safe_load(fh))
