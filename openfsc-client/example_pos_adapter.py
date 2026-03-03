import logging
import random
import threading
from collections.abc import Callable
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

        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._transaction_notification_handler: Callable[[Transaction], None] | None = None

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

        # Simulated state
        self.pump_states = {
            1: 'locked',
            2: 'locked',
            3: 'locked',
            11: 'free',
            12: 'free',
            13: 'free',
            21: 'ready-to-pay',
            22: 'ready-to-pay',
            23: 'ready-to-pay',
        }

        self.open_transactions: dict[int, Transaction] = {
            pump_number: self._create_random_ready_to_pay_transaction(pump_number)
            for pump_number in (21, 22, 23)
        }

        self._simulator = ExamplePosSimulator(
            logger=self.logger,
            state_lock=self._state_lock,
            stop_event=self._stop_event,
            pump_states=self.pump_states,
            open_transactions=self.open_transactions,
            products=self.products,
            create_transaction_for_pump=self._create_random_ready_to_pay_transaction,
            create_transaction_for_unlock=self._create_unlock_transaction,
            notify_completed_unlock_transaction=self._on_completed_unlock_transaction,
        )
        self._simulator.start_price_simulation()
        self._simulator.start_pump_traffic_simulation()
        self._simulator.start_unlock_flow_simulation()

    def set_transaction_notification_handler(self, handler: Callable[[Transaction], None]):
        self._transaction_notification_handler = handler

    def _on_completed_unlock_transaction(self, transaction: Transaction):
        handler = self._transaction_notification_handler
        if callable(handler):
            handler(transaction)

    def _next_site_transaction_id(self) -> str:
        return f'TX-{date.today().isoformat()}-{random.randint(0, 999999):06d}'

    def _create_random_ready_to_pay_transaction(self, pump_number: int) -> Transaction:
        product = random.choice(self.products)
        volume = round(random.uniform(12.0, 62.0), 2)
        price_with_vat = round(volume * product.price_per_unit, 2)
        price_without_vat = round(price_with_vat / (1 + product.vat_rate / 100), 2)
        vat_amount = round(price_with_vat - price_without_vat, 2)

        return Transaction(
            pump_number=pump_number,
            site_transaction_id=self._next_site_transaction_id(),
            status='open',
            product_id=product.product_id,
            currency=product.currency,
            price_with_vat=price_with_vat,
            price_without_vat=price_without_vat,
            vat_rate=product.vat_rate,
            vat_amount=vat_amount,
            unit=product.unit,
            volume=volume,
            price_per_unit=product.price_per_unit,
        )

    def _create_unlock_transaction(
        self,
        pump_number: int,
        fsc_transaction_id: str,
        credit: float,
        product_ids: Optional[list[str]],
    ) -> Transaction:
        allowed_products = self.products
        if product_ids:
            mapped = [product for product in self.products if product.product_id in set(product_ids)]
            if mapped:
                allowed_products = mapped

        product = random.choice(allowed_products)
        if credit <= 0:
            target_gross = product.price_per_unit
        else:
            target_gross = credit * random.uniform(0.55, 0.95)

        volume = max(0.01, round(target_gross / product.price_per_unit, 2))
        price_with_vat = round(volume * product.price_per_unit, 2)

        if credit > 0 and price_with_vat > credit:
            volume = max(0.01, round(credit / product.price_per_unit, 2))
            price_with_vat = round(volume * product.price_per_unit, 2)

        price_without_vat = round(price_with_vat / (1 + product.vat_rate / 100), 2)
        vat_amount = round(price_with_vat - price_without_vat, 2)

        return Transaction(
            pump_number=pump_number,
            site_transaction_id=fsc_transaction_id,
            status='open',
            product_id=product.product_id,
            currency=product.currency,
            price_with_vat=price_with_vat,
            price_without_vat=price_without_vat,
            vat_rate=product.vat_rate,
            vat_amount=vat_amount,
            unit=product.unit,
            volume=volume,
            price_per_unit=product.price_per_unit,
            fsc_transaction_id=fsc_transaction_id,
        )

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
        with self._state_lock:
            return [Pump(pump_number=num, status=status) for num, status in self.pump_states.items()]

    def get_pump_status(self, pump_number: int) -> Optional[Pump]:
        self.logger.info('[POS] get_pump_status(pump=%d) called', pump_number)
        with self._state_lock:
            status = self.pump_states.get(pump_number)
            if status is None:
                return None
            return Pump(pump_number=pump_number, status=status)

    def get_transactions(self, pump_number: Optional[int] = None) -> list[Transaction]:
        self.logger.info('[POS] get_transactions(pump=%s) called', pump_number)
        with self._state_lock:
            txns = list(self.open_transactions.values())
            if pump_number is not None:
                txns = [tx for tx in txns if tx.pump_number == pump_number]
            return txns

    def on_pumpstatus_requested(self, pump_number: int):
        self._simulator.on_pumpstatus_requested(pump_number)

    def on_transaction_cleared(self, pump_number: int):
        self._simulator.on_transaction_cleared(pump_number)

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

        with self._state_lock:
            if pump_number not in self.pump_states:
                return UnlockPumpResult(success=False, error_code=404, error_message='Pump unknown')

            if self.pump_states[pump_number] in {'in-use', 'ready-to-pay'}:
                return UnlockPumpResult(success=False, error_code=412, error_message='Pump is already in transaction flow')

            if self.pump_states[pump_number] != 'locked':
                return UnlockPumpResult(success=False, error_code=412, error_message='Pump is not locked on site')

        self._simulator.on_unlock_pump_authorized(pump_number, fsc_transaction_id, credit, product_ids)
        return UnlockPumpResult(success=True)

    def lock_pump(self, pump_number: int) -> LockPumpResult:
        self.logger.info('[POS] lock_pump(pump=%d) called', pump_number)

        with self._state_lock:
            if pump_number not in self.pump_states:
                return LockPumpResult(success=False, error_code=404, error_message='Pump unknown')

            if self.pump_states[pump_number] == 'ready-to-pay':
                return LockPumpResult(success=False, error_code=402, error_message='Payment required')

            # Simulate locking
            self.pump_states[pump_number] = 'locked'

        self._simulator.on_pump_locked(pump_number)
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

        with self._state_lock:
            tx = self.open_transactions.get(pump_number)
            if tx is None:
                return ClearTransactionResult(
                    success=False, error_code=404, error_message='Pump and SiteTransactionID unknown'
                )

            if tx.site_transaction_id != site_transaction_id:
                return ClearTransactionResult(
                    success=False, error_code=404, error_message='Pump and SiteTransactionID unknown'
                )

            if tx.fsc_transaction_id is not None and tx.fsc_transaction_id != fsc_transaction_id:
                return ClearTransactionResult(
                    success=False,
                    error_code=404,
                    error_message='Pump, SiteTransactionID and FSCTransactionID mismatch',
                )

            # Simulate clearing
            del self.open_transactions[pump_number]
            if tx.fsc_transaction_id is not None:
                self.pump_states[pump_number] = 'locked'
            else:
                self.pump_states[pump_number] = 'free'

        self.on_transaction_cleared(pump_number)
        return ClearTransactionResult(success=True)
