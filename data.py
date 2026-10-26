"""Оставлен ради старых импортов."""
from core.market import fetch_moex_candles, fetch_moex_forts, fetch_moex_ims, load_api, load_go, load_lists, load_marketdata, to_float, vlookup
from core.config import MARGIN_COL_MAP
from core.calc import get_instrument
from core import state, storage

def get_margin(go_df, ticker, risk_level, direction) -> float:
    cl, cs = MARGIN_COL_MAP.get(risk_level, (4, 5))
    return to_float(vlookup(go_df, ticker, cl if direction == "LONG" else cs))

def load_trend_cache() -> dict:
    return state.get_state()

def save_trend_cache(key, value):
    if key == "_global": state.get_state()["global"].update(value)
    else: state.get_state()["tickers"][key] = value
    state.autosave(force=True)

def export_cache_to_string() -> str:
    return storage.dumps(state.get_state())

def import_cache_from_string(text: str) -> bool:
    parsed = storage.loads(text)
    if parsed is None: return False
    state.replace_state(parsed)
    return True
