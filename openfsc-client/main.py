import asyncio

from client import OpenFscClient
from config import OpenFscConfig
from logging_pos_adapter import LoggingPosAdapter


async def run() -> None:
    config = OpenFscConfig.from_env()
    pos_adapter = LoggingPosAdapter()
    client = OpenFscClient(config, pos_adapter)
    await client.main()


def main() -> None:
    asyncio.run(run())


if __name__ == '__main__':
    main()
