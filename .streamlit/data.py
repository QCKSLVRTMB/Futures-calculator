import pandas as pd
import streamlit as st

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

@st.cache_data(ttl=60, show_spinner=False)
def _load(gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        return pd.read_csv(url)
    except Exception as e:
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
