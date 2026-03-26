from __future__ import annotations

import copy
import json
from typing import Any

import httpx
from httpx_retries import Retry, RetryTransport

from .auth import TokenProvider
from .config import RetryConfig, TimeoutConfig
from .errors import ProxyAuthError, ProxyProtocolError, ProxyTransportError

JSONObj = dict[str, Any]
DEFAULT_PROTOCOL_VERSION = "2025-03-26"


class McpHttpTransport:
    def __init__(
        self,
        *,
        url: str,
        token_provider: TokenProvider,
        timeout_config: TimeoutConfig,
        retry_config: RetryConfig,
        user_project: str | None = None,
        base_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url
        self._token_provider = token_provider
        self._user_project = user_project
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        self._initialize_request: JSONObj | None = None
        self._initialized_notification: JSONObj | None = None

        timeout = httpx.Timeout(
            connect=timeout_config.connect_seconds,
            read=timeout_config.read_seconds,
            write=timeout_config.write_seconds,
            pool=timeout_config.pool_seconds,
        )

        retry = Retry(
            total=retry_config.max_retries,
            backoff_factor=retry_config.backoff_factor,
            allowed_methods={"POST"},
            status_forcelist={408, 429, 500, 502, 503, 504},
        )
        retry_transport = RetryTransport(transport=base_transport, retry=retry)

        self._client = httpx.Client(timeout=timeout, transport=retry_transport)

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    def close(self) -> None:
        self._client.close()

    def send(self, message: JSONObj) -> list[JSONObj]:
        self._cache_lifecycle_message(message)
        return self._send_with_optional_reset(message, allow_reset=True)

    def _send_with_optional_reset(self, message: JSONObj, *, allow_reset: bool) -> list[JSONObj]:
        try:
            response = self._post(message)
            responses = self._parse_response(response)
            self._record_successful_exchange(
                message=message,
                response=response,
                responses=responses,
            )
            return responses
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in (401, 403):
                raise ProxyAuthError(
                    f"HTTP auth error from MCP endpoint ({status_code})",
                    details={"status_code": status_code},
                ) from exc

            if status_code == 404 and self._session_id and allow_reset:
                return self._reinitialize_after_session_loss(message)

            raise ProxyTransportError(
                f"HTTP error from MCP endpoint ({status_code})",
                details={"status_code": status_code, "body": _safe_response_text(exc.response)},
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProxyTransportError("Timeout while calling MCP endpoint") from exc
        except httpx.HTTPError as exc:
            raise ProxyTransportError("Transport failure while calling MCP endpoint") from exc

    def _post(self, message: JSONObj) -> httpx.Response:
        bearer = self._token_provider.get_bearer_token()
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._user_project:
            headers["x-goog-user-project"] = self._user_project
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        response = self._client.post(self._url, json=message, headers=headers)
        response.raise_for_status()
        return response

    def _parse_response(self, response: httpx.Response) -> list[JSONObj]:
        if response.status_code in (202, 204):
            return []

        if not response.text.strip():
            return []

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return _parse_event_stream(response.text)

        return _parse_json_payload(response.text)

    def _cache_lifecycle_message(self, message: JSONObj) -> None:
        if _is_initialize_request(message):
            self._initialize_request = copy.deepcopy(message)
            self._initialized_notification = None
            return

        if _is_initialized_notification(message):
            self._initialized_notification = copy.deepcopy(message)

    def _record_successful_exchange(
        self,
        *,
        message: JSONObj,
        response: httpx.Response,
        responses: list[JSONObj],
    ) -> None:
        self._session_id = response.headers.get("mcp-session-id", self._session_id)
        if not _is_initialize_request(message):
            return

        self._protocol_version = _resolve_protocol_version(
            initialize_request=message,
            responses=responses,
        )

    def _reinitialize_after_session_loss(self, message: JSONObj) -> list[JSONObj]:
        initialize_request = self._initialize_request
        if initialize_request is None:
            raise ProxyProtocolError(
                "MCP session expired with HTTP 404, but no initialize request "
                "was cached for re-initialization"
            )

        self._session_id = None
        self._send_with_optional_reset(initialize_request, allow_reset=False)

        if self._initialized_notification and not _is_initialized_notification(message):
            self._send_with_optional_reset(self._initialized_notification, allow_reset=False)

        return self._send_with_optional_reset(message, allow_reset=False)


def _safe_response_text(response: httpx.Response, *, limit: int = 1200) -> str:
    text = response.text
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated>"


def _parse_json_payload(payload: str) -> list[JSONObj]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProxyProtocolError("MCP endpoint returned malformed JSON") from exc

    if isinstance(parsed, dict):
        return [parsed]

    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        return [item for item in parsed if isinstance(item, dict)]

    raise ProxyProtocolError("MCP endpoint returned unsupported JSON shape")


def _extract_protocol_version(responses: list[JSONObj]) -> str | None:
    if not responses:
        return None

    result = responses[0].get("result")
    if not isinstance(result, dict):
        return None

    protocol_version = result.get("protocolVersion")
    if isinstance(protocol_version, str) and protocol_version:
        return protocol_version

    return None


def _extract_initialize_request_protocol_version(message: JSONObj) -> str | None:
    params = message.get("params")
    if not isinstance(params, dict):
        return None

    protocol_version = params.get("protocolVersion")
    if isinstance(protocol_version, str) and protocol_version:
        return protocol_version

    return None


def _resolve_protocol_version(
    *,
    initialize_request: JSONObj,
    responses: list[JSONObj],
) -> str:
    return (
        _extract_protocol_version(responses)
        or _extract_initialize_request_protocol_version(initialize_request)
        or DEFAULT_PROTOCOL_VERSION
    )


def _is_initialize_request(message: JSONObj) -> bool:
    return message.get("method") == "initialize"


def _is_initialized_notification(message: JSONObj) -> bool:
    return message.get("method") == "notifications/initialized"


def _parse_event_stream(payload: str) -> list[JSONObj]:
    messages: list[JSONObj] = []
    event_data_lines: list[str] = []

    def flush_event() -> None:
        if not event_data_lines:
            return

        event_data = "\n".join(event_data_lines).strip()
        event_data_lines.clear()
        if event_data == "[DONE]" or not event_data:
            return

        try:
            parsed = json.loads(event_data)
        except json.JSONDecodeError as exc:
            raise ProxyProtocolError("SSE payload contained malformed JSON") from exc

        if not isinstance(parsed, dict):
            raise ProxyProtocolError("SSE payload contained a non-object MCP message")

        messages.append(parsed)

    for raw_line in payload.splitlines():
        line = raw_line.rstrip()
        if line == "":
            flush_event()
            continue

        if line.startswith("data:"):
            event_data_lines.append(line.removeprefix("data:").lstrip())

    flush_event()

    if not messages:
        raise ProxyProtocolError("SSE payload did not include any MCP JSON messages")

    return messages
