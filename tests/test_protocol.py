import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLIENT_DIR = os.path.join(PROJECT_ROOT, 'openfsc-client')
if CLIENT_DIR not in sys.path:
    sys.path.insert(0, CLIENT_DIR)

from protocol import ProtocolMessage, parse_message, serialize_message


class ProtocolTests(unittest.TestCase):
    def test_serialize_message_with_args(self):
        message = ProtocolMessage(tag='S1', method='PUMP', args=['3', 'free'])
        self.assertEqual(serialize_message(message), 'S1 PUMP 3 free\r\n')

    def test_parse_err_with_text_message(self):
        parsed = parse_message('S3 ERR 404 Pump unknown\r\n')
        self.assertEqual(parsed.tag, 'S3')
        self.assertEqual(parsed.method, 'ERR')
        self.assertEqual(parsed.args, ['404', 'Pump unknown'])

    def test_parse_quit_preserves_reason(self):
        parsed = parse_message('* QUIT server maintenance in 1 minute\r\n')
        self.assertEqual(parsed.tag, '*')
        self.assertEqual(parsed.method, 'QUIT')
        self.assertEqual(parsed.args, ['server maintenance in 1 minute'])

    def test_parse_invalid_message_raises(self):
        with self.assertRaises(ValueError):
            parse_message('BROKEN\r\n')


if __name__ == '__main__':
    unittest.main()
