from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from config_loader import load_json, save_json
from local_cache import cached_payload, is_cache_fresh, load_cache_record, save_cache_record
from runtime_common import b64url, make_basic_auth


DEFAULT_SSO_METADATA_URL = "https://login.eveonline.com/.well-known/oauth-authorization-server"
DEFAULT_AUTHORIZATION_ENDPOINT = "https://login.eveonline.com/v2/oauth/authorize"
DEFAULT_TOKEN_ENDPOINT = "https://login.eveonline.com/v2/oauth/token"


class SSOAuthError(RuntimeError):
    pass


def normalize_scopes(value) -> list[str]:
    if isinstance(value, str):
        raw = str(value).strip().split()
    elif isinstance(value, (list, tuple, set)):
        raw = [str(v).strip() for v in value]
    else:
        raw = []
    seen = set()
    out: list[str] = []
    for item in raw:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def decode_access_token_claims(access_token: str) -> dict:
    token = str(access_token or "").strip()
    if token.count(".") < 2:
        return {}
    payload = token.split(".")[1]
    pad = "=" * (-len(payload) % 4)
    try:
        raw = json.loads(b64url_decode(payload + pad).decode("utf-8"))
    except Exception:
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def b64url_decode(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value.encode("utf-8"))


def token_identity_from_claims(claims: dict) -> dict:
    sub = str(claims.get("sub", "") or "").strip()
    character_id = 0
    if sub:
        parts = sub.split(":")
        if len(parts) >= 3 and parts[0] == "CHARACTER" and parts[1] == "EVE":
            try:
                character_id = int(parts[2])
            except Exception:
                character_id = 0
    return {
        "character_id": int(character_id),
        "character_name": str(claims.get("name", "") or "").strip(),
        "scopes": normalize_scopes(claims.get("scp", [])),
        "issuer": str(claims.get("iss", "") or "").strip(),
        "subject": sub,
    }


@dataclass
class CallbackState:
    expected_path: str
    expected_state: str
    code: str | None = None
    error: str | None = None


class OAuthHandler(BaseHTTPRequestHandler):
    state_obj: CallbackState | None = None

    def do_GET(self):
        state = OAuthHandler.state_obj
        parsed = urlparse(self.path)
        if state is None or parsed.path != state.expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        q = parse_qs(parsed.query)
        returned_state = str(q.get("state", [""])[0] or "")
        if returned_state and returned_state != state.expected_state:
            state.error = "state_mismatch"
        if "error" in q:
            state.error = str(q.get("error", ["unknown"])[0] or "unknown")
        if "code" in q:
            state.code = str(q.get("code", [None])[0] or "")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Login ok</h2><p>Du kannst dieses Fenster schliessen.</p></body></html>"
        )

    def log_message(self, format, *args):
        return


class EveSSOAuth:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str = "",
        callback_url: str,
        user_agent: str,
        token_path: str,
        metadata_path: str,
        metadata_url: str = DEFAULT_SSO_METADATA_URL,
        session: requests.Session | None = None,
        browser_opener=webbrowser.open,
    ):
        self.client_id = str(client_id or "").strip()
        self.client_secret = str(client_secret or "").strip()
        self.callback_url = str(callback_url or "").strip()
        self.user_agent = str(user_agent or "NullsecTrader/1.0").strip()
        self.token_path = str(token_path)
        self.metadata_path = str(metadata_path)
        self.metadata_url = str(metadata_url or DEFAULT_SSO_METADATA_URL).strip()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.browser_opener = browser_opener
        self._metadata_lock = threading.Lock()

    def load_token(self) -> dict:
        token = load_json(self.token_path, {})
        return dict(token) if isinstance(token, dict) else {}

    def save_token(self, token: dict) -> dict:
        record = dict(token or {})
        save_json(self.token_path, record)
        return record

    def load_metadata(self, *, force_refresh: bool = False) -> dict:
        with self._metadata_lock:
            cached = load_cache_record(self.metadata_path)
            if not force_refresh and is_cache_fresh(cached, 24 * 3600):
                payload = cached_payload(cached, {})
                if isinstance(payload, dict) and payload:
                    return dict(payload)

            metadata = {
                "authorization_endpoint": DEFAULT_AUTHORIZATION_ENDPOINT,
                "token_endpoint": DEFAULT_TOKEN_ENDPOINT,
            }
            try:
                response = self.session.get(self.metadata_url, timeout=20)
                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict):
                        metadata.update(payload)
            except Exception:
                pass
            save_cache_record(self.metadata_path, metadata, source="live")
            return metadata

    def token_claims(self, token: dict | None = None) -> dict:
        token_obj = dict(token or self.load_token())
        access_token = str(token_obj.get("access_token", "") or "").strip()
        if not access_token:
            return {}
        return decode_access_token_claims(access_token)

    def token_identity(self, token: dict | None = None) -> dict:
        return token_identity_from_claims(self.token_claims(token))

    def token_scopes(self, token: dict | None = None) -> list[str]:
        token_obj = dict(token or self.load_token())
        claims = self.token_claims(token_obj)
        scopes = normalize_scopes(claims.get("scp", []))
        if scopes:
            return scopes
        return normalize_scopes(token_obj.get("requested_scopes", []))

    def token_expires_at(self, token: dict | None = None) -> int:
        token_obj = dict(token or self.load_token())
        try:
            created_at = int(token_obj.get("created_at", 0) or 0)
            expires_in = int(token_obj.get("expires_in", 0) or 0)
        except Exception:
            return 0
        return int(created_at + max(0, expires_in))

    def token_valid(self, token: dict | None = None, *, slack_sec: int = 60) -> bool:
        expires_at = self.token_expires_at(token)
        return bool(expires_at > int(time.time()) + int(max(0, slack_sec)))

    def has_scopes(self, requested_scopes, token: dict | None = None) -> bool:
        required = set(normalize_scopes(requested_scopes))
        granted = set(self.token_scopes(token))
        return required.issubset(granted)

    def describe_token_status(self) -> dict:
        token = self.load_token()
        identity = self.token_identity(token)
        return {
            "has_token": bool(token.get("access_token")),
            "valid": self.token_valid(token),
            "expires_at": int(self.token_expires_at(token) or 0),
            "scopes": self.token_scopes(token),
            **identity,
            "token_path": self.token_path,
        }

    def ensure_token(self, requested_scopes, *, allow_login: bool = True) -> dict:
        if not self.client_id:
            raise SSOAuthError("ESI client_id fehlt fuer EVE SSO.")
        required = normalize_scopes(requested_scopes)
        token = self.load_token()

        if token and self.token_valid(token) and self.has_scopes(required, token):
            return token

        if token and str(token.get("refresh_token", "")).strip():
            try:
                token = self.refresh_token(token)
            except SSOAuthError:
                token = {}
            if token and self.token_valid(token) and self.has_scopes(required, token):
                return token

        if not allow_login:
            raise SSOAuthError("Kein gueltiger EVE SSO Token mit den benoetigten Scopes verfuegbar.")
        return self.oauth_authorize(required)

    def oauth_authorize(self, requested_scopes) -> dict:
        metadata = self.load_metadata()
        auth_endpoint = str(metadata.get("authorization_endpoint", DEFAULT_AUTHORIZATION_ENDPOINT) or DEFAULT_AUTHORIZATION_ENDPOINT)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = b64url(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        state_value = secrets.token_urlsafe(24)

        parsed = urlparse(self.callback_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 12563
        path = parsed.path or "/callback"

        state = CallbackState(expected_path=path, expected_state=state_value)
        OAuthHandler.state_obj = state
        server = HTTPServer((host, port), OAuthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        params = {
            "response_type": "code",
            "redirect_uri": self.callback_url,
            "client_id": self.client_id,
            "scope": " ".join(normalize_scopes(requested_scopes)),
            "state": state_value,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        url = auth_endpoint.rstrip("/") + "?" + urlencode(params)
        self.browser_opener(url)

        t0 = time.time()
        try:
            while time.time() - t0 < 180:
                if state.error:
                    raise SSOAuthError(f"EVE SSO Fehler: {state.error}")
                if state.code:
                    return self.exchange_code_for_token(state.code, code_verifier, requested_scopes)
                time.sleep(0.2)
        finally:
            try:
                server.shutdown()
            except Exception:
                pass
        raise SSOAuthError("EVE SSO Login Timeout. Bitte erneut starten.")

    def exchange_code_for_token(self, code: str, code_verifier: str, requested_scopes) -> dict:
        metadata = self.load_metadata()
        token_endpoint = str(metadata.get("token_endpoint", DEFAULT_TOKEN_ENDPOINT) or DEFAULT_TOKEN_ENDPOINT)
        headers = {"User-Agent": self.user_agent}
        data = {
            "grant_type": "authorization_code",
            "code": str(code or "").strip(),
            "redirect_uri": self.callback_url,
            "code_verifier": str(code_verifier or "").strip(),
        }
        if self.client_secret:
            headers["Authorization"] = make_basic_auth(self.client_id, self.client_secret)
        else:
            data["client_id"] = self.client_id
        response = self.session.post(token_endpoint, headers=headers, data=data, timeout=30)
        if response.status_code != 200:
            raise SSOAuthError(f"Token exchange fehlgeschlagen: HTTP {response.status_code} {response.text}")
        token = response.json()
        if not isinstance(token, dict):
            raise SSOAuthError("Token exchange lieferte keine gueltige JSON-Antwort.")
        token["created_at"] = int(time.time())
        token["requested_scopes"] = normalize_scopes(requested_scopes)
        if "refresh_token" not in token and self.load_token().get("refresh_token"):
            token["refresh_token"] = self.load_token()["refresh_token"]
        return self.save_token(token)

    def refresh_token(self, token: dict | None = None) -> dict:
        current = dict(token or self.load_token())
        refresh = str(current.get("refresh_token", "") or "").strip()
        if not refresh:
            raise SSOAuthError("Kein refresh_token verfuegbar.")
        metadata = self.load_metadata()
        token_endpoint = str(metadata.get("token_endpoint", DEFAULT_TOKEN_ENDPOINT) or DEFAULT_TOKEN_ENDPOINT)
        headers = {"User-Agent": self.user_agent}
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        }
        if self.client_secret:
            headers["Authorization"] = make_basic_auth(self.client_id, self.client_secret)
        else:
            data["client_id"] = self.client_id
        response = self.session.post(token_endpoint, headers=headers, data=data, timeout=30)
        if response.status_code != 200:
            raise SSOAuthError(f"Token refresh fehlgeschlagen: HTTP {response.status_code} {response.text}")
        new_token = response.json()
        if not isinstance(new_token, dict):
            raise SSOAuthError("Token refresh lieferte keine gueltige JSON-Antwort.")
        new_token["created_at"] = int(time.time())
        if "refresh_token" not in new_token:
            new_token["refresh_token"] = refresh
        new_token["requested_scopes"] = normalize_scopes(
            new_token.get("requested_scopes", current.get("requested_scopes", self.token_scopes(current)))
        )
        return self.save_token(new_token)


__all__ = [
    "CallbackState",
    "DEFAULT_AUTHORIZATION_ENDPOINT",
    "DEFAULT_SSO_METADATA_URL",
    "DEFAULT_TOKEN_ENDPOINT",
    "EveSSOAuth",
    "OAuthHandler",
    "SSOAuthError",
    "decode_access_token_claims",
    "normalize_scopes",
    "token_identity_from_claims",
]
