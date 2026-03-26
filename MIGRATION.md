# Migration Notes: `mcp-gcp-proxy.py` -> split proxy architecture

## Previous state

- Single script in `sdp-infra/mcp-gcp-proxy.py`.
- Auth depended on `gcloud` subprocess calls.
- Only access-token flow for Google-managed MCP endpoints.

## New state

- Reusable sibling package: `../mcp-gcp-proxy`.
- Two thin wrappers in `sdp-infra/scripts/`:
  - `mcp-googleapis-proxy.py`
  - `mcp-cloudrun-proxy.py`
- `.mcp.json` now invokes wrappers with:
  - `uv run --with ../mcp-gcp-proxy ...`
- Toolbox Cloud Run example config lives in `sdp-infra/.mcp.toolbox.example.json` to avoid shipping a broken placeholder in active config.

## Behavior changes

- Access tokens and ID tokens are minted with `google-auth` impersonation libraries.
- Retry/timeouts are standardized via `httpx` + `httpx-retries`.
- After initialize succeeds, subsequent HTTP requests include the negotiated `MCP-Protocol-Version` header.
- If an active MCP session returns HTTP 404, the proxy starts a fresh session by replaying cached `initialize` and `notifications/initialized` before replaying the failed request.
- JSON-RPC errors are shaped consistently without dumping stack traces.

## Rollout checklist

1. Ensure local ADC is configured and has `roles/iam.serviceAccountTokenCreator` on `mcp-readonly`.
2. Ensure Terraform has applied MCP resources (`mcp-readonly`, `toolbox-runtime`, Cloud Run service, invoker IAM).
3. Replace placeholder Toolbox URL/audience values in `sdp-infra/.mcp.json`.
   - The Cloud Run proxy now fails fast if placeholder markers (e.g. `REPLACE_ME`, `<...>`) are still present.
4. Run quick smoke checks:
   - `uv run --with ../mcp-gcp-proxy scripts/mcp-googleapis-proxy.py --help`
   - `uv run --with ../mcp-gcp-proxy scripts/mcp-cloudrun-proxy.py --help`
