import streamlit as st
import pandas as pd
from data import fetch_moex_forts, vlookup, to_float, MARGIN_COL_MAP


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

    c1, c2 = st.columns([3, 2])
    with c1:
        selected_from_iss = st.multiselect(
            "Выбрать из списка MOEX ISS",
            options=available_tickers,
            default=st.session_state.get("active_tickers", []),
            key="picker_ms",
            help="Показаны только контракты, по которым были торги в текущую сессию",
        )
    with c2:
        manual_input = st.text_input(
            "Ввести тикер вручную (через запятую)",
            value=st.session_state.get("picker_txt", ""),
            key="picker_txt",
            help="Например: RIZ6, SiZ6",
        )

    # ---------- Синхронизация со session_state ----------
    manual_list = [x.strip().upper() for x in manual_input.split(",") if x.strip()]
    new_active = list(dict.fromkeys(selected_from_iss + manual_list))  # dedup + порядок
    current = st.session_state.get("active_tickers", [])

    if new_active != current:
        st.session_state["active_tickers"] = new_active
        st.rerun()  # перестроит вкладки

    picked = st.session_state["active_tickers"]
    st.caption(
        f"Выбрано: **{len(picked)}** · Депозит: **{deposit:,.0f} ₽** · "
        f"Тип ГО: **{margin_type}**"
    )

    if not picked:
        st.info(
            "👆 Выберите хотя бы один тикер — для каждого появится отдельная "
            "вкладка с калькулятором позиции."
        )
        return

    # ---------- Таблица по выбранным тикерам ----------
    col_go, _ = MARGIN_COL_MAP[margin_type]
    rows = []
    for t in picked:
        margin = to_float(vlookup(go_df, t, col_go))
        rows.append({
            "Тикер":        t,
            "Код":          vlookup(api_df, t, 9),
            "Наименование": vlookup(api_df, t, 3),
            "Шаг":          vlookup(api_df, t, 6),
            "Ст. шага":     vlookup(api_df, t, 17),
            f"ГО ({margin_type})": margin if margin else "—",
            "Цена":         vlookup(md_df, t, 9),
            "Экспирация":   vlookup(api_df, t, 7),
            "Макс. контрактов": int(deposit // margin) if margin else "—",
            "Риск, %":      round(margin / deposit * 100, 2) if margin else None,
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
