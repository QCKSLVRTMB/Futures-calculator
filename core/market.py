from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter, Retry

ISS = "https://iss.moex.com/iss/engines/futures/markets/forts"
MOEX_URL = f"{ISS}/securities.json?iss.meta=off&iss.only=securities,marketdata"
MOEX_IMS_URL = f"{ISS}/ims"
MOEX_CANDLES_URL = ISS + "/securities/{ticker}/candles.json"

SHEET_ID = "" 
GIDS = {"API": "0", "MARKETDATA": "0", "ГО": "0", "Списки": "0"}
USE_GSHEETS = bool(SHEET_ID) and "ВАШ_ID" not in SHEET_ID

@st.cache_resource(show_spinner=False)
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "futures-calc/2.0"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504)), pool_maxsize=8))
    return s

@st.cache_data(ttl=600, show_spinner=False)
def _load(gid: str) -> pd.DataFrame:
    if not USE_GSHEETS: return pd.DataFrame()
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try: return pd.read_csv(url)
    except Exception: return pd.DataFrame()

def load_api():        return _load(GIDS["API"])
def load_go():         return _load(GIDS["ГО"])
def load_marketdata(): return _load(GIDS["MARKETDATA"])
def load_lists():      return _load(GIDS["Списки"])

def to_float(x, default: float = 0.0) -> float:
    try: return float(str(x).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except Exception: return default

def vlookup(df: pd.DataFrame, key, col_idx: int):
    if df is None or df.empty: return "-"
    try:
        mask = df.iloc[:, 0].astype(str).str.strip() == str(key).strip()
        rows = df.loc[mask]
        if rows.empty: return "-"
        val = rows.iloc[0, col_idx - 1]
        return val if pd.notna(val) else "-"
    except Exception: return "-"

SEC_COLS = ["SECID", "SHORTNAME", "ASSETCODE", "LOTSIZE", "MINSTEP", "STEPPRICE", "LASTTRADEDATE", "INITIALMARGIN", "PREVPRICE", "PREVSETTLEPRICE", "BUYSELLFEE", "DECIMALS", "HIGHLIMIT", "LOWLIMIT"]
MKT_COLS = ["SECID", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW", "UPDATETIME", "LASTCHANGEPRCNT", "NUMTRADES"]
NUMERIC = ["BUYSELLFEE", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW", "INITIALMARGIN", "STEPPRICE", "MINSTEP", "PREVPRICE", "PREVSETTLEPRICE", "LOTSIZE", "DECIMALS", "HIGHLIMIT", "LOWLIMIT", "LASTCHANGEPRCNT", "NUMTRADES"]

def _subset(raw: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=raw.index)
    for c in cols: out[c] = raw[c] if c in raw.columns else None
    return out

@st.cache_data(ttl=120, show_spinner=False)
def fetch_moex_forts() -> pd.DataFrame:
    try:
        r = _session().get(MOEX_URL, timeout=15)
        r.raise_for_status()
        js = r.json()
        sec = pd.DataFrame(js["securities"]["data"], columns=js["securities"]["columns"])
        mkt = pd.DataFrame(js["marketdata"]["data"], columns=js["marketdata"]["columns"])
    except Exception as e:
        st.warning(f"MOEX ISS недоступен: {e}")
        return pd.DataFrame()

    df = _subset(sec, SEC_COLS).merge(_subset(mkt, MKT_COLS), on="SECID", how="left")
    for c in NUMERIC: df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0.0)

    df["PRICE"] = df["LAST"].where(df["LAST"] > 0, df["PREVSETTLEPRICE"])
    df["POINT_VALUE"] = df["STEPPRICE"] / df["MINSTEP"].replace(0, pd.NA)
    df["POINT_VALUE"] = df["POINT_VALUE"].fillna(1.0)
    df["Notional"] = df["PRICE"] * df["POINT_VALUE"]
    df["Updated"] = pd.to_datetime(df["UPDATETIME"], errors="coerce")
    return df

@st.cache_data(ttl=900, show_spinner=False)
def fetch_moex_ims() -> pd.DataFrame:
    try:
        r = _session().get(MOEX_IMS_URL, params={"iss.meta": "off", "format": "json"}, timeout=15)
        r.raise_for_status()
        block = r.json().get("ims") or {}
        df = pd.DataFrame(block.get("data") or [], columns=block.get("columns") or [])
    except Exception:
        try:
            r = _session().get(MOEX_IMS_URL, params={"iss.meta": "off"}, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text), sep="|")
            df.columns = [c.split("(")[0].strip() for c in df.columns]
        except Exception: return pd.DataFrame()
    if df.empty: return df
    df.columns = [str(c).upper() for c in df.columns]
    for c in df.columns:
        if c.startswith("IM_") and c != "IM_TIME":
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "IM_TIME" in df.columns: df["IM_TIME"] = pd.to_datetime(df["IM_TIME"], errors="coerce")
    return df

@st.cache_data(ttl=180, show_spinner=False, max_entries=64)
def fetch_moex_candles(ticker: str, interval: int, days_back: int = 60) -> pd.DataFrame:
    frm = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    till = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    chunks, start = [], 0
    for _ in range(30):
        try:
            r = _session().get(MOEX_CANDLES_URL.format(ticker=ticker), params={"interval": interval, "from": frm, "till": till, "start": start, "iss.meta": "off"}, timeout=15)
            r.raise_for_status()
            block = r.json().get("candles") or {}
        except Exception: break
        data = block.get("data") or []
        if not data: break
        chunks.append(pd.DataFrame(data, columns=block["columns"]))
        if len(data) < 500: break
        start += 500

    if not chunks: return pd.DataFrame()
    df = pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["begin"])
    need = {"begin", "open", "high", "low", "close"}
    if not need.issubset(df.columns): return pd.DataFrame()
    df = df.rename(columns={"begin": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
    if "Volume" not in df: df["Volume"] = 0
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date").sort_index().dropna(subset=["Open", "High", "Low", "Close"])[["Open", "High", "Low", "Close", "Volume"]]
