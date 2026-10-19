import asyncio
import importlib.util
import os
import random
import sys
import types
import unittest
from unittest import mock


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLIENT_DIR = os.path.join(PROJECT_ROOT, 'openfsc-client')


def load_module(name: str, filename: str):
    # Reuse modules another test file already loaded: reloading them would
    # create a second PosAdapter class and break isinstance checks there.
    if name in sys.modules and getattr(sys.modules[name], '__file__', None):
        return sys.modules[name]
    path = os.path.join(CLIENT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module {name} from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


config_module = load_module('config', 'config.py')
load_module('state', 'state.py')
protocol_module = load_module('protocol', 'protocol.py')
load_module('pos_adapter', 'pos_adapter.py')
load_module('example_pos_simulator', 'example_pos_simulator.py')
example_pos_adapter_module = load_module('example_pos_adapter', 'example_pos_adapter.py')
sys.modules.setdefault('websockets', types.SimpleNamespace(connect=None))
client_module = load_module('client', 'client.py')

OpenFscConfig = config_module.OpenFscConfig
OpenFscClient = client_module.OpenFscClient
ReconnectBackoff = client_module.ReconnectBackoff
ReconnectLimitReached = client_module.ReconnectLimitReached
ExamplePosAdapter = example_pos_adapter_module.ExamplePosAdapter


class StopLoop(Exception):
    pass


def make_client(**reconnect):
    config = OpenFscConfig(
        fsc_url='wss://example.invalid/ws/text',
        site_access_key='key',
        site_secret='secret',
        **reconnect,
    )
    client = OpenFscClient(config, ExamplePosAdapter())
    client.backoff._rng = random.Random(1)
    return client


def scripted(client, outcomes, max_sleeps=None):
    """Replace run_session/sleep: each outcome is 'auth', 'authfail' or an exception."""
    outcomes = list(outcomes)
    delays = []

    async def run_session():
        client._session_authenticated = False
        client._auth_failed = False
        outcome = outcomes.pop(0)
        if outcome == 'auth':
            client._session_authenticated = True
        elif outcome == 'authfail':
            client._auth_failed = True
        else:
            raise outcome

    async def sleep(delay):
        delays.append(delay)
        if not outcomes or (max_sleeps is not None and len(delays) >= max_sleeps):
            raise StopLoop()

    client.run_session = run_session
    client._sleep = sleep
    return delays


class BackoffTests(unittest.TestCase):
    def test_delay_doubles_and_is_capped(self):
        backoff = ReconnectBackoff(1.0, 8.0, rng=random.Random(0))
        nominal = [1, 2, 4, 8, 8, 8]
        for expected in nominal:
            delay = backoff.next_delay()
            self.assertGreaterEqual(delay, expected / 2)
            self.assertLessEqual(delay, expected)

    def test_reset_starts_over(self):
        backoff = ReconnectBackoff(1.0, 60.0)
        for _ in range(5):
            backoff.next_delay()
        backoff.reset()
        self.assertLessEqual(backoff.next_delay(), 1.0)


class ReconnectLoopTests(unittest.TestCase):
    def test_reconnects_quickly_after_healthy_session(self):
        # e.g. the server sent QUIT after a validator test run
        client = make_client()
        delays = scripted(client, ['auth', 'auth'])
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertEqual(len(delays), 2)
        self.assertTrue(all(d <= 1.0 for d in delays), delays)

    def test_backs_off_on_repeated_connection_errors(self):
        client = make_client(reconnect_initial_delay=1.0, reconnect_max_delay=8.0)
        delays = scripted(client, [ConnectionRefusedError('refused')] * 6)
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertGreater(delays[3], 2.0)  # nominal 8 s, at least 4 s
        self.assertTrue(all(d <= 8.0 for d in delays))

    def test_backoff_resets_after_successful_authentication(self):
        client = make_client(reconnect_initial_delay=1.0, reconnect_max_delay=60.0)
        delays = scripted(client, [OSError('down')] * 5 + ['auth'])
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertGreater(delays[4], 8.0)
        self.assertLessEqual(delays[5], 1.0)

    def test_auth_failure_waits_max_delay(self):
        client = make_client(reconnect_max_delay=30.0)
        delays = scripted(client, ['authfail', 'authfail'])
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertEqual(delays, [30.0, 30.0])

    def test_unlimited_retries_by_default(self):
        client = make_client()
        delays = scripted(client, [OSError('down')] * 50)
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertEqual(len(delays), 50)

    def test_gives_up_after_max_retries(self):
        client = make_client(reconnect_max_retries=3)
        delays = scripted(client, [OSError('down')] * 10)
        with self.assertRaisesRegex(ReconnectLimitReached, '4 consecutive'):
            asyncio.run(client.main())
        self.assertEqual(len(delays), 3)

    def test_successful_session_resets_retry_counter(self):
        client = make_client(reconnect_max_retries=2)
        outcomes = [OSError('down')] * 2 + ['auth'] + [OSError('down')] * 2 + ['auth']
        delays = scripted(client, outcomes)
        with self.assertRaises(StopLoop):
            asyncio.run(client.main())
        self.assertEqual(len(delays), 6)

    def test_cancel_during_backoff_stops_cleanly(self):
        client = make_client()

        async def run_session():
            raise OSError('down')

        client.run_session = run_session

        async def scenario():
            task = asyncio.create_task(client.main())
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())


class ConfigTests(unittest.TestCase):
    def test_env_parsing(self):
        env = {
            'OPENFSC_RECONNECT_INITIAL_DELAY': '0.5',
            'OPENFSC_RECONNECT_MAX_DELAY': '120',
            'OPENFSC_RECONNECT_MAX_RETRIES': '10',
        }
        with mock.patch.dict(os.environ, env):
            config = OpenFscConfig.from_env()
        self.assertEqual(config.reconnect_initial_delay, 0.5)
        self.assertEqual(config.reconnect_max_delay, 120.0)
        self.assertEqual(config.reconnect_max_retries, 10)

    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = OpenFscConfig.from_env()
        self.assertEqual(
            (config.reconnect_initial_delay, config.reconnect_max_delay, config.reconnect_max_retries),
            (1.0, 60.0, 0),
        )

    def test_invalid_values_rejected(self):
        for env in ({'OPENFSC_RECONNECT_MAX_RETRIES': '-1'},
                    {'OPENFSC_RECONNECT_INITIAL_DELAY': 'abc'},
                    {'OPENFSC_RECONNECT_INITIAL_DELAY': '10', 'OPENFSC_RECONNECT_MAX_DELAY': '5'}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                OpenFscConfig.from_env()


if __name__ == '__main__':
    unittest.main()
