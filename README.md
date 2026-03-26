# mcp-gcp-proxy

Reusable MCP stdio-to-HTTP proxy library for Google Cloud authentication paths.

## Why this exists

This package keeps Claude MCP access least-privileged while removing the old `gcloud` subprocess dependency.

- Category 1 (Google-managed MCP endpoints): use impersonated OAuth access tokens from a dedicated read-only service account.
- Category 2 (private Cloud Run Toolbox endpoint): use impersonated audience-bound OIDC ID tokens.

## Identity model

- Developer machine identity: local ADC with permission to impersonate `mcp-readonly`.
- Developer-side invoker identity: `mcp-readonly`.
- Toolbox runtime identity: separate `toolbox-runtime` Cloud Run service account.

`mcp-readonly` and `toolbox-runtime` are intentionally separate.

## Package layout

- `src/mcp_gcp_proxy/auth.py`
  - Access-token and ID-token impersonation providers with refresh-before-expiry caching.
- `src/mcp_gcp_proxy/transport.py`
  - HTTP transport with `httpx` + `httpx-retries`, timeout controls, negotiated `MCP-Protocol-Version` headers after initialize, and session re-initialization on HTTP 404.
- `src/mcp_gcp_proxy/proxy.py`
  - stdio JSON-RPC loop and error shaping.
- `src/mcp_gcp_proxy/config.py`
  - CLI config parsing shared by wrappers.
- `src/mcp_gcp_proxy/cli.py`
  - thin entrypoints for Google APIs and Cloud Run modes.

## Running checks

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy
uv run pytest
```

## Integration from `sdp-infra`

`sdp-infra/.mcp.json` uses this sibling package via `uv` without adding Python package files to `sdp-infra`:

```bash
uv run --with ../mcp-gcp-proxy scripts/mcp-googleapis-proxy.py ...
uv run --with ../mcp-gcp-proxy scripts/mcp-cloudrun-proxy.py ...
```

## Security boundaries

- No static service account keys.
- No background localhost daemon.
- No direct user OAuth path that would grant Claude user-level write permissions.
- Optional IAM deny policy remains defense-in-depth for Google-managed MCP tool calls.

## Known limitations

- Cloud Run URL and audience are deployment-specific and must be configured in `.mcp.json`.
- Placeholder values such as `REPLACE_ME` are rejected at CLI parse time for Cloud Run mode.
- Retries are disabled by default (`--max-retries=0`) to avoid accidental replay of non-idempotent tool calls.
- Session-scoped HTTP 404 handling follows Streamable HTTP session semantics: the proxy re-sends cached `initialize`, then cached `notifications/initialized`, before replaying the failed request.
- Toolbox custom tool policy is still the primary data-plane safeguard for sensitive systems.
