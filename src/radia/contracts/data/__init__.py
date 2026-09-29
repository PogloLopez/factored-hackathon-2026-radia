"""Contratos de tablas (pandera). El productor valida al escribir y el consumidor al leer."""

import pandas as pd
import pandera.pandas as pa


def validate[M: pa.DataFrameModel](model: type[M], df: pd.DataFrame) -> pd.DataFrame:
    """Valida `df` contra `model` con índice limpio.

    Con pandas 3, pandera se cae al formatear el error si el índice tiene
    duplicados (p. ej. tras un `concat`). Resetear el índice evita ese fallo y
    deja que el chequeo de unicidad reporte el error real.
    """
    return model.validate(df.reset_index(drop=True))
