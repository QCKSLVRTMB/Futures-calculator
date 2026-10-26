import streamlit as st
from datetime import datetime
from data import (
    load_api, load_go, load_marketdata, fetch_moex_forts,
    export_cache_to_string, import_cache_from_string,
    load_trend_cache, save_trend_cache
)
from tabs.main_table import render_main_tab
from tabs.screener import render_screener
from tabs.trade_planner import render_trade_planner

st.set_page_config(page_title="Калькулятор фьючерсов", page_icon="📈", layout="wide")

try:
    # Загружаем глобальные настройки из JSON
    cache = load_trend_cache()
    global_settings = cache.get("_global", {})

    # Инициализация стейта бокового меню
    if "sb_strategy" not in st.session_state:
        st.session_state["sb_strategy"] = global_settings.get("strategy", "Зигзаг тенденции")
    if "sb_deposit" not in st.session_state:
        st.session_state["sb_deposit"] = global_settings.get("deposit", 75000)
    if "sb_comm" not in st.session_state:
        st.session_state["sb_comm"] = global_settings.get("commission", "Т-Инвестиции")
    if "sb_margin" not in st.session_state:
        st.session_state["sb_margin"] = global_settings.get("margin_type", "КСУР")
    if "sb_rr" not in st.session_state:
        st.session_state["sb_rr"] = global_settings.get("rr_ratio", 3.0)

    with st.sidebar:
        st.header("Параметры")
        
        strategy = st.selectbox(
            "Стратегия", 
            ["Зигзаг тенденции", "Свинг торговля"], 
            key="sb_strategy"
        )
        
        deposit = st.number_input(
            "Депозит, ₽", min_value=1_000, step=1_000, key="sb_deposit"
        )
        
        commission = st.selectbox(
            "Комиссия", 
            ["Т-Инвестиции", "Финам СТАНДАРТНЫЙ ФОРТС", "Без комиссии"], 
            key="sb_comm"
        )
        
        margin_type = st.selectbox(
            "Тип ГО (базовый)", ["НАЧ. ГО", "КНУР", "КСУР", "КПУР", "КОУР"], 
            key="sb_margin"
        )
        
        rr_ratio = st.number_input(
            "Risk Reward (1 к ...)", min_value=1.0, step=0.5, key="sb_rr",
            help="Глобальное соотношение риска к прибыли для всех калькуляторов"
        )
        
        if st.button("Обновить данные", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
            
        st.markdown("---")
        st.header("Управление настройками")
        
        cache_str = export_cache_to_string()
        filename = datetime.now().strftime('%d.%m.%y.%H-%M') + ".futures"
        
        st.download_button(
            label="Экспорт сессии",
            data=cache_str,
            file_name=filename,
            mime="application/json",
            use_container_width=True,
        )
        
        uploaded_file = st.file_uploader("Импорт сессии", type=["futures", "json"])
        if uploaded_file is not None:
            if st.button("Применить импорт", type="primary", use_container_width=True):
                string_data = uploaded_file.getvalue().decode("utf-8")
                if import_cache_from_string(string_data):
                    st.success("Настройки успешно загружены!")
                    for k in list(st.session_state.keys()):
                        if k.startswith("deal_") or k.startswith("picker_") or k.startswith("main_") or k.startswith("sb_"):
                            del st.session_state[k]
                    st.rerun()
                else:
                    st.error("Ошибка: неверный формат файла.")

    # Сохраняем глобальные настройки в JSON, если они изменились
    new_global_settings = {
        "strategy": strategy,
        "deposit": deposit,
        "commission": commission,
        "margin_type": margin_type,
        "rr_ratio": rr_ratio
    }
    if new_global_settings != global_settings:
        save_trend_cache("_global", new_global_settings)

    with st.spinner("Загрузка данных с MOEX ISS..."):
        iss_df = fetch_moex_forts()

    api_df = load_api()
    go_df = load_go()
    md_df = load_marketdata()

    if "active_tickers" not in st.session_state:
        st.session_state["active_tickers"] = []
    if "market_state" not in st.session_state:
        st.session_state["market_state"] = {}

    tab_names = ["Данные с биржи", "Скринер"] + st.session_state["active_tickers"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_main_tab(
            api_df=api_df, go_df=go_df, md_df=md_df, 
            iss_df=iss_df, deposit=deposit, margin_type=margin_type
        )

    with tabs[1]:
        render_screener(iss_df=iss_df)

    for i, ticker in enumerate(st.session_state["active_tickers"]):
        with tabs[2 + i]:
            render_trade_planner(
                ticker=ticker,
                api_df=api_df, go_df=go_df, md_df=md_df,
                iss_df=iss_df,
                deposit=deposit,
                rr_ratio=rr_ratio,
                commission=commission,
                strategy=strategy,
            )

except Exception as e:
    st.error("Критическая ошибка приложения:")
    st.exception(e)
