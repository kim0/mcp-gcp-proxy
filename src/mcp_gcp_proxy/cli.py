from __future__ import annotations

import sys
from collections.abc import Sequence

from .auth import ImpersonatedAccessTokenProvider, ImpersonatedIdTokenProvider
from .config import parse_cloudrun_args, parse_googleapis_args
from .errors import ProxyConfigError
from .proxy import StdioMcpProxy
from .transport import McpHttpTransport


def googleapis_main(argv: Sequence[str] | None = None) -> int:
    try:
        config = parse_googleapis_args(argv)
    except ProxyConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    token_provider = ImpersonatedAccessTokenProvider(
        impersonate_service_account=config.impersonate_service_account,
        scopes=config.scopes,
        quota_project=config.quota_project,
    )
    transport = McpHttpTransport(
        url=config.url,
        token_provider=token_provider,
        timeout_config=config.timeouts,
        retry_config=config.retries,
        user_project=config.project,
        server_instructions=(
            f"The GCP project ID is {config.project}."
            f" Use it in resource paths (e.g. projects/{config.project}/...)."
        ),
    )
    StdioMcpProxy(transport=transport).run()
    return 0


def cloudrun_main(argv: Sequence[str] | None = None) -> int:
    try:
        config = parse_cloudrun_args(argv)
    except ProxyConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    token_provider = ImpersonatedIdTokenProvider(
        impersonate_service_account=config.impersonate_service_account,
        audience=config.audience,
        quota_project=config.quota_project,
    )
    transport = McpHttpTransport(
        url=config.url,
        token_provider=token_provider,
        timeout_config=config.timeouts,
        retry_config=config.retries,
    )
    StdioMcpProxy(transport=transport).run()
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: mcp-proxy <googleapis|cloudrun> [args...]")

    mode = sys.argv[1]
    args = sys.argv[2:]

    if mode == "googleapis":
        return googleapis_main(args)
    if mode == "cloudrun":
        return cloudrun_main(args)

    raise SystemExit(f"Unsupported mode '{mode}'. Expected googleapis|cloudrun")


if __name__ == "__main__":
    raise SystemExit(main())
