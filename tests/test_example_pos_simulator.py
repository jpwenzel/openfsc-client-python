import importlib.util
import os
import sys
import threading
import time
import unittest
from unittest import mock


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLIENT_DIR = os.path.join(PROJECT_ROOT, 'openfsc-client')


def load_module(name: str, filename: str):
    path = os.path.join(CLIENT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module {name} from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


pos_adapter_module = load_module('pos_adapter', 'pos_adapter.py')
simulator_module = load_module('example_pos_simulator', 'example_pos_simulator.py')

Product = pos_adapter_module.Product
Transaction = pos_adapter_module.Transaction
ExamplePosSimulator = simulator_module.ExamplePosSimulator


class DummyLogger:
    def info(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


class ExamplePosSimulatorTests(unittest.TestCase):
    def create_simulator(self, notify_completed_unlock_transaction=None):
        products = [
            Product('0100', 'ron95e5', 19.0, 'LTR', 'EUR', 1.709, 'Super E5'),
            Product('0500', 'dieselB7', 19.0, 'LTR', 'EUR', 1.609, 'Diesel B7'),
            Product('0800', 'lpg', 19.0, 'LTR', 'EUR', 1.009, 'LPG'),
        ]

        pump_states = {
            11: 'free',
            12: 'free',
            13: 'free',
            21: 'ready-to-pay',
        }
        open_transactions: dict[int, Transaction] = {}

        def create_transaction_for_pump(pump_number: int) -> Transaction:
            return Transaction(
                pump_number=pump_number,
                site_transaction_id=f'TX-2026-03-03-{pump_number:06d}',
                status='open',
                product_id='0500',
                currency='EUR',
                price_with_vat=19.04,
                price_without_vat=16.00,
                vat_rate=19.0,
                vat_amount=3.04,
                unit='LTR',
                volume=10.00,
                price_per_unit=1.904,
            )

        def create_transaction_for_unlock(
            pump_number: int,
            fsc_transaction_id: str,
            credit: float,
            product_ids: list[str] | None,
        ) -> Transaction:
            return Transaction(
                pump_number=pump_number,
                site_transaction_id=fsc_transaction_id,
                status='open',
                product_id='0100',
                currency='EUR',
                price_with_vat=min(credit, 10.00),
                price_without_vat=8.40,
                vat_rate=19.0,
                vat_amount=1.60,
                unit='LTR',
                volume=5.00,
                price_per_unit=2.000,
            )

        simulator = ExamplePosSimulator(
            logger=DummyLogger(),
            state_lock=threading.Lock(),
            stop_event=threading.Event(),
            pump_states=pump_states,
            open_transactions=open_transactions,
            products=products,
            create_transaction_for_pump=create_transaction_for_pump,
            create_transaction_for_unlock=create_transaction_for_unlock,
            notify_completed_unlock_transaction=notify_completed_unlock_transaction,
        )
        return simulator, pump_states, open_transactions, products

    def test_price_tick_changes_only_supported_unblocked_product(self):
        simulator, pump_states, open_transactions, products = self.create_simulator()

        open_transactions[21] = Transaction(
            pump_number=21,
            site_transaction_id='TX-2026-03-03-111111',
            status='open',
            product_id='0100',
            currency='EUR',
            price_with_vat=10.00,
            price_without_vat=8.40,
            vat_rate=19.0,
            vat_amount=1.60,
            unit='LTR',
            volume=5.00,
            price_per_unit=2.000,
        )

        old_ron_price = products[0].price_per_unit
        old_diesel_price = products[1].price_per_unit
        old_lpg_price = products[2].price_per_unit

        with mock.patch.object(simulator_module.random, 'choice', side_effect=[products[1], 1]):
            with mock.patch.object(simulator_module.random, 'randint', return_value=7):
                simulator._run_price_simulation_tick()

        self.assertEqual(products[0].price_per_unit, old_ron_price)
        self.assertEqual(products[2].price_per_unit, old_lpg_price)
        self.assertEqual(products[1].price_per_unit, round(old_diesel_price + 0.07, 3))
        self.assertEqual(str(products[1].price_per_unit).split('.')[-1][-1], '9')

    def test_price_tick_keeps_value_within_plus_minus_eight_percent(self):
        simulator, _, _, products = self.create_simulator()

        products[0].price_per_unit = 1.849
        with mock.patch.object(simulator_module.random, 'choice', side_effect=[products[0], 1]):
            with mock.patch.object(simulator_module.random, 'randint', return_value=3):
                simulator._run_price_simulation_tick()

        self.assertEqual(products[0].price_per_unit, 1.839)

    def test_price_tick_does_not_reprice_same_product_within_two_minutes(self):
        simulator, _, _, products = self.create_simulator()

        simulator._price_change_not_before_by_product_id['0100'] = 5000.0
        old_diesel_price = products[1].price_per_unit

        with mock.patch.object(simulator_module.random, 'choice', side_effect=[products[1], 1]):
            with mock.patch.object(simulator_module.random, 'randint', return_value=7):
                simulator._run_price_simulation_tick(now=1000.0)

        changed_diesel_price = products[1].price_per_unit
        self.assertEqual(changed_diesel_price, round(old_diesel_price + 0.07, 3))

        with mock.patch.object(simulator_module.random, 'choice', side_effect=[1]):
            with mock.patch.object(simulator_module.random, 'randint', return_value=4):
                simulator._run_price_simulation_tick(now=1119.0)

        self.assertEqual(products[1].price_per_unit, changed_diesel_price)

    def test_pump_traffic_tick_marks_selected_pump_paid_in_store_after_timeout(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        pump_states[12] = 'locked'
        pump_states[13] = 'locked'
        pump_states[11] = 'ready-to-pay'
        open_transactions[11] = Transaction(
            pump_number=11,
            site_transaction_id='TX-2026-03-03-222222',
            status='open',
            product_id='0500',
            currency='EUR',
            price_with_vat=10.00,
            price_without_vat=8.40,
            vat_rate=19.0,
            vat_amount=1.60,
            unit='LTR',
            volume=5.00,
            price_per_unit=2.000,
        )

        simulator.on_pumpstatus_requested(11)
        simulator._run_pump_traffic_simulation_tick(now=time.monotonic() + 61.0)

        self.assertNotIn(11, open_transactions)
        self.assertEqual(pump_states[11], 'free')

    def test_pump_traffic_tick_marks_unselected_pump_paid_in_store_after_fallback_timeout(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        pump_states[11] = 'ready-to-pay'
        open_transactions[11] = Transaction(
            pump_number=11,
            site_transaction_id='TX-2026-03-03-333333',
            status='open',
            product_id='0500',
            currency='EUR',
            price_with_vat=10.00,
            price_without_vat=8.40,
            vat_rate=19.0,
            vat_amount=1.60,
            unit='LTR',
            volume=5.00,
            price_per_unit=2.000,
        )

        now = time.monotonic()
        simulator._fallback_deadline_by_pump[11] = now + 1.0
        simulator._run_pump_traffic_simulation_tick(now=now + 2.0)

        self.assertNotIn(11, open_transactions)
        self.assertEqual(pump_states[11], 'free')

    def test_pumpstatus_request_extends_fallback_to_at_least_60_seconds(self):
        simulator, _, open_transactions, _ = self.create_simulator()

        open_transactions[11] = Transaction(
            pump_number=11,
            site_transaction_id='TX-2026-03-03-444444',
            status='open',
            product_id='0500',
            currency='EUR',
            price_with_vat=10.00,
            price_without_vat=8.40,
            vat_rate=19.0,
            vat_amount=1.60,
            unit='LTR',
            volume=5.00,
            price_per_unit=2.000,
        )

        with mock.patch.object(simulator_module.time, 'monotonic', return_value=1000.0):
            simulator._fallback_deadline_by_pump[11] = 1010.0
            simulator.on_pumpstatus_requested(11)

        self.assertGreaterEqual(simulator._fallback_deadline_by_pump[11], 1060.0)

    def test_pump_traffic_tick_creates_transaction_on_free_traffic_pump(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        self.assertNotIn(12, open_transactions)
        self.assertEqual(pump_states[12], 'free')

        with mock.patch.object(simulator_module.random, 'choice', return_value=12):
            simulator._run_pump_traffic_simulation_tick(now=time.monotonic())

        self.assertIn(12, open_transactions)
        self.assertEqual(open_transactions[12].pump_number, 12)
        self.assertEqual(pump_states[12], 'ready-to-pay')

    def test_pump_traffic_tick_respects_recreation_cooldown(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        now = time.monotonic()
        simulator._creation_not_before_by_pump[11] = now + 20.0
        simulator._creation_not_before_by_pump[12] = now + 20.0
        simulator._creation_not_before_by_pump[13] = now + 20.0

        simulator._run_pump_traffic_simulation_tick(now=now + 5.0)

        self.assertNotIn(12, open_transactions)
        self.assertEqual(pump_states[12], 'free')

    def test_on_transaction_cleared_sets_recreation_cooldown(self):
        simulator, _, _, _ = self.create_simulator()

        with mock.patch.object(simulator_module.time, 'monotonic', return_value=1000.0):
            with mock.patch.object(simulator_module.random, 'uniform', return_value=17.0):
                simulator.on_transaction_cleared(11)

        self.assertEqual(simulator._creation_not_before_by_pump[11], 1017.0)

    def test_unlock_authorized_keeps_pump_free_until_delay(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        pump_states[1] = 'locked'
        with mock.patch.object(simulator_module.time, 'monotonic', return_value=1000.0):
            with mock.patch.object(simulator_module.random, 'randint', return_value=3):
                simulator.on_unlock_pump_authorized(1, 'fsc-123', 15.0, None)

        self.assertEqual(pump_states[1], 'free')
        self.assertIn(1, simulator._pending_unlock_by_pump)
        self.assertNotIn(1, open_transactions)
        self.assertAlmostEqual(simulator._pending_unlock_by_pump[1]['in_use_at'], 1003.0, places=3)
        self.assertAlmostEqual(simulator._pending_unlock_by_pump[1]['started_at'], 1003.0, places=3)
        complete_at = simulator._pending_unlock_by_pump[1]['complete_at']
        self.assertAlmostEqual(complete_at, 1008.0, places=3)

    def test_unlock_flow_transitions_from_free_to_in_use_after_delay(self):
        simulator, pump_states, _, _ = self.create_simulator()

        pump_states[1] = 'locked'
        with mock.patch.object(simulator_module.time, 'monotonic', return_value=1000.0):
            with mock.patch.object(simulator_module.random, 'randint', return_value=2):
                simulator.on_unlock_pump_authorized(1, 'fsc-delay', 15.0, None)

        simulator._run_unlock_flow_tick(now=1001.0)
        self.assertEqual(pump_states[1], 'free')

        simulator._run_unlock_flow_tick(now=1002.0)
        self.assertEqual(pump_states[1], 'in-use')

    def test_unlock_flow_logs_progress_every_5_seconds(self):
        simulator, pump_states, _, _ = self.create_simulator()
        simulator.logger = mock.Mock()

        transaction = Transaction(
            pump_number=1,
            site_transaction_id='fsc-progress',
            status='open',
            product_id='0100',
            currency='EUR',
            price_with_vat=20.00,
            price_without_vat=16.81,
            vat_rate=19.0,
            vat_amount=3.19,
            unit='LTR',
            volume=12.00,
            price_per_unit=1.667,
        )

        with simulator._state_lock:
            pump_states[1] = 'in-use'
            simulator._pending_unlock_by_pump[1] = {
                'transaction': transaction,
                'started_at': 1000.0,
                'complete_at': 1012.0,
                'next_progress_log_at': 1005.0,
            }

        simulator._run_unlock_flow_tick(now=1011.0)

        progress_calls = [
            call
            for call in simulator.logger.info.call_args_list
            if call.args and call.args[0] == '[POS] pre-auth fueling progress at pump %d: %.2f/%.2f L dispensed'
        ]
        self.assertEqual(len(progress_calls), 2)
        self.assertEqual(progress_calls[0].args[1], 1)
        self.assertAlmostEqual(progress_calls[0].args[2], 5.0, places=2)
        self.assertAlmostEqual(progress_calls[1].args[2], 10.0, places=2)

    def test_unlock_flow_emits_notification_one_second_after_completion(self):
        notifications: list[Transaction] = []
        simulator, pump_states, open_transactions, _ = self.create_simulator(
            notify_completed_unlock_transaction=notifications.append
        )

        pump_states[1] = 'locked'
        with mock.patch.object(simulator_module.time, 'monotonic', return_value=1000.0):
            with mock.patch.object(simulator_module.random, 'randint', return_value=1):
                simulator.on_unlock_pump_authorized(1, 'fsc-789', 15.0, ['0100'])

        simulator._run_unlock_flow_tick(now=1005.9)
        self.assertEqual(pump_states[1], 'in-use')
        self.assertNotIn(1, open_transactions)
        self.assertEqual(len(notifications), 0)

        simulator._run_unlock_flow_tick(now=1006.0)
        self.assertEqual(pump_states[1], 'locked')
        self.assertIn(1, open_transactions)
        self.assertEqual(len(notifications), 0)

        simulator._run_unlock_flow_tick(now=1007.0)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].site_transaction_id, 'fsc-789')
        self.assertIn(1, open_transactions)
        self.assertEqual(pump_states[1], 'locked')

        simulator._run_unlock_flow_tick(now=1009.1)
        self.assertNotIn(1, open_transactions)
        self.assertEqual(pump_states[1], 'locked')

    def test_unlock_flow_tick_completes_to_locked_transaction(self):
        simulator, pump_states, open_transactions, _ = self.create_simulator()

        pump_states[1] = 'locked'
        simulator.on_unlock_pump_authorized(1, 'fsc-456', 15.0, ['0100'])
        simulator._run_unlock_flow_tick(now=time.monotonic() + 30.0)

        self.assertEqual(pump_states[1], 'locked')
        self.assertIn(1, open_transactions)
        self.assertEqual(open_transactions[1].site_transaction_id, 'fsc-456')
        self.assertNotIn(1, simulator._pending_unlock_by_pump)


if __name__ == '__main__':
    unittest.main()
