import streamlit as st
import pandas as pd
from data import vlookup, to_float, MARGIN_COL_MAP
from rules import TREND_VALUES

def render_main_tab(*, api_df, go_df, md_df, iss_df, deposit, margin_type):
    st.subheader("📊 Данные с биржи")

    if not iss_df.empty:
        active_iss = iss_df[iss_df["VALTODAY"].fillna(0) > 0]
        available_tickers = sorted(active_iss["SECID"].dropna().unique().tolist())
    else:
        available_tickers = []

    st.markdown("#### Выбор инструментов")
    st.caption("Каждый выбранный тикер открывает отдельную вкладку с калькулятором позиции.")

    current = st.session_state.get("active_tickers", [])
    iss_selected = [t for t in current if t in available_tickers]

    if "picker_txt" not in st.session_state:
        manual_current = [t for t in current if t not in available_tickers]
        st.session_state["picker_txt"] = ", ".join(manual_current)

    c1, c2 = st.columns([3, 2])
    with c1:
        selected_from_iss = st.multiselect(
            "Выбрать из списка MOEX ISS",
            options=available_tickers,
            default=iss_selected,
            key="picker_ms",
        )
    with c2:
        manual_input = st.text_input(
            "Ввести тикер вручную (через запятую)",
            key="picker_txt",
        )

    manual_list = [x.strip().upper() for x in manual_input.split(",") if x.strip()]
    new_active = list(dict.fromkeys(selected_from_iss + manual_list))

    if new_active != current:
        st.session_state["active_tickers"] = new_active
        st.rerun()

    picked = st.session_state["active_tickers"]
    if not picked:
        st.info("👆 Выберите хотя бы один тикер для отображения данных.")
        return

    # ---------- Формирование таблицы ----------
    col_go, _ = MARGIN_COL_MAP[margin_type]
    rows = []
    
    for t in picked:
        iss_row = iss_df[iss_df["SECID"] == t] if not iss_df.empty else pd.DataFrame()
        
        price = 0.0
        if not iss_row.empty:
            price = to_float(iss_row.iloc[0]["LAST"])
            if price == 0:
                price = to_float(iss_row.iloc[0]["PREVSETTLEPRICE"])
        if price == 0:
            price = to_float(vlookup(md_df, t, 9))
            
        step_price, step_cost = 0.0, 0.0
        if not iss_row.empty:
            step_price = to_float(iss_row.iloc[0]["MINSTEP"])
            step_cost = to_float(iss_row.iloc[0]["STEPPRICE"])
        if step_price == 0:
            step_price = to_float(vlookup(api_df, t, 6))
            step_cost = to_float(vlookup(api_df, t, 17))

        margin = 0.0
        if not iss_row.empty:
            margin = to_float(iss_row.iloc[0]["INITIALMARGIN"])
        if margin == 0:
            margin = to_float(vlookup(go_df, t, col_go))

        code_gs = vlookup(api_df, t, 9)
        name_gs = vlookup(api_df, t, 3)
        expiry_gs = vlookup(api_df, t, 7)
        
        code = code_gs if code_gs != "-" else (iss_row.iloc[0]["ASSETCODE"] if not iss_row.empty else "-")
        name = name_gs if name_gs != "-" else (iss_row.iloc[0]["SHORTNAME"] if not iss_row.empty else "-")
        expiry = expiry_gs if expiry_gs != "-" else (str(iss_row.iloc[0]["LASTTRADEDATE"]) if not iss_row.empty else "-")

        max_contracts = int(deposit // margin) if margin > 0 else 0
        risk_pct = round(margin / deposit * 100, 2) if margin > 0 else 0.0

        state = st.session_state["market_state"].get(t, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})

        rows.append({
            "Код": code,
            "Наименование": name,
            "Тикер": t,
            "Шаг цены": step_price,
            "Ст. шага": step_cost,
            "ГО": margin,
            "Доступно": max_contracts,
            "Цена": price,
            "Экспирация": expiry,
            "Риск, %": risk_pct,
            "Тренд": state["trend"],
            "Волна": state["wave"],
            "Тенденция": state["tendency"],
        })
        
    df = pd.DataFrame(rows)

    st.markdown("#### Таблица данных (редактируемая)")
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
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
        t = row["Тикер"]
        new_state = {
            "trend": row["Тренд"],
            "wave": row["Волна"],
            "tendency": row["Тенденция"]
        }
        if st.session_state["market_state"].get(t) != new_state:
            st.session_state["market_state"][t] = new_state
