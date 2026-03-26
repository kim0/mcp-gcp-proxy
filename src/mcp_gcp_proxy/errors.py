from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ProxyError(Exception):
    code: int
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class ProxyAuthError(ProxyError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=-32010, message=message, details=details)


class ProxyTransportError(ProxyError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=-32011, message=message, details=details)


class ProxyProtocolError(ProxyError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=-32012, message=message, details=details)


class ProxyConfigError(ProxyError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=-32013, message=message, details=details)
