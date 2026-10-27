from __future__ import annotations
import streamlit as st
import pandas as pd
from core import state
from core.market import to_float, vlookup
from core.config import TREND_VALUES, MARGIN_COL_MAP

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

    col_go, _ = MARGIN_COL_MAP.get(margin_type, (4, 5))
    rows = []
    
    for t in picked:
        iss_row = iss_df[iss_df["SECID"] == t] if not iss_df.empty and "SECID" in iss_df.columns else pd.DataFrame()
        price = 0.0
        if not iss_row.empty:
            price = to_float(iss_row.iloc[0].get("LAST", 0)) or to_float(iss_row.iloc[0].get("PREVSETTLEPRICE", 0))
        if price == 0: price = to_float(vlookup(md_df, t, 9))
            
        step_price, step_cost = 0.0, 0.0
        if not iss_row.empty:
            step_price = to_float(iss_row.iloc[0].get("MINSTEP", 0))
            step_cost = to_float(iss_row.iloc[0].get("STEPPRICE", 0))
        if step_price == 0:
            step_price = to_float(vlookup(api_df, t, 6))
            step_cost = to_float(vlookup(api_df, t, 17))

        margin = 0.0
        if not iss_row.empty:
            margin = to_float(iss_row.iloc[0].get("INITIALMARGIN", 0))
        if margin == 0:
            margin = to_float(vlookup(go_df, t, col_go))

        code_gs = vlookup(api_df, t, 9)
        name_gs = vlookup(api_df, t, 3)
        expiry_gs = vlookup(api_df, t, 7)
        
        code = code_gs if code_gs != "-" else (iss_row.iloc[0].get("ASSETCODE", "-") if not iss_row.empty else "-")
        name = name_gs if name_gs != "-" else (iss_row.iloc[0].get("SHORTNAME", "-") if not iss_row.empty else "-")
        expiry = expiry_gs if expiry_gs != "-" else (str(iss_row.iloc[0].get("LASTTRADEDATE", "-")) if not iss_row.empty else "-")

        max_contracts = int(deposit // margin) if margin > 0 else 0
        risk_pct = round(margin / deposit * 100, 2) if margin > 0 else 0.0

        m = state.ticker(t)["market"]
        rows.append({
            "Код": code, "Наименование": name, "Тикер": t, "Шаг цены": step_price,
            "Ст. шага": step_cost, "ГО": margin, "Доступно": max_contracts, "Цена": price,
            "Экспирация": expiry, "Риск, %": risk_pct,
            "Тренд": m["trend"], "Волна": m["wave"], "Тенденция": m["tendency"],
        })
        
    df = pd.DataFrame(rows)

    st.markdown("#### Таблица данных")
    MOBILE_COLS = ["Тикер", "Цена", "ГО", "Доступно", "Тренд", "Волна", "Тенденция"]
    
    edited_df = st.data_editor(
        df, use_container_width=True, hide_index=True,
        column_order=MOBILE_COLS if mobile else None,
        column_config={
            "Тренд": st.column_config.SelectboxColumn("Тренд", options=TREND_VALUES, required=True),
            "Волна": st.column_config.SelectboxColumn("Волна", options=TREND_VALUES, required=True),
            "Тенденция": st.column_config.SelectboxColumn("Тенденция", options=TREND_VALUES, required=True),
            "Шаг цены": st.column_config.NumberColumn(format="%.4f"),
            "Ст. шага": st.column_config.NumberColumn(format="%.4f"),
            "ГО": st.column_config.NumberColumn(format="%.2f ₽"),
            "Цена": st.column_config.NumberColumn(format="%.2f"),
            "Риск, %": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100),
        },
        disabled=["Код", "Наименование", "Тикер", "Шаг цены", "Ст. шага", "ГО", "Цена", "Доступно"],
        key="main_table_editor"
    )

    for _, row in edited_df.iterrows():
        state.ticker(row["Тикер"])["market"].update({"trend": row["Тренд"], "wave": row["Волна"], "tendency": row["Тенденция"]})
    state.autosave()
