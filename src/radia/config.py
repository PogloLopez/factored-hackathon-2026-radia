"""Configuración del proyecto con pydantic-settings.

Se lee de variables de entorno y, si existe, del archivo de entorno local de la
raíz (ver `.env.example`). Los secretos son `SecretStr`: no se imprimen en logs
ni en reprs. Nunca se commitean.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tablas del dataset que usa el workflow de crédito. El resto no se descarga.
CREDIT_TABLES = (
    "customers",
    "products",
    "transactions",
    "daily_exchange_rates",
    "marketing_campaigns",
    "campaign_sends",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_default_region: str = "us-east-2"
    s3_bucket_name: str | None = None
    s3_prefix: str = "data/"

    data_dir: Path = Path("data/local")
    # Descargas concurrentes hacia el bucket. Bajo a propósito: el bucket es de
    # Factored y compartido por todos los equipos.
    s3_max_concurrency: int = Field(default=4, ge=1, le=8)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def manifest_dir(self) -> Path:
        return self.data_dir / "manifest"


@lru_cache
def get_settings() -> Settings:
    return Settings()
