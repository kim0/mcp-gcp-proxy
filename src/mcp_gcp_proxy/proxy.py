from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from mcp.types import JSONRPCMessage
from pydantic import ValidationError

from .errors import ProxyError
from .transport import McpHttpTransport

JSONObj = dict[str, Any]


class StdioMcpProxy:
    def __init__(self, transport: McpHttpTransport) -> None:
        self._transport = transport

    def run(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        try:
            for raw_line in stdin:
                line = raw_line.strip()
                if not line:
                    continue
                self._handle_line(line=line, stdout=stdout)
        finally:
            self._transport.close()

    def _handle_line(self, *, line: str, stdout: TextIO) -> None:
        request_id: object | None = None
        is_notification = False
        try:
            incoming = json.loads(line)
            if isinstance(incoming, dict):
                request_id = incoming.get("id")
                is_notification = "id" not in incoming and "method" in incoming

            parsed = JSONRPCMessage.model_validate(incoming)
            message = parsed.model_dump(mode="json", exclude_none=True)
            responses = self._transport.send(message)
            for response in responses:
                validated = JSONRPCMessage.model_validate(response)
                self._emit(validated.model_dump(mode="json", exclude_none=True), stdout)
        except json.JSONDecodeError:
            self._emit_error(
                request_id,
                code=-32700,
                message="Invalid JSON received on stdin",
                stdout=stdout,
            )
        except ValidationError as exc:
            self._emit_error(
                request_id,
                code=-32600,
                message="Invalid JSON-RPC message",
                details={"validation": str(exc)},
                stdout=stdout,
            )
        except ProxyError as exc:
            if is_notification:
                return
            self._emit_error(
                request_id,
                code=exc.code,
                message=exc.message,
                details=exc.details,
                stdout=stdout,
            )
        except Exception as exc:  # pragma: no cover - last-resort guardrail
            if is_notification:
                return
            self._emit_error(
                request_id,
                code=-32099,
                message="Unexpected proxy failure",
                details={"error": str(exc)},
                stdout=stdout,
            )

    def _emit(self, payload: JSONObj, stdout: TextIO) -> None:
        stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        stdout.flush()

    def _emit_error(
        self,
        request_id: object | None,
        *,
        code: int,
        message: str,
        stdout: TextIO,
        details: JSONObj | None = None,
    ) -> None:
        error_payload: JSONObj = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if details:
            error_payload["error"]["data"] = details
        self._emit(error_payload, stdout)
