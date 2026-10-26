"""Персистентность: схема v2, миграция с v1, атомарная запись, debounce."""
from __future__ import annotations

import json, os, re, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import SCHEMA_VERSION, DEFAULT_GLOBAL, TIMEFRAMES

CACHE_DIR = Path(os.getenv("FUTURES_CACHE_DIR", ".cache"))
PROFILE_RE = re.compile(r"[^A-Za-z0-9_\-а-яА-Я ]+")

def default_ticker_state() -> dict:
    return {
        "market": {"trend": "вверх", "wave": "вверх", "tendency": "вверх", "trade_type": "трендовая"},
        "charts": {tf: {"channel": [], "fib": [], "zigzag": [], "levels": []} for tf in TIMEFRAMES},
        "deal": {"direction": "LONG", "sl": None, "tp": None, "entries": []},
        "note": "",
        "updated_at": None,
    }

def default_state() -> dict:
    return {"version": SCHEMA_VERSION, "saved_at": None, "global": dict(DEFAULT_GLOBAL), "tickers": {}}

def _norm_point(p: Any) -> list | None:
    try:
        if isinstance(p, dict):
            x, y = p.get("x"), p.get("y")
        else:
            x, y = p[0], p[1]
        if x is None or y is None: return None
        return [str(x), round(float(y), 8)]
    except Exception:
        return None

def normalize_points(points) -> list:
    return [q for q in (_norm_point(p) for p in (points or [])) if q]

def _normalize_ticker(raw: dict) -> dict:
    base = default_ticker_state()
    if not isinstance(raw, dict): return base
    base["market"].update({k: v for k, v in (raw.get("market") or {}).items() if v})
    for tf, tools in (raw.get("charts") or {}).items():
        if tf not in base["charts"]: continue
        for tool, pts in (tools or {}).items():
            if tool == "levels":
                base["charts"][tf]["levels"] = sorted({round(float(v), 8) for v in (pts or []) if v is not None})
            elif tool in base["charts"][tf]:
                base["charts"][tf][tool] = normalize_points(pts)
    deal = raw.get("deal") or {}
    base["deal"]["direction"] = deal.get("direction") or "LONG"
    base["deal"]["sl"] = deal.get("sl")
    base["deal"]["tp"] = deal.get("tp")
    base["deal"]["entries"] = [
        {"price": float(e.get("price", 0) or 0), "qty": int(e.get("qty", 0) or 0), "note": str(e.get("note", "") or "")}
        for e in (deal.get("entries") or []) if e
    ]
    base["note"] = str(raw.get("note", "") or "")
    base["updated_at"] = raw.get("updated_at")
    return base

_LEGACY_MAP = {
    "d1_manual_pts": ("D1", "channel"), "d1_fib_pts": ("D1", "fib"),
    "h1_tend_pts": ("H1", "zigzag"), "h1_fib_pts": ("H1", "fib"),
    "h1_levels": ("H1", "levels"), "m10_zig_pts": ("M10", "zigzag"),
}

def _migrate_v1(raw: dict) -> dict:
    st_ = default_state()
    g = raw.get("_global") or {}
    st_["global"].update({k: v for k, v in g.items() if k in DEFAULT_GLOBAL})
    st_["global"]["active_tickers"] = list(raw.get("_active_tickers") or [])
    market = raw.get("_market_state") or {}

    for key, val in raw.items():
        if key.startswith("_") or not isinstance(val, dict): continue
        t = default_ticker_state()
        for legacy_key, (tf, tool) in _LEGACY_MAP.items():
            if legacy_key in val:
                t["charts"][tf][tool] = (
                    sorted({float(x) for x in val[legacy_key] or []}) if tool == "levels" else normalize_points(val[legacy_key])
                )
        t["deal"]["direction"] = val.get("direction") or "LONG"
        t["deal"]["sl"] = val.get("sl_price")
        t["deal"]["tp"] = val.get("tp_price")
        t["deal"]["entries"] = [
            {"price": float(e.get("price", e.get("Цена", 0)) or 0),
             "qty": int(e.get("qty", e.get("Кол-во", 0)) or 0),
             "note": str(e.get("note", e.get("Комментарий", "")) or "")}
            for e in (val.get("entries") or [])
        ]
        if key in market: t["market"].update(market[key])
        st_["tickers"][key] = t
    return st_

def migrate(raw: dict) -> dict:
    if not isinstance(raw, dict): return default_state()
    version = raw.get("version")
    if version is None: return _migrate_v1(raw)
    st_ = default_state()
    st_["global"].update({k: v for k, v in (raw.get("global") or {}).items() if k in DEFAULT_GLOBAL})
    st_["tickers"] = {k: _normalize_ticker(v) for k, v in (raw.get("tickers") or {}).items()}
    st_["saved_at"] = raw.get("saved_at")
    return st_

def profile_path(profile: str) -> Path:
    safe = PROFILE_RE.sub("", profile or "default").strip() or "default"
    return CACHE_DIR / f"{safe}.json"

def list_profiles() -> list[str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(p.stem for p in CACHE_DIR.glob("*.json")) or ["default"]

def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def load_profile(profile: str = "default") -> dict:
    path = profile_path(profile)
    if not path.exists(): return default_state()
    try:
        with path.open("r", encoding="utf-8") as f:
            return migrate(json.load(f))
    except Exception:
        bad = path.with_suffix(f".corrupt-{int(time.time())}.json")
        try: path.rename(bad)
        except Exception: pass
        return default_state()

def dumps(state: dict, pretty: bool = True) -> str:
    state = dict(state)
    state["version"] = SCHEMA_VERSION
    state["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return json.dumps(state, ensure_ascii=False, indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), sort_keys=True)

def save_profile(state: dict, profile: str = "default") -> None:
    _atomic_write(profile_path(profile), dumps(state))

def loads(text: str) -> dict | None:
    try: return migrate(json.loads(text))
    except Exception: return None
