import os
from dataclasses import dataclass


def _float_env(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f'{name} must be a number (got "{raw}")') from None
    if value < minimum:
        raise ValueError(f'{name} must be >= {minimum} (got {value})')
    return value


def _int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f'{name} must be an integer (got "{raw}")') from None
    if value < minimum:
        raise ValueError(f'{name} must be >= {minimum} (got {value})')
    return value


@dataclass
class OpenFscConfig:
    fsc_url: str
    site_access_key: str
    site_secret: str
    # Reconnect with exponential back-off. A site connector is a long-running
    # service, so by default it never gives up (max_retries = 0 means unlimited).
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 60.0
    reconnect_max_retries: int = 0

    def __post_init__(self):
        if self.reconnect_max_delay < self.reconnect_initial_delay:
            raise ValueError('OPENFSC_RECONNECT_MAX_DELAY must be >= OPENFSC_RECONNECT_INITIAL_DELAY')

    @classmethod
    def from_env(cls) -> 'OpenFscConfig':
        return cls(
            fsc_url=os.getenv('OPENFSC_URL', 'wss://fsc.sandbox.euca.pacelink.net/ws/text'),
            site_access_key=os.getenv('OPENFSC_SITE_ACCESS_KEY', ''),
            site_secret=os.getenv('OPENFSC_SITE_SECRET', ''),
            reconnect_initial_delay=_float_env('OPENFSC_RECONNECT_INITIAL_DELAY', 1.0, 0.1),
            reconnect_max_delay=_float_env('OPENFSC_RECONNECT_MAX_DELAY', 60.0, 0.1),
            reconnect_max_retries=_int_env('OPENFSC_RECONNECT_MAX_RETRIES', 0, 0),
        )
