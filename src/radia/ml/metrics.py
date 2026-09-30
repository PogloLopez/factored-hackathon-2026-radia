"""Métricas del modelo de cupo, iguales para el modelo y el baseline.

Entrada: un DataFrame con `y_true`, `pred`, `lower` y `upper` en USD, una fila
por producto de test. Ver sección 5 de [[propuesta]].

- MAE en USD.
- Error porcentual absoluto, mediana y media. La mediana resiste los cupos
  muy chicos, donde el error relativo explota.
- Cobertura: fracción de cupos reales dentro del rango de negociación.
- Ancho del rango relativo a la predicción: un rango enorme cubre todo y no sirve.
"""

import pandas as pd

COLUMNS = ("y_true", "pred", "lower", "upper")


def _check(results: pd.DataFrame) -> None:
    """Rechaza entradas que sesgarían las métricas en silencio."""
    missing = set(COLUMNS) - set(results.columns)
    if missing:
        raise ValueError(f"faltan columnas: {sorted(missing)}")
    if results.empty:
        raise ValueError("sin filas para evaluar")
    cols = results[list(COLUMNS)]
    if cols.isna().any().any():
        raise ValueError("hay nulos en y_true, pred, lower o upper")
    # Cupos en 0 harían infinito el error porcentual y el ancho relativo.
    if not ((cols["y_true"] > 0) & (cols["pred"] > 0)).all():
        raise ValueError("y_true y pred deben ser > 0")
    if not (cols["lower"] <= cols["upper"]).all():
        raise ValueError("se exige lower <= upper")


def limit_metrics(results: pd.DataFrame) -> dict[str, float]:
    _check(results)
    y, pred = results["y_true"], results["pred"]
    ape = (y - pred).abs() / y
    covered = (results["lower"] <= y) & (y <= results["upper"])
    width = (results["upper"] - results["lower"]) / pred
    return {
        "n": float(len(results)),
        "mae_usd": float((y - pred).abs().mean()),
        "median_ape": float(ape.median()),
        "mean_ape": float(ape.mean()),
        "coverage": float(covered.mean()),
        "median_width_pct": float(width.median()),
    }


def metrics_by_group(results: pd.DataFrame, by: str) -> pd.DataFrame:
    """Una fila por valor de `by` (país, segmento, familia). Base del análisis de fairness."""
    if results[by].isna().any():
        raise ValueError(f"hay nulos en {by}: esas filas quedarían fuera del reporte")
    rows = {
        key: limit_metrics(group)
        for key, group in results.groupby(by, observed=True, sort=True)
    }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis(by)
