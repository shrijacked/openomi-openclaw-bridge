from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
import urllib.error
import urllib.request


@dataclass(frozen=True)
class BridgeConfig:
    openclaw_base_url: str
    default_tool_name: str
    openclaw_api_key: str | None = None
    timeout_seconds: float = 20.0


class OpenClawGatewayError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GatewayClientProtocol(Protocol):
    def invoke_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class OpenClawGatewayClient:
    def __init__(self, config: BridgeConfig) -> None:
        if not config.openclaw_base_url.strip():
            raise ValueError("OPENCLAW_BASE_URL must be configured.")
        self._config = config

    def invoke_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._config.openclaw_api_key:
            headers["Authorization"] = f"Bearer {self._config.openclaw_api_key}"

        request = urllib.request.Request(
            url=self._tools_invoke_url(),
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read().decode("utf-8").strip()
                if not raw:
                    return {}
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    return decoded
                raise OpenClawGatewayError("OpenClaw gateway response must be a JSON object.")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OpenClawGatewayError(
                f"OpenClaw gateway returned HTTP {exc.code}: {error_body}",
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise OpenClawGatewayError(f"Failed to reach OpenClaw gateway: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise OpenClawGatewayError("OpenClaw gateway response is not valid JSON.") from exc

    def _tools_invoke_url(self) -> str:
        return f"{self._config.openclaw_base_url.rstrip('/')}/tools/invoke"


class OmiOpenClawBridge:
    def __init__(
        self,
        config: BridgeConfig,
        gateway_client: GatewayClientProtocol | None = None,
    ) -> None:
        self._config = config
        self._gateway_client = gateway_client or OpenClawGatewayClient(config)

    def handle_chat_tool_invocation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object.")

        tool_name = self._resolve_tool_name(payload)
        tool_input = self._resolve_tool_input(payload)

        request_payload: dict[str, Any] = {
            "tool": tool_name,
            "name": tool_name,
            "input": tool_input,
            "arguments": tool_input,
        }
        session_id = payload.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            request_payload["session_id"] = session_id.strip()

        openclaw_response = self._gateway_client.invoke_tool(request_payload)

        return {
            "status": "ok",
            "text": self._extract_text(openclaw_response),
            "openclaw": openclaw_response,
        }

    def _resolve_tool_name(self, payload: dict[str, Any]) -> str:
        candidate_names = [
            payload.get("openclaw_tool"),
            payload.get("tool"),
            payload.get("name"),
            self._config.default_tool_name,
        ]
        for name in candidate_names:
            if isinstance(name, str) and name.strip():
                return name.strip()
        raise ValueError(
            "No tool name provided. Set OPENCLAW_DEFAULT_TOOL or pass openclaw_tool in request."
        )

    def _resolve_tool_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("arguments", "input", "params"):
            candidate = payload.get(key)
            if isinstance(candidate, dict):
                return candidate

        passthrough = {
            k: v
            for k, v in payload.items()
            if k not in {"openclaw_tool", "tool", "name", "session_id"}
        }
        return passthrough

    def _extract_text(self, response: dict[str, Any]) -> str:
        for key in ("output", "result", "text", "message"):
            value = response.get(key)
            if isinstance(value, str):
                return value
            if value is not None:
                return json.dumps(value, ensure_ascii=True)

        if "data" in response:
            return json.dumps(response["data"], ensure_ascii=True)
        return json.dumps(response, ensure_ascii=True)
