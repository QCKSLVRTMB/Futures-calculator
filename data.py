import pandas as pd
import streamlit as st
import requests
from datetime import datetime, timedelta
import json
import os

SHEET_ID = "ВАШ_ID_ТАБЛИЦЫ_ИЗ_ССЫЛКИ"
GIDS = {
    "API": "0",
    "MARKETDATA": "0",
    "ГО": "0",
    "Списки": "0",
}

MARGIN_COL_MAP = {
    "НАЧ. ГО": (4, 5),
    "КНУР":    (6, 7),
    "КСУР":    (8, 9),
    "КПУР":    (10, 11),
    "КОУР":    (12, 13),
}

# ==========================================
# 1. ЗАГРУЗКА ИЗ GOOGLE SHEETS
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def _load(gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        return pd.read_csv(url)
    except Exception:
        return pd.DataFrame()

def load_api():         return _load(GIDS["API"])
def load_go():          return _load(GIDS["ГО"])
def load_marketdata():  return _load(GIDS["MARKETDATA"])
def load_lists():       return _load(GIDS["Списки"])

def vlookup(df: pd.DataFrame, key, col_idx: int):
    if df.empty:
        return "-"
    try:
        mask = df.iloc[:, 0].astype(str).str.strip() == str(key).strip()
        rows = df.loc[mask]
        if rows.empty:
            return "-"
        val = rows.iloc[0, col_idx - 1]
        return val if pd.notna(val) else "-"
    except Exception:
        return "-"

def to_float(x, default=0.0) -> float:
    try:
        return float(str(x).replace(" ", "").replace(",", "."))
    except Exception:
        return default

def get_margin(go_df, ticker, risk_level, direction) -> float:
    if risk_level not in MARGIN_COL_MAP:
        return 0.0
    col_long, col_short = MARGIN_COL_MAP[risk_level]
    col = col_long if direction == "LONG" else col_short
    return to_float(vlookup(go_df, ticker, col))


# ==========================================
# 2. ЗАГРУЗКА ИЗ MOEX ISS (Текущие данные)
# ==========================================
MOEX_URL = (
    "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json"
    "?iss.meta=off&iss.only=securities,marketdata"
)

SEC_COLS = {
    "SECID": ["SECID"],
    "SHORTNAME": ["SHORTNAME"],
    "ASSETCODE": ["ASSETCODE"],
    "GROUP": ["GROUP"],
    "SECTYPE": ["SECTYPE"],
    "DELIVERYTYPE": ["DELIVERYTYPE"],
    "LOTSIZE": ["LOTSIZE"],
    "MINSTEP": ["MINSTEP"],
    "STEPPRICE": ["STEPPRICE"],
    "LASTTRADEDATE": ["LASTTRADEDATE"],
    "INITIALMARGIN": ["INITIALMARGIN"],
    "PREVPRICE": ["PREVPRICE"],
    "PREVSETTLEPRICE": ["PREVSETTLEPRICE"],
    "BUYSELLFEE": ["BUYSELLFEE"],
    "DECIMALS": ["DECIMALS"],
}

MKT_COLS = {
    "SECID": ["SECID"], "LAST": ["LAST"], "VALTODAY": ["VALTODAY"],
    "OPENPOSITION": ["OPENPOSITION"], "HIGH": ["HIGH"], "LOW": ["LOW"],
    "UPDATETIME": ["UPDATETIME"], "LOTVOLUME": ["LOTVOLUME", "NUMTRADES"],
}

def _pick_columns(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = pd.DataFrame()
    for std_name, candidates in mapping.items():
        found = False
        for c in candidates:
            if c in df.columns:
                out[std_name] = df[c]
                found = True
                break
        if not found:
            out[std_name] = None
    return out

@st.cache_data(ttl=30, show_spinner="Загрузка данных MOEX ISS…")
def fetch_moex_forts() -> pd.DataFrame:
    try:
        r = requests.get(MOEX_URL, timeout=15)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        st.error(f"Ошибка MOEX ISS: {e}")
        return pd.DataFrame()

    sec_raw = pd.DataFrame(js["securities"]["data"], columns=js["securities"]["columns"])
    mkt_raw = pd.DataFrame(js["marketdata"]["data"], columns=js["marketdata"]["columns"])

    sec = _pick_columns(sec_raw, SEC_COLS)
    mkt = _pick_columns(mkt_raw, MKT_COLS)

    df = sec.merge(mkt, on="SECID", how="left")

    # Числовые колонки
    numeric_cols = ["BUYSELLFEE", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW",
                    "INITIALMARGIN", "STEPPRICE", "MINSTEP", "PREVPRICE",
                    "PREVSETTLEPRICE", "LOTSIZE", "LOTVOLUME", "DECIMALS"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    # Текстовые колонки — приводим к строке и заполняем пустой строкой
    text_cols = ["SHORTNAME", "ASSETCODE", "GROUP", "SECTYPE", "DELIVERYTYPE"]
    for col in text_cols:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("").astype(str)

    price = df["LAST"].where(df["LAST"] > 0, df["PREVSETTLEPRICE"])
    multiplier = df["STEPPRICE"] / df["MINSTEP"].replace(0, 1)
    df["Notional"] = price * multiplier
    df["Updated"] = pd.to_datetime(df["UPDATETIME"], errors="coerce")
    return df


# ==========================================
# 2b. ЗАГРУЗКА ГО ПО УРОВНЯМ РИСКА (IMS)
# ==========================================
MOEX_IMS_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/ims"

@st.cache_data(ttl=60, show_spinner="Загрузка ГО (IMS)…")
def fetch_moex_ims() -> pd.DataFrame:
    params = {"iss.meta": "off", "format": "json"}
    try:
        r = requests.get(MOEX_IMS_URL, params=params, timeout=15)
        r.raise_for_status()
        js = r.json()
        block = js.get("ims")
        if not block or not block.get("data"):
            return pd.DataFrame()
        df = pd.DataFrame(block["data"], columns=block["columns"])
    except Exception:
        try:
            r = requests.get(MOEX_IMS_URL, params={"iss.meta": "off"}, timeout=15)
            r.raise_for_status()
            from io import StringIO
            df = pd.read_csv(StringIO(r.text), sep="|")
            df.columns = [c.split("(")[0].strip() for c in df.columns]
        except Exception as e:
            st.warning(f"Не удалось загрузить данные ГО (IMS): {e}")
            return pd.DataFrame()

    df.columns = [str(c).upper() for c in df.columns]

    numeric_cols = ["IM_BUY", "IM_SELL", "IM_BUY_LRC", "IM_SELL_LRC",
                    "IM_BUY_MRC", "IM_SELL_MRC", "IM_BUY_HRC", "IM_SELL_HRC",
                    "IM_BUY_ERC", "IM_SELL_ERC"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    if "IM_TIME" in df.columns:
        df["IM_TIME"] = pd.to_datetime(df["IM_TIME"], errors="coerce")
    return df


# ==========================================
# 3. ЗАГРУЗКА СВЕЧЕЙ
# ==========================================
MOEX_CANDLES_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{ticker}/candles.json"

@st.cache_data(ttl=300, show_spinner=False)
def fetch_moex_candles(ticker: str, interval: int, days_back: int = 60) -> pd.DataFrame:
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    till_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    all_chunks = []
    start = 0
    max_pages = 30

    for _ in range(max_pages):
        params = {
            "interval": interval, "from": from_date, "till": till_date,
            "start": start, "iss.meta": "off",
        }
        try:
            r = requests.get(MOEX_CANDLES_URL.format(ticker=ticker), params=params, timeout=15)
            r.raise_for_status()
            js = r.json()
        except Exception:
            break

        block = js.get("candles")
        if not block or not block.get("data"):
            break

        chunk = pd.DataFrame(block["data"], columns=block["columns"])
        all_chunks.append(chunk)

        if len(chunk) < 500:
            break
        start += 500

    if not all_chunks:
        return pd.DataFrame()

    df = pd.concat(all_chunks, ignore_index=True).drop_duplicates(subset=["begin"])

    required = ["begin", "open", "high", "low", "close"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    df = df.rename(columns={"begin": "Date", "open": "Open", "high": "High",
                            "low": "Low", "close": "Close", "volume": "Volume"})
    if "Volume" not in df.columns:
        df["Volume"] = 0

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df


# ==========================================
# 4. СОХРАНЕНИЕ / ЗАГРУЗКА АНАЛИТИКИ
# ==========================================
CACHE_FILE = "trend_cache.json"

def load_trend_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_trend_cache(ticker: str, data_dict: dict):
    cache = load_trend_cache()
    cache[ticker] = data_dict
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Не удалось сохранить кэш: {e}")

def build_export_cache() -> dict:
    cache = load_trend_cache()

    if "sb_strategy" in st.session_state:
        cache["_global"] = {
            "strategy": st.session_state.get("sb_strategy", "Зигзаг тенденции"),
            "deposit": st.session_state.get("sb_deposit", 75000),
            "risk_pct": st.session_state.get("sb_risk", 1.0),
            "commission": st.session_state.get("sb_comm", "Т-Инвестиции"),
            "margin_type": st.session_state.get("sb_margin", "КСУР"),
            "rr_ratio": st.session_state.get("sb_rr", 3.0),
            "mobile_view": st.session_state.get("sb_mobile", False),
        }

    cache["_active_tickers"] = st.session_state.get("active_tickers", [])
    cache["_market_state"] = st.session_state.get("market_state", {})

    for ticker in st.session_state.get("active_tickers", []):
        pts_keys = {
            "d1_manual_pts": f"manual_channel_{ticker}_D1",
            "d1_fib_pts":    f"manual_fib_{ticker}_D1",
            "h1_tend_pts":   f"manual_tend_{ticker}_H1",
            "h1_fib_pts":    f"manual_fib_{ticker}_H1",
            "m10_zig_pts":   f"manual_zig_{ticker}_M10",
            "h1_levels":     f"manual_levels_{ticker}_H1",
        }
        ticker_data = {}
        for cache_key, skey in pts_keys.items():
            if cache_key == "h1_levels":
                ticker_data[cache_key] = st.session_state.get(skey, [])
            else:
                pts = st.session_state.get(skey, [])
                ticker_data[cache_key] = [(str(t), float(p)) for t, p in pts]

        entries_key = f"deal_{ticker}_entries_raw"
        if entries_key in st.session_state:
            try:
                ticker_data["entries"] = st.session_state[entries_key].to_dict("records")
            except Exception:
                ticker_data["entries"] = []
        else:
            ticker_data["entries"] = []

        ticker_data["sl_price"] = st.session_state.get(f"deal_{ticker}_sl_price", None)
        ticker_data["tp_price"] = st.session_state.get(f"deal_{ticker}_tp_price", None)
        ticker_data["direction"] = st.session_state.get(f"deal_{ticker}_dir", None)

        cache[ticker] = ticker_data

    return cache

def export_cache_to_string() -> str:
    cache = build_export_cache()
    return json.dumps(cache, ensure_ascii=False, indent=4)

def import_cache_from_string(json_str: str) -> bool:
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return False
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False
