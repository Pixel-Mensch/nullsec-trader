from __future__ import annotations

import requests

from eve_sso import EveSSOAuth, SSOAuthError, normalize_scopes
from runtime_common import CHARACTER_SSO_METADATA_PATH, CHARACTER_SSO_TOKEN_PATH


class CharacterESIError(RuntimeError):
    pass


class EveCharacterClient:
    def __init__(self, cfg: dict, *, session: requests.Session | None = None, sso: EveSSOAuth | None = None):
        esi_cfg = cfg.get("esi", {}) if isinstance(cfg, dict) else {}
        if not isinstance(esi_cfg, dict):
            esi_cfg = {}
        char_cfg = cfg.get("character_context", {}) if isinstance(cfg, dict) else {}
        if not isinstance(char_cfg, dict):
            char_cfg = {}
        self.base_url = str(esi_cfg.get("base_url", "https://esi.evetech.net/latest") or "https://esi.evetech.net/latest").rstrip("/")
        self.user_agent = str(esi_cfg.get("user_agent", "NullsecTrader/1.0") or "NullsecTrader/1.0").strip()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.sso = sso or EveSSOAuth(
            client_id=str(esi_cfg.get("client_id", "") or ""),
            client_secret=str(esi_cfg.get("client_secret", "") or ""),
            callback_url=str(esi_cfg.get("callback_url", "http://localhost:12563/callback") or "http://localhost:12563/callback"),
            user_agent=self.user_agent,
            token_path=str(char_cfg.get("token_path", CHARACTER_SSO_TOKEN_PATH) or CHARACTER_SSO_TOKEN_PATH),
            metadata_path=str(char_cfg.get("metadata_path", CHARACTER_SSO_METADATA_PATH) or CHARACTER_SSO_METADATA_PATH),
        )

    def _headers(self, scopes, *, allow_login: bool = True) -> dict:
        headers = {"User-Agent": self.user_agent}
        scope_list = normalize_scopes(scopes)
        if scope_list:
            token = self.sso.ensure_token(scope_list, allow_login=allow_login)
            headers["Authorization"] = "Bearer " + str(token.get("access_token", "") or "")
        return headers

    def _get_json(self, path: str, *, scopes=None, params: dict | None = None, allow_login: bool = True):
        headers = self._headers(scopes, allow_login=allow_login)
        response = self.session.get(self.base_url + path, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            raise CharacterESIError(f"GET {path} failed: HTTP {response.status_code} {response.text}")
        payload = response.json()
        return payload, dict(response.headers or {})

    def _post_json(self, path: str, payload, *, scopes=None, allow_login: bool = True):
        headers = self._headers(scopes, allow_login=allow_login)
        response = self.session.post(self.base_url + path, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            raise CharacterESIError(f"POST {path} failed: HTTP {response.status_code} {response.text}")
        data = response.json()
        return data, dict(response.headers or {})

    def _get_paginated_json(
        self,
        path: str,
        *,
        scopes,
        params: dict | None = None,
        max_pages: int | None = None,
        allow_login: bool = True,
    ) -> list[dict]:
        out: list[dict] = []
        page = 1
        page_cap = int(max_pages) if max_pages is not None else 0
        while True:
            merged_params = dict(params or {})
            merged_params["page"] = int(page)
            data, headers = self._get_json(path, scopes=scopes, params=merged_params, allow_login=allow_login)
            if isinstance(data, list):
                out.extend(data)
            total_pages = 1
            try:
                total_pages = int(headers.get("X-Pages", "1") or "1")
            except Exception:
                total_pages = 1
            if page >= total_pages:
                break
            if page_cap > 0 and page >= page_cap:
                break
            page += 1
        return out

    def get_identity(self, requested_scopes, *, allow_login: bool = True) -> dict:
        token = self.sso.ensure_token(requested_scopes, allow_login=allow_login)
        identity = self.sso.token_identity(token)
        identity["loaded_scopes"] = self.sso.token_scopes(token)
        identity["token_expires_at"] = self.sso.token_expires_at(token)
        return identity

    def get_public_character(self, character_id: int) -> dict:
        data, _ = self._get_json(f"/characters/{int(character_id)}/", scopes=None, params=None, allow_login=False)
        return dict(data) if isinstance(data, dict) else {}

    def get_skills(self, character_id: int, *, allow_login: bool = True) -> dict:
        data, _ = self._get_json(
            f"/characters/{int(character_id)}/skills/",
            scopes=["esi-skills.read_skills.v1"],
            allow_login=allow_login,
        )
        return dict(data) if isinstance(data, dict) else {}

    def get_skill_queue(self, character_id: int, *, allow_login: bool = True) -> list[dict]:
        data, _ = self._get_json(
            f"/characters/{int(character_id)}/skillqueue/",
            scopes=["esi-skills.read_skillqueue.v1"],
            allow_login=allow_login,
        )
        return list(data) if isinstance(data, list) else []

    def get_open_orders(self, character_id: int, *, allow_login: bool = True) -> list[dict]:
        return self._get_paginated_json(
            f"/characters/{int(character_id)}/orders/",
            scopes=["esi-markets.read_character_orders.v1"],
            allow_login=allow_login,
        )

    def get_wallet_balance(self, character_id: int, *, allow_login: bool = True) -> float:
        data, _ = self._get_json(
            f"/characters/{int(character_id)}/wallet/",
            scopes=["esi-wallet.read_character_wallet.v1"],
            allow_login=allow_login,
        )
        try:
            return float(data)
        except Exception:
            return 0.0

    def get_wallet_journal(self, character_id: int, *, max_pages: int | None = None, allow_login: bool = True) -> list[dict]:
        return self._get_paginated_json(
            f"/characters/{int(character_id)}/wallet/journal/",
            scopes=["esi-wallet.read_character_wallet.v1"],
            max_pages=max_pages,
            allow_login=allow_login,
        )

    def get_wallet_transactions(self, character_id: int, *, max_pages: int | None = None, allow_login: bool = True) -> list[dict]:
        return self._get_paginated_json(
            f"/characters/{int(character_id)}/wallet/transactions/",
            scopes=["esi-wallet.read_character_wallet.v1"],
            max_pages=max_pages,
            allow_login=allow_login,
        )

    def resolve_names(self, ids: list[int]) -> dict[int, str]:
        clean_ids: list[int] = []
        seen = set()
        for raw in ids:
            try:
                item_id = int(raw)
            except Exception:
                continue
            if item_id <= 0 or item_id in seen:
                continue
            seen.add(item_id)
            clean_ids.append(item_id)
        if not clean_ids:
            return {}
        out: dict[int, str] = {}
        chunk_size = 500
        for i in range(0, len(clean_ids), chunk_size):
            chunk = clean_ids[i : i + chunk_size]
            data, _ = self._post_json("/universe/names/", chunk, scopes=None, allow_login=False)
            if not isinstance(data, list):
                continue
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                try:
                    item_id = int(entry.get("id", 0) or 0)
                except Exception:
                    item_id = 0
                if item_id <= 0:
                    continue
                out[item_id] = str(entry.get("name", f"id_{item_id}") or f"id_{item_id}")
        return out


__all__ = [
    "CharacterESIError",
    "EveCharacterClient",
    "SSOAuthError",
]
