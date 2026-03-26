from __future__ import annotations

import io
import json

from mcp_gcp_proxy.errors import ProxyAuthError
from mcp_gcp_proxy.proxy import StdioMcpProxy


class FakeTransport:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def send(self, _message: dict[str, object]) -> list[dict[str, object]]:
        self.calls += 1
        if self.calls == 1:
            return [{"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}]
        raise ProxyAuthError("auth failure")

    def close(self) -> None:
        self.closed = True


def test_stdio_proxy_success_then_error() -> None:
    transport = FakeTransport()
    proxy = StdioMcpProxy(transport=transport)  # type: ignore[arg-type]

    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()

    proxy.run(stdin=stdin, stdout=stdout)

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["id"] == 1
    assert lines[0]["result"]["ok"] is True
    assert lines[1]["id"] == 2
    assert lines[1]["error"]["code"] == -32010
    assert transport.closed is True


def test_invalid_json_returns_parse_error() -> None:
    transport = FakeTransport()
    proxy = StdioMcpProxy(transport=transport)  # type: ignore[arg-type]
    stdin = io.StringIO("{bad json}\n")
    stdout = io.StringIO()

    proxy.run(stdin=stdin, stdout=stdout)

    payload = json.loads(stdout.getvalue().strip())
    assert payload["error"]["code"] == -32700


def test_notification_with_no_response_stays_silent() -> None:
    class NotificationTransport:
        def close(self) -> None:
            return

        def send(self, _message: dict[str, object]) -> list[dict[str, object]]:
            return []

    proxy = StdioMcpProxy(transport=NotificationTransport())  # type: ignore[arg-type]
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    )
    stdout = io.StringIO()

    proxy.run(stdin=stdin, stdout=stdout)

    assert stdout.getvalue() == ""


def test_notification_transport_error_stays_silent() -> None:
    class NotificationErrorTransport:
        def close(self) -> None:
            return

        def send(self, _message: dict[str, object]) -> list[dict[str, object]]:
            raise ProxyAuthError("auth failure")

    proxy = StdioMcpProxy(transport=NotificationErrorTransport())  # type: ignore[arg-type]
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    )
    stdout = io.StringIO()

    proxy.run(stdin=stdin, stdout=stdout)

    assert stdout.getvalue() == ""
