from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from .errors import ProxyConfigError

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    connect_seconds: float = 10.0
    read_seconds: float = 60.0
    write_seconds: float = 30.0
    pool_seconds: float = 10.0


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_retries: int = 0
    backoff_factor: float = 0.5


@dataclass(frozen=True, slots=True)
class CommonProxyConfig:
    url: str
    impersonate_service_account: str
    quota_project: str | None
    timeouts: TimeoutConfig
    retries: RetryConfig


@dataclass(frozen=True, slots=True)
class GoogleApisProxyConfig(CommonProxyConfig):
    project: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CloudRunProxyConfig(CommonProxyConfig):
    audience: str


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", required=True, help="MCP HTTP endpoint URL")
    parser.add_argument(
        "--impersonate-service-account",
        required=True,
        help="Service account email to impersonate",
    )
    parser.add_argument(
        "--quota-project",
        default=None,
        help="Optional quota project for impersonated credential calls",
    )
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=60.0)
    parser.add_argument("--write-timeout", type=float, default=30.0)
    parser.add_argument("--pool-timeout", type=float, default=10.0)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--backoff-factor", type=float, default=0.5)


def _timeouts_from_namespace(args: argparse.Namespace) -> TimeoutConfig:
    return TimeoutConfig(
        connect_seconds=args.connect_timeout,
        read_seconds=args.read_timeout,
        write_seconds=args.write_timeout,
        pool_seconds=args.pool_timeout,
    )


def _retries_from_namespace(args: argparse.Namespace) -> RetryConfig:
    if args.max_retries < 0:
        raise ProxyConfigError("--max-retries must be >= 0")
    if args.backoff_factor < 0:
        raise ProxyConfigError("--backoff-factor must be >= 0")
    return RetryConfig(max_retries=args.max_retries, backoff_factor=args.backoff_factor)


def _validate_cloudrun_endpoint(url: str, audience: str) -> None:
    placeholder_markers = ("REPLACE_ME", "<", ">")
    if any(marker in url for marker in placeholder_markers):
        raise ProxyConfigError(
            "Cloud Run URL contains placeholder text. Set --url to a real service URL."
        )
    if any(marker in audience for marker in placeholder_markers):
        raise ProxyConfigError(
            "Cloud Run audience contains placeholder text. Set --audience to a real value."
        )


def parse_googleapis_args(argv: Sequence[str] | None = None) -> GoogleApisProxyConfig:
    parser = argparse.ArgumentParser(description="Proxy stdio MCP to Google-managed MCP endpoint")
    _add_common_args(parser)
    parser.add_argument("--project", required=True, help="GCP project for x-goog-user-project")
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="OAuth scope to request (repeatable). Defaults to cloud-platform.",
    )
    args = parser.parse_args(argv)

    scopes = tuple(args.scope) if args.scope else (CLOUD_PLATFORM_SCOPE,)
    return GoogleApisProxyConfig(
        url=args.url,
        impersonate_service_account=args.impersonate_service_account,
        project=args.project,
        scopes=scopes,
        quota_project=args.quota_project,
        timeouts=_timeouts_from_namespace(args),
        retries=_retries_from_namespace(args),
    )


def parse_cloudrun_args(argv: Sequence[str] | None = None) -> CloudRunProxyConfig:
    parser = argparse.ArgumentParser(
        description="Proxy stdio MCP to private Cloud Run MCP endpoint"
    )
    _add_common_args(parser)
    parser.add_argument(
        "--audience",
        default=None,
        help="OIDC token audience. Defaults to --url value.",
    )
    args = parser.parse_args(argv)

    audience = args.audience or args.url
    _validate_cloudrun_endpoint(url=args.url, audience=audience)
    return CloudRunProxyConfig(
        url=args.url,
        impersonate_service_account=args.impersonate_service_account,
        audience=audience,
        quota_project=args.quota_project,
        timeouts=_timeouts_from_namespace(args),
        retries=_retries_from_namespace(args),
    )
