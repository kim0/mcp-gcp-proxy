from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol

import google.auth
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request

from .errors import ProxyAuthError


class TokenProvider(Protocol):
    def get_bearer_token(self) -> str: ...


class RefreshableCredentials(Protocol):
    token: str | None
    expiry: datetime | None

    def refresh(self, request: Request) -> None: ...


@dataclass(slots=True)
class _CachedToken:
    token: str
    expiry: datetime | None


class _BaseGoogleTokenProvider:
    def __init__(
        self,
        *,
        impersonate_service_account: str,
        quota_project: str | None,
        refresh_skew_seconds: int = 300,
    ) -> None:
        self._impersonate_service_account = impersonate_service_account
        self._quota_project = quota_project
        self._refresh_skew = timedelta(seconds=refresh_skew_seconds)
        self._request = Request()
        self._cache: _CachedToken | None = None
        self._lock = Lock()

    def _is_cache_valid(self) -> bool:
        if self._cache is None:
            return False
        if self._cache.expiry is None:
            return True
        now = datetime.now(UTC)
        expiry = self._cache.expiry
        # Google auth returns naive (IDTokenCredentials) or aware
        # (Credentials) expiry depending on credential type. Normalize
        # naive values to aware UTC so the comparison always works.
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry > now + self._refresh_skew

    def get_bearer_token(self) -> str:
        with self._lock:
            cached = self._cache
            if cached is not None and self._is_cache_valid():
                return cached.token

            credentials = self._build_credentials()
            try:
                credentials.refresh(self._request)
            except GoogleAuthError as exc:
                raise ProxyAuthError("Failed to refresh impersonated credentials") from exc

            token = credentials.token
            if not token:
                raise ProxyAuthError("Impersonated credentials returned an empty token")

            expiry = credentials.expiry
            self._cache = _CachedToken(token=token, expiry=expiry)
            return token

    def _default_credentials(self) -> Credentials:
        try:
            source_credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
                quota_project_id=self._quota_project,
            )
            return source_credentials
        except GoogleAuthError as exc:
            raise ProxyAuthError("Failed to load application default credentials") from exc

    def _build_credentials(self) -> RefreshableCredentials:
        raise NotImplementedError


class ImpersonatedAccessTokenProvider(_BaseGoogleTokenProvider):
    def __init__(
        self,
        *,
        impersonate_service_account: str,
        scopes: tuple[str, ...],
        quota_project: str | None,
        refresh_skew_seconds: int = 300,
    ) -> None:
        super().__init__(
            impersonate_service_account=impersonate_service_account,
            quota_project=quota_project,
            refresh_skew_seconds=refresh_skew_seconds,
        )
        self._scopes = scopes

    def _build_credentials(self) -> RefreshableCredentials:
        source_credentials = self._default_credentials()
        return impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
            source_credentials=source_credentials,
            target_principal=self._impersonate_service_account,
            target_scopes=list(self._scopes),
            lifetime=3600,
            quota_project_id=self._quota_project,
        )


class ImpersonatedIdTokenProvider(_BaseGoogleTokenProvider):
    def __init__(
        self,
        *,
        impersonate_service_account: str,
        audience: str,
        quota_project: str | None,
        refresh_skew_seconds: int = 300,
    ) -> None:
        super().__init__(
            impersonate_service_account=impersonate_service_account,
            quota_project=quota_project,
            refresh_skew_seconds=refresh_skew_seconds,
        )
        self._audience = audience

    def _build_credentials(self) -> RefreshableCredentials:
        source_credentials = self._default_credentials()
        access_credentials = impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
            source_credentials=source_credentials,
            target_principal=self._impersonate_service_account,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=3600,
            quota_project_id=self._quota_project,
        )
        return impersonated_credentials.IDTokenCredentials(  # type: ignore[no-untyped-call]
            target_credentials=access_credentials,
            target_audience=self._audience,
            include_email=True,
            quota_project_id=self._quota_project,
        )
