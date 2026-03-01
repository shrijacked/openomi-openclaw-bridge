import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from omi_openclaw_bridge.server import _is_authorized, _read_timeout_seconds, create_handler


class OmiOpenClawServerTests(unittest.TestCase):
    def test_create_handler_returns_handler_type(self):
        class _FakeBridge:
            def handle_chat_tool_invocation(self, payload):
                return payload

        handler = create_handler(_FakeBridge(), webhook_token="secret-token")
        self.assertTrue(issubclass(handler, object))

    def test_authorized_without_token(self):
        self.assertTrue(_is_authorized({}, webhook_token=None))

    def test_authorized_with_bearer_token(self):
        headers = {"Authorization": "Bearer secret-token"}
        self.assertTrue(_is_authorized(headers, webhook_token="secret-token"))

    def test_authorized_with_lowercase_bearer_scheme(self):
        headers = {"Authorization": "bearer secret-token"}
        self.assertTrue(_is_authorized(headers, webhook_token="secret-token"))

    def test_authorized_with_x_omi_token(self):
        headers = {"X-Omi-Token": "secret-token"}
        self.assertTrue(_is_authorized(headers, webhook_token="secret-token"))

    def test_unauthorized_with_wrong_token(self):
        headers = {"Authorization": "Bearer wrong-token"}
        self.assertFalse(_is_authorized(headers, webhook_token="secret-token"))

    def test_timeout_defaults_to_20_seconds(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_read_timeout_seconds(), 20.0)

    def test_timeout_rejects_non_numeric_value(self):
        with patch.dict("os.environ", {"OPENCLAW_TIMEOUT_SECONDS": "abc"}, clear=True):
            with self.assertRaises(ValueError):
                _read_timeout_seconds()

    def test_timeout_rejects_nan(self):
        with patch.dict("os.environ", {"OPENCLAW_TIMEOUT_SECONDS": "nan"}, clear=True):
            with self.assertRaises(ValueError):
                _read_timeout_seconds()

    def test_timeout_rejects_inf(self):
        with patch.dict("os.environ", {"OPENCLAW_TIMEOUT_SECONDS": "inf"}, clear=True):
            with self.assertRaises(ValueError):
                _read_timeout_seconds()


if __name__ == "__main__":
    unittest.main()
