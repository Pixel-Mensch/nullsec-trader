"""Shared imports and helper fixtures for split tests."""

import math

import os

import json

import tempfile

import threading

import io

import glob

import subprocess

import sys

from contextlib import redirect_stdout

from datetime import datetime, timedelta, timezone

from fee_engine import FeeEngine

import nullsectrader as nst


class _FakeESI:
    def __init__(self, history_30: int, history_7: int, reference_price: float):
        self.history_30 = int(history_30)
        self.history_7 = int(history_7)
        self.reference_price = float(reference_price)

    def resolve_type_names(self, type_ids):
        return {int(tid): f"Type_{int(tid)}" for tid in type_ids}

    def get_region_history_stats(self, region_id, tid, days):
        if int(days) == 7:
            return {"volume": int(self.history_7), "order_count": int(self.history_7), "days_with_trades": 7, "recent_activity": True}
        return {"volume": int(self.history_30), "order_count": int(self.history_30), "days_with_trades": 30, "recent_activity": True}

    def get_market_history_stats(self, dest_structure_id, tid, days):
        return self.get_region_history_stats(0, tid, days)

    def resolve_type_volume(self, tid):
        return 1.0

    def preload_market_prices(self):
        return None

    def get_market_reference_price(self, tid, prefer="average_price", fallback_to_adjusted=True):
        rp = float(self.reference_price)
        return rp, ("average_price" if rp > 0 else ""), rp, 0.0

class _FakeResp:
    def __init__(self, status_code: int, payload):
        self.status_code = int(status_code)
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload

class _HistoryProbeESI(nst.ESIClient):
    def __init__(self, status_code: int, payload):
        self.base_url = "http://fake"
        self.user_agent = "test"
        self.client_id = "x"
        self.client_secret = "x"
        self.callback_url = "http://localhost"
        self.scope = ""
        self.session = None
        self.diagnostics_enabled = False
        self.request_min_interval_sec = 0.0
        self.rate_limit_cooldown_sec = 0.0
        self._request_pacing_lock = None
        self._next_request_at = 0.0
        self.token = {"access_token": "x"}
        self.type_cache = {}
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
        self._resp_status = int(status_code)
        self._resp_payload = payload
        self.history_calls = 0
        self.http_calls = 0

    def esi_get(self, path: str, params=None, auth: bool = False):
        self.http_calls += 1
        if "/markets/" in path and "/history/" in path:
            self.history_calls += 1
        return _FakeResp(self._resp_status, self._resp_payload)

class _SeqResponse:
    def __init__(self, status_code: int, payload, headers: dict | None = None):
        self.status_code = int(status_code)
        self._payload = payload
        self.headers = dict(headers or {})
        self.text = str(payload)

    def json(self):
        return self._payload

class _SeqSession:
    def __init__(self, responses: list[_SeqResponse]):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=60):
        self.calls.append({"url": url, "params": params, "headers": dict(headers or {})})
        if not self._responses:
            raise RuntimeError("no fake responses left")
        return self._responses.pop(0)

def _make_cacheable_client(responses: list[_SeqResponse]) -> nst.ESIClient:
    cfg = {
        "esi": {
            "base_url": "https://esi.evetech.net/latest",
            "user_agent": "test-agent",
            "client_id": "x",
            "client_secret": "x",
            "callback_url": "http://localhost:12563/callback",
            "scope": "esi-markets.structure_markets.v1",
            "request_min_interval_sec": 0.0,
            "rate_limit_cooldown_sec": 0.0,
            "cache_default_ttl_sec": 60,
            "request_log_limit": 200,
        },
        "diagnostics": {"network_verbose": False},
    }
    c = nst.ESIClient(cfg)
    c.session = _SeqSession(responses)
    c.token = {"access_token": "x", "created_at": int(0), "expires_in": 999999}
    c.type_cache = {}
    c._http_cache = {}
    c.request_log = []
    c._request_pacing_lock = threading.Lock()
    c._next_request_at = 0.0
    return c

class _NodeFetchProbeESI:
    def __init__(self):
        self.structure_calls = 0
        self.jita_calls = 0
        self.location_calls = 0

    def fetch_structure_orders(self, structure_id: int):
        self.structure_calls += 1
        return [{"type_id": 1, "location_id": int(structure_id), "is_buy_order": False, "price": 10.0, "volume_remain": 5}]

    def get_jita_44_orders(self, region_id=10000002, location_id=60003760, order_type="all", type_ids=None):
        self.jita_calls += 1
        return [{"type_id": 2, "location_id": int(location_id), "is_buy_order": False, "price": 100.0, "volume_remain": 10}]

    def get_location_orders(self, region_id: int, location_id: int, order_type: str = "all", type_ids=None):
        self.location_calls += 1
        return [{"type_id": 3, "location_id": int(location_id), "is_buy_order": True, "price": 90.0, "volume_remain": 7}]

def _strict_filters() -> dict:
    return {
        "mode": "planned_sell",
        "price_depth_pct": 0.3,
        "min_depth_units": 1,
        "min_profit_pct": 0.0,
        "min_profit_isk_total": 0.0,
        "max_turnover_factor": 3.0,
        "min_fill_probability": 0.0,
        "min_instant_fill_ratio": 0.0,
        "min_dest_buy_depth_units": 0,
        "fallback_daily_volume": 0.2,
        "fallback_volume_penalty": 0.35,
        "min_avg_daily_volume": 0.0,
        "min_expected_profit_isk": 0.0,
        "max_expected_days_to_sell": 9999.0,
        "min_sell_through_ratio_90d": 0.0,
        "history_days": 30,
        "horizon_days": 90,
        "min_market_history_order_count": 1,
        "min_depth_within_2pct_sell": 1,
        "max_competition_density_near_best": 8,
        "structure_region_map": {123: 10000002},
        "ranking_metric": "expected_profit_per_m3_90d",
        "strict_mode": {
            "enabled": True,
            "require_reference_price_for_planned": True,
            "disable_fallback_volume_for_planned": True,
            "planned_min_avg_daily_volume_7d": 0.0,
        },
        "strict_require_reference_price_for_planned": True,
        "strict_disable_fallback_volume_for_planned": True,
        "strict_require_avg_daily_volume_7d": 0.0,
        "reference_price": {
            "enabled": True,
            "prefer": "average_price",
            "fallback_to_adjusted": True,
            "soft_sell_markup_vs_ref_planned": 0.20,
            "max_sell_markup_vs_ref_planned": 0.40,
            "hard_max_sell_markup_vs_ref_planned": 0.80,
            "ranking_penalty_strength": 0.60,
        },
    }

def _simple_orders(tid: int = 42, dest_price: float = 300.0) -> tuple[list[dict], list[dict]]:
    source_orders = [
        {"type_id": tid, "is_buy_order": False, "price": 100.0, "volume_remain": 10},
    ]
    dest_orders = [
        {"type_id": tid, "is_buy_order": False, "price": float(dest_price), "volume_remain": 10},
    ]
    return source_orders, dest_orders

def _minimal_valid_config() -> dict:
    return {
        "esi": {
            "base_url": "https://esi.evetech.net/latest",
            "user_agent": "NullsecTrader/Test",
            "client_id": "",
            "client_secret": "",
            "request_min_interval_sec": 0.1,
            "cache_default_ttl_sec": 60,
            "strict_region_mapping": False,
            "auto_fill_structure_regions": False,
        },
        "replay": {"enabled": False},
        "structures": {"o4t": 1040804972352, "cj6": 1049588174021},
        "structure_regions": {
            "1040804972352": 10000059,
            "1049588174021": 10000009,
        },
        "fees": {
            "sales_tax": 0.075,
            "buy_broker_fee": 0.0,
            "sell_broker_fee": 0.03,
            "scc_surcharge": 0.005,
            "sell_market_type": "upwell",
            "skills": {
                "accounting": 3,
                "broker_relations": 3,
                "advanced_broker_relations": 3,
            },
            "relist_budget_pct": 0.0,
            "relist_budget_isk": 0.0,
        },
        "filters_forward": {"mode": "instant"},
        "filters_return": {"mode": "fast_sell"},
        "defaults": {"cargo_m3": 10000, "budget_isk": 500000000},
    }


__all__ = [name for name in globals() if not name.startswith('__')]

