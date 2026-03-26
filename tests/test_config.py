from __future__ import annotations

import pytest

from mcp_gcp_proxy.config import parse_cloudrun_args, parse_googleapis_args
from mcp_gcp_proxy.errors import ProxyConfigError


def test_cloudrun_placeholder_url_rejected() -> None:
    with pytest.raises(ProxyConfigError):
        parse_cloudrun_args(
            [
                "--url",
                "https://mcp-toolbox-REPLACE_ME-uc.a.run.app/mcp",
                "--impersonate-service-account",
                "mcp-readonly@example.com",
            ]
        )


def test_cloudrun_placeholder_audience_rejected() -> None:
    with pytest.raises(ProxyConfigError):
        parse_cloudrun_args(
            [
                "--url",
                "https://mcp-toolbox-real-uc.a.run.app/mcp",
                "--audience",
                "https://mcp-toolbox-<set-me>.a.run.app",
                "--impersonate-service-account",
                "mcp-readonly@example.com",
            ]
        )


def test_default_retries_are_disabled() -> None:
    config = parse_googleapis_args(
        [
            "--url",
            "https://logging.googleapis.com/mcp",
            "--impersonate-service-account",
            "mcp-readonly@example.com",
            "--project",
            "sdp-tealbook-dev",
        ]
    )
    assert config.retries.max_retries == 0
