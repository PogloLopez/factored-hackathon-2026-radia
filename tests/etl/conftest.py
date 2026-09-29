"""Fixtures sintéticos del raw para Bronze y Silver.

Casos cubiertos: duplicados exactos, versiones viejas por PK, nulos, un valor
que no castea, PK nula, columna extra en una partición (evolución de esquema),
partición tardía, reproceso de una transacción y huérfanos por FK.

Silver sintético para Gold (`silver_settings`): cliente con varios créditos y
monedas, cliente sin crédito, ingreso y credit_score nulos, tasa solo inversa
(USD -> COP), tasa posterior al corte, depósitos fuera de la ventana de 6
meses, posteriores al corte, rechazados y de otro tipo, y un cliente
registrado después del corte.
"""

import tempfile
from pathlib import Path

import duckdb
import pytest

from radia.config import Settings
from radia.etl.bronze import sql_literal
from radia.etl.silver import ident, silver_path
from radia.etl.tables import TABLES

CUSTOMERS = """customer_id,first_name,credit_score,accepts_marketing,last_updated
C1,Ana ,700,true,2026-01-01 00:00:00
C1,Ana,710,true,2026-03-01 00:00:00
C2,Luis,abc,false,2026-01-01 00:00:00
C2,Luis,abc,false,2026-01-01 00:00:00
C3,,,true,2026-02-01 00:00:00
,Sin PK,600,true,2026-01-01 00:00:00
"""

PRODUCTS = """product_id,customer_id,current_balance,last_updated
P1,C1,100.50,2026-01-01 00:00:00
P2,C9,20,2026-01-01 00:00:00
"""

EXCHANGE_RATES = """date,source_currency,target_currency,exchange_rate,source
2026-01-01,MXN,USD,0.050000,BM
2026-01-01,MXN,USD,0.050000,BM
2026-01-02,MXN,USD,0.051000,BM
"""

HEADER = "transaction_id,process_date,product_id,customer_id,amount"
TRANSACTIONS = {
    "year=2026/month=01/day=01/transactions_20260101.csv": f"""{HEADER}
T1,2026-01-01,P1,C1,10.00
T2,2026-01-01,P1,C1,5
""",
    # Evolución de esquema: columna nueva solo en esta partición.
    "year=2026/month=01/day=02/transactions_20260102.csv": f"""{HEADER},channel_v2
T3,2026-01-02,P2,C9,7,app
T5,2026-01-02,P404,C1,1,web
""",
    # Reproceso: T2 vuelve con otra fecha de proceso y otro monto.
    "year=2026/month=01/day=03/transactions_20260103.csv": f"""{HEADER}
T2,2026-01-03,P1,C1,6
""",
    # Partición tardía: fecha vieja que llega después.
    "year=2025/month=12/day=31/transactions_20251231.csv": f"""{HEADER}
T4,2025-12-31,P1,C1,3
""",
}


def write_raw(raw_dir: Path) -> None:
    base = raw_dir / "data"
    files = {
        "customers.csv": CUSTOMERS,
        "products.csv": PRODUCTS,
        "daily_exchange_rates.csv": EXCHANGE_RATES,
        **{f"transactions/{k}": v for k, v in TRANSACTIONS.items()},
    }
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture
def raw_settings():
    """Settings aislados con el raw sintético ya escrito."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        write_raw(settings.raw_dir)
        yield settings


SILVER = {
    "customers": """
        SELECT * FROM (VALUES
            ('C1', 'Mexico', 'Premium', 'Active', 750, 20000.00, TIMESTAMP '2024-06-17 10:00:00'),
            ('C2', 'Colombia', 'Basic', 'Active', 600, 4000000.00, TIMESTAMP '2026-01-10 00:00:00'),
            ('C3', 'Argentina', 'Plus', 'Active', NULL, 1000000.00, TIMESTAMP '2025-06-17 00:00:00'),
            ('C4', 'Mexico', 'Student', 'Inactive', 700, NULL, TIMESTAMP '2025-06-17 00:00:00'),
            ('C5', 'Mexico', 'Basic', 'Active', 800, 10000.00, TIMESTAMP '2026-07-01 00:00:00')
        ) t(customer_id, country, segment, customer_status, credit_score,
            estimated_monthly_income, registration_date)
    """,
    "products": """
        SELECT * FROM (VALUES
            ('P1', 'C1', 'Credit Card', 'MXN', 10000.00, 40000.00, 'Active', NULL),
            ('P2', 'C1', 'Personal Loan', 'USD', 1000.00, 5000.00, 'Active', 15),
            ('P3', 'C1', 'Mortgage', 'MXN', 0.00, 1000000.00, 'Closed', 90),
            ('P4', 'C1', 'Savings Account', 'MXN', 99999.00, NULL, 'Active', NULL),
            ('P5', 'C3', 'Credit Card', 'ARS', 500000.00, 0.00, 'Active', NULL),
            ('P6', 'C4', 'Credit Card', 'MXN', 2000.00, 10000.00, 'Blocked', 45)
        ) t(product_id, customer_id, product_type, currency, current_balance,
            credit_limit, product_status, days_past_due)
    """,
    "daily_exchange_rates": """
        SELECT * FROM (VALUES
            (DATE '2026-06-01', 'MXN', 'USD', 0.05),
            (DATE '2026-06-17', 'MXN', 'USD', 0.06),
            (DATE '2026-06-20', 'MXN', 'USD', 0.10),
            (DATE '2026-06-10', 'USD', 'COP', 4000.0),
            (DATE '2026-06-15', 'ARS', 'USD', 0.001)
        ) t(date, source_currency, target_currency, exchange_rate)
    """,
    "transactions": """
        SELECT * FROM (VALUES
            ('T1', TIMESTAMP '2026-06-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T2', TIMESTAMP '2026-05-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T3', TIMESTAMP '2026-01-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T4', TIMESTAMP '2025-12-10 12:00:00', 'C1', 'Deposit', 'Approved', 5000.0),
            ('T5', TIMESTAMP '2026-06-20 12:00:00', 'C1', 'Deposit', 'Approved', 9999.0),
            ('T6', TIMESTAMP '2026-06-05 12:00:00', 'C1', 'Deposit', 'Declined', 7777.0),
            ('T7', TIMESTAMP '2026-06-05 12:00:00', 'C1', 'Withdrawal', 'Approved', 555.0),
            ('T8', TIMESTAMP '2026-06-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T9', TIMESTAMP '2026-05-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T10', TIMESTAMP '2026-04-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T11', TIMESTAMP '2026-03-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T12', TIMESTAMP '2026-02-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T13', TIMESTAMP '2026-01-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0)
        ) t(transaction_id, transaction_date, customer_id, transaction_type,
            transaction_status, amount_usd)
    """,
}


def write_silver(settings: Settings) -> None:
    """Escribe cada tabla con el esquema completo de su spec, como Silver real.

    Las columnas que el caso no define quedan NULL con su tipo.
    """
    con = duckdb.connect()
    for table, sql in SILVER.items():
        given = {r[0] for r in con.execute(f"DESCRIBE {sql}").fetchall()}
        select = ", ".join(
            f"CAST({ident(c)} AS {t}) AS {ident(c)}"
            if c in given
            else f"NULL::{t} AS {ident(c)}"
            for c, t in TABLES[table].columns.items()
        )
        path = silver_path(settings, table)
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY (SELECT {select} FROM ({sql})) TO {sql_literal(path)} (FORMAT parquet)"
        )


@pytest.fixture
def silver_settings():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        write_silver(settings)
        yield settings
