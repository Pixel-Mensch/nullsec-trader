from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from config_loader import load_json, save_json
from runtime_common import CACHE_DIR, HTTP_CACHE_PATH, TOKEN_PATH, TYPE_CACHE_PATH, die, make_basic_auth


class CallbackState:
    def __init__(self):
        self.code = None
        self.error = None


class CachedResponse:
    def __init__(self, status_code: int, payload, headers: dict | None = None):
        self.status_code = int(status_code)
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
        self.content = self.text.encode("utf-8")
        self.ok = 200 <= self.status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class OAuthHandler(BaseHTTPRequestHandler):
    state_obj: CallbackState = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        q = parse_qs(parsed.query)
        if "error" in q:
            OAuthHandler.state_obj.error = q.get("error", ["unknown"])[0]
        if "code" in q:
            OAuthHandler.state_obj.code = q.get("code", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Login ok</h2><p>Du kannst dieses Fenster schliessen.</p></body></html>"
        )

    def log_message(self, format, *args):
        return


class ESIClient:
    def __init__(self, cfg: dict):
        self.base_url = cfg["esi"]["base_url"].rstrip("/")
        self.user_agent = cfg["esi"]["user_agent"]
        self.client_id = cfg["esi"]["client_id"]
        self.client_secret = cfg["esi"]["client_secret"]
        self.callback_url = cfg["esi"]["callback_url"]
        self.scope = cfg["esi"]["scope"]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.diagnostics_enabled = bool(cfg.get("diagnostics", {}).get("network_verbose", True))
        self.request_min_interval_sec = float(cfg.get("esi", {}).get("request_min_interval_sec", 0.35))
        self.rate_limit_cooldown_sec = float(cfg.get("esi", {}).get("rate_limit_cooldown_sec", 0.0))
        self.error_limit_backoff_sec = float(cfg.get("esi", {}).get("error_limit_backoff_sec", 2.0))
        self.http_cache_default_ttl_sec = int(cfg.get("esi", {}).get("cache_default_ttl_sec", 60))
        self.request_log_limit = int(cfg.get("esi", {}).get("request_log_limit", 2000))
        self._request_pacing_lock = threading.Lock()
        self._next_request_at = 0.0

        self.token = load_json(TOKEN_PATH, {})
        self.type_cache = load_json(TYPE_CACHE_PATH, {})
        self.structure_region_map: dict[int, int] = {}
        self._http_cache = load_json(HTTP_CACHE_PATH, {})
        if not isinstance(self._http_cache, dict):
            self._http_cache = {}
        legacy_http_cache = self.type_cache.get("_http_cache", {})
        if not self._http_cache and isinstance(legacy_http_cache, dict):
            self._http_cache = dict(legacy_http_cache)
        if "_http_cache" in self.type_cache:
            try:
                del self.type_cache["_http_cache"]
            except Exception:
                pass
        self.request_log = []
        self._type_cache_dirty = 0
        self._perf_stats = {
            "history_requests_total": 0,
            "history_http_404": 0,
            "history_cache_hits": 0,
            "history_raw_cache_hits": 0,
            "history_negative_cache_hits": 0,
            "history_skipped_negative": 0,
            "history_served_from_cache": 0,
            "type_name_cache_hits": 0,
            "type_name_network_fetches": 0,
            "type_volume_cache_hits": 0,
            "type_volume_network_fetches": 0,
        }

    def diag(self, msg: str) -> None:
        if self.diagnostics_enabled:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            print(f"[DIAG {ts}] {msg}", flush=True)

    def _pace_before_request(self, label: str) -> None:
        now = time.time()
        sleep_for = 0.0
        with self._request_pacing_lock:
            if self._next_request_at > now:
                sleep_for = self._next_request_at - now
            scheduled = max(now, self._next_request_at) + self.request_min_interval_sec
            self._next_request_at = scheduled
        if sleep_for > 0:
            self.diag(f"{label}: pacing sleep {sleep_for:.2f}s")
            time.sleep(sleep_for)

    def _set_global_cooldown(self, seconds: float, label: str) -> None:
        if seconds <= 0:
            return
        with self._request_pacing_lock:
            new_next = time.time() + seconds
            if new_next > self._next_request_at:
                self._next_request_at = new_next
        self.diag(f"{label}: global cooldown set to {seconds:.2f}s")

    def save_caches(self):
        save_json(TOKEN_PATH, self.token)
        save_json(TYPE_CACHE_PATH, self.type_cache)
        save_json(HTTP_CACHE_PATH, self._http_cache)
        self._type_cache_dirty = 0

    def _mark_type_cache_dirty(self, delta: int = 1, flush_threshold: int = 200) -> None:
        self._type_cache_dirty += max(0, int(delta))
        if self._type_cache_dirty >= max(1, int(flush_threshold)):
            save_json(TYPE_CACHE_PATH, self.type_cache)
            save_json(HTTP_CACHE_PATH, self._http_cache)
            self._type_cache_dirty = 0

    def oauth_authorize(self) -> None:
        self.diag("oauth_authorize gestartet")
        print("OAuth Login startet. Browser wird geoeffnet.")
        cb = urlparse(self.callback_url)
        host = cb.hostname or "localhost"
        port = cb.port or 12563

        state = CallbackState()
        OAuthHandler.state_obj = state
        server = HTTPServer((host, port), OAuthHandler)

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        params = {
            "response_type": "code",
            "redirect_uri": self.callback_url,
            "client_id": self.client_id,
            "scope": self.scope,
            "state": "nullsectrader",
        }
        url = "https://login.eveonline.com/v2/oauth/authorize/?" + urlencode(params)
        webbrowser.open(url)

        t0 = time.time()
        while time.time() - t0 < 180:
            if state.error:
                server.shutdown()
                die(f"OAuth Fehler: {state.error}")
            if state.code:
                code = state.code
                server.shutdown()
                self.exchange_code_for_token(code)
                return
            time.sleep(0.2)

        server.shutdown()
        self.diag("oauth_authorize timeout nach 180s")
        die("OAuth Timeout. Bitte erneut starten.")

    def exchange_code_for_token(self, code: str) -> None:
        self.diag("exchange_code_for_token gestartet")
        auth = make_basic_auth(self.client_id, self.client_secret)
        headers = {"Authorization": auth, "User-Agent": self.user_agent}
        data = {"grant_type": "authorization_code", "code": code}
        r = requests.post("https://login.eveonline.com/v2/oauth/token", headers=headers, data=data, timeout=30)
        if r.status_code != 200:
            self.diag(f"exchange_code_for_token fehlgeschlagen: HTTP {r.status_code}")
            die(f"Token Exchange fehlgeschlagen: {r.status_code} {r.text}")
        self.token = r.json()
        self.token["created_at"] = int(time.time())
        self.save_caches()
        self.diag("exchange_code_for_token erfolgreich")
        print("Token gespeichert.")

    def refresh_token_if_needed(self) -> None:
        self.diag("refresh_token_if_needed gestartet")
        if not self.token or "access_token" not in self.token:
            self.diag("kein access_token vorhanden -> oauth_authorize")
            self.oauth_authorize()
            return

        expires_in = int(self.token.get("expires_in", 0))
        created_at = int(self.token.get("created_at", 0))
        if int(time.time()) < created_at + max(expires_in - 60, 0):
            self.diag("token noch gueltig, kein refresh noetig")
            return

        refresh = self.token.get("refresh_token")
        if not refresh:
            self.diag("kein refresh_token vorhanden -> oauth_authorize")
            self.oauth_authorize()
            return

        age = int(time.time()) - created_at
        self.diag(f"token abgelaufen/nahe ablauf (age={age}s, expires_in={expires_in}s), starte refresh")
        auth = make_basic_auth(self.client_id, self.client_secret)
        headers = {"Authorization": auth, "User-Agent": self.user_agent}
        data = {"grant_type": "refresh_token", "refresh_token": refresh}
        r = requests.post("https://login.eveonline.com/v2/oauth/token", headers=headers, data=data, timeout=30)
        if r.status_code != 200:
            self.diag(f"token refresh fehlgeschlagen: HTTP {r.status_code}")
            print("Refresh fehlgeschlagen. Neue Autorisierung.")
            self.oauth_authorize()
            return
        newt = r.json()
        newt["created_at"] = int(time.time())
        if "refresh_token" not in newt:
            newt["refresh_token"] = refresh
        self.token = newt
        self.save_caches()
        self.diag("token refresh erfolgreich")
        print("Token refresh ok.")

    def _params_hash(self, params: dict | None) -> str:
        base = params if isinstance(params, dict) else {}
        raw = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _request_cache_key(self, path: str, params: dict | None, auth: bool) -> str:
        return f"GET|{path}|auth={1 if auth else 0}|p={self._params_hash(params)}"

    def _parse_expires_header(self, value: str | None) -> int:
        if not value:
            return int(time.time()) + int(self.http_cache_default_ttl_sec)
        try:
            dt = parsedate_to_datetime(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return int(time.time()) + int(self.http_cache_default_ttl_sec)

    def _build_cached_response(self, entry: dict) -> CachedResponse:
        headers = dict(entry.get("headers", {})) if isinstance(entry, dict) else {}
        headers["X-NullsecTrader-Cache"] = "HIT"
        return CachedResponse(200, entry.get("payload", []), headers=headers)

    def _record_request_log(
        self,
        endpoint: str,
        params: dict | None,
        status: int,
        latency_sec: float,
        expires_at: int | None,
        etag: str | None,
        ratelimit_remaining: str | None,
        retry_after: str | None,
        error_limit_remaining: str | None,
    ) -> None:
        self.request_log.append(
            {
                "ts": int(time.time()),
                "endpoint": str(endpoint),
                "params_hash": self._params_hash(params),
                "status": int(status),
                "latency_ms": int(max(0.0, float(latency_sec)) * 1000),
                "expires": int(expires_at) if expires_at is not None else None,
                "etag": str(etag) if etag else "",
                "x_ratelimit_remaining": str(ratelimit_remaining) if ratelimit_remaining is not None else "",
                "retry_after": str(retry_after) if retry_after is not None else "",
                "x_esi_error_limit_remaining": str(error_limit_remaining) if error_limit_remaining is not None else "",
            }
        )
        if len(self.request_log) > max(50, int(self.request_log_limit)):
            self.request_log = self.request_log[-int(self.request_log_limit) :]

    def _dynamic_throttle_from_headers(self, path: str, headers: dict) -> None:
        retry_after_raw = headers.get("Retry-After")
        if retry_after_raw:
            try:
                wait = max(0.0, float(retry_after_raw))
                if wait > 0:
                    self._set_global_cooldown(wait, f"GET {path} retry_after")
                    time.sleep(wait)
                    return
            except Exception:
                pass

        ratelimit_remaining_raw = headers.get("X-Ratelimit-Remaining")
        if ratelimit_remaining_raw is not None:
            try:
                remaining = int(float(ratelimit_remaining_raw))
                if remaining <= 2:
                    wait = max(self.request_min_interval_sec * 2.0, 1.5)
                    self._set_global_cooldown(wait, f"GET {path} low_rate_remaining")
                    time.sleep(wait)
            except Exception:
                pass

        error_limit_remaining_raw = headers.get("X-Esi-Error-Limit-Remain")
        error_limit_reset_raw = headers.get("X-Esi-Error-Limit-Reset")
        if error_limit_remaining_raw is not None:
            try:
                remain = int(float(error_limit_remaining_raw))
                if remain <= 5:
                    reset_wait = 0.0
                    try:
                        reset_wait = max(0.0, float(error_limit_reset_raw or 0.0))
                    except Exception:
                        reset_wait = 0.0
                    wait = max(self.error_limit_backoff_sec, reset_wait)
                    self._set_global_cooldown(wait, f"GET {path} low_error_limit")
                    time.sleep(wait)
            except Exception:
                pass

    def esi_get(
        self,
        path: str,
        params: dict | None = None,
        auth: bool = False,
        force_refresh: bool = False,
    ) -> requests.Response | CachedResponse:
        url = self.base_url + path
        headers = {"User-Agent": self.user_agent}
        if auth:
            self.refresh_token_if_needed()
            headers["Authorization"] = "Bearer " + self.token["access_token"]

        cache_key = self._request_cache_key(path, params, auth)
        cache_entry = self._http_cache.get(cache_key)
        now_ts = int(time.time())
        if (
            not force_refresh
            and isinstance(cache_entry, dict)
            and int(cache_entry.get("expires_at", 0)) > now_ts
            and "payload" in cache_entry
        ):
            self._record_request_log(
                endpoint=path,
                params=params,
                status=200,
                latency_sec=0.0,
                expires_at=int(cache_entry.get("expires_at", 0)),
                etag=cache_entry.get("etag", ""),
                ratelimit_remaining=None,
                retry_after=None,
                error_limit_remaining=None,
            )
            self.diag(f"GET {path}: served from cache until {int(cache_entry.get('expires_at', 0))}")
            return self._build_cached_response(cache_entry)

        if isinstance(cache_entry, dict):
            etag = str(cache_entry.get("etag", "") or "")
            if etag:
                headers["If-None-Match"] = etag

        last_response = None
        for attempt in range(6):
            try:
                self._pace_before_request(f"GET {path}")
                t0 = time.time()
                self.diag(f"GET {path} attempt={attempt+1}/6 params={params} auth={auth}")
                r = self.session.get(url, params=params, headers=headers, timeout=60)
                dt = time.time() - t0
                last_response = r
                self.diag(f"GET {path} attempt={attempt+1} -> HTTP {r.status_code} in {dt:.2f}s")
                resp_headers = dict(getattr(r, "headers", {}) or {})
                self._dynamic_throttle_from_headers(path, resp_headers)
                expires_at = self._parse_expires_header(resp_headers.get("Expires"))
                etag = str(resp_headers.get("ETag", "") or "")
                self._record_request_log(
                    endpoint=path,
                    params=params,
                    status=int(r.status_code),
                    latency_sec=dt,
                    expires_at=expires_at,
                    etag=etag,
                    ratelimit_remaining=resp_headers.get("X-Ratelimit-Remaining"),
                    retry_after=resp_headers.get("Retry-After"),
                    error_limit_remaining=resp_headers.get("X-Esi-Error-Limit-Remain"),
                )
                if r.status_code == 420:
                    wait = int(r.headers.get("X-Esi-Error-Limit-Reset", "2"))
                    sleep_for = max(wait, 2) + self.rate_limit_cooldown_sec
                    self._set_global_cooldown(sleep_for, f"GET {path}")
                    self.diag(f"GET {path} rate-limited (420), wait={sleep_for:.2f}s")
                    time.sleep(sleep_for)
                    continue
                if r.status_code == 429:
                    wait_header = r.headers.get("Retry-After")
                    try:
                        wait = max(1.0, float(wait_header or 1.0))
                    except Exception:
                        wait = 1.0
                    self._set_global_cooldown(wait, f"GET {path} rate-limited (429)")
                    time.sleep(wait)
                    continue
                if r.status_code >= 500:
                    self.diag(f"GET {path} server error HTTP {r.status_code}, retry")
                    time.sleep(2.0 + attempt * 0.5)
                    continue
                if r.status_code == 304 and isinstance(cache_entry, dict) and "payload" in cache_entry:
                    cache_entry["expires_at"] = int(expires_at)
                    cache_entry["headers"] = dict(resp_headers)
                    if etag:
                        cache_entry["etag"] = etag
                    self._http_cache[cache_key] = cache_entry
                    self._mark_type_cache_dirty()
                    return self._build_cached_response(cache_entry)
                if r.status_code == 200:
                    payload = None
                    try:
                        payload = r.json()
                    except Exception:
                        payload = None
                    self._http_cache[cache_key] = {
                        "payload": payload,
                        "expires_at": int(expires_at),
                        "etag": etag,
                        "headers": dict(resp_headers),
                        "cached_at": int(time.time()),
                    }
                    self._mark_type_cache_dirty()
                return r
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
                wait_time = 2.0 + attempt * 1.0
                self.diag(f"GET {path} attempt={attempt+1} exception={type(e).__name__} wait={wait_time}s")
                print(f"Netzwerkfehler bei {path} (Versuch {attempt+1}/6): {type(e).__name__}. Warte {wait_time}s...")
                time.sleep(wait_time)
                continue
        if last_response is not None:
            self.diag(f"GET {path} exhausted retries, returning last HTTP {last_response.status_code}")
            return last_response
        self.diag(f"GET {path} exhausted retries without HTTP response")
        raise RuntimeError(f"ESI GET fehlgeschlagen ohne HTTP-Response: {path}")

    def esi_post(self, path: str, json_body, auth: bool = False) -> requests.Response:
        url = self.base_url + path
        headers = {"User-Agent": self.user_agent}
        if auth:
            self.refresh_token_if_needed()
            headers["Authorization"] = "Bearer " + self.token["access_token"]

        last_response = None
        for attempt in range(6):
            try:
                self._pace_before_request(f"POST {path}")
                t0 = time.time()
                self.diag(f"POST {path} attempt={attempt+1}/6 auth={auth}")
                r = self.session.post(url, json=json_body, headers=headers, timeout=60)
                dt = time.time() - t0
                last_response = r
                self.diag(f"POST {path} attempt={attempt+1} -> HTTP {r.status_code} in {dt:.2f}s")
                if r.status_code == 420:
                    wait = int(r.headers.get("X-Esi-Error-Limit-Reset", "2"))
                    sleep_for = max(wait, 2) + self.rate_limit_cooldown_sec
                    self._set_global_cooldown(sleep_for, f"POST {path}")
                    self.diag(f"POST {path} rate-limited (420), wait={sleep_for:.2f}s")
                    time.sleep(sleep_for)
                    continue
                if r.status_code >= 500:
                    self.diag(f"POST {path} server error HTTP {r.status_code}, retry")
                    time.sleep(2.0 + attempt * 0.5)
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError) as e:
                wait_time = 2.0 + attempt * 1.0
                self.diag(f"POST {path} attempt={attempt+1} exception={type(e).__name__} wait={wait_time}s")
                print(f"Netzwerkfehler bei {path} (Versuch {attempt+1}/6): {type(e).__name__}. Warte {wait_time}s...")
                time.sleep(wait_time)
                continue
        if last_response is not None:
            self.diag(f"POST {path} exhausted retries, returning last HTTP {last_response.status_code}")
            return last_response
        self.diag(f"POST {path} exhausted retries without HTTP response")
        raise RuntimeError(f"ESI POST fehlgeschlagen ohne HTTP-Response: {path}")

    def preflight_structure_request(self, structure_id: int) -> None:
        self.diag(f"preflight_structure_request start structure_id={structure_id}")
        self.refresh_token_if_needed()
        url = self.base_url + f"/markets/structures/{structure_id}/"
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": "Bearer " + self.token["access_token"],
        }
        t0 = time.time()
        r = self.session.get(url, params={"page": 1}, headers=headers, timeout=30)
        self.diag(
            f"preflight_structure_request structure_id={structure_id} "
            f"HTTP {r.status_code} in {time.time()-t0:.2f}s"
        )
        if r.status_code == 420:
            reset_s = int(r.headers.get("X-Esi-Error-Limit-Reset", "60"))
            die(
                f"ESI Error-Limit aktiv (HTTP 420) vor Start fuer Struktur {structure_id}. "
                f"Bitte ca. {reset_s}s warten und erneut starten."
            )
        if r.status_code in (401, 403):
            die(f"Kein Zugriff auf Struktur {structure_id} (HTTP {r.status_code}).")
        if r.status_code != 200:
            die(f"Preflight fehlgeschlagen fuer Struktur {structure_id}: HTTP {r.status_code} {r.text}")
        self.diag(f"preflight_structure_request ok structure_id={structure_id}")

    def fetch_structure_orders(self, structure_id: int) -> list[dict]:
        ckpt_path = os.path.join(CACHE_DIR, f"orders_{structure_id}_checkpoint.json")
        checkpoint = load_json(ckpt_path, None)
        if isinstance(checkpoint, dict) and int(checkpoint.get("structure_id", 0)) == int(structure_id):
            orders = list(checkpoint.get("orders", []))
            page = int(checkpoint.get("next_page", 1))
            self.diag(
                f"fetch_structure_orders resume structure_id={structure_id} "
                f"next_page={page} cached_orders={len(orders)}"
            )
        else:
            orders = []
            page = 1
        self.diag(f"fetch_structure_orders start structure_id={structure_id}")
        while True:
            last_error = None
            response = None
            for attempt in range(1, 9):
                try:
                    self.diag(f"fetch_structure_orders structure={structure_id} page={page} attempt={attempt}/8")
                    response = self.esi_get(f"/markets/structures/{structure_id}/", params={"page": page}, auth=True)
                    if response.status_code == 200:
                        break
                    last_error = f"HTTP {response.status_code}"
                except Exception as e:
                    last_error = f"{type(e).__name__}: {e}"
                wait_s = min(20.0, 1.5 * attempt)
                print(
                    f"Struktur {structure_id} Seite {page}: Versuch {attempt}/8 fehlgeschlagen"
                    f" ({last_error}). Warte {wait_s:.1f}s..."
                )
                time.sleep(wait_s)

            if response is None or response.status_code != 200:
                die(
                    f"ESI Fehler beim Laden der Struktur {structure_id} auf Seite {page}. "
                    f"Letzter Fehler: {last_error}. Bereits geladene Orders: {len(orders)}"
                )

            data = response.json()
            orders.extend(data)
            pages = int(response.headers.get("X-Pages", "1"))
            save_json(
                ckpt_path,
                {
                    "structure_id": int(structure_id),
                    "next_page": int(page + 1),
                    "pages": int(pages),
                    "orders": orders,
                },
            )
            self.diag(
                f"fetch_structure_orders structure={structure_id} page={page}/{pages} "
                f"orders_this_page={len(data)} total_orders={len(orders)}"
            )
            if pages > 1 and page % 10 == 0:
                print(f"    Struktur {structure_id}: Seite {page}/{pages} geladen...")
            if page >= pages:
                break
            page += 1
        if os.path.exists(ckpt_path):
            try:
                os.remove(ckpt_path)
            except Exception:
                pass
        self.diag(f"fetch_structure_orders done structure_id={structure_id} total_orders={len(orders)}")
        return orders

    def fetch_region_orders(self, region_id: int, order_type: str = "all") -> list[dict]:
        rid = int(region_id)
        ot = str(order_type or "all").lower()
        if ot not in ("all", "buy", "sell"):
            ot = "all"
        orders: list[dict] = []
        page = 1
        while True:
            params = {"order_type": ot, "page": page}
            response = self.esi_get(f"/markets/{rid}/orders/", params=params, auth=False)
            if response.status_code != 200:
                break
            data = response.json()
            if isinstance(data, list):
                orders.extend(data)
            pages = int(response.headers.get("X-Pages", "1"))
            if page >= pages:
                break
            page += 1
        return orders

    def get_location_orders(
        self,
        region_id: int,
        location_id: int,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        rid = int(region_id)
        lid = int(location_id)
        tset = set(int(x) for x in type_ids) if type_ids else None
        order_types = ["sell", "buy"] if str(order_type or "all").lower() == "all" else [str(order_type or "all").lower()]
        out: list[dict] = []
        for ot in order_types:
            region_orders = self.fetch_region_orders(rid, ot)
            for o in region_orders:
                try:
                    if int(o.get("location_id", 0) or 0) != lid:
                        continue
                    if tset is not None and int(o.get("type_id", 0) or 0) not in tset:
                        continue
                except Exception:
                    continue
                out.append(o)
        return out

    def get_jita_44_orders(
        self,
        region_id: int = 10000002,
        location_id: int = 60003760,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        return self.get_location_orders(
            region_id=int(region_id),
            location_id=int(location_id),
            order_type=str(order_type or "all"),
            type_ids=type_ids,
        )

    def resolve_type_names(self, type_ids: list[int]) -> dict[int, str]:
        missing = [tid for tid in type_ids if self.type_cache.get(str(tid), {}).get("name") is None]
        self._perf_stats["type_name_cache_hits"] += max(0, len(type_ids) - len(missing))
        if missing:
            chunk_size = 500
            for i in range(0, len(missing), chunk_size):
                chunk = missing[i : i + chunk_size]
                try:
                    r = self.esi_post("/universe/names/", chunk, auth=False)
                    if r.status_code == 200:
                        for obj in r.json():
                            if obj.get("category") == "inventory_type":
                                tid = int(obj["id"])
                                self.type_cache.setdefault(str(tid), {})["name"] = obj.get("name", f"type_{tid}")
                                self._perf_stats["type_name_network_fetches"] += 1
                except Exception as e:
                    print(f"Fehler bei Bulk-Abfrage: {e}. Verwende Einzelabfragen...")
                    break

        still_missing = [tid for tid in type_ids if self.type_cache.get(str(tid), {}).get("name") is None]
        for idx, tid in enumerate(still_missing):
            try:
                r = self.esi_get(f"/universe/types/{tid}/", auth=False)
                if r.status_code == 200:
                    data = r.json()
                    entry = self.type_cache.setdefault(str(tid), {})
                    entry["name"] = data.get("name", f"type_{tid}")
                    if "volume" not in entry:
                        try:
                            entry["volume"] = float(data.get("packaged_volume") or data.get("volume") or 1.0)
                        except Exception:
                            entry["volume"] = 1.0
                    self._perf_stats["type_name_network_fetches"] += 1
                else:
                    self.type_cache.setdefault(str(tid), {})["name"] = f"type_{tid}"
            except Exception as e:
                print(f"Fehler bei Typ {tid}: {e}. Verwende Default-Name.")
                self.type_cache.setdefault(str(tid), {})["name"] = f"type_{tid}"

            if (idx + 1) % 50 == 0:
                print(f"Typ-Namen aufloesen: {idx + 1}/{len(still_missing)}...")

        self._mark_type_cache_dirty(delta=max(1, len(still_missing)), flush_threshold=200)
        return {tid: self.type_cache.get(str(tid), {}).get("name", f"type_{tid}") for tid in type_ids}

    def resolve_type_volume(self, type_id: int) -> float:
        entry = self.type_cache.get(str(type_id), {})
        if "volume" in entry:
            self._perf_stats["type_volume_cache_hits"] += 1
            return float(entry["volume"])

        try:
            r = self.esi_get(f"/universe/types/{type_id}/", auth=False)
            if r.status_code != 200:
                vol = 1.0
            else:
                obj = r.json()
                vol = float(obj.get("packaged_volume") or obj.get("volume") or 1.0)
                if self.type_cache.get(str(type_id), {}).get("name") is None:
                    self.type_cache.setdefault(str(type_id), {})["name"] = obj.get("name", f"type_{type_id}")
                self._perf_stats["type_volume_network_fetches"] += 1
        except Exception as e:
            print(f"Fehler beim Aufloesen von Volumen fuer Typ {type_id}: {e}. Verwende Default.")
            vol = 1.0

        self.type_cache.setdefault(str(type_id), {})["volume"] = vol
        self._mark_type_cache_dirty()
        return vol

    def preload_market_prices(self) -> None:
        if bool(getattr(self, "_market_prices_loaded", False)):
            return
        try:
            r = self.esi_get("/markets/prices/", auth=False)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for obj in data:
                        try:
                            tid = int(obj.get("type_id", 0))
                        except Exception:
                            continue
                        if tid <= 0:
                            continue
                        entry = self.type_cache.setdefault(str(tid), {})
                        if "average_price" in obj:
                            try:
                                entry["average_price"] = float(obj.get("average_price", 0.0) or 0.0)
                            except Exception:
                                pass
                        if "adjusted_price" in obj:
                            try:
                                entry["adjusted_price"] = float(obj.get("adjusted_price", 0.0) or 0.0)
                            except Exception:
                                pass
                    self.type_cache["_market_prices_cached_at"] = int(time.time())
                    self._mark_type_cache_dirty(delta=max(1, len(data)), flush_threshold=1)
        except Exception:
            pass
        finally:
            self._market_prices_loaded = True

    def get_market_reference_price(
        self,
        type_id: int,
        prefer: str = "average_price",
        fallback_to_adjusted: bool = True,
    ) -> tuple[float, str, float, float]:
        self.preload_market_prices()
        entry = self.type_cache.get(str(int(type_id)), {})
        avg = float(entry.get("average_price", 0.0) or 0.0)
        adj = float(entry.get("adjusted_price", 0.0) or 0.0)
        pref = str(prefer or "average_price").lower()
        if pref == "adjusted_price":
            if adj > 0:
                return adj, "adjusted_price", avg, adj
            if fallback_to_adjusted and avg > 0:
                return avg, "average_price", avg, adj
            return 0.0, "", avg, adj
        if avg > 0:
            return avg, "average_price", avg, adj
        if fallback_to_adjusted and adj > 0:
            return adj, "adjusted_price", avg, adj
        return 0.0, "", avg, adj

    def get_region_history_stats(self, region_id: int, type_id: int, days: int = 30) -> dict:
        rid = int(region_id)
        tid = int(type_id)
        days_i = int(days)
        cache_key = f"hist_stats_region_{rid}_{tid}_{days_i}"
        if cache_key in self.type_cache:
            self._perf_stats["history_cache_hits"] += 1
            self._perf_stats["history_served_from_cache"] += 1
            return self.type_cache[cache_key]

        missing_key = f"hist_missing_region_{rid}_{tid}"
        if bool(self.type_cache.get(missing_key, False)):
            self._perf_stats["history_negative_cache_hits"] += 1
            self._perf_stats["history_skipped_negative"] += 1
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing": True}
            self.type_cache[cache_key] = stats
            return stats

        raw_key = f"hist_raw_region_{rid}_{tid}"
        history = self.type_cache.get(raw_key)
        if isinstance(history, list):
            self._perf_stats["history_raw_cache_hits"] += 1
        else:
            self._perf_stats["history_requests_total"] += 1
            try:
                r = self.esi_get(f"/markets/{rid}/history/", params={"type_id": tid}, auth=False)
            except Exception:
                r = None
            if r is None:
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                self.type_cache[cache_key] = stats
                return stats
            if r.status_code == 404:
                self._perf_stats["history_http_404"] += 1
                self.type_cache[missing_key] = True
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing": True}
                self.type_cache[cache_key] = stats
                self._mark_type_cache_dirty()
                return stats
            if r.status_code != 200:
                stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
                self.type_cache[cache_key] = stats
                return stats
            try:
                history = r.json()
            except Exception:
                history = []
            if not isinstance(history, list):
                history = []
            self.type_cache[raw_key] = history
            self._mark_type_cache_dirty()

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_i)
            recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            total_vol = 0
            total_orders = 0
            days_with = 0
            recent = False
            seen_dates = set()
            for entry in history:
                date_s = str(entry.get("date", "")).strip()
                try:
                    dt = datetime.fromisoformat(date_s.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                vol = int(entry.get("volume", 0) or 0)
                order_count = int(entry.get("order_count", 0) or 0)
                if dt >= cutoff:
                    total_vol += vol
                    total_orders += order_count
                    if dt.date() not in seen_dates and vol > 0:
                        days_with += 1
                        seen_dates.add(dt.date())
                if dt >= recent_cutoff and vol > 0:
                    recent = True
            stats = {
                "volume": int(total_vol),
                "order_count": int(total_orders),
                "days_with_trades": int(days_with),
                "recent_activity": bool(recent),
            }
            self.type_cache[cache_key] = stats
            self._mark_type_cache_dirty()
            return stats
        except Exception:
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}
            self.type_cache[cache_key] = stats
            return stats

    def get_market_history_stats(self, structure_id: int, type_id: int, days: int = 30) -> dict:
        sid = int(structure_id)
        region_id = 0
        if isinstance(self.structure_region_map, dict) and self.structure_region_map:
            region_id = int(self.structure_region_map.get(int(sid), 0) or 0)
        if region_id <= 0:
            region_map = self.type_cache.get("_structure_region_map", {})
            if isinstance(region_map, dict):
                try:
                    region_id = int(region_map.get(str(sid), region_map.get(int(sid), 0)) or 0)
                except Exception:
                    region_id = 0
        if region_id <= 0:
            try:
                region_id = int(self.type_cache.get(f"_sid_region_{sid}", 0) or 0)
            except Exception:
                region_id = 0
        if region_id <= 0:
            stats = {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing_region": True}
            cache_key = f"hist_stats_region_missing_{sid}_{int(type_id)}_{int(days)}"
            self.type_cache[cache_key] = stats
            return stats
        return self.get_region_history_stats(region_id, int(type_id), int(days))

    def get_performance_summary_lines(self) -> list[str]:
        s = dict(self._perf_stats)
        return [
            "PERFORMANCE SUMMARY:",
            f"  history_requests_total: {int(s.get('history_requests_total', 0))}",
            f"  history_http_404: {int(s.get('history_http_404', 0))}",
            f"  history_cache_hits: {int(s.get('history_cache_hits', 0))}",
            f"  history_raw_cache_hits: {int(s.get('history_raw_cache_hits', 0))}",
            f"  history_negative_cache_hits: {int(s.get('history_negative_cache_hits', 0))}",
            f"  history_skipped_negative: {int(s.get('history_skipped_negative', 0))}",
            f"  history_served_from_cache: {int(s.get('history_served_from_cache', 0))}",
            f"  type_name_cache_hits: {int(s.get('type_name_cache_hits', 0))}",
            f"  type_name_network_fetches: {int(s.get('type_name_network_fetches', 0))}",
            f"  type_volume_cache_hits: {int(s.get('type_volume_cache_hits', 0))}",
            f"  type_volume_network_fetches: {int(s.get('type_volume_network_fetches', 0))}",
        ]

    def get_market_history_volume(self, structure_id: int, type_id: int, days: int = 30) -> int:
        stats = self.get_market_history_stats(structure_id, type_id, days)
        if isinstance(stats, dict):
            return int(stats.get("volume", 0) or 0)
        try:
            return int(stats)
        except Exception:
            return 0


class ReplayESIClient:
    """Offline replacement for ESIClient using a persisted type/history cache."""

    def __init__(self, type_cache: dict | None = None):
        self.type_cache = type_cache or {}
        self.structure_region_map: dict[int, int] = {}

    def resolve_type_names(self, type_ids: list[int]) -> dict[int, str]:
        result = {}
        for tid in type_ids:
            result[tid] = self.type_cache.get(str(tid), {}).get("name", f"type_{tid}")
        return result

    def resolve_type_volume(self, type_id: int) -> float:
        entry = self.type_cache.get(str(type_id), {})
        try:
            return float(entry.get("volume", 1.0))
        except Exception:
            return 1.0

    def get_region_history_stats(self, region_id: int, type_id: int, days: int = 30) -> dict:
        key = f"hist_stats_region_{region_id}_{type_id}_{days}"
        stats = self.type_cache.get(key)
        if isinstance(stats, dict):
            return stats
        return {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False}

    def get_market_history_stats(self, structure_id: int, type_id: int, days: int = 30) -> dict:
        region_id = 0
        if isinstance(self.structure_region_map, dict) and self.structure_region_map:
            region_id = int(self.structure_region_map.get(int(structure_id), 0) or 0)
        if region_id <= 0:
            region_map = self.type_cache.get("_structure_region_map", {})
            if isinstance(region_map, dict):
                try:
                    region_id = int(region_map.get(str(int(structure_id)), region_map.get(int(structure_id), 0)) or 0)
                except Exception:
                    region_id = 0
        if region_id <= 0:
            try:
                region_id = int(self.type_cache.get(f"_sid_region_{int(structure_id)}", 0) or 0)
            except Exception:
                region_id = 0
        if region_id <= 0:
            return {"volume": 0, "order_count": 0, "days_with_trades": 0, "recent_activity": False, "missing_region": True}
        return self.get_region_history_stats(region_id, type_id, days)

    def preload_market_prices(self) -> None:
        return

    def get_market_reference_price(
        self,
        type_id: int,
        prefer: str = "average_price",
        fallback_to_adjusted: bool = True,
    ) -> tuple[float, str, float, float]:
        entry = self.type_cache.get(str(int(type_id)), {})
        avg = float(entry.get("average_price", 0.0) or 0.0)
        adj = float(entry.get("adjusted_price", 0.0) or 0.0)
        pref = str(prefer or "average_price").lower()
        if pref == "adjusted_price":
            if adj > 0:
                return adj, "adjusted_price", avg, adj
            if fallback_to_adjusted and avg > 0:
                return avg, "average_price", avg, adj
            return 0.0, "", avg, adj
        if avg > 0:
            return avg, "average_price", avg, adj
        if fallback_to_adjusted and adj > 0:
            return adj, "adjusted_price", avg, adj
        return 0.0, "", avg, adj

    def get_performance_summary_lines(self) -> list[str]:
        return ["PERFORMANCE SUMMARY:", "  replay_mode: no_live_request_metrics"]

    def fetch_region_orders(self, region_id: int, order_type: str = "all") -> list[dict]:
        key = f"replay_region_orders_{int(region_id)}_{str(order_type or 'all').lower()}"
        data = self.type_cache.get(key, [])
        return list(data) if isinstance(data, list) else []

    def get_location_orders(
        self,
        region_id: int,
        location_id: int,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        rid = int(region_id)
        lid = int(location_id)
        tset = set(int(x) for x in type_ids) if type_ids else None
        order_types = ["sell", "buy"] if str(order_type or "all").lower() == "all" else [str(order_type or "all").lower()]
        out: list[dict] = []
        for ot in order_types:
            for o in self.fetch_region_orders(rid, ot):
                try:
                    if int(o.get("location_id", 0) or 0) != lid:
                        continue
                    if tset is not None and int(o.get("type_id", 0) or 0) not in tset:
                        continue
                except Exception:
                    continue
                out.append(o)
        return out

    def get_jita_44_orders(
        self,
        region_id: int = 10000002,
        location_id: int = 60003760,
        order_type: str = "all",
        type_ids: set[int] | None = None,
    ) -> list[dict]:
        return self.get_location_orders(
            region_id=int(region_id),
            location_id=int(location_id),
            order_type=str(order_type or "all"),
            type_ids=type_ids,
        )


__all__ = [
    "CallbackState",
    "CachedResponse",
    "OAuthHandler",
    "ESIClient",
    "ReplayESIClient",
]
