from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Product:
    product_id: str
    product_type: str  # OpenFSC product mapping category, e.g., 'ron95e5', 'dieselB7'
    vat_rate: float
    unit: str  # e.g., 'LTR'
    currency: str  # e.g., 'EUR'
    price_per_unit: float
    description: str


@dataclass
class Pump:
    pump_number: int
    status: str  # 'free', 'in-use', 'in-transaction', 'ready-to-pay', 'locked', 'out-of-order'


@dataclass
class Transaction:
    pump_number: int
    site_transaction_id: str
    status: str  # 'open', 'deferred'
    product_id: str
    currency: str
    price_with_vat: float
    price_without_vat: float
    vat_rate: float
    vat_amount: float
    unit: str
    volume: float
    price_per_unit: float
    fsc_transaction_id: Optional[str] = None


@dataclass
class UnlockPumpResult:
    success: bool
    error_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class LockPumpResult:
    success: bool
    error_code: Optional[int] = None
    error_message: Optional[str] = None


@dataclass
class ClearTransactionResult:
    success: bool
    error_code: Optional[int] = None
    error_message: Optional[str] = None


class PosAdapter(ABC):
    """Abstract interface for POS system integration."""

    @abstractmethod
    def get_products(self) -> list[Product]:
        """Return all available products with current prices."""
        pass

    @abstractmethod
    def get_pumps(self) -> list[Pump]:
        """Return status of all pumps."""
        pass

    @abstractmethod
    def get_pump_status(self, pump_number: int) -> Optional[Pump]:
        """Return status of a specific pump, or None if pump doesn't exist."""
        pass

    @abstractmethod
    def get_transactions(self, pump_number: Optional[int] = None) -> list[Transaction]:
        """Return all open/deferred transactions, optionally filtered by pump."""
        pass

    @abstractmethod
    def unlock_pump(
        self,
        pump_number: int,
        currency: str,
        credit: float,
        fsc_transaction_id: str,
        payment_method: str,
        product_ids: Optional[list[str]] = None,
    ) -> UnlockPumpResult:
        """Unlock a pump for pre-authorized fueling."""
        pass

    @abstractmethod
    def lock_pump(self, pump_number: int) -> LockPumpResult:
        """Lock/cancel a pump's current authorization."""
        pass

    @abstractmethod
    def clear_transaction(
        self,
        pump_number: int,
        site_transaction_id: str,
        fsc_transaction_id: str,
        payment_method: str,
    ) -> ClearTransactionResult:
        """Clear/complete a transaction (mark as paid)."""
        pass
