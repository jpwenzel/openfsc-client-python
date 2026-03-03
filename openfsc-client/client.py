import asyncio
import logging
from importlib import import_module
from typing import Any

from config import OpenFscConfig
from pos_adapter import PosAdapter
from protocol import ProtocolMessage, now_rfc3339_utc, parse_message, serialize_message
from state import ConnectionState

websockets = import_module('websockets')


class OpenFscClient:
    def __init__(self, config: OpenFscConfig, pos_adapter: PosAdapter):
        self.logger = logging.getLogger('openfsc-client')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(logging.StreamHandler())

        self.fsc_url = config.fsc_url
        self.site_access_key = config.site_access_key
        self.site_secret = config.site_secret
        self.pos_adapter = pos_adapter

        self.client_supported_fsc_capabilities = sorted({
            'CLEAR',
            'HEARTBEAT',
            'LOCKPUMP',
            'PRICES',
            'PRODUCTS',
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
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_quit_sent = False

        register_transaction_notification_handler = getattr(self.pos_adapter, 'set_transaction_notification_handler', None)
        if callable(register_transaction_notification_handler):
            register_transaction_notification_handler(self._on_completed_unlock_transaction)

        register_pump_status_notification_handler = getattr(self.pos_adapter, 'set_pump_status_notification_handler', None)
        if callable(register_pump_status_notification_handler):
            register_pump_status_notification_handler(self._on_pump_status_changed)

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

    async def send_transaction_notification(self, transaction):
        await self.send_notification(
            'TRANSACTION',
            str(transaction.pump_number),
            transaction.site_transaction_id,
            transaction.status,
            transaction.product_id,
            transaction.currency,
            f'{transaction.price_with_vat:.2f}',
            f'{transaction.price_without_vat:.2f}',
            f'{transaction.vat_rate:.1f}',
            f'{transaction.vat_amount:.2f}',
            transaction.unit,
            f'{transaction.volume:.2f}',
            f'{transaction.price_per_unit:.3f}',
        )

    async def send_quit_for_shutdown(self, reason: str = 'Client shutdown'):
        if self._shutdown_quit_sent:
            return

        connection = self.ws_connection
        if connection is None:
            return

        self._shutdown_quit_sent = True

        if not bool(getattr(connection, 'closed', False)):
            try:
                await asyncio.shield(self.send_notification('QUIT', reason))
            except Exception:
                self.logger.warning('Failed to send QUIT during shutdown', exc_info=True)

        try:
            if not bool(getattr(connection, 'closed', False)):
                await asyncio.shield(connection.close())
        except Exception:
            self.logger.warning('Failed to close websocket during shutdown', exc_info=True)

    def _on_completed_unlock_transaction(self, transaction):
        loop = self._event_loop
        if loop is None or loop.is_closed():
            self.logger.warning(
                'Skipping completed pre-auth TRANSACTION notification for pump %d: no active event loop',
                transaction.pump_number,
            )
            return

        future = asyncio.run_coroutine_threadsafe(self.send_transaction_notification(transaction), loop)

        def _log_notification_result(done_future):
            try:
                done_future.result()
            except Exception:
                self.logger.exception(
                    'Failed to send completed pre-auth TRANSACTION notification for pump %d',
                    transaction.pump_number,
                )

        future.add_done_callback(_log_notification_result)

    def _on_pump_status_changed(self, pump_number: int, status: str):
        loop = self._event_loop
        if loop is None or loop.is_closed():
            self.logger.warning(
                'Skipping PUMP notification for pump %d (%s): no active event loop',
                pump_number,
                status,
            )
            return

        future = asyncio.run_coroutine_threadsafe(
            self.send_notification('PUMP', str(pump_number), status),
            loop,
        )

        def _log_notification_result(done_future):
            try:
                done_future.result()
            except Exception:
                self.logger.exception(
                    'Failed to send PUMP notification for pump %d (%s)',
                    pump_number,
                    status,
                )

        future.add_done_callback(_log_notification_result)

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

        # Dispatch to authenticated handlers
        if message.method == 'PRICES':
            await self.handle_prices_request(message.tag)
        elif message.method == 'PRODUCTS':
            await self.handle_products_request(message.tag)
        elif message.method == 'PUMPS':
            await self.handle_pumps_request(message.tag)
        elif message.method == 'PUMPSTATUS':
            await self.handle_pumpstatus_request(message.tag, message.args)
        elif message.method == 'TRANSACTIONS':
            await self.handle_transactions_request(message.tag, message.args)
        elif message.method == 'UNLOCKPUMP':
            await self.handle_unlockpump_request(message.tag, message.args)
        elif message.method == 'LOCKPUMP':
            await self.handle_lockpump_request(message.tag, message.args)
        elif message.method == 'CLEAR':
            await self.handle_clear_request(message.tag, message.args)
        else:
            await self.send_err(message.tag, 405, f'Method {message.method} unknown')

    async def handle_prices_request(self, tag: str):
        """Handle PRICES request - send PRICE notifications for all products."""
        products = self.pos_adapter.get_products()
        for product in products:
            await self.send_notification(
                'PRICE',
                product.product_id,
                product.unit,
                product.currency,
                f'{product.price_per_unit:.3f}',
                product.description,
            )
        await self.send_ok(tag)

    async def handle_products_request(self, tag: str):
        """Handle PRODUCTS request - send PRODUCT notifications for all products."""
        products = self.pos_adapter.get_products()
        for product in products:
            await self.send_notification(
                'PRODUCT',
                product.product_id,
                product.product_type,
                f'{product.vat_rate:.1f}',
                product.unit,
                product.description,
            )
        await self.send_ok(tag)

    async def handle_pumps_request(self, tag: str):
        """Handle PUMPS request - send PUMP notifications for all pumps."""
        pumps = self.pos_adapter.get_pumps()
        for pump in pumps:
            await self.send_notification('PUMP', str(pump.pump_number), pump.status)
        await self.send_ok(tag)

    async def handle_pumpstatus_request(self, tag: str, args: list[str]):
        """Handle PUMPSTATUS request - send PUMP notification for specific pump."""
        if len(args) < 1:
            await self.send_err(tag, 400, 'Bad request: missing pump number')
            return

        try:
            pump_number = int(args[0])
        except ValueError:
            await self.send_err(tag, 400, 'Bad request: invalid pump number')
            return

        on_pumpstatus_requested = getattr(self.pos_adapter, 'on_pumpstatus_requested', None)
        if callable(on_pumpstatus_requested):
            on_pumpstatus_requested(pump_number)

        # Optional UpdateTTL parameter
        update_ttl = None
        if len(args) >= 2:
            try:
                update_ttl = int(args[1])
                if update_ttl < 30 or update_ttl > 300:
                    await self.send_err(tag, 416, 'UpdateTTL is too large or too low (valid range 30 - 300)')
                    return
            except ValueError:
                await self.send_err(tag, 400, 'Bad request: invalid UpdateTTL')
                return

        pump = self.pos_adapter.get_pump_status(pump_number)
        if pump is None:
            await self.send_err(tag, 404, 'Pump unknown')
            return

        await self.send_notification('PUMP', str(pump.pump_number), pump.status)
        await self.send_ok(tag)

        # TODO: Implement TTL-based update subscription in Milestone C

    async def handle_transactions_request(self, tag: str, args: list[str]):
        """Handle TRANSACTIONS request - send TRANSACTION notifications."""
        pump_number = None
        update_ttl = None

        if len(args) >= 1:
            try:
                pump_number = int(args[0])
            except ValueError:
                await self.send_err(tag, 400, 'Bad request: invalid pump number')
                return

            # Check if pump exists
            pump = self.pos_adapter.get_pump_status(pump_number)
            if pump is None:
                await self.send_err(tag, 404, 'Pump unknown')
                return

        if len(args) >= 2:
            try:
                update_ttl = int(args[1])
                if update_ttl < 30 or update_ttl > 300:
                    await self.send_err(tag, 416, 'UpdateTTL is too large or too low (valid range 30 - 300)')
                    return
            except ValueError:
                await self.send_err(tag, 400, 'Bad request: invalid UpdateTTL')
                return

            if pump_number is None:
                await self.send_err(tag, 400, 'UpdateTTL requires pump number')
                return

        transactions = self.pos_adapter.get_transactions(pump_number)
        for tx in transactions:
            await self.send_notification(
                'TRANSACTION',
                str(tx.pump_number),
                tx.site_transaction_id,
                tx.status,
                tx.product_id,
                tx.currency,
                f'{tx.price_with_vat:.2f}',
                f'{tx.price_without_vat:.2f}',
                f'{tx.vat_rate:.1f}',
                f'{tx.vat_amount:.2f}',
                tx.unit,
                f'{tx.volume:.2f}',
                f'{tx.price_per_unit:.3f}',
            )
        await self.send_ok(tag)

        # TODO: Implement TTL-based update subscription in Milestone C

    async def handle_unlockpump_request(self, tag: str, args: list[str]):
        """Handle UNLOCKPUMP request - unlock pump for pre-auth fueling."""
        if len(args) < 5:
            await self.send_err(tag, 400, 'Bad request: missing required arguments')
            return

        try:
            pump_number = int(args[0])
            currency = args[1]
            credit = float(args[2])
            fsc_transaction_id = args[3]
            payment_method = args[4]
            product_ids = args[5:] if len(args) > 5 else None
        except (ValueError, IndexError):
            await self.send_err(tag, 400, 'Bad request: invalid arguments')
            return

        result = self.pos_adapter.unlock_pump(
            pump_number, currency, credit, fsc_transaction_id, payment_method, product_ids
        )

        if result.success:
            await self.send_ok(tag)
        else:
            await self.send_err(tag, result.error_code or 500, result.error_message or 'Internal server error')

    async def handle_lockpump_request(self, tag: str, args: list[str]):
        """Handle LOCKPUMP request - cancel/lock pump."""
        if len(args) < 1:
            await self.send_err(tag, 400, 'Bad request: missing pump number')
            return

        try:
            pump_number = int(args[0])
        except ValueError:
            await self.send_err(tag, 400, 'Bad request: invalid pump number')
            return

        result = self.pos_adapter.lock_pump(pump_number)

        if result.success:
            await self.send_ok(tag)
        else:
            await self.send_err(tag, result.error_code or 500, result.error_message or 'Internal server error')

    async def handle_clear_request(self, tag: str, args: list[str]):
        """Handle CLEAR request - clear/complete transaction."""
        if len(args) < 4:
            await self.send_err(tag, 400, 'Bad request: missing required arguments')
            return

        try:
            pump_number = int(args[0])
            site_transaction_id = args[1]
            fsc_transaction_id = args[2]
            payment_method = args[3]
        except (ValueError, IndexError):
            await self.send_err(tag, 400, 'Bad request: invalid arguments')
            return

        result = self.pos_adapter.clear_transaction(pump_number, site_transaction_id, fsc_transaction_id, payment_method)

        if result.success:
            await self.send_ok(tag)
        else:
            await self.send_err(tag, result.error_code or 500, result.error_message or 'Internal server error')

    async def handle_incoming(self, raw: str):
        self._event_loop = asyncio.get_running_loop()

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
            self._event_loop = asyncio.get_running_loop()
            self.ws_connection = websocket
            self.tagged_message_counter = 0
            self.pending_requests = {}
            self.server_capabilities = set()
            self.auth_skipped = False

            await self.start_handshake()

            try:
                async for raw in websocket:
                    if isinstance(raw, bytes):
                        raw = raw.decode('utf-8', errors='replace')
                    await self.handle_incoming(raw)
            except asyncio.CancelledError:
                self.logger.info('Session receive loop canceled, shutting down')
                await self.send_quit_for_shutdown('Client shutdown')
                raise

    async def main(self):
        self.state = ConnectionState.DISCONNECTED
        await self.run_session()
