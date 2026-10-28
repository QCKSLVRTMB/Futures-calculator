from __future__ import annotations
from datetime import datetime
import os
import streamlit as st

from core import state, storage
from core.config import APP_TITLE, MARGIN_HINTS, MARGIN_LEVELS, TARIFF_CONFIGS
from core.market import fetch_moex_forts, fetch_moex_ims, load_api, load_go, load_marketdata
from tabs.main_table import render_main_tab
from tabs.screener import render_screener
from tabs.trade_planner import render_trade_planner
from tabs.help import render_help_tab  # <-- ДОБАВЛЕН ИМПОРТ
from ui.theme import inject_css, seg

st.set_page_config(page_title="QCKSLVR TRADING", page_icon="logo.png", layout="wide", initial_sidebar_state="expanded")
inject_css()

# === КОМПАКТНЫЙ ЗАГОЛОВОК С ЛОГО В ПРАВОМ УГЛУ ===
col1, col2 = st.columns([5, 1])
with col1:
    st.markdown("<h1 style='color: #0F172A; margin: 0; font-size: 2rem;'>Калькулятор фьючерсов MOEX</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color: #475569; margin: 0; font-size: 16px;'>сообщества QCKSLVR TRADING</p>", unsafe_allow_html=True)
with col2:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_column_width=False, width=100)
    elif os.path.exists("logo.jpg"):
        st.image("logo.jpg", use_column_width=False, width=100)

st.write("")

S = state.get_state()
G = S["global"]

def _sync(key, gkey):
    state.set_global(gkey, st.session_state[key])

# Дружелюбные названия для выпадающего списка категорий риска
FRIENDLY_MARGIN_NAMES = {
    "НАЧ. ГО": "НАЧ. ГО — Базовое",
    "КНУР": "КНУР — Начальный (новичкам)",
    "КСУР": "КСУР — Стандартный",
    "КПУР": "КПУР — Повышенный (квалам)",
    "КОУР": "КОУР — Особый"
}

with st.sidebar:
    st.header("Параметры")
    
    profiles = storage.list_profiles()
    current_prof = state.profile()
    idx = profiles.index(current_prof) if current_prof in profiles else 0
    st.selectbox("Профиль данных", profiles + ["+ новый"], key="sb_profile_sel", index=idx)
    
    if st.session_state["sb_profile_sel"] == "+ новый":
        new_name = st.text_input("Имя профиля", key="sb_profile_new")
        if new_name and st.button("Создать", use_container_width=True):
            st.session_state["sb_profile"] = new_name
            state.replace_state(storage.default_state())
            st.rerun()
    elif st.session_state["sb_profile_sel"] != current_prof:
        st.session_state["sb_profile"] = st.session_state["sb_profile_sel"]
        state.replace_state(storage.load_profile(state.profile()), persist=False)
        st.rerun()

    st.selectbox("Стратегия", ["Зигзаг тенденции", "Свинг торговля"], key="sb_strategy", index=0 if G["strategy"] == "Зигзаг тенденции" else 1, on_change=_sync, args=("sb_strategy", "strategy"))
    st.number_input("Депозит, ₽", min_value=1000, step=1000, value=int(G["deposit"]), key="sb_deposit", on_change=_sync, args=("sb_deposit", "deposit"))
    st.number_input("Допустимый риск в сделке, %", 0.1, 100.0, float(G["risk_pct"]), 0.1, key="sb_risk", on_change=_sync, args=("sb_risk", "risk_pct"))
    st.number_input("Risk/Reward (1 к ...)", 1.0, 20.0, float(G["rr_ratio"]), 0.5, key="sb_rr", on_change=_sync, args=("sb_rr", "rr_ratio"))
    st.slider("Макс. использование депо под ГО, %", 10, 100, int(G.get("max_margin_util", 50)), 5, key="sb_mmu", on_change=_sync, args=("sb_mmu", "max_margin_util"))
    st.selectbox("Комиссия", list(TARIFF_CONFIGS), key="sb_comm", index=list(TARIFF_CONFIGS).index(G["commission"]), on_change=_sync, args=("sb_comm", "commission"))
    
    st.selectbox(
        "Категория риска", 
        MARGIN_LEVELS, 
        key="sb_margin", 
        index=MARGIN_LEVELS.index(G["margin_type"]), 
        format_func=lambda x: FRIENDLY_MARGIN_NAMES.get(x, x), 
        on_change=_sync, 
        args=("sb_margin", "margin_type")
    )
    
    st.toggle("Мобильный вид", key="sb_mobile", value=bool(G["mobile_view"]), on_change=_sync, args=("sb_mobile", "mobile_view"))

    if st.button("Обновить котировки", use_container_width=True):
        fetch_moex_forts.clear(); fetch_moex_ims.clear()
        st.rerun()

    st.divider()
    st.header("Управление настройками")
    st.download_button("Экспорт сессии", data=storage.dumps(S), file_name=datetime.now().strftime("%d.%m.%y_%H-%M") + ".futures", mime="application/json", use_container_width=True)
    up = st.file_uploader("Импорт", type=["futures", "json"], label_visibility="collapsed")
    if up and st.button("Применить импорт", type="primary", use_container_width=True):
        parsed = storage.loads(up.getvalue().decode("utf-8"))
        if parsed:
            state.replace_state(parsed)
            for k in [k for k in st.session_state if k.startswith(("m_", "tf_", "tool_", "dir_", "sl_", "tp_", "entries_", "chart_", "picker_", "main_"))]:
                del st.session_state[k]
            st.success("Загружено"); st.rerun()
        else: st.error("Неверный формат файла")
    if S.get("saved_at"): st.caption(f"Автосохранение: {S['saved_at'][11:19]} UTC")

mobile = bool(G["mobile_view"])
iss_df, ims_df = fetch_moex_forts(), fetch_moex_ims()
api_df, go_df, md_df = load_api(), load_go(), load_marketdata()

tickers = state.active_tickers()
tab_plan_name = f"Калькуляторы фьючерсов ({len(tickers)})" if tickers else "Калькуляторы фьючерсов"

# ДОБАВЛЕНА ВКЛАДКА "СПРАВКА"
tab_market, tab_screen, tab_plan, tab_help = st.tabs(["Данные", "Скринер", tab_plan_name, "Справка"])

with tab_market:
    render_main_tab(
        api_df=api_df, go_df=go_df, md_df=md_df, iss_df=iss_df, ims_df=ims_df,
        deposit=G["deposit"], margin_type=G["margin_type"], mobile=mobile
    )

with tab_screen:
    render_screener(iss_df=iss_df, go_df=go_df, ims_df=ims_df, deposit=G["deposit"], margin_type=G["margin_type"], commission=G["commission"], mobile=mobile)

with tab_plan:
    if not tickers:
        st.info("Добавьте инструменты на вкладке «Данные».")
    else:
        active = seg("Инструмент", tickers, key="plan_ticker", default=st.session_state.get("plan_ticker", tickers[0]))
        active = active if active in tickers else tickers[0]
        render_trade_planner(ticker=active, iss_df=iss_df, ims_df=ims_df, go_df=go_df, api_df=api_df, md_df=md_df, deposit=G["deposit"], risk_pct=G["risk_pct"], rr_ratio=G["rr_ratio"], commission=G["commission"], strategy=G["strategy"], mobile=mobile)

# ОТОБРАЖЕНИЕ ВКЛАДКИ "СПРАВКА"
with tab_help:
    render_help_tab()

state.autosave()
