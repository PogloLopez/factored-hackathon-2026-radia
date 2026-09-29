"""Capa Gold: features por cliente (C1) y etiquetas de cupo (C2) desde Silver.

Todo se calcula con DuckDB sobre los parquet de Silver y con datos de fecha
menor o igual a `snapshot_date`. Los montos se llevan a USD con la tasa más
reciente de `daily_exchange_rates` a la fecha de corte.

Supuestos a verificar con los datos reales (ver README):
- La tasa `source_currency -> USD` se multiplica: `usd = monto * exchange_rate`.
  Si solo existe `USD -> moneda`, se usa la inversa.
- `customers` y `products` son la foto más reciente, no una historia: sus
  atributos (segmento, saldo, mora) no se pueden reconstruir a una fecha pasada.
- Los ingresos del cliente son depósitos aprobados (`Deposit` + `Approved`).
"""

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from radia.config import Settings
from radia.contracts.common import (
    Country,
    CustomerStatus,
    ProductFamily,
    Segment,
    values,
)
from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.gold_labels import GoldLimitLabels
from radia.etl.bronze import sql_literal
from radia.etl.silver import silver_path

log = logging.getLogger(__name__)

# Moneda local del ingreso declarado, por país.
COUNTRY_CURRENCY = {
    Country.MEXICO.value: "MXN",
    Country.COLOMBIA.value: "COP",
    Country.ARGENTINA.value: "ARS",
}
INFLOW_MONTHS = 6
GOLD_TABLES = ("customers", "products", "transactions", "daily_exchange_rates")


def gold_path(settings: Settings, name: str) -> Path:
    return settings.data_dir / "gold" / f"{name}.parquet"


def _sql_list(items: list[str]) -> str:
    return ", ".join(sql_literal(i) for i in items)


def _connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    """Conexión con una vista por tabla de Silver. Falla si falta alguna."""
    con = duckdb.connect()
    for table in GOLD_TABLES:
        path = silver_path(settings, table)
        if not path.exists():
            raise FileNotFoundError(f"{table}: falta Silver en {path}")
        con.execute(
            f"CREATE VIEW {table} AS SELECT * FROM read_parquet({sql_literal(path)})"
        )
    return con


def _resolve_snapshot(con: duckdb.DuckDBPyConnection, snapshot: date | None) -> date:
    """Por defecto, la fecha de la última transacción en Silver."""
    if snapshot is not None:
        return snapshot
    found = con.execute(
        "SELECT CAST(MAX(transaction_date) AS DATE) FROM transactions"
    ).fetchone()[0]
    if found is None:
        raise ValueError("transactions no tiene fechas: pasar snapshot_date explícito")
    return found


def _create_fx(con: duckdb.DuckDBPyConnection, snapshot: date) -> None:
    """Tabla `fx(currency, to_usd)`: tasa más reciente ≤ corte, por moneda.

    Prefiere la tasa directa `moneda -> USD`. Si ese día solo hay `USD -> moneda`,
    usa la inversa. USD vale 1.
    """
    snap = sql_literal(snapshot.isoformat())
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE fx AS
        WITH candidates AS (
            SELECT source_currency AS currency, date,
                   CAST(exchange_rate AS DOUBLE) AS to_usd, 0 AS priority
            FROM daily_exchange_rates
            WHERE target_currency = 'USD' AND exchange_rate > 0
              AND date <= DATE {snap}
            UNION ALL
            SELECT target_currency, date,
                   1.0 / CAST(exchange_rate AS DOUBLE), 1
            FROM daily_exchange_rates
            WHERE source_currency = 'USD' AND exchange_rate > 0
              AND date <= DATE {snap}
        )
        SELECT currency, to_usd FROM candidates
        WHERE currency <> 'USD'
        QUALIFY row_number() OVER (
            PARTITION BY currency ORDER BY date DESC, priority
        ) = 1
        UNION ALL
        SELECT 'USD', 1.0
        """
    )


def _create_credit_products(con: duckdb.DuckDBPyConnection, snapshot: date) -> None:
    """Productos de crédito abiertos al corte, con saldo y cupo en USD."""
    snap = sql_literal(snapshot.isoformat())
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE credit_products AS
        SELECT p.product_id, p.customer_id, p.product_type, p.product_status,
               p.currency, fx.to_usd,
               GREATEST(CAST(p.current_balance AS DOUBLE), 0) * fx.to_usd
                   AS balance_usd,
               CAST(p.credit_limit AS DOUBLE) * fx.to_usd AS limit_usd,
               COALESCE(p.days_past_due, 0) AS days_past_due
        FROM products p
        LEFT JOIN fx ON fx.currency = p.currency
        WHERE p.product_type IN ({_sql_list(values(ProductFamily))})
          AND (p.opening_date IS NULL OR p.opening_date <= DATE {snap})
        """
    )
    missing = con.execute(
        "SELECT COUNT(*) FROM credit_products WHERE to_usd IS NULL"
    ).fetchone()[0]
    if missing:
        log.warning("%d productos de crédito sin tasa a USD al corte", missing)


def _features_sql(snapshot: date) -> str:
    snap = sql_literal(snapshot.isoformat())
    currency_case = " ".join(
        f"WHEN {sql_literal(c)} THEN {sql_literal(cur)}"
        for c, cur in COUNTRY_CURRENCY.items()
    )
    return f"""
    WITH base AS (
        SELECT c.customer_id, c.country, c.segment, c.customer_status,
               -- Fuera del rango del buró (300 a 850) se trata como faltante.
               CASE WHEN c.credit_score BETWEEN 300 AND 850 THEN c.credit_score
               END AS credit_score,
               GREATEST(date_sub('month', CAST(c.registration_date AS DATE),
                                 DATE {snap}), 0) AS tenure_months,
               CASE WHEN c.estimated_monthly_income >= 0
                    THEN CAST(c.estimated_monthly_income AS DOUBLE) * fx.to_usd
               END AS monthly_income_usd
        FROM customers c
        LEFT JOIN fx ON fx.currency = CASE c.country {currency_case} END
        WHERE c.registration_date IS NOT NULL
          AND CAST(c.registration_date AS DATE) <= DATE {snap}
          AND c.country IN ({_sql_list(values(Country))})
          AND c.segment IN ({_sql_list(values(Segment))})
          AND c.customer_status IN ({_sql_list(values(CustomerStatus))})
    ),
    active_credit AS (
        SELECT customer_id,
               COUNT(*) AS n_credit_products,
               COALESCE(SUM(balance_usd), 0) AS total_credit_balance_usd,
               SUM(balance_usd) FILTER (WHERE product_type = 'Credit Card')
                   AS card_balance_usd,
               SUM(limit_usd) FILTER (
                   WHERE product_type = 'Credit Card' AND limit_usd > 0
               ) AS card_limit_usd
        FROM credit_products
        WHERE product_status = 'Active'
        GROUP BY customer_id
    ),
    arrears AS (
        -- Mora en todo crédito no cerrado: un producto bloqueado sigue debiendo.
        SELECT customer_id, MAX(days_past_due) AS max_days_past_due
        FROM credit_products
        WHERE product_status IS DISTINCT FROM 'Closed'
        GROUP BY customer_id
    ),
    deposits AS (
        -- Mes 0 = (corte - 1 mes, corte]; mes 5 = el más viejo de la ventana.
        SELECT customer_id,
               date_sub('month', CAST(transaction_date AS DATE), DATE {snap})
                   AS month_back,
               CAST(amount_usd AS DOUBLE) AS amount_usd
        FROM transactions
        WHERE transaction_type = 'Deposit'
          AND transaction_status = 'Approved'
          AND amount_usd > 0
          AND CAST(transaction_date AS DATE) <= DATE {snap}
    ),
    monthly AS (
        -- Meses sin depósitos cuentan como 0 para el promedio y la variación.
        SELECT b.customer_id, m.month_back, COALESCE(SUM(d.amount_usd), 0) AS inflow
        FROM base b
        CROSS JOIN range({INFLOW_MONTHS}) m(month_back)
        LEFT JOIN deposits d
            ON d.customer_id = b.customer_id AND d.month_back = m.month_back
        GROUP BY b.customer_id, m.month_back
    ),
    inflows AS (
        SELECT customer_id,
               AVG(inflow) AS avg_monthly_inflow_usd_6m,
               CASE WHEN AVG(inflow) > 0 THEN stddev_pop(inflow) / AVG(inflow)
               END AS income_stability_6m
        FROM monthly
        GROUP BY customer_id
    )
    SELECT b.customer_id,
           CAST(DATE {snap} AS TIMESTAMP) AS snapshot_date,
           b.country, b.segment, b.customer_status, b.credit_score,
           CAST(b.tenure_months AS BIGINT) AS tenure_months,
           b.monthly_income_usd,
           COALESCE(ac.total_credit_balance_usd, 0) AS total_credit_balance_usd,
           CASE WHEN b.monthly_income_usd > 0
                THEN COALESCE(ac.total_credit_balance_usd, 0) / b.monthly_income_usd
           END AS debt_to_income,
           ac.card_balance_usd / ac.card_limit_usd AS credit_utilization,
           i.avg_monthly_inflow_usd_6m,
           i.income_stability_6m,
           CAST(COALESCE(ac.n_credit_products, 0) AS BIGINT) AS n_credit_products,
           CAST(COALESCE(a.max_days_past_due, 0) AS BIGINT) AS max_days_past_due
    FROM base b
    LEFT JOIN active_credit ac USING (customer_id)
    LEFT JOIN arrears a USING (customer_id)
    LEFT JOIN inflows i USING (customer_id)
    ORDER BY b.customer_id
    """


def _write(con: duckdb.DuckDBPyConnection, df: pd.DataFrame, path: Path) -> None:
    """Escribe el parquet de forma atómica (archivo temporal y renombre)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    con.register("out_df", df)
    con.execute(f"COPY out_df TO {sql_literal(tmp)} (FORMAT parquet)")
    con.unregister("out_df")
    tmp.replace(path)


def build_features(
    settings: Settings, snapshot_date: date | None = None
) -> pd.DataFrame:
    """Construye C1 (`GoldCustomerFeatures`), lo valida y lo escribe en Gold.

    Clientes con país, segmento o estado fuera del vocabulario, o sin fecha de
    registro, se descartan y se cuentan en el log: C1 no los admite.
    """
    con = _connect(settings)
    snapshot = _resolve_snapshot(con, snapshot_date)
    _create_fx(con, snapshot)
    _create_credit_products(con, snapshot)
    df = con.execute(_features_sql(snapshot)).df()
    total = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    if total - len(df):
        log.warning(
            "%d clientes fuera de C1 (vocabulario, registro nulo o posterior al corte)",
            total - len(df),
        )
    df["credit_score"] = df["credit_score"].astype("Int64")
    df = validate(GoldCustomerFeatures, df)
    _write(con, df, gold_path(settings, "customer_features"))
    return df


def build_limit_labels(
    settings: Settings, snapshot_date: date | None = None
) -> pd.DataFrame:
    """Construye C2 (`GoldLimitLabels`): cupo en USD por producto de crédito.

    Productos sin cupo positivo o sin tasa a USD al corte se descartan.
    """
    con = _connect(settings)
    snapshot = _resolve_snapshot(con, snapshot_date)
    _create_fx(con, snapshot)
    _create_credit_products(con, snapshot)
    snap = sql_literal(snapshot.isoformat())
    df = con.execute(
        f"""
        SELECT product_id, customer_id,
               CAST(DATE {snap} AS TIMESTAMP) AS snapshot_date,
               product_type AS product_family,
               limit_usd AS credit_limit_usd
        FROM credit_products
        WHERE limit_usd > 0
        ORDER BY product_id
        """
    ).df()
    df = validate(GoldLimitLabels, df)
    _write(con, df, gold_path(settings, "limit_labels"))
    return df
