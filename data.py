import pandas as pd
import streamlit as st
import requests
from datetime import datetime, timedelta

# ВАЖНО: Замените на ваш ID таблицы и GID вкладок!
SHEET_ID = "ВАШ_ID_ТАБЛИЦЫ_ИЗ_ССЫЛКИ"
GIDS = {
    "API": "0",         # Замените на реальный gid
    "MARKETDATA": "0",  # Замените на реальный gid
    "ГО": "0",          # Замените на реальный gid
    "Списки": "0",      # Замените на реальный gid
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
    "SECID": ["SECID"], "SHORTNAME": ["SHORTNAME"], "ASSETCODE": ["ASSETCODE"],
    "LOTSIZE": ["LOTSIZE"], "MINSTEP": ["MINSTEP"], "STEPPRICE": ["STEPPRICE"],
    "LASTTRADEDATE": ["LASTTRADEDATE"], "INITIALMARGIN": ["INITIALMARGIN"],
    "PREVPRICE": ["PREVPRICE"], "PREVSETTLEPRICE": ["PREVSETTLEPRICE"], 
    "BUYSELLFEE": ["BUYSELLFEE"], "DECIMALS": ["DECIMALS"], # <-- Добавлено
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

    # Добавлен "DECIMALS" в числовые колонки
    numeric_cols = ["BUYSELLFEE", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW",
                    "INITIALMARGIN", "STEPPRICE", "MINSTEP", "PREVPRICE",
                    "PREVSETTLEPRICE", "LOTSIZE", "LOTVOLUME", "DECIMALS"] 
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    price = df["LAST"].where(df["LAST"] > 0, df["PREVSETTLEPRICE"])
    multiplier = df["STEPPRICE"] / df["MINSTEP"].replace(0, 1)
    df["Notional"] = price * multiplier
    df["Updated"] = pd.to_datetime(df["UPDATETIME"], errors="coerce")
    return df


# ==========================================
# 3. ЗАГРУЗКА СВЕЧЕЙ (Исторические данные)
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
