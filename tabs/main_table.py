import streamlit as st
import pandas as pd
from data import fetch_moex_forts, vlookup, to_float, MARGIN_COL_MAP

def render_main_tab(*, api_df, go_df, md_df, deposit, margin_type):
    st.subheader("📊 Фьючерсы — обзор")

    # 1. Получаем данные ISS для списка тикеров
    iss_df = fetch_moex_forts()
    
    # Фильтруем для списка только те, по которым сегодня были сделки (чтобы не засорять выпадающий список)
    if not iss_df.empty:
        active_iss = iss_df[iss_df["VALTODAY"].fillna(0) > 0]
        available_tickers = sorted(active_iss["SECID"].dropna().unique().tolist())
    else:
        available_tickers = []

    # 2. Интерфейс выбора тикеров
    st.markdown("#### Выбор инструментов для расчетов")
    c1, c2 = st.columns([3, 2])
    
    with c1:
        # Стандартный набор (если он есть в ISS)
        default_tickers = ["RMM6", "MMM6", "GNM6", "SRM6", "BMK6", "SFM6", "GZM6", "BTM6", "GKM6"]
        default_selection = [t for t in default_tickers if t in available_tickers]
        if not default_selection and available_tickers:
            default_selection = available_tickers[:5]

        selected_from_iss = st.multiselect(
            "Выберите из списка MOEX ISS",
            options=available_tickers,
            default=default_selection,
            help="Показаны только контракты, по которым были торги в текущую сессию"
        )
        
    with c2:
        manual_input = st.text_input(
            "Ввести тикер вручную (через запятую)",
            "",
            help="Например: RIZ6, SiZ6. Добавится к выбранным выше."
        )

    # 3. Объединяем списки и убираем дубликаты
    manual_list = [x.strip().upper() for x in manual_input.split(",") if x.strip()]
    picked = list(dict.fromkeys(selected_from_iss + manual_list)) # dict.fromkeys сохраняет порядок и убирает дубли

    st.session_state["tickers"] = picked
    st.caption(f"Выбрано: **{len(picked)}** · Депозит: **{deposit:,.0f} ₽** · Тип ГО: **{margin_type}**")

    if not picked:
        st.info("Выберите хотя бы один тикер для отображения таблицы.")
        return

    # 4. Формирование таблицы из Google Sheets (как и раньше)
    col_go, col_go2 = MARGIN_COL_MAP[margin_type]
    rows = []
    for t in picked:
        margin = to_float(vlookup(go_df, t, col_go))
        rows.append({
            "Тикер":       t,
            "Код":         vlookup(api_df, t, 9),
            "Наименование":vlookup(api_df, t, 3),
            "Шаг":         vlookup(api_df, t, 6),
            "Ст. шага":    vlookup(api_df, t, 17),
            f"ГО ({margin_type})": margin if margin else "—",
            "Цена":        vlookup(md_df, t, 9),
            "Экспирация":  vlookup(api_df, t, 7),
            "Макс. контрактов": int(deposit // margin) if margin else "—",
            "Риск, %":     round(margin/deposit*100, 2) if margin else None,
        })
        
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
