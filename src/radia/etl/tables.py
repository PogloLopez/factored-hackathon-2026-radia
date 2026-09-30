"""Especificación declarativa de las tablas que pasan por Bronze y Silver.

Tipos DuckDB tomados de [[latam_bank_complete_data_dictionary]]. Si los datos
reales traen otro formato, se ajusta aquí y no en el código de las capas.
"""

import unicodedata
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ForeignKey(BaseModel):
    """Columna que debe existir en otra tabla (se reporta, no se filtra)."""

    model_config = ConfigDict(frozen=True)

    column: str
    ref_table: str
    ref_column: str


class TableSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    # Ruta o glob relativo a `settings.raw_dir`.
    source: str
    primary_key: tuple[str, ...] = Field(min_length=1)
    # Columna para quedarse con la última versión por PK. None: sin versión
    # explícita, se desempata por archivo de origen (el más reciente gana).
    order_by: str | None
    columns: dict[str, str]
    foreign_keys: tuple[ForeignKey, ...] = ()
    # Traducción de valores reales al vocabulario de los contratos, por columna.
    # Un valor que no está en el mapa pasa tal cual.
    value_map: dict[str, dict[str, str]] = {}

    @field_validator("value_map")
    @classmethod
    def nfc_keys(
        cls, value_map: dict[str, dict[str, str]]
    ) -> dict[str, dict[str, str]]:
        # Silver compara en NFC: "é" puede venir como un carácter o como "e" + tilde.
        return {
            col: {unicodedata.normalize("NFC", k): v for k, v in mapping.items()}
            for col, mapping in value_map.items()
        }

    @model_validator(mode="after")
    def check_value_map(self) -> Self:
        unknown = sorted(set(self.value_map) - set(self.columns))
        if unknown:
            raise ValueError(
                f"{self.name}: value_map usa columnas fuera de la spec {unknown}"
            )
        # Un mapa vacío arma `IN ()` y un CASE sin WHEN: SQL inválido en Silver.
        empty = sorted(c for c, mapping in self.value_map.items() if not mapping)
        if empty:
            raise ValueError(f"{self.name}: value_map vacío en {empty}")
        return self


CUSTOMERS = TableSpec(
    name="customers",
    source="data/customers.csv",
    primary_key=("customer_id",),
    order_by="last_updated",
    columns={
        "customer_id": "VARCHAR",
        "document_number": "VARCHAR",
        "document_type": "VARCHAR",
        "first_name": "VARCHAR",
        "last_name": "VARCHAR",
        "date_of_birth": "DATE",
        "gender": "VARCHAR",
        "email": "VARCHAR",
        "mobile_phone": "VARCHAR",
        "landline_phone": "VARCHAR",
        "address": "VARCHAR",
        "city": "VARCHAR",
        "state": "VARCHAR",
        "country": "VARCHAR",
        "postal_code": "VARCHAR",
        "detected_accent": "VARCHAR",
        "segment": "VARCHAR",
        "credit_score": "INTEGER",
        "estimated_monthly_income": "DECIMAL(12,2)",
        "occupation": "VARCHAR",
        "marital_status": "VARCHAR",
        "education_level": "VARCHAR",
        "registration_date": "TIMESTAMP",
        "registration_branch_id": "VARCHAR",
        "customer_status": "VARCHAR",
        "last_updated": "TIMESTAMP",
        "accepts_marketing": "BOOLEAN",
    },
    # Los datos reales traen el país con tilde (verificado 2026-09-30).
    value_map={"country": {"México": "Mexico"}},
)

PRODUCTS = TableSpec(
    name="products",
    source="data/products.csv",
    primary_key=("product_id",),
    order_by="last_updated",
    columns={
        "product_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "product_type": "VARCHAR",
        "product_number": "VARCHAR",
        "currency": "VARCHAR",
        "current_balance": "DECIMAL(15,2)",
        "credit_limit": "DECIMAL(15,2)",
        "interest_rate": "DECIMAL(5,2)",
        "opening_date": "DATE",
        "expiration_date": "DATE",
        "opening_branch_id": "VARCHAR",
        "product_status": "VARCHAR",
        "opening_channel": "VARCHAR",
        "has_linked_app": "BOOLEAN",
        "days_past_due": "INTEGER",
        "last_transaction_date": "TIMESTAMP",
        "last_updated": "TIMESTAMP",
    },
    foreign_keys=(
        ForeignKey(
            column="customer_id", ref_table="customers", ref_column="customer_id"
        ),
    ),
    # Los datos reales traen el tipo en español (verificado 2026-09-30). Solo se
    # traducen las familias de crédito; cuentas, débito, seguros e inversión no
    # entran al workflow y quedan tal cual.
    value_map={
        "product_type": {
            "Tarjeta Crédito": "Credit Card",
            "Préstamo Personal": "Personal Loan",
            "Préstamo Hipotecario": "Mortgage",
        }
    },
)

TRANSACTIONS = TableSpec(
    name="transactions",
    source="data/transactions/**/*.csv",
    primary_key=("transaction_id",),
    order_by="process_date",
    columns={
        "transaction_id": "VARCHAR",
        "transaction_date": "TIMESTAMP",
        "process_date": "DATE",
        "product_id": "VARCHAR",
        "customer_id": "VARCHAR",
        "transaction_type": "VARCHAR",
        "transaction_category": "VARCHAR",
        "amount": "DECIMAL(15,2)",
        "currency": "VARCHAR",
        "amount_usd": "DECIMAL(15,2)",
        "channel": "VARCHAR",
        "branch_id": "VARCHAR",
        "merchant_name": "VARCHAR",
        "merchant_category": "VARCHAR",
        "transaction_country": "VARCHAR",
        "transaction_city": "VARCHAR",
        "transaction_status": "VARCHAR",
        "response_code": "VARCHAR",
        "is_fraud": "BOOLEAN",
        "fraud_score": "DECIMAL(5,2)",
        "latitude": "DECIMAL(10,7)",
        "longitude": "DECIMAL(10,7)",
    },
    foreign_keys=(
        ForeignKey(
            column="customer_id", ref_table="customers", ref_column="customer_id"
        ),
        ForeignKey(column="product_id", ref_table="products", ref_column="product_id"),
    ),
)

DAILY_EXCHANGE_RATES = TableSpec(
    name="daily_exchange_rates",
    source="data/daily_exchange_rates.csv",
    primary_key=("date", "source_currency", "target_currency"),
    order_by=None,
    columns={
        "date": "DATE",
        "source_currency": "VARCHAR",
        "target_currency": "VARCHAR",
        "exchange_rate": "DECIMAL(12,6)",
        "buy_rate": "DECIMAL(12,6)",
        "sell_rate": "DECIMAL(12,6)",
        "source": "VARCHAR",
    },
)

CALL_CENTER_INTERACTIONS = TableSpec(
    name="call_center_interactions",
    source="data/call_center_interactions/**/*.csv",
    primary_key=("interaction_id",),
    order_by="process_date",
    columns={
        "interaction_id": "VARCHAR",
        "interaction_date": "TIMESTAMP",
        "process_date": "DATE",
        "customer_id": "VARCHAR",
        "agent_id": "VARCHAR",
        "interaction_type": "VARCHAR",
        "channel": "VARCHAR",
        "contact_reason": "VARCHAR",
        "reason_category": "VARCHAR",
        "duration_seconds": "INTEGER",
        "wait_time_seconds": "INTEGER",
        "was_resolved": "BOOLEAN",
        "requires_followup": "BOOLEAN",
        "detected_sentiment": "VARCHAR",
        "sentiment_score": "DECIMAL(3,2)",
        "customer_detected_accent": "VARCHAR",
        "agent_used_accent": "VARCHAR",
        "was_escalated": "BOOLEAN",
        "mentioned_products": "VARCHAR",
        "has_transcript": "BOOLEAN",
        "has_recording": "BOOLEAN",
    },
    foreign_keys=(
        ForeignKey(
            column="customer_id", ref_table="customers", ref_column="customer_id"
        ),
    ),
)

CALL_TRANSCRIPTS = TableSpec(
    name="call_transcripts",
    source="data/call_transcripts/**/*.csv",
    primary_key=("transcript_id",),
    order_by="process_date",
    columns={
        "transcript_id": "VARCHAR",
        "interaction_id": "VARCHAR",
        "process_date": "DATE",
        "customer_id": "VARCHAR",
        "agent_id": "VARCHAR",
        "full_text": "VARCHAR",
        "customer_text": "VARCHAR",
        "agent_text": "VARCHAR",
        "detected_language": "VARCHAR",
        "detected_accent": "VARCHAR",
        "accent_confidence": "DECIMAL(3,2)",
        "detected_keywords": "VARCHAR",
        "mentioned_entities": "VARCHAR",
        "detected_intents": "VARCHAR",
        "main_topics": "VARCHAR",
        "transcription_model": "VARCHAR",
        "audio_quality": "VARCHAR",
        "duration_seconds": "INTEGER",
    },
    foreign_keys=(
        ForeignKey(
            column="customer_id", ref_table="customers", ref_column="customer_id"
        ),
        ForeignKey(
            column="interaction_id",
            ref_table="call_center_interactions",
            ref_column="interaction_id",
        ),
    ),
)

# Orden de construcción: dimensiones antes que hechos, para medir huérfanos.
TABLES: dict[str, TableSpec] = {
    t.name: t for t in (CUSTOMERS, PRODUCTS, DAILY_EXCHANGE_RATES, TRANSACTIONS)
}
# Tablas de contacto (clasificador de intención). No entran al default: solo se
# construyen si se piden con --tables, así nadie necesita descargarlas.
CONTACT_TABLES: dict[str, TableSpec] = {
    t.name: t for t in (CALL_CENTER_INTERACTIONS, CALL_TRANSCRIPTS)
}
ALL_TABLES: dict[str, TableSpec] = TABLES | CONTACT_TABLES


def select_tables(names: str | None) -> list[TableSpec]:
    """Specs pedidas (lista separada por comas) en orden de construcción."""
    if not names:
        return list(TABLES.values())
    wanted = {n.strip() for n in names.split(",") if n.strip()}
    unknown = wanted - ALL_TABLES.keys()
    if unknown:
        raise ValueError(f"tablas sin spec de Bronze/Silver: {sorted(unknown)}")
    return [t for t in ALL_TABLES.values() if t.name in wanted]
