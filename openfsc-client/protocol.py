from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ProtocolMessage:
    tag: str
    method: str
    args: list[str]


def now_rfc3339_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def serialize_message(message: ProtocolMessage) -> str:
    head = f'{message.tag} {message.method}'
    if message.args:
        head = f"{head} {' '.join(message.args)}"
    return f'{head}\r\n'


def parse_message(raw: str) -> ProtocolMessage:
    line = raw.rstrip('\r\n')
    first_split = line.split(' ', maxsplit=2)
    if len(first_split) < 2:
        raise ValueError(f'Invalid OpenFSC message: {raw!r}')

    tag = first_split[0]
    method = first_split[1]
    args_tail = first_split[2] if len(first_split) > 2 else ''

    if not args_tail:
        args = []
    elif method == 'ERR':
        code_and_message = args_tail.split(' ', maxsplit=1)
        if len(code_and_message) == 1:
            args = [code_and_message[0]]
        else:
            args = [code_and_message[0], code_and_message[1]]
    elif method == 'QUIT':
        args = [args_tail]
    else:
        args = args_tail.split(' ')

    return ProtocolMessage(tag=tag, method=method, args=args)
