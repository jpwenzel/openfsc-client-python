import logging
from importlib import import_module
from typing import Any

from config import OpenFscConfig
from protocol import ProtocolMessage, now_rfc3339_utc, parse_message, serialize_message
from state import ConnectionState

websockets = import_module('websockets')


class OpenFscClient:
    def __init__(self, config: OpenFscConfig):
        self.logger = logging.getLogger('openfsc-client')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(logging.StreamHandler())

        self.fsc_url = config.fsc_url
        self.site_access_key = config.site_access_key
        self.site_secret = config.site_secret

        self.client_supported_fsc_capabilities = sorted({
            'CLEAR',
            'HEARTBEAT',
            'LOCKPUMP',
            'PRICES',
            'PUMPS',
            'PUMPSTATUS',
            'QUIT',
            'TRANSACTIONS',
            'UNLOCKPUMP',
        })

        self.tagged_message_counter = 0
        self.pending_requests: dict[str, str] = {}
        self.server_capabilities: set[str] = set()
        self.state = ConnectionState.DISCONNECTED
        self.ws_connection: Any | None = None
        self.auth_skipped = False

    def next_client_tag(self) -> str:
        tag = f'C{self.tagged_message_counter}'
        self.tagged_message_counter += 1
        return tag

    async def send(self, message: ProtocolMessage):
        wire = serialize_message(message)
        if message.tag == '*':
            self.logger.info('> [C-NOTIF     ] %s', wire.rstrip())
        elif message.tag.startswith('C'):
            self.logger.info('> [C-REQ #%5s] %s', message.tag[1:], wire.rstrip())
        elif message.tag.startswith('S'):
            self.logger.info('> [C-RES #%5s] %s', message.tag[1:], wire.rstrip())
        connection = self.require_connection()
        await connection.send(wire)

    def require_connection(self):
        if self.ws_connection is None:
            raise RuntimeError('WebSocket connection is not established')
        return self.ws_connection

    async def send_notification(self, method: str, *args: str):
        await self.send(ProtocolMessage('*', method, list(args)))

    async def send_request(self, purpose: str, method: str, *args: str) -> str:
        tag = self.next_client_tag()
        self.pending_requests[tag] = purpose
        await self.send(ProtocolMessage(tag, method, list(args)))
        return tag

    async def send_ok(self, server_tag: str):
        await self.send(ProtocolMessage(server_tag, 'OK', []))

    async def send_err(self, server_tag: str, code: int, message: str):
        await self.send(ProtocolMessage(server_tag, 'ERR', [str(code), message]))

    async def start_handshake(self):
        self.state = ConnectionState.HANDSHAKE
        await self.send_notification('CAPABILITY', *self.client_supported_fsc_capabilities)

    async def maybe_send_charset_request(self):
        if 'CHARSET' in self.server_capabilities:
            await self.send_request('charset', 'CHARSET', 'UTF-8')
            return
        await self.send_plainauth_request()

    async def send_plainauth_request(self):
        if not self.site_access_key or not self.site_secret:
            self.auth_skipped = True
            self.logger.warning(
                'Missing OPENFSC_SITE_ACCESS_KEY or OPENFSC_SITE_SECRET; running in unauthenticated mode '
                '(HEARTBEAT/BEAT only until credentials are provided)'
            )
            return
        await self.send_request('plainauth', 'PLAINAUTH', self.site_access_key, self.site_secret)

    async def handle_client_request_response(self, message: ProtocolMessage):
        purpose = self.pending_requests.pop(message.tag, None)
        if not purpose:
            self.logger.warning('Received response for unknown client tag: %s', message.tag)
            return

        if message.method == 'OK':
            if purpose == 'charset':
                self.logger.info('CHARSET accepted by server')
                await self.send_plainauth_request()
                return
            if purpose == 'plainauth':
                self.state = ConnectionState.AUTHENTICATED
                self.logger.info('OpenFSC session is authenticated')
                return
            return

        if message.method == 'ERR':
            err_code = message.args[0] if message.args else 'unknown'
            err_message = message.args[1] if len(message.args) > 1 else 'unknown error'

            if purpose == 'charset':
                self.logger.warning('CHARSET rejected by server (%s): %s; continue with default encoding', err_code, err_message)
                await self.send_plainauth_request()
                return

            if purpose == 'plainauth':
                self.logger.error('PLAINAUTH failed (%s): %s', err_code, err_message)
                await self.send_notification('QUIT', 'Authentication failed')
                await self.require_connection().close()
                return

            self.logger.warning('Request %s failed (%s): %s', purpose, err_code, err_message)
            return

        self.logger.warning('Unexpected response method for client tag %s: %s', message.tag, message.method)

    async def handle_server_notification(self, message: ProtocolMessage):
        self.logger.info('< [S-NOTIF     ] %s %s', message.method, ' '.join(message.args).strip())

        if message.method == 'CAPABILITY':
            self.server_capabilities = set(message.args)
            await self.maybe_send_charset_request()
            return

        if message.method == 'QUIT':
            self.logger.warning('Server sent QUIT: %s', message.args[0] if message.args else '')
            await self.require_connection().close()
            return

    async def handle_server_request(self, message: ProtocolMessage):
        self.logger.info('< [S-REQ #%5s] %s %s', message.tag[1:], message.method, ' '.join(message.args).strip())

        if message.method == 'HEARTBEAT':
            if len(message.args) != 1:
                await self.send_err(message.tag, 422, 'Timestamp invalid')
                return

            await self.send(ProtocolMessage(message.tag, 'BEAT', [now_rfc3339_utc()]))
            await self.send_ok(message.tag)
            return

        if self.state != ConnectionState.AUTHENTICATED:
            await self.send_err(message.tag, 403, 'Wrong connection state')
            return

        await self.send_err(message.tag, 405, f'Method {message.method} not implemented in Milestone A')

    async def handle_incoming(self, raw: str):
        try:
            message = parse_message(raw)
        except ValueError as exc:
            self.logger.error('%s', exc)
            return

        if message.tag == '*':
            await self.handle_server_notification(message)
            return

        if message.tag.startswith('C'):
            self.logger.info('< [C-RES #%5s] %s %s', message.tag[1:], message.method, ' '.join(message.args).strip())
            await self.handle_client_request_response(message)
            return

        if message.tag.startswith('S'):
            await self.handle_server_request(message)
            return

        self.logger.error('Unknown tag received: %s', message.tag)

    async def run_session(self):
        async with websockets.connect(self.fsc_url) as websocket:
            self.ws_connection = websocket
            self.tagged_message_counter = 0
            self.pending_requests = {}
            self.server_capabilities = set()
            self.auth_skipped = False

            await self.start_handshake()

            async for raw in websocket:
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8', errors='replace')
                await self.handle_incoming(raw)

    async def main(self):
        self.state = ConnectionState.DISCONNECTED
        await self.run_session()
