import streamlit as st
from data import load_api, load_go, load_marketdata, load_lists
from rules import build_rules_map
from tabs.main_table import render_main_tab
from tabs.screener import render_screener
from tabs.trade_planner import render_trade_planner

st.set_page_config(page_title="Калькулятор фьючерсов", page_icon="📈", layout="wide")

with st.sidebar:
    st.header("⚙️ Параметры")
    deposit = st.number_input("Депозит, ₽", min_value=1_000, value=75_000, step=1_000, key="deposit")
    margin_type = st.selectbox("Тип ГО (для обзора)", ["НАЧ. ГО", "КНУР", "КСУР", "КПУР", "КОУР"], key="margin_type")
    if st.button("🔄 Обновить данные"):
        st.cache_data.clear()
        st.rerun()

api_df   = load_api()
go_df    = load_go()
md_df    = load_marketdata()
rules_df = load_lists()
rules_map = build_rules_map(rules_df)

if "tickers" not in st.session_state:
    st.session_state["tickers"] = []

NAMES = ["📊 Основные", "🔍 Скринер"] + [f"🎯 Сделка {i}" for i in range(1, 9)]
tabs  = st.tabs(NAMES)

with tabs[0]:
    render_main_tab(api_df=api_df, go_df=go_df, md_df=md_df, deposit=deposit, margin_type=margin_type)

with tabs[1]:
    render_screener()

for i, tab in enumerate(tabs[2:], start=1):
    with tab:
        render_trade_planner(
            tab_id=f"deal_{i}",
            tickers=st.session_state["tickers"],
            api_df=api_df, go_df=go_df, md_df=md_df,
            deposit=deposit, rules_map=rules_map,
        )
