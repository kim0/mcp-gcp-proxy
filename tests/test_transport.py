from __future__ import annotations

from typing import Any

import httpx
import pytest

from mcp_gcp_proxy.config import RetryConfig, TimeoutConfig
from mcp_gcp_proxy.errors import ProxyAuthError, ProxyProtocolError
from mcp_gcp_proxy.transport import McpHttpTransport


class StaticTokenProvider:
    def get_bearer_token(self) -> str:
        return "token-123"


def _transport(handler: Any) -> McpHttpTransport:
    return McpHttpTransport(
        url="https://example.test/mcp",
        token_provider=StaticTokenProvider(),
        timeout_config=TimeoutConfig(
            connect_seconds=1,
            read_seconds=2,
            write_seconds=3,
            pool_seconds=4,
        ),
        retry_config=RetryConfig(max_retries=1, backoff_factor=0.0),
        user_project="sdp-tealbook-dev",
        base_transport=httpx.MockTransport(handler),
    )


def test_protocol_version_header_is_sent_on_subsequent_requests() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-05",
                        "capabilities": {},
                        "serverInfo": {},
                    },
                },
                headers={"mcp-session-id": "session-a"},
                request=request,
            )
        if len(calls) == 2:
            return httpx.Response(202, text="", request=request)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
            request=request,
        )

    transport = _transport(handler)

    _ = transport.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-05", "capabilities": {}, "clientInfo": {}},
        }
    )
    _ = transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    _ = transport.send({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})

    assert calls[0].headers.get("mcp-protocol-version") is None
    assert calls[1].headers.get("mcp-protocol-version") == "2025-11-05"
    assert calls[1].headers.get("mcp-session-id") == "session-a"
    assert calls[2].headers.get("mcp-protocol-version") == "2025-11-05"
    assert calls[2].headers.get("mcp-session-id") == "session-a"


def test_protocol_version_header_falls_back_to_initialize_request_version() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"capabilities": {}, "serverInfo": {}},
                },
                headers={"mcp-session-id": "session-a"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
            request=request,
        )

    transport = _transport(handler)

    _ = transport.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-05", "capabilities": {}, "clientInfo": {}},
        }
    )
    _ = transport.send({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})

    assert calls[0].headers.get("mcp-protocol-version") is None
    assert calls[1].headers.get("mcp-protocol-version") == "2025-11-05"


def test_protocol_version_header_falls_back_to_default_version() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"capabilities": {}, "serverInfo": {}},
                },
                headers={"mcp-session-id": "session-a"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
            request=request,
        )

    transport = _transport(handler)

    _ = transport.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"capabilities": {}, "clientInfo": {}},
        }
    )
    _ = transport.send({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})

    assert calls[0].headers.get("mcp-protocol-version") is None
    assert calls[1].headers.get("mcp-protocol-version") == "2025-03-26"


def test_session_404_triggers_reinitialize_before_replaying_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-05",
                        "capabilities": {},
                        "serverInfo": {},
                    },
                },
                headers={"mcp-session-id": "session-a"},
                request=request,
            )
        if len(calls) == 2:
            return httpx.Response(202, text="", request=request)
        if len(calls) == 3:
            return httpx.Response(404, text="stale session", request=request)
        if len(calls) == 4:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "protocolVersion": "2025-11-05",
                        "capabilities": {},
                        "serverInfo": {},
                    },
                },
                headers={"mcp-session-id": "fresh-session"},
                request=request,
            )
        if len(calls) == 5:
            return httpx.Response(202, text="", request=request)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 7, "result": {"ok": True}},
            request=request,
        )

    transport = _transport(handler)

    _ = transport.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-05", "capabilities": {}, "clientInfo": {}},
        }
    )
    _ = transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    response = transport.send({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}})

    assert response[0]["id"] == 7
    assert transport.session_id == "fresh-session"
    assert len(calls) == 6
    assert calls[2].headers.get("mcp-session-id") == "session-a"
    assert calls[2].headers.get("mcp-protocol-version") == "2025-11-05"
    assert calls[3].headers.get("mcp-session-id") is None
    assert calls[3].headers.get("mcp-protocol-version") == "2025-11-05"
    assert calls[4].headers.get("mcp-session-id") == "fresh-session"
    assert calls[4].headers.get("mcp-protocol-version") == "2025-11-05"
    assert calls[5].headers.get("mcp-session-id") == "fresh-session"
    assert calls[5].headers.get("mcp-protocol-version") == "2025-11-05"


def test_session_404_without_cached_initialize_context_raises_protocol_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404, text="stale session", request=request)

    transport = _transport(handler)
    transport.session_id = "stale-session"

    with pytest.raises(ProxyProtocolError):
        transport.send({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}})

    assert attempts["count"] == 1


def test_retry_on_transient_transport_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("temporary network issue", request=request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 9, "result": {}}, request=request)

    transport = _transport(handler)
    response = transport.send({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}})

    assert response[0]["id"] == 9
    assert attempts["count"] == 2


def test_no_retry_on_auth_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(401, text="unauthorized", request=request)

    transport = _transport(handler)

    with pytest.raises(ProxyAuthError):
        transport.send({"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}})

    assert attempts["count"] == 1


def test_no_retry_on_forbidden_auth_error() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(403, text="forbidden", request=request)

    transport = _transport(handler)

    with pytest.raises(ProxyAuthError):
        transport.send({"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}})

    assert attempts["count"] == 1


def test_sse_payload_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = "\n".join(
            [
                "event: message",
                'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}',
                "",
            ]
        )
        return httpx.Response(
            200,
            text=payload,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    transport = _transport(handler)
    response = transport.send({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})

    assert response == [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}]


def test_sse_multiline_event_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = "\n".join(
            [
                "event: message",
                'data: {"jsonrpc":"2.0",',
                'data: "id":2,"result":{"ok":true}}',
                "",
            ]
        )
        return httpx.Response(
            200,
            text=payload,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    transport = _transport(handler)
    response = transport.send({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})

    assert response == [{"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}]


def test_empty_notification_response_returns_no_messages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204, text="", request=request)

    transport = _transport(handler)
    response = transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    assert response == []


def test_user_project_header_is_set() -> None:
    seen_header = {"value": None}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_header["value"] = request.headers.get("x-goog-user-project")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 3, "result": {"ok": True}},
            request=request,
        )

    transport = _transport(handler)
    _ = transport.send({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})

    assert seen_header["value"] == "sdp-tealbook-dev"
