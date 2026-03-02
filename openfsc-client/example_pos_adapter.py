import logging
from typing import Optional

from pos_adapter import (
    ClearTransactionResult,
    LockPumpResult,
    PosAdapter,
    Product,
    Pump,
    Transaction,
    UnlockPumpResult,
)


class ExamplePosAdapter(PosAdapter):
    """Example POS adapter that returns fake data and logs all operations."""

    def __init__(self):
        self.logger = logging.getLogger('pos-adapter')
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            self.logger.addHandler(logging.StreamHandler())

        # Simulated state
        self.pump_states = {
            1: 'free',
            2: 'free',
            3: 'in-use',
            4: 'ready-to-pay',
        }
        self.open_transactions: dict[int, Transaction] = {
            4: Transaction(
                pump_number=4,
                site_transaction_id='TX-2026-02-26-001',
                status='open',
                product_id='0100',
                currency='EUR',
                price_with_vat=86.83,
                price_without_vat=72.98,
                vat_rate=19.0,
                vat_amount=13.85,
                unit='LTR',
                volume=54.40,
                price_per_unit=1.596,
            )
        }

    def get_products(self) -> list[Product]:
        self.logger.info('[POS] get_products() called')
        return [
            Product(
                product_id='0100',
                unit='LTR',
                currency='EUR',
                price_per_unit=1.596,
                description='Super Plus',
            ),
            Product(
                product_id='0200',
                unit='LTR',
                currency='EUR',
                price_per_unit=1.489,
                description='Super 95',
            ),
            Product(
                product_id='0300',
                unit='LTR',
                currency='EUR',
                price_per_unit=1.449,
                description='Diesel',
            ),
        ]

    def get_pumps(self) -> list[Pump]:
        self.logger.info('[POS] get_pumps() called')
        return [Pump(pump_number=num, status=status) for num, status in self.pump_states.items()]

    def get_pump_status(self, pump_number: int) -> Optional[Pump]:
        self.logger.info('[POS] get_pump_status(pump=%d) called', pump_number)
        status = self.pump_states.get(pump_number)
        if status is None:
            return None
        return Pump(pump_number=pump_number, status=status)

    def get_transactions(self, pump_number: Optional[int] = None) -> list[Transaction]:
        self.logger.info('[POS] get_transactions(pump=%s) called', pump_number)
        txns = list(self.open_transactions.values())
        if pump_number is not None:
            txns = [tx for tx in txns if tx.pump_number == pump_number]
        return txns

    def unlock_pump(
        self,
        pump_number: int,
        currency: str,
        credit: float,
        fsc_transaction_id: str,
        payment_method: str,
        product_ids: Optional[list[str]] = None,
    ) -> UnlockPumpResult:
        self.logger.info(
            '[POS] unlock_pump(pump=%d, currency=%s, credit=%.2f, fsc_tx=%s, method=%s, products=%s) called',
            pump_number,
            currency,
            credit,
            fsc_transaction_id,
            payment_method,
            product_ids,
        )

        if pump_number not in self.pump_states:
            return UnlockPumpResult(success=False, error_code=404, error_message='Pump unknown')

        if self.pump_states[pump_number] == 'locked':
            return UnlockPumpResult(success=False, error_code=412, error_message='Pump is already locked on site')

        # Simulate unlocking
        self.pump_states[pump_number] = 'locked'
        return UnlockPumpResult(success=True)

    def lock_pump(self, pump_number: int) -> LockPumpResult:
        self.logger.info('[POS] lock_pump(pump=%d) called', pump_number)

        if pump_number not in self.pump_states:
            return LockPumpResult(success=False, error_code=404, error_message='Pump unknown')

        if self.pump_states[pump_number] == 'ready-to-pay':
            return LockPumpResult(success=False, error_code=402, error_message='Payment required')

        # Simulate locking
        self.pump_states[pump_number] = 'locked'
        return LockPumpResult(success=True)

    def clear_transaction(
        self,
        pump_number: int,
        site_transaction_id: str,
        fsc_transaction_id: str,
        payment_method: str,
    ) -> ClearTransactionResult:
        self.logger.info(
            '[POS] clear_transaction(pump=%d, site_tx=%s, fsc_tx=%s, method=%s) called',
            pump_number,
            site_transaction_id,
            fsc_transaction_id,
            payment_method,
        )

        tx = self.open_transactions.get(pump_number)
        if tx is None:
            return ClearTransactionResult(
                success=False, error_code=404, error_message='Pump and SiteTransactionID unknown'
            )

        if tx.site_transaction_id != site_transaction_id:
            return ClearTransactionResult(
                success=False, error_code=404, error_message='Pump and SiteTransactionID unknown'
            )

        # Simulate clearing
        del self.open_transactions[pump_number]
        self.pump_states[pump_number] = 'free'
        return ClearTransactionResult(success=True)
