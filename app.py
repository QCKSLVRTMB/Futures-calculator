import streamlit as st
from data import load_api, load_go, load_marketdata, load_lists
from rules import build_rules_map
from tabs.main_table import render_main_tab
from tabs.screener import render_screener
from tabs.trade_planner import render_trade_planner

st.set_page_config(page_title="Калькулятор фьючерсов", page_icon="📈", layout="wide")

# ---------- Сайдбар ----------
with st.sidebar:
    st.header("⚙️ Параметры")
    deposit = st.number_input(
        "Депозит, ₽", min_value=1_000, value=75_000, step=1_000, key="deposit"
    )
    margin_type = st.selectbox(
        "Тип ГО (базовый)", ["НАЧ. ГО", "КНУР", "КСУР", "КПУР", "КОУР"],
        key="margin_type",
    )
    if st.button("🔄 Обновить данные"):
        st.cache_data.clear()
        st.rerun()

# ---------- Данные ----------
api_df    = load_api()
go_df     = load_go()
md_df     = load_marketdata()
rules_df  = load_lists()
rules_map = build_rules_map(rules_df)

# ---------- Инициализация активных тикеров ----------
if "active_tickers" not in st.session_state:
    st.session_state["active_tickers"] = []
if "market_state" not in st.session_state:
    st.session_state["market_state"] = {} # Формат: {"RIZ6": {"trend": "вверх", "wave": "вниз", "tendency": "рейндж"}}

# ---------- Построение имён вкладок ----------
tab_names = ["📊 Данные с биржи", "🔍 Скринер"] + st.session_state["active_tickers"]
tabs = st.tabs(tab_names)

# ---------- Вкладка 1: Данные с биржи ----------
with tabs[0]:
    render_main_tab(
        api_df=api_df, go_df=go_df, md_df=md_df,
        deposit=deposit, margin_type=margin_type,
    )

# ---------- Вкладка 2: Скринер ----------
with tabs[1]:
    render_screener()

# ---------- Вкладки 3+: калькуляторы по тикерам ----------
for i, ticker in enumerate(st.session_state["active_tickers"]):
    with tabs[2 + i]:
        render_trade_planner(
            ticker=ticker,
            api_df=api_df, go_df=go_df, md_df=md_df,
            deposit=deposit,
            rules_map=rules_map,
        )
