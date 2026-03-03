import random
import threading

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
    ):
        self.logger = logger
        self._state_lock = state_lock
        self._stop_event = stop_event
        self.pump_states = pump_states
        self.open_transactions = open_transactions
        self.products = products
        self._initial_prices = {product.product_id: product.price_per_unit for product in self.products}
        self._price_simulation_thread: threading.Thread | None = None

    def start_price_simulation(self):
        if self._price_simulation_thread and self._price_simulation_thread.is_alive():
            return
        self._price_simulation_thread = threading.Thread(target=self._price_simulation_loop, daemon=True)
        self._price_simulation_thread.start()

    def _price_simulation_loop(self):
        while not self._stop_event.is_set():
            wait_seconds = random.uniform(15, 45)
            if self._stop_event.wait(wait_seconds):
                break

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
                ]

                if not candidates:
                    continue

                product = random.choice(candidates)
                initial_price = self._initial_prices[product.product_id]
                min_price = initial_price * 0.95
                max_price = initial_price * 1.05

                delta = random.choice([-1, 1]) * random.uniform(0.01, 0.03)
                new_price = product.price_per_unit + delta
                new_price = min(max(new_price, min_price), max_price)
                new_price = round(new_price, 3)

                if new_price == product.price_per_unit:
                    continue

                old_price = product.price_per_unit
                product.price_per_unit = new_price

            self.logger.info(
                '[POS] simulated price change for %s (%s): %.3f -> %.3f',
                product.description,
                product.product_id,
                old_price,
                new_price,
            )
