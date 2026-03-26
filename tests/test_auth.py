from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp_gcp_proxy.auth import (
    ImpersonatedAccessTokenProvider,
    ImpersonatedIdTokenProvider,
    _CachedToken,
)


class FakeCredentials:
    def __init__(self, token_prefix: str) -> None:
        self._token_prefix = token_prefix
        self.token: str | None = None
        self.expiry: datetime | None = None
        self.refresh_calls = 0

    def refresh(self, _request: Any) -> None:
        self.refresh_calls += 1
        self.token = f"{self._token_prefix}-{self.refresh_calls}"
        self.expiry = datetime.now(UTC) + timedelta(minutes=30)


class FactoryRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_access_provider_caches_until_refresh_window(monkeypatch: Any) -> None:
    source_credentials = object()
    access_credentials = FakeCredentials("access")

    monkeypatch.setattr("google.auth.default", lambda **_: (source_credentials, "sdp-tealbook-dev"))

    recorder = FactoryRecorder()

    def fake_access_factory(**kwargs: Any) -> FakeCredentials:
        recorder.record(**kwargs)
        return access_credentials

    monkeypatch.setattr("google.auth.impersonated_credentials.Credentials", fake_access_factory)

    provider = ImpersonatedAccessTokenProvider(
        impersonate_service_account="mcp-readonly@sdp-tealbook-dev.iam.gserviceaccount.com",
        scopes=("scope-1",),
        quota_project="sdp-tealbook-dev",
    )

    first = provider.get_bearer_token()
    second = provider.get_bearer_token()

    assert first == second
    assert access_credentials.refresh_calls == 1
    assert (
        recorder.calls[0]["target_principal"]
        == "mcp-readonly@sdp-tealbook-dev.iam.gserviceaccount.com"
    )

    provider._cache = _CachedToken(token=first, expiry=datetime.now(UTC) + timedelta(seconds=30))  # type: ignore[attr-defined]
    third = provider.get_bearer_token()

    assert third != first
    assert access_credentials.refresh_calls == 2


def test_access_provider_uses_impersonation_scopes(monkeypatch: Any) -> None:
    source_credentials = object()
    monkeypatch.setattr("google.auth.default", lambda **_: (source_credentials, None))

    recorder = FactoryRecorder()

    def fake_access_factory(**kwargs: Any) -> FakeCredentials:
        recorder.record(**kwargs)
        return FakeCredentials("access")

    monkeypatch.setattr("google.auth.impersonated_credentials.Credentials", fake_access_factory)

    provider = ImpersonatedAccessTokenProvider(
        impersonate_service_account="sa@example.com",
        scopes=("scope-a", "scope-b"),
        quota_project=None,
    )

    _ = provider.get_bearer_token()

    assert recorder.calls[0]["target_principal"] == "sa@example.com"
    assert recorder.calls[0]["target_scopes"] == ["scope-a", "scope-b"]


def test_id_provider_uses_audience(monkeypatch: Any) -> None:
    source_credentials = object()
    monkeypatch.setattr("google.auth.default", lambda **_: (source_credentials, None))

    recorder = FactoryRecorder()

    def fake_access_factory(**kwargs: Any) -> object:
        recorder.record(kind="access", **kwargs)
        return object()

    class FakeIdCredentials(FakeCredentials):
        pass

    id_creds = FakeIdCredentials("id")

    def fake_id_factory(**kwargs: Any) -> FakeIdCredentials:
        recorder.record(kind="id", **kwargs)
        return id_creds

    monkeypatch.setattr("google.auth.impersonated_credentials.Credentials", fake_access_factory)
    monkeypatch.setattr("google.auth.impersonated_credentials.IDTokenCredentials", fake_id_factory)

    provider = ImpersonatedIdTokenProvider(
        impersonate_service_account="sa@example.com",
        audience="https://toolbox.run.app",
        quota_project="sdp-tealbook-dev",
    )

    token = provider.get_bearer_token()

    assert token.startswith("id-")
    id_call = next(call for call in recorder.calls if call["kind"] == "id")
    assert id_call["target_audience"] == "https://toolbox.run.app"
