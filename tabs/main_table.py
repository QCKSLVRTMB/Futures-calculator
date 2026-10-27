from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import datetime
from core import state
from core.market import to_float, vlookup
from core.config import TREND_VALUES, MARGIN_COL_MAP
from core.calc import get_instrument
from ui.theme import format_date

def update_active_tickers():
    sel = st.session_state.get("picker_ms", [])
    manual = [x.strip().upper() for x in st.session_state.get("picker_txt", "").split(",") if x.strip()]
    state.set_active_tickers(sel + manual)
    state.autosave(force=True)

def render_main_tab(*, api_df, go_df, md_df, iss_df, deposit, margin_type, mobile=False):
    st.subheader("Данные с биржи")

    if not iss_df.empty and "VALTODAY" in iss_df.columns:
        active_iss = iss_df[iss_df["VALTODAY"].fillna(0) > 0]
        available_tickers = sorted(active_iss["SECID"].dropna().unique().tolist())
    else:
        available_tickers = []

    if "active_tickers" not in st.session_state:
        st.session_state["active_tickers"] = []
    if "picker_ms" not in st.session_state:
        st.session_state["picker_ms"] = [t for t in st.session_state["active_tickers"] if t in available_tickers]
    if "picker_txt" not in st.session_state:
        manual = [t for t in st.session_state["active_tickers"] if t not in available_tickers]
        st.session_state["picker_txt"] = ", ".join(manual)

    st.markdown("#### Выбор инструментов")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.multiselect("Выбрать из списка MOEX ISS", options=available_tickers, key="picker_ms", on_change=update_active_tickers)
    with c2:
        st.text_input("Ввести тикер вручную (через запятую)", key="picker_txt", on_change=update_active_tickers)

    picked = st.session_state["active_tickers"]
    if not picked:
        st.info("Выберите хотя бы один тикер для отображения данных.")
        return

    rows = []
    for t in picked:
        # Используем get_instrument для сбора всех данных в одном месте
        inst = get_instrument(t, iss_df=iss_df, go_df=go_df, api_df=api_df, md_df=md_df, margin_type=margin_type)
        
        # Логика расчета доступных контрактов (берем минимальное из ГО LONG/SHORT)
        margin_go = min(inst.margin_long, inst.margin_short) if inst.margin_long > 0 and inst.margin_short > 0 else max(inst.margin_long, inst.margin_short)
        max_contracts = int(deposit // margin_go) if margin_go > 0 else 0
        
        risk_pct = round(margin_go / deposit * 100, 2) if margin_go > 0 and deposit > 0 else 0.0

        # Получаем время обновления из ISS
        update_time = "-"
        if not iss_df.empty:
            iss_row = iss_df[iss_df["SECID"] == t]
            if not iss_row.empty and pd.notna(iss_row.iloc[0].get("Updated")):
                update_time = pd.to_datetime(iss_row.iloc[0].get("Updated")).strftime("%d.%m.%y %H:%M")

        m = state.ticker(t)["market"]
        rows.append({
            "Код контракта": inst.asset_code,
            "Наименование контракта": inst.name,
            "Тикер": t,
            "Шаг цены": inst.min_step,
            "Стоимость шага цены": inst.step_price,
            "ГО LONG": inst.margin_long,
            "ГО SHORT": inst.margin_short,
            "Доступно контрактов": max_contracts,
            "Рыночная цена": inst.price,
            "Свободно для сделок": "",  # Оставляем пустым как в примере
            "Дата экспирации": format_date(inst.expiry),
            "Процент от депо": "100%", # Как в вашем примере
            "Обновлено": update_time,
            "Риск (ГО, %)": risk_pct,
            "Тренд": m["trend"],
            "Волна": m["wave"],
            "Тенденция": m["tendency"],
        })
        
    df = pd.DataFrame(rows)

    st.markdown("#### Таблица данных")
    
    # Настраиваем формат чисел (динамические знаки после запятой)
    step_fmt = f"%.{int(inst.decimals)}f" if 'inst' in locals() else "%.4f"
    
    edited_df = st.data_editor(
        df, use_container_width=True, hide_index=True,
        column_config={
            "Шаг цены": st.column_config.NumberColumn(format=step_fmt),
            "Стоимость шага цены": st.column_config.NumberColumn(format=step_fmt),
            "ГО LONG": st.column_config.NumberColumn(format="%.2f ₽"),
            "ГО SHORT": st.column_config.NumberColumn(format="%.2f ₽"),
            "Доступно контрактов": st.column_config.NumberColumn(format="%d"),
            "Рыночная цена": st.column_config.NumberColumn(format="%.2f"),
            "Риск (ГО, %)": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100),
            "Тренд": st.column_config.SelectboxColumn("Тренд", options=TREND_VALUES, required=True),
            "Волна": st.column_config.SelectboxColumn("Волна", options=TREND_VALUES, required=True),
            "Тенденция": st.column_config.SelectboxColumn("Тенденция", options=TREND_VALUES, required=True),
        },
        disabled=["Код контракта", "Наименование контракта", "Тикер", "Шаг цены", "Стоимость шага цены", "ГО LONG", "ГО SHORT", "Доступно контрактов", "Рыночная цена", "Свободно для сделок", "Дата экспирации", "Процент от депо", "Обновлено", "Риск (ГО, %)"],
        key="main_table_editor"
    )

    for _, row in edited_df.iterrows():
        state.ticker(row["Тикер"])["market"].update({"trend": row["Тренд"], "wave": row["Волна"], "tendency": row["Тенденция"]})
    state.autosave()
