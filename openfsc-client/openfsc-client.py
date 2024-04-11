import asyncio
import logging
from datetime import datetime, timezone

import websockets


class OpenFscClient:
    logger = logging.getLogger('websockets')
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    fsc_url = 'wss://fsc.sandbox.euca.pacelink.net/ws/text'

    client_supported_fsc_capabilities = {
        'CLEAR',
        'HEARTBEAT',
        'LOCKPUMP',
        'PRODUCTS',
        'PRICES',
        'PUMPS',
        'PUMPSTATUS',
        'QUIT',
        'TRANSACTIONS',
        'UNLOCKPUMP',
    }

    tagged_message_counter = 0

    ws_connection = None

    async def send_message(self, m):
        await self.ws_connection.send(m)

    def create_ws_message(self, m):
        return '' + m + '\r\n'

    def produce_notification_message(self, m):
        return '* ' + m

    def produce_tagged_message(self, m):
        counter = self.tagged_message_counter
        msg = 'C' + str(counter) + ' ' + m
        c = str(counter)
        print(f'> [C-REQ #{c:5}] {msg}')
        counter += 1
        return msg

    def produce_capability_message(self):
        m = self.produce_notification_message(
            'CAPABILITY ' + ' '.join(str(s) for s in self.client_supported_fsc_capabilities))
        print(f'> [C-NOTIF     ] {m}')
        return m

    def produce_charset_message(self):
        m = self.produce_tagged_message('CHARSET UTF-8')
        return m

    async def produce_and_send_heartbeat_response_message(self, request_id):
        timestamp = datetime.now(
            tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        message = f'S{request_id} BEAT {timestamp}'
        print(f'> [C-RES #{request_id:5}] {message}')
        await self.send_message(self.create_ws_message(message))
        return

    async def parse_message(self, m):
        chunks = m.rstrip().split(maxsplit=1)
        seq = chunks.pop(0)
        if str(seq).startswith('*'):
            # Notification
            notification_message = str(chunks.pop(0))
            print(f'< [S-NOTIF     ] {notification_message}')
            return
        elif str(seq).startswith('C'):
            # Response to client request
            response_id = seq[1:]
            response_message = str(chunks.pop(0))
            print(f'< [C-RES #{response_id:5}] {response_message}')
            return
        elif str(seq).startswith('S'):
            # Server Request
            request_id = seq[1:]
            request_message = str(chunks.pop(0))
            print(f'< [S-REQ #{request_id:5}] {request_message}')
            if request_message.startswith('HEARTBEAT'):
                await self.produce_and_send_heartbeat_response_message(request_id)
                return
        else:
            print(f'ERROR: message cannot be parsed: {m}')
            return

    async def consumer(self, m):
        await self.parse_message(m)
        return

    async def producer_handler(self, websocket):
        message = self.produce_capability_message()
        await websocket.send(self.create_ws_message(message))

        message = self.produce_charset_message()
        await websocket.send(self.create_ws_message(message))

    async def consumer_handler(self, websocket):
        async for message in websocket:
            decoded_message = message.decode('utf-8')
            await self.consumer(decoded_message)

    async def handler(self, websocket):
        await asyncio.gather(
            self.producer_handler(websocket),
            self.consumer_handler(websocket),
        )

    async def main(self):
        async with websockets.connect(self.fsc_url) as websocket:
            self.ws_connection = websocket
            await self.handler(websocket)
            await asyncio.Future()  # run forever


client = OpenFscClient()
asyncio.run(client.main())
