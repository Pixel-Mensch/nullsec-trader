from __future__ import annotations

from typing import Any


REASON_CATALOG: dict[str, str] = {
    "STRONG_EXPECTED_PROFIT": "Konservativer erwarteter Profit ist stark.",
    "STRONG_INSTANT_EXIT": "Sofortiger Exit wirkt belastbar.",
    "REALISTIC_EXIT_VOLUME": "Verkaufbare Menge innerhalb des Horizonts wirkt realistisch.",
    "LOW_SHIPPING_COST": "Transportkosten sind im Verhaeltnis zum Trade niedrig.",
    "SOLID_JITA_BUY": "Einkauf liegt klar unter der Referenz.",
    "RELIABLE_PRICE_BASIS": "Zielpreis hat eine belastbare Preisbasis.",
    "FAST_LIQUIDATION": "Erwartete Liquidationsdauer ist kurz.",
    "HIGH_CONFIDENCE": "Gesamtkonfidenz ist hoch.",
    "LOW_LIQUIDITY": "Marktliquiditaet ist zu schwach.",
    "DEAD_MARKET_RISK": "Markt wirkt fuer reale Positionen zu duenn.",
    "THIN_SELL_WALL": "Sell-Queue oder Sell-Wall am Ziel ist problematisch.",
    "WEAK_EXIT_CONFIDENCE": "Exit-Annahme ist zu schwach.",
    "CAPITAL_LOCK_RISK": "Kapital waere zu lange gebunden.",
    "WEAK_PRICE_BASIS": "Preisableitung fuer den Exit ist schwach.",
    "WEAK_INSTANT_EXIT": "Sofortiger Exit hat zu wenig echte Gegenseite.",
    "HIGH_TRANSPORT_RISK": "Transportmodell oder Transportrisiko drueckt den Trade.",
    "HIGH_TRANSPORT_COST": "Transportkosten fressen den Trade auf.",
    "THIN_TOP_OF_BOOK": "Die Top-of-Book-Lage ist zu duenn.",
    "UNUSABLE_DEPTH": "Die nutzbare Ordertiefe reicht fuer die Position nicht.",
    "FAKE_SPREAD_RISK": "Der sichtbare Spread wirkt irrefuehrend oder nicht belastbar.",
    "EXTREME_REFERENCE_DEVIATION": "Der Preis weicht zu stark von Referenz oder Plausibilitaet ab.",
    "DEPTH_COLLAPSE": "Die Ordertiefe bricht hinter den ersten Levels weg.",
    "ORDERBOOK_CONCENTRATION": "Einzelne Orders dominieren das Marktbild zu stark.",
    "HISTORY_ONLY_SIGNAL": "Bewertung stuetzt sich zu stark auf schwache History-Signale.",
    "CONFIDENCE_DOWNGRADED": "Kalibrierung stuft die rohe Confidence ab.",
    "CALIBRATION_WEAK_DATA": "Kalibrierung basiert auf zu wenig Journal-Daten.",
    "SPECULATIVE_EXIT": "Exit bleibt spekulativ.",
    "EXCESSIVE_CONCENTRATION": "Zu viel Ergebnis haengt an wenigen Picks.",
    "STRONG_ROUTE_CONFIDENCE": "Die Route kombiniert belastbare Picks.",
    "STRONG_ROUTE_PROFIT": "Die Route liefert guten konservativen Erwartungsprofit.",
    "GOOD_PROFIT_TO_CARGO": "Profit pro m3 ist attraktiv.",
    "RELIABLE_TRANSPORT_MODEL": "Transportkosten fuer die Route sind belastbar modelliert.",
    "TOO_MANY_SPECULATIVE_PICKS": "Die Route enthaelt zu viele spekulative Picks.",
    "SLOW_ROUTE_LIQUIDATION": "Die Route liquidiert voraussichtlich langsam.",
    "STALE_MARKET_SIGNAL": "Mehrere Picks basieren auf schwachen oder veralteten Marktsignalen.",
    "NO_SHIPPING_MODEL": "Ohne belastbares Shipping-Modell ist die Route nicht handelbar.",
    "NO_ACTIONABLE_CANDIDATES": "Es gibt keine brauchbaren Kandidaten fuer diese Route.",
    "NO_ORDERBOOK": "Es fehlt ein brauchbares Orderbuch.",
    "LOW_PROFIT_AFTER_COSTS": "Nach Gebuehren und Kosten bleibt zu wenig Profit.",
    "EXCLUDED_TYPE": "Typ ist konfigurationsseitig ausgeschlossen.",
    "EXCLUDED_NAME_KEYWORD": "Name-Matching hat den Typ ausgeschlossen.",
}

INTERNAL_REASON_CODES: dict[str, str] = {
    "excluded_type_id": "EXCLUDED_TYPE",
    "excluded_name_keyword": "EXCLUDED_NAME_KEYWORD",
    "market_history": "LOW_LIQUIDITY",
    "market_history_order_count": "DEAD_MARKET_RISK",
    "liquidity_score": "LOW_LIQUIDITY",
    "orderbook_window_units_too_low": "WEAK_INSTANT_EXIT",
    "no_orderbook": "NO_ORDERBOOK",
    "planned_price_unreliable_orderbook": "WEAK_PRICE_BASIS",
    "isolated_top_sell_wall": "THIN_SELL_WALL",
    "unsupported_sell_queue": "THIN_SELL_WALL",
    "orderbook_min_source_sell_price": "LOW_PROFIT_AFTER_COSTS",
    "min_depth_units": "WEAK_INSTANT_EXIT",
    "non_positive_profit": "LOW_PROFIT_AFTER_COSTS",
    "non_positive_profit_90d": "LOW_PROFIT_AFTER_COSTS",
    "min_profit_pct": "LOW_PROFIT_AFTER_COSTS",
    "profit_threshold": "LOW_PROFIT_AFTER_COSTS",
    "strict_reference_price_hard_sell_markup": "WEAK_PRICE_BASIS",
    "reference_price_hard_sell_markup": "WEAK_PRICE_BASIS",
    "strict_missing_reference_price": "WEAK_PRICE_BASIS",
    "reference_price_plausibility": "WEAK_PRICE_BASIS",
    "missing_region_mapping": "HISTORY_ONLY_SIGNAL",
    "dest_buy_depth_units": "WEAK_INSTANT_EXIT",
    "no_history_volume": "DEAD_MARKET_RISK",
    "strict_no_fallback_volume": "HISTORY_ONLY_SIGNAL",
    "avg_daily_volume_too_low": "LOW_LIQUIDITY",
    "strict_avg_daily_volume_7d_too_low": "LOW_LIQUIDITY",
    "planned_history_order_count": "DEAD_MARKET_RISK",
    "fallback_profit_pct_too_low": "HISTORY_ONLY_SIGNAL",
    "planned_structure_micro_liquidity": "THIN_SELL_WALL",
    "planned_queue_ahead_too_heavy": "THIN_SELL_WALL",
    "planned_demand_cap_zero": "DEAD_MARKET_RISK",
    "planned_demand_cap_too_low": "LOW_LIQUIDITY",
    "planned_low_confidence": "WEAK_EXIT_CONFIDENCE",
    "strict_expected_days_too_high": "CAPITAL_LOCK_RISK",
    "expected_days_too_high": "CAPITAL_LOCK_RISK",
    "strict_sell_through_too_low": "LOW_LIQUIDITY",
    "sell_through_too_low": "LOW_LIQUIDITY",
    "expected_profit_too_low": "LOW_PROFIT_AFTER_COSTS",
    "shipping_cost_non_positive_profit": "HIGH_TRANSPORT_COST",
    "min_profit_pct_after_shipping": "HIGH_TRANSPORT_COST",
    "expected_profit_too_low_after_shipping": "HIGH_TRANSPORT_COST",
    "thin_top_of_book": "THIN_TOP_OF_BOOK",
    "unusable_depth": "UNUSABLE_DEPTH",
    "fake_spread_risk": "FAKE_SPREAD_RISK",
    "extreme_reference_deviation": "EXTREME_REFERENCE_DEVIATION",
    "depth_collapse": "DEPTH_COLLAPSE",
    "orderbook_concentration": "ORDERBOOK_CONCENTRATION",
    "fill_probability": "WEAK_INSTANT_EXIT",
    "missing_transport_cost_model": "NO_SHIPPING_MODEL",
    "no_picks": "NO_ACTIONABLE_CANDIDATES",
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value or 0.0)))


def _record_get(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _record_set(record: Any, key: str, value: Any) -> None:
    if isinstance(record, dict):
        record[key] = value
    else:
        setattr(record, key, value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return int(default)


def _fmt_isk_short(value: Any) -> str:
    amount = _safe_float(value)
    if abs(amount) >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}b ISK"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}m ISK"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.2f}k ISK"
    return f"{amount:.2f} ISK"


def reason_code_for_internal_reason(reason: str) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "UNKNOWN_REASON"
    if raw in REASON_CATALOG:
        return raw
    mapped = INTERNAL_REASON_CODES.get(raw)
    if mapped:
        return mapped
    return raw.upper()


def build_reason_entry(
    code: str,
    *,
    text: str | None = None,
    metrics: dict | None = None,
    severity: str = "info",
    source: str = "model",
) -> dict:
    return {
        "code": str(code or "UNKNOWN_REASON"),
        "text": str(text or REASON_CATALOG.get(str(code or ""), str(code or "UNKNOWN_REASON"))),
        "metrics": dict(metrics or {}),
        "severity": str(severity or "info"),
        "source": str(source or "model"),
    }


def build_contributor(
    key: str,
    *,
    value: float,
    effect: float,
    text: str,
    weight: float | None = None,
) -> dict:
    out = {
        "key": str(key),
        "value": float(value),
        "effect": float(effect),
        "text": str(text),
    }
    if weight is not None:
        out["weight"] = float(weight)
    return out


def normalize_reason_entry(reason: str, metrics: dict | None = None) -> dict:
    code = reason_code_for_internal_reason(reason)
    metrics = dict(metrics or {})
    text = REASON_CATALOG.get(code)
    if code == "LOW_LIQUIDITY":
        if "avg_daily_volume_30d" in metrics and "min_avg_daily_volume" in metrics:
            text = (
                f"Avg Daily Volume {metrics['avg_daily_volume_30d']:.2f} "
                f"liegt unter {metrics['min_avg_daily_volume']:.2f}."
            )
        else:
            text = text or "Liquiditaet ist zu schwach."
    elif code == "DEAD_MARKET_RISK":
        if "estimated_sellable_units_90d" in metrics:
            text = (
                f"Realistisch verkaufbare Menge ist zu klein "
                f"({metrics['estimated_sellable_units_90d']:.2f} in 90d)."
            )
        else:
            text = text or "Der Markt wirkt fuer die geplante Position zu duenn."
    elif code == "THIN_SELL_WALL":
        queue = _safe_int(metrics.get("queue_ahead_units", 0))
        text = (
            f"Queue/Wall vor dem Exit ist zu schwer ({queue} Einheiten vor uns)."
            if queue > 0
            else (text or "Sell-Wall oder Queue am Ziel ist problematisch.")
        )
    elif code == "WEAK_EXIT_CONFIDENCE":
        liq = _safe_float(metrics.get("liquidity_confidence", 0.0))
        exit_conf = _safe_float(metrics.get("exit_confidence", 0.0))
        text = f"Exit-Confidence {exit_conf:.2f}, Liquidity-Confidence {liq:.2f}."
    elif code == "CAPITAL_LOCK_RISK":
        days = _safe_float(metrics.get("expected_days_to_sell", 0.0))
        max_days = _safe_float(metrics.get("max_expected_days_to_sell", metrics.get("strict_max_expected_days_to_sell", 0.0)))
        text = f"Erwartete Sell-Dauer {days:.1f}d liegt ueber dem Limit {max_days:.1f}d."
    elif code == "WEAK_INSTANT_EXIT":
        depth = _safe_int(metrics.get("dest_buy_depth_units", metrics.get("max_units", 0)))
        text = f"Instant-Exit hat zu wenig echte Gegenseite ({depth} Einheiten)."
    elif code == "HIGH_TRANSPORT_COST":
        ship = _safe_float(metrics.get("estimated_shipping_total", 0.0))
        text = f"Transportkosten von {_fmt_isk_short(ship)} machen den Trade unattraktiv."
    elif code == "THIN_TOP_OF_BOOK":
        ratio = _safe_float(metrics.get("top_of_book_volume_ratio", 0.0))
        gap = _safe_float(metrics.get("price_gap_after_top_levels", 0.0))
        text = f"Top-of-Book ist zu duenn (ratio {ratio:.2f}, gap {gap:.2f})."
    elif code == "UNUSABLE_DEPTH":
        depth_ratio = _safe_float(metrics.get("usable_depth_ratio", 0.0))
        usable = _safe_int(metrics.get("usable_depth_at_confidence_price", 0))
        text = f"Nutzbare Tiefe ist zu klein ({usable} Einheiten, ratio {depth_ratio:.2f})."
    elif code == "FAKE_SPREAD_RISK":
        top_profit = _safe_float(metrics.get("profit_at_top_of_book", 0.0))
        cons_profit = _safe_float(metrics.get("profit_at_conservative_executable_price", 0.0))
        text = f"Paper-Profit {_fmt_isk_short(top_profit)} kollabiert konservativ auf {_fmt_isk_short(cons_profit)}."
    elif code == "EXTREME_REFERENCE_DEVIATION":
        deviation = _safe_float(metrics.get("reference_price_deviation", 0.0))
        text = f"Preisabweichung zur Referenz liegt bei {deviation * 100.0:.1f}%."
    elif code == "DEPTH_COLLAPSE":
        decay = _safe_float(metrics.get("depth_decay", 0.0))
        text = f"Ordertiefe bricht zu schnell weg (depth_decay {decay:.2f})."
    elif code == "ORDERBOOK_CONCENTRATION":
        conc = _safe_float(metrics.get("order_concentration_ratio", 0.0))
        text = f"Einzelne Orders dominieren das Orderbuch (ratio {conc:.2f})."
    elif code == "LOW_PROFIT_AFTER_COSTS":
        profit = _safe_float(metrics.get("expected_realized_profit_90d", metrics.get("max_profit_total", metrics.get("profit_per_unit", 0.0))))
        text = f"Nach Kosten bleibt nur {_fmt_isk_short(profit)} konservativer Profit."
    elif code == "HISTORY_ONLY_SIGNAL":
        text = text or "Die Aussage stuetzt sich zu stark auf schwache History-/Fallback-Signale."
    elif code == "NO_SHIPPING_MODEL":
        text = text or "Ohne Shipping-Modell wird die Route blockiert."
    elif code == "NO_ACTIONABLE_CANDIDATES":
        text = text or "Nach allen Filtern bleiben keine brauchbaren Kandidaten uebrig."
    elif code == "WEAK_PRICE_BASIS":
        text = text or "Der geplante Zielpreis ist nicht belastbar genug abgeleitet."
    elif code == "NO_ORDERBOOK":
        text = text or "Orderbuchdaten reichen fuer eine belastbare Aussage nicht aus."
    elif code == "EXCLUDED_TYPE":
        text = text or "Dieser Typ wurde per Konfiguration ausgeschlossen."
    elif code == "EXCLUDED_NAME_KEYWORD":
        text = text or "Der Typ wurde ueber Name-Filter ausgeschlossen."
    return build_reason_entry(code, text=text, metrics=metrics, severity="error" if code in {"NO_SHIPPING_MODEL", "NO_ACTIONABLE_CANDIDATES"} else "info")


def _dedupe_reasons(entries: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for entry in entries:
        code = str(entry.get("code", "") or "")
        text = str(entry.get("text", "") or "")
        marker = (code, text)
        if not code or marker in seen:
            continue
        seen.add(marker)
        out.append(entry)
    return out


def _build_confidence_contributors(record: Any) -> list[dict]:
    raw_exit = _clamp01(_safe_float(_record_get(record, "raw_exit_confidence", _record_get(record, "exit_confidence", 0.0))))
    raw_liq = _clamp01(_safe_float(_record_get(record, "raw_liquidity_confidence", _record_get(record, "liquidity_confidence", 0.0))))
    raw_transport = _clamp01(_safe_float(_record_get(record, "raw_transport_confidence", _record_get(record, "transport_confidence", 1.0))))
    raw_overall = _clamp01(_safe_float(_record_get(record, "raw_overall_confidence", _record_get(record, "raw_confidence", _record_get(record, "overall_confidence", 0.0)))))
    calibrated_overall = _clamp01(_safe_float(_record_get(record, "calibrated_overall_confidence", _record_get(record, "calibrated_confidence", raw_overall))))
    decision_overall = _clamp01(_safe_float(_record_get(record, "decision_overall_confidence", calibrated_overall)))
    return [
        build_contributor("exit_confidence_raw", value=raw_exit, effect=raw_exit, text=f"Roher Exit-Confidence-Wert {raw_exit:.2f}."),
        build_contributor("liquidity_confidence_raw", value=raw_liq, effect=raw_liq, text=f"Roher Liquidity-Confidence-Wert {raw_liq:.2f}."),
        build_contributor("transport_confidence_raw", value=raw_transport, effect=raw_transport, text=f"Roher Transport-Confidence-Wert {raw_transport:.2f}."),
        build_contributor("overall_confidence_raw", value=raw_overall, effect=raw_overall, text=f"Rohes Gesamt-Confidence-Minimum {raw_overall:.2f}."),
        build_contributor(
            "overall_confidence_calibration_delta",
            value=calibrated_overall,
            effect=calibrated_overall - raw_overall,
            text=f"Kalibrierung verschiebt die Overall-Confidence von {raw_overall:.2f} auf {calibrated_overall:.2f}.",
        ),
        build_contributor(
            "overall_confidence_for_decision",
            value=decision_overall,
            effect=decision_overall - calibrated_overall,
            text=f"Fuer die Entscheidung wird {decision_overall:.2f} verwendet.",
        ),
    ]


def format_reason_digest(reasons: list[dict], limit: int = 3) -> str:
    codes = [str(r.get("code", "") or "").strip() for r in list(reasons or []) if str(r.get("code", "") or "").strip()]
    if not codes:
        return ""
    unique: list[str] = []
    for code in codes:
        if code not in unique:
            unique.append(code)
    digest = ", ".join(unique[: max(1, int(limit or 3))])
    if len(unique) > max(1, int(limit or 3)):
        digest += ", ..."
    return digest


def build_pick_score_breakdown(record: Any, *, max_liq_days: float) -> tuple[float, list[dict]]:
    expected_profit = max(
        0.0,
        _safe_float(_record_get(record, "expected_realized_profit_90d", _record_get(record, "expected_profit_90d", _record_get(record, "profit", 0.0)))),
    )
    per_m3 = max(
        0.0,
        _safe_float(_record_get(record, "expected_realized_profit_per_m3_90d", _record_get(record, "expected_profit_per_m3_90d", _record_get(record, "profit_per_m3", 0.0)))),
    )
    confidence = _clamp01(_safe_float(_record_get(record, "decision_overall_confidence", _record_get(record, "calibrated_overall_confidence", _record_get(record, "overall_confidence", 0.0)))))
    expected_days = max(0.0, _safe_float(_record_get(record, "expected_days_to_sell", 0.0)))
    transport_conf = _clamp01(_safe_float(_record_get(record, "raw_transport_confidence", _record_get(record, "transport_confidence", 1.0))))
    exit_type = str(_record_get(record, "exit_type", "instant") or "instant").strip().lower()
    used_fallback = bool(_record_get(record, "used_volume_fallback", False))
    market_plausibility_score = _clamp01(_safe_float(_record_get(record, "market_plausibility_score", 1.0)))

    base_profit_score = expected_profit
    confidence_factor = 0.70 + (0.30 * confidence)
    days_penalty = 1.0 + (expected_days / max(1.0, float(max_liq_days or 1.0))) if max_liq_days > 0 else 1.0
    liquidity_factor = 1.0 / max(1.0, days_penalty)
    transport_factor = 0.90 + (0.10 * transport_conf)
    market_plausibility_factor = 0.50 + (0.50 * market_plausibility_score)
    stale_market_factor = 0.90 if used_fallback else 1.0
    speculative_factor = 1.0 if exit_type == "instant" else (0.96 if exit_type == "planned" else 0.90)

    after_conf = base_profit_score * confidence_factor
    after_liq = after_conf * liquidity_factor
    after_transport = after_liq * transport_factor
    after_plaus = after_transport * market_plausibility_factor
    after_stale = after_plaus * stale_market_factor
    after_spec = after_stale * speculative_factor
    density_bonus = per_m3 * 0.05
    final_score = after_spec + density_bonus

    contributors = [
        build_contributor("base_profit_score", value=base_profit_score, effect=base_profit_score, text=f"Start mit konservativem Erwartungsprofit {_fmt_isk_short(base_profit_score)}."),
        build_contributor(
            "confidence_penalty",
            value=confidence_factor,
            effect=after_conf - base_profit_score,
            text=f"Confidence-Faktor {confidence_factor:.3f} auf Basis von {confidence:.2f}.",
        ),
        build_contributor(
            "liquidity_adjustment",
            value=liquidity_factor,
            effect=after_liq - after_conf,
            text=f"Liquiditaetsfaktor {liquidity_factor:.3f} bei erwarteten {expected_days:.1f}d Sell-Dauer.",
        ),
        build_contributor(
            "transport_adjustment",
            value=transport_factor,
            effect=after_transport - after_liq,
            text=f"Transport-Faktor {transport_factor:.3f} bei Transport-Confidence {transport_conf:.2f}.",
        ),
        build_contributor(
            "market_plausibility_adjustment",
            value=market_plausibility_factor,
            effect=after_plaus - after_transport,
            text=f"Orderbuch-Plausibilitaetsfaktor {market_plausibility_factor:.3f} bei Score {market_plausibility_score:.2f}.",
        ),
        build_contributor(
            "stale_market_penalty",
            value=stale_market_factor,
            effect=after_stale - after_plaus,
            text="Fallback-/History-only-Signal reduziert den Score." if used_fallback else "Kein zusaetzlicher Stale-Market-Abzug.",
        ),
        build_contributor(
            "speculative_penalty",
            value=speculative_factor,
            effect=after_spec - after_stale,
            text=f"Exit-Typ {exit_type} erzeugt Faktor {speculative_factor:.3f}.",
        ),
        build_contributor("concentration_penalty", value=1.0, effect=0.0, text="Kein separater Single-Pick-Konzentrationsabzug."),
        build_contributor("density_bonus", value=per_m3, effect=density_bonus, text=f"Dichte-Bonus aus {_fmt_isk_short(per_m3)} pro m3."),
    ]
    return float(final_score), contributors


def build_candidate_explainability(record: Any, *, max_liq_days: float | None = None) -> dict:
    exit_type = str(_record_get(record, "exit_type", "instant") or "instant").strip().lower()
    expected_profit = max(
        0.0,
        _safe_float(_record_get(record, "expected_realized_profit_90d", _record_get(record, "expected_profit_90d", _record_get(record, "profit", 0.0)))),
    )
    full_sell_profit = max(0.0, _safe_float(_record_get(record, "gross_profit_if_full_sell", _record_get(record, "profit", expected_profit))))
    expected_days = max(0.0, _safe_float(_record_get(record, "expected_days_to_sell", 0.0)))
    expected_sold = max(0.0, _safe_float(_record_get(record, "expected_units_sold_90d", 0.0)))
    expected_unsold = max(0.0, _safe_float(_record_get(record, "expected_units_unsold_90d", 0.0)))
    qty = max(0.0, _safe_float(_record_get(record, "qty", _record_get(record, "max_units", 0))))
    fill_probability = _clamp01(_safe_float(_record_get(record, "fill_probability", 0.0)))
    liquidity_conf = _clamp01(_safe_float(_record_get(record, "liquidity_confidence", fill_probability)))
    exit_conf = _clamp01(_safe_float(_record_get(record, "exit_confidence", liquidity_conf)))
    raw_conf = _clamp01(_safe_float(_record_get(record, "raw_confidence", _record_get(record, "raw_overall_confidence", _record_get(record, "overall_confidence", exit_conf)))))
    calibrated_conf = _clamp01(_safe_float(_record_get(record, "calibrated_confidence", _record_get(record, "calibrated_overall_confidence", raw_conf))))
    decision_conf = _clamp01(_safe_float(_record_get(record, "decision_overall_confidence", calibrated_conf)))
    transport_conf = _clamp01(_safe_float(_record_get(record, "raw_transport_confidence", _record_get(record, "transport_confidence", 1.0))))
    target_conf = _clamp01(_safe_float(_record_get(record, "target_price_confidence", 0.0)))
    queue_ahead = max(0, _safe_int(_record_get(record, "queue_ahead_units", 0)))
    buy_discount = _safe_float(_record_get(record, "buy_discount_vs_ref", 0.0))
    est_transport_cost = max(0.0, _safe_float(_record_get(record, "estimated_transport_cost", _record_get(record, "transport_cost", 0.0))))
    used_fallback = bool(_record_get(record, "used_volume_fallback", False))
    calibration_warning = str(_record_get(record, "calibration_warning", "") or "").strip()
    blocked_transport = str(_record_get(record, "transport_cost_confidence", _record_get(record, "cost_model_confidence", "")) or "").strip().lower() == "blocked"
    market_plausibility = _record_get(record, "market_plausibility", {})
    if not isinstance(market_plausibility, dict):
        market_plausibility = {}
    market_plausibility_score = _clamp01(_safe_float(_record_get(record, "market_plausibility_score", market_plausibility.get("market_plausibility_score", 1.0))))
    manipulation_risk_score = _clamp01(_safe_float(_record_get(record, "manipulation_risk_score", market_plausibility.get("manipulation_risk_score", 0.0))))

    positive_reasons: list[dict] = []
    negative_reasons: list[dict] = []
    warnings: list[dict] = []
    gating_failures: list[dict] = []

    sold_ratio = (expected_sold / max(1.0, qty)) if qty > 0 else 0.0
    transport_ratio = (est_transport_cost / max(expected_profit, 1.0)) if expected_profit > 0 else 0.0

    if expected_profit > 0.0 and (expected_profit >= max(1_000_000.0, full_sell_profit * 0.50) or decision_conf >= 0.70):
        positive_reasons.append(build_reason_entry("STRONG_EXPECTED_PROFIT", text=f"Erwarteter Realized Profit: {_fmt_isk_short(expected_profit)}."))
    if exit_type == "instant" and fill_probability >= 0.85:
        positive_reasons.append(build_reason_entry("STRONG_INSTANT_EXIT", text=f"Instant-Exit mit Fill-Proxy {fill_probability:.2f}."))
    elif sold_ratio >= 0.65:
        positive_reasons.append(build_reason_entry("REALISTIC_EXIT_VOLUME", text=f"Erwartet verkauft: {expected_sold:.2f} von {max(qty, expected_sold):.2f}."))
    if transport_conf >= 0.75 and transport_ratio <= 0.25:
        positive_reasons.append(build_reason_entry("LOW_SHIPPING_COST", text=f"Transportkosten nur {_fmt_isk_short(est_transport_cost)} gegen {_fmt_isk_short(expected_profit)} Erwartungsprofit."))
    if buy_discount >= 0.05:
        positive_reasons.append(build_reason_entry("SOLID_JITA_BUY", text=f"Einkauf liegt {buy_discount * 100.0:.1f}% unter Referenz."))
    if target_conf >= 0.75:
        positive_reasons.append(build_reason_entry("RELIABLE_PRICE_BASIS", text=f"Zielpreis-Confidence {target_conf:.2f}."))
    if expected_days > 0.0 and expected_days <= 14.0:
        positive_reasons.append(build_reason_entry("FAST_LIQUIDATION", text=f"Erwartete Liquidation in {expected_days:.1f} Tagen."))
    if decision_conf >= 0.75:
        positive_reasons.append(build_reason_entry("HIGH_CONFIDENCE", text=f"Entscheidungs-Confidence {decision_conf:.2f}."))

    if blocked_transport or transport_conf <= 0.05:
        gating_failures.append(build_reason_entry("NO_SHIPPING_MODEL", text="Ohne belastbares Shipping-Modell bleibt der Trade blockiert."))
    elif transport_conf < 0.75:
        negative_reasons.append(build_reason_entry("HIGH_TRANSPORT_RISK", text=f"Transport-Confidence nur {transport_conf:.2f}."))
    if liquidity_conf < 0.45 or sold_ratio < 0.50:
        negative_reasons.append(build_reason_entry("LOW_LIQUIDITY", text=f"Erwartete Verkaufsquote {sold_ratio:.2f}, Liquidity-Confidence {liquidity_conf:.2f}."))
    if expected_unsold > max(1.0, qty * 0.25):
        negative_reasons.append(build_reason_entry("DEAD_MARKET_RISK", text=f"Unsold-Rest nach 90d: {expected_unsold:.2f} Einheiten."))
    if queue_ahead > max(10, int(expected_sold)):
        negative_reasons.append(build_reason_entry("THIN_SELL_WALL", text=f"Queue vor dem Exit: {queue_ahead} Einheiten."))
    if exit_conf < 0.50:
        negative_reasons.append(build_reason_entry("WEAK_EXIT_CONFIDENCE", text=f"Exit-Confidence nur {exit_conf:.2f}."))
    if exit_type != "instant" and target_conf < 0.50:
        negative_reasons.append(build_reason_entry("WEAK_PRICE_BASIS", text=f"Zielpreis-Confidence nur {target_conf:.2f}."))
    if expected_days > 30.0 or (max_liq_days is not None and expected_days > float(max_liq_days)):
        limit_days = float(max_liq_days) if max_liq_days is not None else 30.0
        negative_reasons.append(build_reason_entry("CAPITAL_LOCK_RISK", text=f"Erwartete Sell-Dauer {expected_days:.1f}d gegen Limit {limit_days:.1f}d."))
    if exit_type == "speculative":
        negative_reasons.append(build_reason_entry("SPECULATIVE_EXIT", text="Exit ist nicht instant und nicht sauber planned modelliert."))
    for flag in list(market_plausibility.get("flags", []) or []):
        if str(flag):
            negative_reasons.append(build_reason_entry(str(flag), metrics=market_plausibility))

    if used_fallback:
        warnings.append(build_reason_entry("HISTORY_ONLY_SIGNAL", text="Menge/Absatz wird ueber Fallback- oder schwache History-Signale abgeschaetzt.", severity="warning"))
    if calibration_warning:
        warnings.append(build_reason_entry("CALIBRATION_WEAK_DATA", text=calibration_warning, severity="warning"))
    if raw_conf - calibrated_conf >= 0.10:
        warnings.append(build_reason_entry("CONFIDENCE_DOWNGRADED", text=f"Kalibrierung senkt Confidence von {raw_conf:.2f} auf {calibrated_conf:.2f}.", severity="warning"))
    if manipulation_risk_score >= 0.45 or market_plausibility_score <= 0.65:
        warnings.append(
            build_reason_entry(
                "FAKE_SPREAD_RISK" if "FAKE_SPREAD_RISK" in set(market_plausibility.get("flags", []) or []) else "THIN_TOP_OF_BOOK",
                text=(
                    f"Market-Plausibility {market_plausibility_score:.2f}, Manipulation-Risk {manipulation_risk_score:.2f}."
                ),
                severity="warning",
                metrics=market_plausibility,
            )
        )

    pruned_reason = gating_failures[0] if gating_failures else None
    score_value = None
    score_contributors: list[dict] = []
    if max_liq_days is not None:
        score_value, score_contributors = build_pick_score_breakdown(record, max_liq_days=float(max_liq_days))

    return {
        "positive_reasons": _dedupe_reasons(positive_reasons),
        "negative_reasons": _dedupe_reasons(negative_reasons),
        "gating_failures": _dedupe_reasons(gating_failures),
        "score_contributors": score_contributors,
        "confidence_contributors": _build_confidence_contributors(record),
        "pruned_reason": pruned_reason,
        "warnings": _dedupe_reasons(warnings),
        "explainability_score": float(score_value) if score_value is not None else None,
    }


def ensure_record_explainability(record: Any, *, max_liq_days: float | None = None) -> Any:
    explain = build_candidate_explainability(record, max_liq_days=max_liq_days)
    for key, value in explain.items():
        _record_set(record, key, value)
    return record


def build_route_explainability(
    route: dict,
    *,
    base_profit_score: float,
    route_confidence: float,
    liquidation_speed: float,
    transport_confidence: float,
    concentration_penalty: float,
    stale_market_penalty: float,
    speculative_penalty: float,
    risk_adjusted_score: float,
    average_expected_days_to_sell: float,
    capital_lock_risk: float,
    prune_reason: str,
) -> dict:
    picks = list(route.get("picks", []) or [])
    cargo_used = max(0.0, _safe_float(route.get("m3_used", route.get("total_route_m3", 0.0))))
    profit_per_m3 = (base_profit_score / cargo_used) if cargo_used > 0 else 0.0

    concentration_factor = max(0.0, 1.0 - (concentration_penalty * 0.75))
    stale_market_factor = max(0.0, 1.0 - stale_market_penalty)
    speculative_factor = max(0.0, 1.0 - speculative_penalty)
    after_conf = base_profit_score * route_confidence
    after_liq = after_conf * liquidation_speed
    after_conc = after_liq * concentration_factor
    after_stale = after_conc * stale_market_factor
    after_spec = after_stale * speculative_factor
    after_transport = after_spec * transport_confidence

    positive_reasons: list[dict] = []
    negative_reasons: list[dict] = []
    warnings: list[dict] = []
    gating_failures: list[dict] = []

    if base_profit_score > 0.0:
        positive_reasons.append(build_reason_entry("STRONG_ROUTE_PROFIT", text=f"Route liefert {_fmt_isk_short(base_profit_score)} konservativen Erwartungsprofit."))
    if route_confidence >= 0.70:
        positive_reasons.append(build_reason_entry("STRONG_ROUTE_CONFIDENCE", text=f"Route-Confidence {route_confidence:.2f}."))
    if transport_confidence >= 0.85:
        positive_reasons.append(build_reason_entry("RELIABLE_TRANSPORT_MODEL", text=f"Transport-Confidence {transport_confidence:.2f}."))
    if profit_per_m3 >= 50_000.0:
        positive_reasons.append(build_reason_entry("GOOD_PROFIT_TO_CARGO", text=f"Profit pro m3: {_fmt_isk_short(profit_per_m3)}."))

    if concentration_penalty >= 0.15:
        negative_reasons.append(build_reason_entry("EXCESSIVE_CONCENTRATION", text=f"Top-Pick-Dominanz erzeugt Konzentrationspenalty {concentration_penalty:.2f}."))
    if average_expected_days_to_sell > 25.0:
        negative_reasons.append(build_reason_entry("SLOW_ROUTE_LIQUIDATION", text=f"Durchschnittliche Sell-Dauer {average_expected_days_to_sell:.1f}d."))
    if transport_confidence < 0.75:
        negative_reasons.append(build_reason_entry("HIGH_TRANSPORT_RISK", text=f"Transport-Confidence nur {transport_confidence:.2f}."))
    if speculative_penalty >= 0.08:
        negative_reasons.append(build_reason_entry("TOO_MANY_SPECULATIVE_PICKS", text="Zu viele nicht-instantane Picks druecken den Score."))
    if stale_market_penalty >= 0.05:
        warnings.append(build_reason_entry("STALE_MARKET_SIGNAL", text="Mehrere Picks basieren auf schwachen History-/Fallback-Signalen.", severity="warning"))
    calibration_warning = str(route.get("calibration_warning", "") or "").strip()
    if calibration_warning:
        warnings.append(build_reason_entry("CALIBRATION_WEAK_DATA", text=calibration_warning, severity="warning"))

    pruned_reason = None
    if prune_reason:
        pruned_reason = normalize_reason_entry(prune_reason)
        gating_failures.append(pruned_reason)
    elif not picks:
        pruned_reason = build_reason_entry("NO_ACTIONABLE_CANDIDATES", text="Diese Route hat keine actionable Picks.")
        gating_failures.append(pruned_reason)

    score_contributors = [
        build_contributor("base_profit_score", value=base_profit_score, effect=base_profit_score, text=f"Start mit {_fmt_isk_short(base_profit_score)} konservativem Erwartungsprofit."),
        build_contributor("confidence_penalty", value=route_confidence, effect=after_conf - base_profit_score, text=f"Route-Confidence {route_confidence:.2f} wirkt direkt auf den Score."),
        build_contributor("liquidity_adjustment", value=liquidation_speed, effect=after_liq - after_conf, text=f"Liquidation-Speed-Faktor {liquidation_speed:.3f}."),
        build_contributor("concentration_penalty", value=concentration_factor, effect=after_conc - after_liq, text=f"Konzentrationsfaktor {concentration_factor:.3f}."),
        build_contributor("stale_market_penalty", value=stale_market_factor, effect=after_stale - after_conc, text=f"Stale-Market-Faktor {stale_market_factor:.3f}."),
        build_contributor("speculative_penalty", value=speculative_factor, effect=after_spec - after_stale, text=f"Speculative-Faktor {speculative_factor:.3f}."),
        build_contributor("transport_adjustment", value=transport_confidence, effect=after_transport - after_spec, text=f"Transport-Faktor {transport_confidence:.3f}."),
    ]
    confidence_contributors = [
        build_contributor("route_confidence_for_decision", value=route_confidence, effect=route_confidence, text=f"Entscheidungs-Route-Confidence {route_confidence:.2f}."),
        build_contributor("transport_confidence", value=transport_confidence, effect=transport_confidence, text=f"Transport-Confidence {transport_confidence:.2f}."),
        build_contributor("capital_lock_risk", value=capital_lock_risk, effect=-capital_lock_risk, text=f"Capital-Lock-Risk {capital_lock_risk:.2f}."),
    ]

    return {
        "positive_reasons": _dedupe_reasons(positive_reasons),
        "negative_reasons": _dedupe_reasons(negative_reasons),
        "gating_failures": _dedupe_reasons(gating_failures),
        "score_contributors": score_contributors,
        "confidence_contributors": confidence_contributors,
        "pruned_reason": pruned_reason,
        "warnings": _dedupe_reasons(warnings),
        "route_explainability_score": float(risk_adjusted_score),
    }


def build_rejected_candidate_table(explain: dict | None, *, limit: int = 10) -> list[dict]:
    if not isinstance(explain, dict):
        return []
    rejected = list(explain.get("rejected", []) or [])
    enriched: list[dict] = []
    for entry in rejected:
        if not isinstance(entry, dict):
            continue
        metrics = dict(entry.get("metrics", {}) or {})
        normalized = normalize_reason_entry(str(entry.get("reason_code", entry.get("reason", "")) or ""), metrics)
        nominal_profit_proxy = 0.0
        for key in (
            "gross_profit_if_full_sell",
            "expected_realized_profit_90d",
            "max_profit_total",
            "expected_units_sold_90d",
            "profit_per_unit",
        ):
            nominal_profit_proxy = max(nominal_profit_proxy, _safe_float(metrics.get(key, 0.0)))
        enriched.append({
            "type_id": _safe_int(entry.get("type_id", 0)),
            "name": str(entry.get("name", "") or ""),
            "reason": str(entry.get("reason", "") or ""),
            "reason_code": str(normalized.get("code", "") or ""),
            "reason_text": str(normalized.get("text", "") or ""),
            "pruned_reason": normalized,
            "gating_failures": [normalized],
            "negative_reasons": [normalized],
            "warnings": [],
            "metrics": metrics,
            "nominal_profit_proxy": float(nominal_profit_proxy),
        })
    enriched.sort(key=lambda item: (float(item.get("nominal_profit_proxy", 0.0)), int(item.get("type_id", 0))), reverse=True)
    return enriched[: max(1, int(limit or 10))]


__all__ = [
    "REASON_CATALOG",
    "INTERNAL_REASON_CODES",
    "build_candidate_explainability",
    "build_contributor",
    "build_pick_score_breakdown",
    "build_reason_entry",
    "build_rejected_candidate_table",
    "build_route_explainability",
    "ensure_record_explainability",
    "format_reason_digest",
    "normalize_reason_entry",
    "reason_code_for_internal_reason",
]
