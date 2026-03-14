from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import os

from fastapi import Request
from fastapi.responses import HTMLResponse, Response


_AUTH_REALM = "Nullsec Trader Tool"
_LOCAL_HOST_TOKENS = {"", "localhost", "127.0.0.1", "::1", "testserver", "testclient"}
_PROXY_HINT_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "via")
_SENSITIVE_PREFIXES = ("/character", "/config")


def _host_token(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:].split("]", 1)[0]
    elif raw.count(":") == 1 and raw.split(":", 1)[1].isdigit():
        raw = raw.split(":", 1)[0]
    return raw


def _is_local_host(value: str) -> bool:
    token = _host_token(value)
    if token in _LOCAL_HOST_TOKENS:
        return True
    try:
        return bool(ipaddress.ip_address(token).is_loopback)
    except ValueError:
        return False


def _forwarded_client_host(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for", "") or "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    forwarded_header = str(request.headers.get("forwarded", "") or "").strip()
    if not forwarded_header:
        return ""
    for part in forwarded_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() != "for":
            continue
        return value.strip().strip("\"")
    return ""


def _request_client_host(request: Request) -> str:
    if request.client is None:
        return ""
    return str(request.client.host or "").strip()


def _proxy_headers_present(request: Request) -> bool:
    return any(str(request.headers.get(name, "") or "").strip() for name in _PROXY_HINT_HEADERS)


def resolve_access_settings(cfg: dict | None = None) -> dict:
    raw_cfg = {}
    if isinstance(cfg, dict) and isinstance(cfg.get("webapp", {}), dict):
        raw_cfg = dict(cfg.get("webapp", {}) or {})
    password = str(os.environ.get("NULLSEC_WEBAPP_PASSWORD", "") or raw_cfg.get("access_password", "") or "").strip()
    username = str(os.environ.get("NULLSEC_WEBAPP_USERNAME", "") or raw_cfg.get("access_username", "trader") or "trader").strip()
    if not username:
        username = "trader"
    return {
        "username": username,
        "password": password,
        "password_configured": bool(password),
        "sensitive_prefixes": list(_SENSITIVE_PREFIXES),
    }


def describe_request_access(request: Request, settings: dict | None = None) -> dict:
    settings = dict(settings or {})
    client_host = _request_client_host(request)
    forwarded_host = _forwarded_client_host(request)
    forwarded_request_host = _host_token(str(request.headers.get("x-forwarded-host", "") or ""))
    host_header = _host_token(str(request.headers.get("host", "") or ""))
    proxy_headers = _proxy_headers_present(request)
    direct_local_request = bool(client_host and host_header and _is_local_host(client_host) and _is_local_host(host_header) and not proxy_headers)
    sensitive_path = any(str(request.url.path or "").startswith(prefix) for prefix in list(settings.get("sensitive_prefixes", []) or []))
    return {
        "password_configured": bool(settings.get("password_configured", False)),
        "username": str(settings.get("username", "trader") or "trader"),
        "request_is_local": bool(direct_local_request),
        "remote_access_blocked": bool(not direct_local_request and not settings.get("password_configured", False)),
        "sensitive_path": bool(sensitive_path),
        "proxy_headers_present": bool(proxy_headers),
        "client_host": client_host,
        "forwarded_host": forwarded_host,
        "forwarded_request_host": forwarded_request_host,
        "request_host": host_header,
    }


def _authorization_matches(request: Request, settings: dict) -> bool:
    password = str(settings.get("password", "") or "")
    if not password:
        return False
    header = str(request.headers.get("authorization", "") or "").strip()
    if not header.lower().startswith("basic "):
        return False
    token = header.split(" ", 1)[1].strip()
    try:
        raw = base64.b64decode(token).decode("utf-8")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    username, sep, candidate = raw.partition(":")
    if not sep:
        return False
    expected_user = str(settings.get("username", "trader") or "trader")
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(candidate, password)


def _remote_blocked_response(request: Request) -> HTMLResponse:
    path = str(request.url.path or "/")
    body = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Remote Access Blocked</title></head><body>"
        "<h1>Remote access blocked</h1>"
        "<p>This web app is running without a configured access password.</p>"
        "<p>Without a password, only direct localhost requests are allowed.</p>"
        "<p>Proxy, tunnel, and other non-direct requests to "
        f"<code>{path}</code> are blocked until <code>NULLSEC_WEBAPP_PASSWORD</code> "
        "or <code>webapp.access_password</code> is configured.</p>"
        "<p>Direct localhost access remains available.</p>"
        "</body></html>"
    )
    return HTMLResponse(body, status_code=403)


def _basic_auth_challenge() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": f'Basic realm="{_AUTH_REALM}"'})


def enforce_request_access(request: Request, settings: dict | None = None) -> Response | None:
    settings = dict(settings or {})
    context = describe_request_access(request, settings)
    request.state.web_access = context
    if context["remote_access_blocked"]:
        return _remote_blocked_response(request)
    if not bool(settings.get("password_configured", False)):
        request.state.web_access_authenticated = False
        return None
    authorized = _authorization_matches(request, settings)
    request.state.web_access_authenticated = bool(authorized)
    if authorized:
        return None
    return _basic_auth_challenge()
