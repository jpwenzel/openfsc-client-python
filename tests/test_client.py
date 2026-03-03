import asyncio
import importlib.util
import os
import sys
import types
import unittest


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


load_module('config', 'config.py')
load_module('state', 'state.py')
protocol_module = load_module('protocol', 'protocol.py')
load_module('pos_adapter', 'pos_adapter.py')
load_module('example_pos_simulator', 'example_pos_simulator.py')
example_pos_adapter_module = load_module('example_pos_adapter', 'example_pos_adapter.py')
sys.modules.setdefault('websockets', types.SimpleNamespace(connect=None))
client_module = load_module('client', 'client.py')

OpenFscClient = client_module.OpenFscClient
OpenFscConfig = sys.modules['config'].OpenFscConfig
ExamplePosAdapter = example_pos_adapter_module.ExamplePosAdapter
ProtocolMessage = protocol_module.ProtocolMessage
parse_message = protocol_module.parse_message
ConnectionState = sys.modules['state'].ConnectionState


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, wire: str):
        self.sent.append(wire)

    async def close(self):
        self.closed = True


class ClientHandlerTests(unittest.TestCase):
    def create_client(self, *, access_key: str = '', secret: str = ''):
        config = OpenFscConfig(
            fsc_url='wss://example.invalid/ws/text',
            site_access_key=access_key,
            site_secret=secret,
        )
        client = OpenFscClient(config, ExamplePosAdapter())
        client.ws_connection = FakeWebSocket()
        return client

    def run_async(self, coro):
        return asyncio.run(coro)

    def parse_sent(self, client):
        return [parse_message(wire) for wire in client.ws_connection.sent]

    def test_heartbeat_works_while_unauthenticated(self):
        client = self.create_client()
        client.state = ConnectionState.HANDSHAKE

        self.run_async(
            client.handle_server_request(
                ProtocolMessage(tag='S42', method='HEARTBEAT', args=['2026-02-26T10:00:00Z'])
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0].tag, 'S42')
        self.assertEqual(sent[0].method, 'BEAT')
        self.assertEqual(sent[1].tag, 'S42')
        self.assertEqual(sent[1].method, 'OK')

    def test_prices_rejected_when_not_authenticated(self):
        client = self.create_client()
        client.state = ConnectionState.HANDSHAKE

        self.run_async(
            client.handle_server_request(
                ProtocolMessage(tag='S1', method='PRICES', args=[])
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '403')

    def test_prices_returns_notifications_and_ok_when_authenticated(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(
            client.handle_server_request(
                ProtocolMessage(tag='S2', method='PRICES', args=[])
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 9)
        self.assertEqual([m.method for m in sent[:-1]], ['PRICE'] * 8)
        self.assertEqual(sent[0].args[0], '0100')
        self.assertEqual(sent[-1].tag, 'S2')
        self.assertEqual(sent[-1].method, 'OK')

    def test_products_returns_notifications_and_ok_when_authenticated(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(
            client.handle_server_request(
                ProtocolMessage(tag='S9', method='PRODUCTS', args=[])
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 9)
        self.assertEqual([m.method for m in sent[:-1]], ['PRODUCT'] * 8)
        self.assertEqual(sent[0].args[0], '0100')
        self.assertEqual(sent[0].args[1], 'ron95e5')
        self.assertEqual(sent[-1].tag, 'S9')
        self.assertEqual(sent[-1].method, 'OK')

    def test_integration_handle_incoming_products_request(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(client.handle_incoming('S10 PRODUCTS\r\n'))

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 9)
        self.assertEqual([m.method for m in sent[:-1]], ['PRODUCT'] * 8)
        self.assertEqual(sent[0].args[:2], ['0100', 'ron95e5'])
        self.assertEqual(sent[-2].args[:2], ['0800', 'lpg'])
        self.assertEqual(sent[-1].tag, 'S10')
        self.assertEqual(sent[-1].method, 'OK')

    def test_integration_handle_incoming_prices_request(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(client.handle_incoming('S11 PRICES\r\n'))

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 9)
        self.assertEqual([m.method for m in sent[:-1]], ['PRICE'] * 8)
        self.assertEqual(sent[0].args[0], '0100')
        self.assertEqual(sent[-2].args[0], '0800')
        self.assertEqual(sent[-1].tag, 'S11')
        self.assertEqual(sent[-1].method, 'OK')

    def test_pumpstatus_unknown_pump_returns_404(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(
            client.handle_server_request(
                ProtocolMessage(tag='S3', method='PUMPSTATUS', args=['999'])
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '404')

    def test_integration_unlockpump_unknown_pump_returns_404(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(
            client.handle_incoming(
                'S24 UNLOCKPUMP 999 EUR 10.0 12345678-1234-1234-1234-123456789012 pace\r\n'
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S24')
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '404')

    def test_integration_lockpump_unknown_pump_returns_404(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(client.handle_incoming('S25 LOCKPUMP 999\r\n'))

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S25')
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '404')

    def test_integration_clear_unknown_pump_returns_404(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED

        self.run_async(
            client.handle_incoming(
                'S26 CLEAR 999 TX-2026-03-03-000001 12345678-1234-1234-1234-123456789012 pace\r\n'
            )
        )

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S26')
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '404')

    def test_integration_unlockpump_preauth_flow_for_pump_1(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED
        fsc_transaction_id = '8dad9fe7-3cc5-4baa-95b3-cb6611361737'

        self.run_async(
            client.handle_incoming(
                f'S20 UNLOCKPUMP 1 EUR 15.0 {fsc_transaction_id} pace\r\n'
            )
        )
        sent = self.parse_sent(client)
        self.assertEqual(sent[-1].tag, 'S20')
        self.assertEqual(sent[-1].method, 'OK')

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S21 PUMPSTATUS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(sent[0].method, 'PUMP')
        self.assertEqual(sent[0].args, ['1', 'free'])
        self.assertEqual(sent[1].tag, 'S21')
        self.assertEqual(sent[1].method, 'OK')

        adapter = client.pos_adapter
        with adapter._state_lock:
            adapter._simulator._pending_unlock_by_pump[1]['complete_at'] = 0.0
        adapter._simulator._run_unlock_flow_tick(now=1.0)

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S22 PUMPSTATUS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(sent[0].method, 'PUMP')
        self.assertEqual(sent[0].args, ['1', 'locked'])
        self.assertEqual(sent[1].tag, 'S22')
        self.assertEqual(sent[1].method, 'OK')

        adapter._simulator._run_unlock_flow_tick(now=2.0)

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S23 TRANSACTIONS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(sent[0].method, 'TRANSACTION')
        self.assertEqual(sent[0].args[0], '1')
        self.assertEqual(sent[0].args[1], fsc_transaction_id)
        self.assertEqual(sent[0].args[2], 'open')
        self.assertEqual(sent[1].tag, 'S23')
        self.assertEqual(sent[1].method, 'OK')

        adapter._simulator._run_unlock_flow_tick(now=4.1)

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S24 TRANSACTIONS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S24')
        self.assertEqual(sent[0].method, 'OK')

    def test_integration_unlockpump_in_use_transition_sends_pump_notification(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED
        fsc_transaction_id = '06db6b40-87ea-44a0-a4bb-7c7939635eaf'

        self.run_async(
            client.handle_incoming(
                f'S50 UNLOCKPUMP 1 EUR 15.0 {fsc_transaction_id} pace\r\n'
            )
        )

        adapter = client.pos_adapter
        with adapter._state_lock:
            adapter._simulator._pending_unlock_by_pump[1]['in_use_at'] = 0.0

        client.ws_connection.sent = []

        async def run_unlock_tick_and_flush_notifications():
            client._event_loop = asyncio.get_running_loop()
            adapter._simulator._run_unlock_flow_tick(now=1.0)
            await asyncio.sleep(0)

        self.run_async(run_unlock_tick_and_flush_notifications())

        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, '*')
        self.assertEqual(sent[0].method, 'PUMP')
        self.assertEqual(sent[0].args, ['1', 'in-use'])

    def test_integration_clear_preauth_uses_local_site_id_and_matching_fsc_id(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED
        fsc_transaction_id = '70644955-ef32-4d33-a88b-67b500a7c00d'

        self.run_async(
            client.handle_incoming(
                f'S30 UNLOCKPUMP 1 EUR 20.0 {fsc_transaction_id} pace\r\n'
            )
        )

        adapter = client.pos_adapter
        with adapter._state_lock:
            adapter._simulator._pending_unlock_by_pump[1]['complete_at'] = 0.0
        adapter._simulator._run_unlock_flow_tick(now=1.0)

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S31 TRANSACTIONS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(sent[0].method, 'TRANSACTION')
        site_transaction_id = sent[0].args[1]
        self.assertEqual(site_transaction_id, fsc_transaction_id)
        self.assertEqual(sent[0].args[2], 'open')

        client.ws_connection.sent = []
        self.run_async(
            client.handle_incoming(
                f'S32 CLEAR 1 {site_transaction_id} {fsc_transaction_id} pace\r\n'
            )
        )
        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S32')
        self.assertEqual(sent[0].method, 'OK')

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S33 PUMPSTATUS 1\r\n'))
        sent = self.parse_sent(client)
        self.assertEqual(sent[0].method, 'PUMP')
        self.assertEqual(sent[0].args, ['1', 'locked'])
        self.assertEqual(sent[1].tag, 'S33')
        self.assertEqual(sent[1].method, 'OK')

    def test_integration_clear_preauth_rejects_mismatching_fsc_id(self):
        client = self.create_client(access_key='key', secret='secret')
        client.state = ConnectionState.AUTHENTICATED
        fsc_transaction_id = '70644955-ef32-4d33-a88b-67b500a7c00d'

        self.run_async(
            client.handle_incoming(
                f'S40 UNLOCKPUMP 1 EUR 20.0 {fsc_transaction_id} pace\r\n'
            )
        )

        adapter = client.pos_adapter
        with adapter._state_lock:
            adapter._simulator._pending_unlock_by_pump[1]['complete_at'] = 0.0
        adapter._simulator._run_unlock_flow_tick(now=1.0)

        client.ws_connection.sent = []
        self.run_async(client.handle_incoming('S41 TRANSACTIONS 1\r\n'))
        sent = self.parse_sent(client)
        site_transaction_id = sent[0].args[1]

        client.ws_connection.sent = []
        self.run_async(
            client.handle_incoming(
                f'S42 CLEAR 1 {site_transaction_id} 00000000-0000-0000-0000-000000000000 pace\r\n'
            )
        )
        sent = self.parse_sent(client)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].tag, 'S42')
        self.assertEqual(sent[0].method, 'ERR')
        self.assertEqual(sent[0].args[0], '404')

    def test_capability_without_credentials_skips_auth(self):
        client = self.create_client()

        self.run_async(
            client.handle_server_notification(
                ProtocolMessage(tag='*', method='CAPABILITY', args=['HEARTBEAT', 'PRICES'])
            )
        )

        self.assertTrue(client.auth_skipped)
        self.assertEqual(client.pending_requests, {})
        self.assertEqual(client.ws_connection.sent, [])


if __name__ == '__main__':
    unittest.main()
