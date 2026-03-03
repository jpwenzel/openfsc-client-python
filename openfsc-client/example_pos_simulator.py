import math
import random
import threading
import time
from collections.abc import Callable

from pos_adapter import Product, Transaction


class ExamplePosSimulator:
    def __init__(
        self,
        logger,
        state_lock: threading.Lock,
        stop_event: threading.Event,
        pump_states: dict[int, str],
        open_transactions: dict[int, Transaction],
        products: list[Product],
        create_transaction_for_pump: Callable[[int], Transaction],
        create_transaction_for_unlock: Callable[[int, str, float, list[str] | None], Transaction],
        notify_completed_unlock_transaction: Callable[[Transaction], None] | None = None,
    ):
        self.logger = logger
        self._state_lock = state_lock
        self._stop_event = stop_event
        self.pump_states = pump_states
        self.open_transactions = open_transactions
        self.products = products
        self._create_transaction_for_pump = create_transaction_for_pump
        self._create_transaction_for_unlock = create_transaction_for_unlock
        self._notify_completed_unlock_transaction = notify_completed_unlock_transaction
        self._initial_prices = {product.product_id: product.price_per_unit for product in self.products}
        self._price_simulation_thread: threading.Thread | None = None
        self._pump_traffic_simulation_thread: threading.Thread | None = None
        self._unlock_flow_simulation_thread: threading.Thread | None = None
        self._traffic_pumps = (11, 12, 13)
        self._selection_deadline_by_pump: dict[int, float] = {}
        self._fallback_deadline_by_pump: dict[int, float] = {}
        self._creation_not_before_by_pump: dict[int, float] = {}
        self._price_change_not_before_by_product_id: dict[str, float] = {}
        self._pending_unlock_by_pump: dict[int, dict[str, object]] = {}
        self._pending_unlock_notification_by_pump: dict[int, dict[str, object]] = {}

    def start_price_simulation(self):
        if self._price_simulation_thread and self._price_simulation_thread.is_alive():
            return
        self._price_simulation_thread = threading.Thread(target=self._price_simulation_loop, daemon=True)
        self._price_simulation_thread.start()
        self.logger.info('[POS] price simulation started (interval: 15-45s)')

    def start_pump_traffic_simulation(self):
        if self._pump_traffic_simulation_thread and self._pump_traffic_simulation_thread.is_alive():
            return
        self._pump_traffic_simulation_thread = threading.Thread(target=self._pump_traffic_simulation_loop, daemon=True)
        self._pump_traffic_simulation_thread.start()
        self.logger.info('[POS] pump traffic simulation started for pumps %s (interval: 10-60s)', self._traffic_pumps)

    def start_unlock_flow_simulation(self):
        if self._unlock_flow_simulation_thread and self._unlock_flow_simulation_thread.is_alive():
            return
        self._unlock_flow_simulation_thread = threading.Thread(target=self._unlock_flow_simulation_loop, daemon=True)
        self._unlock_flow_simulation_thread.start()
        self.logger.info('[POS] unlock flow simulation started')

    def on_pumpstatus_requested(self, pump_number: int):
        if pump_number not in self._traffic_pumps:
            return

        with self._state_lock:
            selection_deadline = time.monotonic() + 60.0
            self._selection_deadline_by_pump[pump_number] = selection_deadline

            fallback_deadline = self._fallback_deadline_by_pump.get(pump_number)
            if fallback_deadline is not None and fallback_deadline < selection_deadline:
                self._fallback_deadline_by_pump[pump_number] = selection_deadline

    def on_transaction_cleared(self, pump_number: int):
        if pump_number not in self._traffic_pumps:
            return

        with self._state_lock:
            self._selection_deadline_by_pump.pop(pump_number, None)
            self._fallback_deadline_by_pump.pop(pump_number, None)
            self._pending_unlock_by_pump.pop(pump_number, None)
            self._pending_unlock_notification_by_pump.pop(pump_number, None)
            self._creation_not_before_by_pump[pump_number] = time.monotonic() + random.uniform(15, 30)

    def on_unlock_pump_authorized(
        self,
        pump_number: int,
        fsc_transaction_id: str,
        credit: float,
        product_ids: list[str] | None,
    ):
        with self._state_lock:
            transaction = self._create_transaction_for_unlock(
                pump_number,
                fsc_transaction_id,
                credit,
                product_ids,
            )
            started_at = time.monotonic()
            fueling_seconds = max(1.0, float(transaction.volume) / 1.0)

            self.pump_states[pump_number] = 'in-use'
            self.open_transactions.pop(pump_number, None)
            self._selection_deadline_by_pump.pop(pump_number, None)
            self._fallback_deadline_by_pump.pop(pump_number, None)
            self._creation_not_before_by_pump.pop(pump_number, None)
            self._pending_unlock_notification_by_pump.pop(pump_number, None)
            self._pending_unlock_by_pump[pump_number] = {
                'transaction': transaction,
                'started_at': started_at,
                'complete_at': started_at + fueling_seconds,
                'next_progress_log_at': started_at + 5.0,
            }

    def on_pump_locked(self, pump_number: int):
        with self._state_lock:
            self._pending_unlock_by_pump.pop(pump_number, None)
            self._pending_unlock_notification_by_pump.pop(pump_number, None)

    def _price_simulation_loop(self):
        while not self._stop_event.is_set():
            wait_seconds = random.uniform(15, 45)
            if self._stop_event.wait(wait_seconds):
                break
            try:
                self._run_price_simulation_tick()
            except Exception:
                self.logger.exception('[POS] price simulation tick failed')

    def _run_price_simulation_tick(self, now: float | None = None):
        if now is None:
            now = time.monotonic()

        with self._state_lock:
            blocked_product_ids = {
                tx.product_id
                for tx in self.open_transactions.values()
                if self.pump_states.get(tx.pump_number) in {'in-use', 'ready-to-pay'}
            }

            candidates = [
                product
                for product in self.products
                if (product.product_type.startswith('ron') or product.product_type.startswith('diesel'))
                and product.product_id not in blocked_product_ids
                and now >= self._price_change_not_before_by_product_id.get(product.product_id, 0.0)
            ]

            if not candidates:
                return

            product = random.choice(candidates)
            initial_price = self._initial_prices[product.product_id]
            min_price = initial_price * 0.92
            max_price = initial_price * 1.08

            min_cents = math.ceil((min_price - 0.009) * 100)
            max_cents = math.floor((max_price - 0.009) * 100)
            if min_cents > max_cents:
                return

            current_cents = round((product.price_per_unit - 0.009) * 100)
            delta_cents = random.choice([-1, 1]) * random.randint(1, 10)
            new_cents = min(max(current_cents + delta_cents, min_cents), max_cents)
            new_price = round((new_cents / 100) + 0.009, 3)

            if new_price == product.price_per_unit:
                return

            old_price = product.price_per_unit
            product.price_per_unit = new_price
            self._price_change_not_before_by_product_id[product.product_id] = now + 120.0

        self.logger.info(
            '[POS] simulated price change for %s (%s): %.3f -> %.3f',
            product.description,
            product.product_id,
            old_price,
            new_price,
        )

    def _pump_traffic_simulation_loop(self):
        while not self._stop_event.is_set():
            wait_seconds = random.uniform(10, 60)
            if self._stop_event.wait(wait_seconds):
                break
            try:
                self._run_pump_traffic_simulation_tick()
            except Exception:
                self.logger.exception('[POS] pump traffic simulation tick failed')

    def _unlock_flow_simulation_loop(self):
        while not self._stop_event.is_set():
            if self._stop_event.wait(1.0):
                break
            try:
                self._run_unlock_flow_tick()
            except Exception:
                self.logger.exception('[POS] unlock flow simulation tick failed')

    def _run_unlock_flow_tick(self, now: float | None = None):
        if now is None:
            now = time.monotonic()

        completed_pumps: list[int] = []
        due_notifications: list[Transaction] = []
        with self._state_lock:
            for pump_number, unlock_data in list(self._pending_unlock_by_pump.items()):
                complete_at = unlock_data.get('complete_at')
                if not isinstance(complete_at, (int, float)) or now < complete_at:
                    started_at = unlock_data.get('started_at')
                    next_progress_log_at = unlock_data.get('next_progress_log_at')
                    transaction = unlock_data.get('transaction')

                    if (
                        isinstance(started_at, (int, float))
                        and isinstance(next_progress_log_at, (int, float))
                        and isinstance(transaction, Transaction)
                        and now >= next_progress_log_at
                    ):
                        while isinstance(unlock_data.get('next_progress_log_at'), (int, float)) and now >= float(unlock_data['next_progress_log_at']):
                            elapsed_seconds = max(0.0, float(unlock_data['next_progress_log_at']) - started_at)
                            dispensed_liters = min(float(transaction.volume), elapsed_seconds * 1.0)
                            self.logger.info(
                                '[POS] pre-auth fueling progress at pump %d: %.2f/%.2f L dispensed',
                                pump_number,
                                dispensed_liters,
                                float(transaction.volume),
                            )
                            unlock_data['next_progress_log_at'] = float(unlock_data['next_progress_log_at']) + 5.0
                    continue

                transaction = unlock_data.get('transaction')
                if not isinstance(transaction, Transaction):
                    del self._pending_unlock_by_pump[pump_number]
                    continue

                self.open_transactions[pump_number] = transaction
                self.pump_states[pump_number] = 'locked'
                self._pending_unlock_notification_by_pump[pump_number] = {
                    'transaction': transaction,
                    'notify_at': now + 1.0,
                }
                completed_pumps.append(pump_number)
                del self._pending_unlock_by_pump[pump_number]

            for pump_number, notification_data in list(self._pending_unlock_notification_by_pump.items()):
                notify_at = notification_data.get('notify_at')
                if not isinstance(notify_at, (int, float)) or now < notify_at:
                    continue

                transaction = notification_data.get('transaction')
                if isinstance(transaction, Transaction):
                    due_notifications.append(transaction)
                del self._pending_unlock_notification_by_pump[pump_number]

        for pump_number in completed_pumps:
            self.logger.info('[POS] simulated unlock flow completion at pump %d (locked)', pump_number)

        notify_callback = self._notify_completed_unlock_transaction
        if notify_callback is not None:
            for transaction in due_notifications:
                try:
                    notify_callback(transaction)
                except Exception:
                    self.logger.exception(
                        '[POS] failed to emit completed pre-auth transaction notification for pump %d',
                        transaction.pump_number,
                    )

    def _run_pump_traffic_simulation_tick(self, now: float | None = None):
        if now is None:
            now = time.monotonic()

        paid_in_store_pumps: list[tuple[int, str]] = []
        created_transaction_pump: int | None = None

        with self._state_lock:
            for pump_number, deadline in list(self._selection_deadline_by_pump.items()):
                if now < deadline:
                    continue
                if pump_number in self.open_transactions:
                    del self.open_transactions[pump_number]
                    self.pump_states[pump_number] = 'free'
                    paid_in_store_pumps.append((pump_number, 'client selection timeout'))
                    self._creation_not_before_by_pump[pump_number] = now + random.uniform(10, 25)
                del self._selection_deadline_by_pump[pump_number]
                self._fallback_deadline_by_pump.pop(pump_number, None)

            for pump_number, deadline in list(self._fallback_deadline_by_pump.items()):
                if now < deadline:
                    continue
                if pump_number in self.open_transactions:
                    del self.open_transactions[pump_number]
                    self.pump_states[pump_number] = 'free'
                    paid_in_store_pumps.append((pump_number, 'fallback timeout'))
                    self._creation_not_before_by_pump[pump_number] = now + random.uniform(10, 25)
                del self._fallback_deadline_by_pump[pump_number]
                self._selection_deadline_by_pump.pop(pump_number, None)

            candidate_pumps = [
                pump_number
                for pump_number in self._traffic_pumps
                if self.pump_states.get(pump_number) == 'free'
                and pump_number not in self.open_transactions
                and pump_number not in {pump for pump, _ in paid_in_store_pumps}
                and now >= self._creation_not_before_by_pump.get(pump_number, 0.0)
            ]

            if candidate_pumps:
                pump_number = random.choice(candidate_pumps)
                self.open_transactions[pump_number] = self._create_transaction_for_pump(pump_number)
                self.pump_states[pump_number] = 'ready-to-pay'
                self._fallback_deadline_by_pump[pump_number] = now + random.uniform(120, 300)
                created_transaction_pump = pump_number

        for pump_number, reason in paid_in_store_pumps:
            self.logger.info(
                '[POS] simulated in-store payment at pump %d after %s',
                pump_number,
                reason,
            )

        if created_transaction_pump is not None:
            self.logger.info(
                '[POS] simulated new ready-to-pay transaction at pump %d',
                created_transaction_pump,
            )
