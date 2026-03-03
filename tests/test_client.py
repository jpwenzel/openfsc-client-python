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
