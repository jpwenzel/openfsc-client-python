import asyncio

from client import OpenFscClient
from config import OpenFscConfig


async def run() -> None:
    client = OpenFscClient(OpenFscConfig.from_env())
    await client.main()


def main() -> None:
    asyncio.run(run())


if __name__ == '__main__':
    main()
