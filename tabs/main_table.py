import streamlit as st
import pandas as pd
from data import vlookup, to_float, MARGIN_COL_MAP

ALL_TICKERS = ["RMM6", "MMM6", "GNM6", "SRM6", "BMK6", "SFM6", "GZM6", "BTM6", "GKM6"]

def render_main_tab(*, api_df, go_df, md_df, deposit, margin_type):
    st.subheader("📊 Фьючерсы — обзор")

    default = st.session_state.get("tickers") or ALL_TICKERS
    picked = st.multiselect(
        "Тикеры для расчётов (доступны на вкладках «Сделка N»)",
        ALL_TICKERS, default=default, key="main_pick",
    )
    st.session_state["tickers"] = picked
    st.caption(f"Выбрано: {len(picked)} · Депозит: {deposit:,.0f} ₽ · ГО: {margin_type}")

    if not picked:
        st.info("Выберите хотя бы один тикер.")
        return

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
