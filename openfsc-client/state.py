from enum import Enum


class ConnectionState(str, Enum):
    DISCONNECTED = 'DISCONNECTED'
    HANDSHAKE = 'HANDSHAKE'
    AUTHENTICATED = 'AUTHENTICATED'
