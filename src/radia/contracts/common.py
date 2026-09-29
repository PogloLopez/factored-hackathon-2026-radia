"""Vocabulario compartido por todos los contratos.

Los valores de país, segmento y estado salen del diccionario de datos
([[latam_bank_complete_data_dictionary]]). El catálogo de productos y los
niveles de atención salen de [[propuesta]].
"""

from enum import StrEnum

CONTRACT_VERSION = "0.1.0"


class Country(StrEnum):
    MEXICO = "Mexico"
    COLOMBIA = "Colombia"
    ARGENTINA = "Argentina"


class Segment(StrEnum):
    PREMIUM = "Premium"
    PLUS = "Plus"
    BASIC = "Basic"
    STUDENT = "Student"


class CustomerStatus(StrEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    SUSPENDED = "Suspended"
    CLOSED = "Closed"


class ProductFamily(StrEnum):
    """Familia de crédito tal como aparece en `products.product_type`.

    Solo productos de crédito. `product_type` también trae cuentas, débito e
    inversión, que quedan fuera del alcance y no se validan con este enum.
    """

    CREDIT_CARD = "Credit Card"
    PERSONAL_LOAN = "Personal Loan"
    MORTGAGE = "Mortgage"


class ProductCode(StrEnum):
    """Catálogo de productos que ofrece el sistema (sintético)."""

    CC_BASIC = "CC_BASIC"
    CC_GOLD = "CC_GOLD"
    CC_BLACK = "CC_BLACK"
    PERSONAL_LOAN = "PERSONAL_LOAN"
    MORTGAGE = "MORTGAGE"

    @property
    def family(self) -> ProductFamily:
        return PRODUCT_FAMILY[self]


# Explícito. tests/contracts/test_common.py falla si un producto nuevo no tiene familia.
PRODUCT_FAMILY: dict[ProductCode, ProductFamily] = {
    ProductCode.CC_BASIC: ProductFamily.CREDIT_CARD,
    ProductCode.CC_GOLD: ProductFamily.CREDIT_CARD,
    ProductCode.CC_BLACK: ProductFamily.CREDIT_CARD,
    ProductCode.PERSONAL_LOAN: ProductFamily.PERSONAL_LOAN,
    ProductCode.MORTGAGE: ProductFamily.MORTGAGE,
}


class Exposure(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Band(StrEnum):
    """Banda del puntaje interno. Los umbrales viven en la política (C7)."""

    EXCELLENT = "excellent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AttentionLevel(StrEnum):
    """Nivel de atención que decide la política. Ver la matriz en [[propuesta]]."""

    AUTOMATIC = "automatic"
    ANALYST = "analyst"
    ADVISOR = "advisor"
    ANALYST_AND_ADVISOR = "analyst_and_advisor"
    NOT_ELIGIBLE = "not_eligible"


def values(enum: type[StrEnum]) -> list[str]:
    """Valores de un enum, para usarlos en `isin` de pandera."""
    return [member.value for member in enum]
