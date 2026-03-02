import asyncio
import importlib
import os

from client import OpenFscClient
from config import OpenFscConfig
from pos_adapter import PosAdapter


DEFAULT_POS_ADAPTER_CLASS = 'example_pos_adapter.ExamplePosAdapter'


def load_pos_adapter() -> PosAdapter:
    adapter_class_spec = os.getenv('POS_ADAPTER_CLASS', DEFAULT_POS_ADAPTER_CLASS).strip()
    if not adapter_class_spec:
        adapter_class_spec = DEFAULT_POS_ADAPTER_CLASS

    module_name, separator, class_name = adapter_class_spec.rpartition('.')
    if not separator:
        raise ValueError(
            'POS_ADAPTER_CLASS must be in the form "module_name.ClassName" '
            f'(got "{adapter_class_spec}")'
        )

    module = importlib.import_module(module_name)
    adapter_class = getattr(module, class_name)

    if not isinstance(adapter_class, type) or not issubclass(adapter_class, PosAdapter):
        raise TypeError(
            'POS_ADAPTER_CLASS must resolve to a PosAdapter subclass '
            f'(got "{adapter_class_spec}")'
        )

    return adapter_class()


async def run() -> None:
    config = OpenFscConfig.from_env()
    pos_adapter = load_pos_adapter()
    client = OpenFscClient(config, pos_adapter)
    await client.main()


def main() -> None:
    asyncio.run(run())


if __name__ == '__main__':
    main()
