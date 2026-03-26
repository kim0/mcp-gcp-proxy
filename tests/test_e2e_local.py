from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_gcp_proxy.config import RetryConfig, TimeoutConfig
from mcp_gcp_proxy.proxy import StdioMcpProxy
from mcp_gcp_proxy.transport import McpHttpTransport


class _TokenProvider:
    def get_bearer_token(self) -> str:
        return "test-token"


class _Handler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        _ = json.loads(body.decode("utf-8"))

        _Handler.calls += 1

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if _Handler.calls == 1:
            self.send_header("mcp-session-id", "session-a")
        self.end_headers()
        response = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_stdio_to_local_http_roundtrip() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{server.server_port}/mcp"
        transport = McpHttpTransport(
            url=url,
            token_provider=_TokenProvider(),
            timeout_config=TimeoutConfig(
                connect_seconds=1,
                read_seconds=2,
                write_seconds=2,
                pool_seconds=1,
            ),
            retry_config=RetryConfig(max_retries=0, backoff_factor=0.0),
        )
        proxy = StdioMcpProxy(transport)

        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}) + "\n"
        )
        stdout = io.StringIO()

        proxy.run(stdin=stdin, stdout=stdout)

        payload = json.loads(stdout.getvalue().strip())
        assert payload["result"]["ok"] is True
        assert transport.session_id == "session-a"
    finally:
        server.shutdown()
        server.server_close()
