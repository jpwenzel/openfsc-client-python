import logging
import random
import threading
from datetime import date
from typing import Optional

from example_pos_simulator import ExamplePosSimulator

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

        site_transaction_id = f'TX-{date.today().isoformat()}-{random.randint(0, 999999):06d}'
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()

        # Simulated state
        self.pump_states = {
            1: 'free',
            2: 'free',
            3: 'free',
            4: 'ready-to-pay',
            11: 'locked',
            12: 'locked',
            13: 'locked',
            14: 'locked',
        }
        self.open_transactions: dict[int, Transaction] = {
            4: Transaction(
                pump_number=4,
                site_transaction_id=site_transaction_id,
                status='open',
                product_id='0300',
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

        self.products: list[Product] = [
            Product(
                product_id='0100',
                product_type='ron95e5',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.749,
                description='Super E5',
            ),
            Product(
                product_id='0200',
                product_type='ron95e10',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.689,
                description='Super E10',
            ),
            Product(
                product_id='0300',
                product_type='ron98e5',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.869,
                description='Super 98',
            ),
            Product(
                product_id='0400',
                product_type='ron100',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=2.019,
                description='Power Fuel 100',
            ),
            Product(
                product_id='0500',
                product_type='dieselB7',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.629,
                description='Efficiency Diesel',
            ),
            Product(
                product_id='0600',
                product_type='dieselB0',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.699,
                description='Pure Diesel',
            ),
            Product(
                product_id='0700',
                product_type='dieselHvo',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=1.799,
                description='HVO Diesel',
            ),
            Product(
                product_id='0800',
                product_type='lpg',
                vat_rate=19.0,
                unit='LTR',
                currency='EUR',
                price_per_unit=0.999,
                description='LPG',
            ),
        ]
        self._simulator = ExamplePosSimulator(
            logger=self.logger,
            state_lock=self._state_lock,
            stop_event=self._stop_event,
            pump_states=self.pump_states,
            open_transactions=self.open_transactions,
            products=self.products,
        )
        self._simulator.start_price_simulation()

    def get_products(self) -> list[Product]:
        self.logger.info('[POS] get_products() called')
        with self._state_lock:
            return [
                Product(
                    product_id=product.product_id,
                    product_type=product.product_type,
                    vat_rate=product.vat_rate,
                    unit=product.unit,
                    currency=product.currency,
                    price_per_unit=product.price_per_unit,
                    description=product.description,
                )
                for product in self.products
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
