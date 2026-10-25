import streamlit as st
import pandas as pd
from data import fetch_moex_forts, vlookup, to_float, MARGIN_COL_MAP
from rules import TREND_VALUES

def render_main_tab(*, api_df, go_df, md_df, deposit, margin_type):
    st.subheader("📊 Данные с биржи")

    # ---------- Список доступных тикеров из ISS ----------
    iss_df = fetch_moex_forts()
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

    # ---------- Формирование таблицы из ISS + Google Sheets ----------
    col_go, col_go2 = MARGIN_COL_MAP[margin_type]
    
    rows = []
    for t in picked:
        # Пытаемся найти данные в ISS
        iss_row = iss_df[iss_df["SECID"] == t] if not iss_df.empty else pd.DataFrame()
        
        # Если есть в ISS - берем оттуда, иначе дефолты
        price = to_float(iss_row.iloc[0]["LAST"]) if not iss_row.empty else 0.0
        step_price = to_float(iss_row.iloc[0]["MINSTEP"]) if not iss_row.empty else 0.0
        step_cost = to_float(iss_row.iloc[0]["STEPPRICE"]) if not iss_row.empty else 0.0
        margin = to_float(iss_row.iloc[0]["INITIALMARGIN"]) if not iss_row.empty else 0.0
        
        # Если ГО из ISS нет, берем из Google Sheets
        if margin == 0:
            margin = to_float(vlookup(go_df, t, col_go))
            
        # Данные из Google Sheets для специфичных полей
        code_gs = vlookup(api_df, t, 9)
        name_gs = vlookup(api_df, t, 3)
        expiry_gs = vlookup(api_df, t, 7)

        # Данные для расчета
        max_contracts = int(deposit // margin) if margin > 0 else 0
        risk_pct = round(margin / deposit * 100, 2) if margin > 0 else 0.0

        # Текущее состояние рынка (из session_state или дефолт)
        state = st.session_state["market_state"].get(t, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})

        rows.append({
            "Код контракта": code_gs if code_gs != "-" else (iss_row.iloc[0]["ASSETCODE"] if not iss_row.empty else "-"),
            "Наименование": name_gs if name_gs != "-" else (iss_row.iloc[0]["SHORTNAME"] if not iss_row.empty else "-"),
            "Тикер": t,
            "Шаг цены": step_price,
            "Стоимость шага": step_cost,
            "Гарантийное обеспечение": margin,
            "Всего контрактов": max_contracts,
            "Рыночная цена": price,
            "Свободно для сделок": max_contracts, # Условно
            "Дата экспирации": expiry_gs if expiry_gs != "-" else (str(iss_row.iloc[0]["LASTTRADEDATE"]) if not iss_row.empty else "-"),
            "Процент от депозита": risk_pct,
            "Тренд": state["trend"],
            "Волна": state["wave"],
            "Тенденция": state["tendency"],
        })
        
    df = pd.DataFrame(rows)

    # ---------- Редактор таблицы ----------
    st.markdown("#### Таблица данных (редактируемая)")
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Тренд": st.column_config.SelectboxColumn(
                "Тренд", options=TREND_VALUES, required=True
            ),
            "Волна": st.column_config.SelectboxColumn(
                "Волна", options=TREND_VALUES, required=True
            ),
            "Тенденция": st.column_config.SelectboxColumn(
                "Тенденция", options=TREND_VALUES, required=True
            ),
            "Шаг цены": st.column_config.NumberColumn(format="%.4f"),
            "Стоимость шага": st.column_config.NumberColumn(format="%.4f"),
            "Гарантийное обеспечение": st.column_config.NumberColumn(format="%.2f ₽"),
            "Рыночная цена": st.column_config.NumberColumn(format="%.2f"),
            "Процент от депозита": st.column_config.ProgressColumn(
                "Процент от депозита", format="%.2f%%", min_value=0, max_value=100
            ),
        },
        disabled=["Код контракта", "Наименование", "Тикер", "Шаг цены", "Стоимость шага", "Гарантийное обеспечение", "Рыночная цена"],
        key="main_table_editor"
    )

    # ---------- Сохранение состояния из редактора ----------
    # Проверяем, изменились ли значения Тренда/Волны/Тенденции
    for index, row in edited_df.iterrows():
        t = row["Тикер"]
        new_state = {
            "trend": row["Тренд"],
            "wave": row["Волна"],
            "tendency": row["Тенденция"]
        }
        if st.session_state["market_state"].get(t) != new_state:
            st.session_state["market_state"][t] = new_state
            # Не делаем st.rerun() здесь, чтобы не сбивать фокус при вводе
