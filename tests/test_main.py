import importlib.util
import os
import sys
import types
import unittest
from unittest import mock


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLIENT_DIR = os.path.join(PROJECT_ROOT, 'openfsc-client')


def load_module(name: str, filename: str):
    path = os.path.join(CLIENT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load module {name} from {path}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


load_module('config', 'config.py')
load_module('state', 'state.py')
load_module('protocol', 'protocol.py')
load_module('pos_adapter', 'pos_adapter.py')
example_pos_adapter_module = load_module('example_pos_adapter', 'example_pos_adapter.py')
websockets_stub = types.ModuleType('websockets')
setattr(websockets_stub, 'connect', None)
sys.modules.setdefault('websockets', websockets_stub)
load_module('client', 'client.py')
main_module = load_module('main_under_test', 'main.py')

ExamplePosAdapter = example_pos_adapter_module.ExamplePosAdapter


class PosAdapterLoaderTests(unittest.TestCase):
    def test_load_pos_adapter_defaults_to_example_adapter(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('POS_ADAPTER_CLASS', None)
            adapter = main_module.load_pos_adapter()

        self.assertIsInstance(adapter, ExamplePosAdapter)

    def test_load_pos_adapter_uses_env_override(self):
        with mock.patch.dict(os.environ, {'POS_ADAPTER_CLASS': 'example_pos_adapter.ExamplePosAdapter'}):
            adapter = main_module.load_pos_adapter()

        self.assertIsInstance(adapter, ExamplePosAdapter)

    def test_load_pos_adapter_rejects_invalid_format(self):
        with mock.patch.dict(os.environ, {'POS_ADAPTER_CLASS': 'ExamplePosAdapter'}):
            with self.assertRaises(ValueError):
                main_module.load_pos_adapter()

    def test_load_pos_adapter_rejects_non_pos_adapter_class(self):
        fake_module = types.ModuleType('fake_plugin')

        class NotAnAdapter:
            pass

        setattr(fake_module, 'NotAnAdapter', NotAnAdapter)

        with mock.patch.dict(sys.modules, {'fake_plugin': fake_module}, clear=False):
            with mock.patch.dict(os.environ, {'POS_ADAPTER_CLASS': 'fake_plugin.NotAnAdapter'}):
                with self.assertRaises(TypeError):
                    main_module.load_pos_adapter()


if __name__ == '__main__':
    unittest.main()
