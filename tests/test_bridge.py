import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from omi_openclaw_bridge.bridge import BridgeConfig, OmiOpenClawBridge


class _FakeGatewayClient:
    def __init__(self, response):
        self.response = response
        self.last_payload = None

    def invoke_tool(self, payload):
        self.last_payload = payload
        return self.response


class OmiOpenClawBridgeTests(unittest.TestCase):
    def test_maps_omi_arguments_to_openclaw_payload(self):
        config = BridgeConfig(openclaw_base_url="https://gateway.example", default_tool_name="calendar.lookup")
        fake_client = _FakeGatewayClient({"result": "2026-03-02 events"})
        bridge = OmiOpenClawBridge(config=config, gateway_client=fake_client)

        response = bridge.handle_chat_tool_invocation(
            {
                "arguments": {"date": "2026-03-02", "timezone": "Asia/Kolkata"},
                "session_id": "session-123",
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["text"], "2026-03-02 events")
        self.assertEqual(fake_client.last_payload["tool"], "calendar.lookup")
        self.assertEqual(fake_client.last_payload["name"], "calendar.lookup")
        self.assertEqual(fake_client.last_payload["input"], {"date": "2026-03-02", "timezone": "Asia/Kolkata"})
        self.assertEqual(fake_client.last_payload["arguments"], {"date": "2026-03-02", "timezone": "Asia/Kolkata"})
        self.assertEqual(fake_client.last_payload["session_id"], "session-123")

    def test_tool_name_can_be_overridden_per_request(self):
        config = BridgeConfig(openclaw_base_url="https://gateway.example", default_tool_name="default.tool")
        fake_client = _FakeGatewayClient({"output": "override worked"})
        bridge = OmiOpenClawBridge(config=config, gateway_client=fake_client)

        response = bridge.handle_chat_tool_invocation(
            {
                "openclaw_tool": "tools.search",
                "arguments": {"query": "latest metrics"},
            }
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["text"], "override worked")
        self.assertEqual(fake_client.last_payload["tool"], "tools.search")

    def test_raises_when_tool_name_missing_everywhere(self):
        config = BridgeConfig(openclaw_base_url="https://gateway.example", default_tool_name="")
        fake_client = _FakeGatewayClient({"result": "unused"})
        bridge = OmiOpenClawBridge(config=config, gateway_client=fake_client)

        with self.assertRaises(ValueError):
            bridge.handle_chat_tool_invocation({"arguments": {"x": 1}})

    def test_passthrough_input_excludes_session_id(self):
        config = BridgeConfig(openclaw_base_url="https://gateway.example", default_tool_name="default.tool")
        fake_client = _FakeGatewayClient({"result": "ok"})
        bridge = OmiOpenClawBridge(config=config, gateway_client=fake_client)

        bridge.handle_chat_tool_invocation(
            {
                "query": "latest metrics",
                "session_id": "session-123",
            }
        )

        self.assertEqual(fake_client.last_payload["input"], {"query": "latest metrics"})
        self.assertEqual(fake_client.last_payload["arguments"], {"query": "latest metrics"})
        self.assertEqual(fake_client.last_payload["session_id"], "session-123")


if __name__ == "__main__":
    unittest.main()
