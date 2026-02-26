import os
from dataclasses import dataclass


@dataclass
class OpenFscConfig:
    fsc_url: str
    site_access_key: str
    site_secret: str

    @classmethod
    def from_env(cls) -> 'OpenFscConfig':
        return cls(
            fsc_url=os.getenv('OPENFSC_URL', 'wss://fsc.sandbox.euca.pacelink.net/ws/text'),
            site_access_key=os.getenv('OPENFSC_SITE_ACCESS_KEY', ''),
            site_secret=os.getenv('OPENFSC_SITE_SECRET', ''),
        )
