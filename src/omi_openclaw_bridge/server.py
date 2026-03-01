from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from typing import Any

from .bridge import BridgeConfig, OmiOpenClawBridge, OpenClawGatewayError


def create_handler(bridge: OmiOpenClawBridge, webhook_token: str | None = None):
    class OmiOpenClawHandler(BaseHTTPRequestHandler):
        server_version = "omi-openclaw-bridge/1.0"

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_json(200, {"status": "ok"})
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/omi/chat-tools/openclaw":
                self._send_json(404, {"error": "not_found"})
                return

            if not _is_authorized(self.headers, webhook_token):
                self._send_json(401, {"error": "unauthorized"})
                return

            try:
                payload = self._read_json_payload()
            except ValueError as exc:
                self._send_json(400, {"error": "bad_request", "message": str(exc)})
                return

            try:
                response_payload = bridge.handle_chat_tool_invocation(payload)
            except ValueError as exc:
                self._send_json(400, {"error": "validation_error", "message": str(exc)})
            except OpenClawGatewayError as exc:
                self._send_json(
                    502,
                    {
                        "error": "openclaw_gateway_error",
                        "message": str(exc),
                        "status_code": exc.status_code,
                    },
                )
            except Exception:
                self._send_json(500, {"error": "internal_error"})
            else:
                self._send_json(200, response_payload)

        def _read_json_payload(self) -> dict[str, Any]:
            length_value = self.headers.get("Content-Length")
            if length_value is None:
                raise ValueError("Content-Length header is required.")

            try:
                content_length = int(length_value)
            except ValueError as exc:
                raise ValueError("Invalid Content-Length header.") from exc

            if content_length <= 0:
                raise ValueError("Request body cannot be empty.")

            raw_body = self.rfile.read(content_length).decode("utf-8")
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ValueError("Request body must be valid JSON.") from exc

            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return OmiOpenClawHandler


def run_server() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    timeout_seconds = _read_timeout_seconds()

    config = BridgeConfig(
        openclaw_base_url=os.getenv("OPENCLAW_BASE_URL", ""),
        default_tool_name=os.getenv("OPENCLAW_DEFAULT_TOOL", ""),
        openclaw_api_key=os.getenv("OPENCLAW_API_KEY") or None,
        timeout_seconds=timeout_seconds,
    )
    bridge = OmiOpenClawBridge(config=config)
    webhook_token = (os.getenv("OMI_WEBHOOK_TOKEN") or "").strip() or None

    handler = create_handler(bridge, webhook_token=webhook_token)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"omi-openclaw-bridge listening on {host}:{port}", flush=True)
    server.serve_forever()


def _is_authorized(headers, webhook_token: str | None) -> bool:
    if not webhook_token:
        return True

    auth_header = headers.get("Authorization", "")
    if auth_header:
        try:
            scheme, token = auth_header.split(" ", 1)
        except ValueError:
            scheme, token = "", ""
        if scheme.lower() == "bearer" and token == webhook_token:
            return True

    omi_header = headers.get("X-Omi-Token", "")
    return omi_header == webhook_token


def _read_timeout_seconds() -> float:
    raw_value = os.getenv("OPENCLAW_TIMEOUT_SECONDS", "20").strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError("OPENCLAW_TIMEOUT_SECONDS must be a number.") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("OPENCLAW_TIMEOUT_SECONDS must be a finite number greater than zero.")
    return value
