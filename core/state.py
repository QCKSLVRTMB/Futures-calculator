from __future__ import annotations

import hashlib
import time
import streamlit as st

from core import storage
from core.config import DEFAULT_GLOBAL

_KEY = "app_state"
_HASH = "_app_state_hash"
_TS = "_app_state_saved_ts"
SAVE_DEBOUNCE_SEC = 1.5

def profile() -> str:
    return st.session_state.get("sb_profile", "default")

def get_state() -> dict:
    if _KEY not in st.session_state:
        st.session_state[_KEY] = storage.load_profile(profile())
        st.session_state[_HASH] = _hash(st.session_state[_KEY])
        st.session_state[_TS] = 0.0
    return st.session_state[_KEY]

def replace_state(new_state: dict, persist: bool = True) -> None:
    st.session_state[_KEY] = new_state
    st.session_state[_HASH] = ""
    if persist: autosave(force=True)

def g(key: str, default=None):
    return get_state()["global"].get(key, DEFAULT_GLOBAL.get(key, default))

def set_global(key: str, value) -> None:
    get_state()["global"][key] = value

def active_tickers() -> list[str]:
    return list(g("active_tickers") or [])

def set_active_tickers(tickers: list[str]) -> None:
    uniq = list(dict.fromkeys(t.strip().upper() for t in tickers if t and t.strip()))
    set_global("active_tickers", uniq)
    for t in uniq: ticker(t)

def ticker(name: str) -> dict:
    tickers = get_state()["tickers"]
    if name not in tickers:
        tickers[name] = storage.default_ticker_state()
    return tickers[name]

def drop_ticker(name: str) -> None:
    get_state()["tickers"].pop(name, None)
    set_global("active_tickers", [t for t in active_tickers() if t != name])

def points(tkr: str, tf: str, tool: str) -> list:
    return ticker(tkr)["charts"].setdefault(tf, {}).setdefault(tool, [])

def _hash(state: dict) -> str:
    return hashlib.md5(storage.dumps(state, pretty=False).encode()).hexdigest()

def autosave(force: bool = False) -> bool:
    state = get_state()
    now = time.time()
    if not force and now - st.session_state.get(_TS, 0.0) < SAVE_DEBOUNCE_SEC:
        return False
    h = _hash(state)
    if not force and h == st.session_state.get(_HASH):
        return False
    storage.save_profile(state, profile())
    st.session_state[_HASH] = h
    st.session_state[_TS] = now
    return True
