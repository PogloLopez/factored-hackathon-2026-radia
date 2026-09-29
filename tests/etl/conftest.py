"""Fixtures sintéticos del raw para Bronze y Silver.

Casos cubiertos: duplicados exactos, versiones viejas por PK, nulos, un valor
que no castea, PK nula, columna extra en una partición (evolución de esquema),
partición tardía, reproceso de una transacción y huérfanos por FK.
"""

import tempfile
from pathlib import Path

import pytest

from radia.config import Settings

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
