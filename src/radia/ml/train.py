"""Entrena el modelo de cupo y lo compara con el baseline sobre el mismo test.

- Split por cliente (`split_by_customer`). El test no se usa para ajustar nada.
- Modelo y baseline se evalúan sobre las mismas filas: productos cuyo dueño
  tiene ingreso > 0. Sin ingreso ninguno de los dos predice (C4).
- Métricas globales y por país, segmento y familia (fairness). Se registran en
  MLflow con los parámetros del experimento.
- Con datos mock el código corre, pero las métricas no significan nada.
"""

from dataclasses import dataclass

import mlflow
import pandas as pd

from radia.contracts.common import ProductCode, ProductFamily
from radia.ml.baseline import MULTIPLES, RANGE, IncomeMultipleBaseline
from radia.ml.dataset import TARGET, build_training_table, split_by_customer
from radia.ml.limit_model import QuantileLimitModel
from radia.ml.metrics import limit_metrics, metrics_by_group

GROUPS = ("country", "segment", "product_family")
# El baseline predice por producto del catálogo y la etiqueta trae la familia.
# Para tarjetas se usa el nivel intermedio: decisión explícita, va al reporte.
BASELINE_CODE = {
    ProductFamily.CREDIT_CARD.value: ProductCode.CC_GOLD,
    ProductFamily.PERSONAL_LOAN.value: ProductCode.PERSONAL_LOAN,
    ProductFamily.MORTGAGE.value: ProductCode.MORTGAGE,
}


@dataclass(frozen=True)
class Evaluation:
    """Métricas de un sistema: global y una tabla por grupo."""

    overall: dict[str, float]
    by_group: dict[str, pd.DataFrame]


def baseline_results(test: pd.DataFrame) -> pd.DataFrame:
    """`lower`, `pred` y `upper` del baseline por fila (producto), en USD."""
    multiple = test["product_family"].map(
        {family: MULTIPLES[code] for family, code in BASELINE_CODE.items()}
    )
    pred = test["monthly_income_usd"] * multiple
    return pd.DataFrame(
        {"lower": pred * (1 - RANGE), "pred": pred, "upper": pred * (1 + RANGE)},
        index=test.index,
    )


def evaluate(test: pd.DataFrame, predictions: pd.DataFrame) -> Evaluation:
    results = predictions.assign(y_true=test[TARGET], **{g: test[g] for g in GROUPS})
    return Evaluation(
        overall=limit_metrics(results),
        by_group={g: metrics_by_group(results, g) for g in GROUPS},
    )


def run_experiment(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    seed: int = 0,
    test_size: float = 0.2,
    data_source: str = "mock",
) -> tuple[QuantileLimitModel, dict[str, Evaluation]]:
    """Entrena, evalúa modelo y baseline, y registra todo en el run activo de MLflow."""
    table = build_training_table(features, labels)
    train, test = split_by_customer(table, test_size=test_size, seed=seed)
    test = test[test["monthly_income_usd"] > 0]
    if test.empty:
        raise ValueError("el test no tiene productos con ingreso > 0")

    model = QuantileLimitModel(seed=seed).fit(train)
    evaluations = {
        "model": evaluate(test, model.predict_table(test)),
        "baseline": evaluate(test, baseline_results(test)),
    }

    mlflow.log_params(
        {
            "data_source": data_source,
            "seed": seed,
            "test_size": test_size,
            "n_train": len(train),
            "n_test": len(test),
            "model_version": model.version,
            "baseline_version": IncomeMultipleBaseline.version,
            "quantiles": model.quantiles,
        }
    )
    for name, ev in evaluations.items():
        mlflow.log_metrics({f"{name}_{k}": v for k, v in ev.overall.items()})
        for group, df in ev.by_group.items():
            mlflow.log_text(df.to_csv(), f"by_group/{name}_{group}.csv")
    return model, evaluations
