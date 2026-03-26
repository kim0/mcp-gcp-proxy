from __future__ import annotations

from mcp_gcp_proxy.cli import cloudrun_main


def test_cloudrun_main_returns_config_error_code_for_placeholder_url() -> None:
    exit_code = cloudrun_main(
        [
            "--url",
            "https://mcp-toolbox-REPLACE_ME-uc.a.run.app/mcp",
            "--impersonate-service-account",
            "mcp-readonly@example.com",
        ]
    )

    assert exit_code == 2
