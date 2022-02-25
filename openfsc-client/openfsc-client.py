import asyncio
from email import message
import websockets
import logging

logger = logging.getLogger('websockets')
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

fsc_url = 'wss://fsc.sandbox.k8s.pacelink.net/ws/text'

client_supported_fsc_capabilities = {
    'CLEAR',
    'HEARTBEAT',
    'LOCKPUMP',
    'PRICES',
    'PUMPS',
    'PUMPSTATUS',
    'QUIT',
    'TRANSACTIONS',
    'UNLOCKPUMP',
}

tagged_message_counter = 0


def create_ws_message(m):
    return '' + m + '\r\n'


def produce_notification_message(m):
    return '* ' + m


def produce_tagged_message(m):
    global tagged_message_counter
    msg = 'C' + str(tagged_message_counter) + ' ' + m
    tagged_message_counter += 1
    return msg


def produce_capability_message():
    return produce_notification_message('CAPABILITY ' + ' '.join(str(s) for s in client_supported_fsc_capabilities))


def produce_charset_message():
    return produce_tagged_message('CHARSET UTF-8')


def parse_message(m):
    chunks = m.split()
    for c in chunks:
        print(str(c))


def consumer(m):
    print('< ' + m)
    parse_message(m)
    return


async def producer_handler(websocket):
    message = produce_capability_message()
    print('> ' + message)
    await websocket.send(create_ws_message(message))

    message = produce_charset_message()
    print('> ' + message)
    await websocket.send(create_ws_message(message))


async def consumer_handler(websocket):
    async for message in websocket:
        decoded_message = message.decode('utf-8')
        consumer(decoded_message)


async def handler(websocket):
    await asyncio.gather(
        producer_handler(websocket),
        consumer_handler(websocket),
    )


async def main():
    async with websockets.connect(fsc_url) as websocket:
        await handler(websocket)
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
