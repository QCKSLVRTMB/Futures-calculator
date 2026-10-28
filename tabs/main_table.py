from __future__ import annotations
import streamlit as st
import pandas as pd
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
        st.multiselect(
            "Выбрать из списка MOEX ISS", 
            options=available_tickers, 
            key="picker_ms", 
            on_change=update_active_tickers,
            help="Нажмите на крестик рядом с тикером, чтобы удалить его"
        )
    with c2:
        st.text_input("Ввести тикер вручную (через запятую)", key="picker_txt", on_change=update_active_tickers)

    picked = st.session_state["active_tickers"]
    if not picked:
        st.info("Выберите хотя бы один тикер для отображения данных.")
        return

    # === 1. НАСТРОЙКА ТРЕНДОВ (Спрятана в спойлер, чтобы не мешать) ===
    with st.expander("Настройка параметров рынка (Тренд, Волна, Тенденция)", expanded=False):
        rows = []
        for t in picked:
            inst = get_instrument(t, iss_df=iss_df, go_df=go_df, api_df=api_df, md_df=md_df, margin_type=margin_type)
            
            margin_go = min(inst.margin_long, inst.margin_short) if inst.margin_long > 0 and inst.margin_short > 0 else max(inst.margin_long, inst.margin_short)
            max_contracts = int(deposit // margin_go) if margin_go > 0 else 0
            risk_pct = round(margin_go / deposit * 100, 2) if margin_go > 0 and deposit > 0 else 0.0

            m = state.ticker(t)["market"]
            rows.append({
                "Тикер": t,
                "Наименование": inst.name,
                "ГО": margin_go,
                "Доступно": max_contracts,
                "Риск, %": risk_pct,
                "Тренд": m["trend"],
                "Волна": m["wave"],
                "Тенденция": m["tendency"],
            })
            
        df = pd.DataFrame(rows)
        
        edited_df = st.data_editor(
            df, use_container_width=True, hide_index=True,
            column_config={
                "Тренд": st.column_config.SelectboxColumn("Тренд", options=TREND_VALUES, required=True),
                "Волна": st.column_config.SelectboxColumn("Волна", options=TREND_VALUES, required=True),
                "Тенденция": st.column_config.SelectboxColumn("Тенденция", options=TREND_VALUES, required=True),
                "ГО": st.column_config.NumberColumn(format="%.2f ₽"),
                "Риск, %": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100),
            },
            disabled=["Тикер", "Наименование", "ГО", "Доступно", "Риск, %"],
            key="main_table_editor"
        )

        for _, row in edited_df.iterrows():
            state.ticker(row["Тикер"])["market"].update({"trend": row["Тренд"], "wave": row["Волна"], "tendency": row["Тенденция"]})
        state.autosave()

    # === 2. РЫНОЧНЫЕ ДАННЫЕ ИЗ ISS ===
    st.markdown("#### Рыночные данные")
    
    view = iss_df[iss_df["SECID"].isin(picked)].copy()
    
    # Сортировка по объему торгов (ликвидности)
    sort_col = "LOTVOLUME" if "LOTVOLUME" in view.columns else ("VALTODAY" if "VALTODAY" in view.columns else "SECID")
    view = view.sort_values(by=sort_col, ascending=False)

    # Подготовка колонок под скриншот
    out = view[["SECID", "LAST", "LASTCHANGEPRCNT", "HIGH", "LOW", "LOTVOLUME", "NUMTRADES", "OPENPOSITION"]].copy()
    out.columns = [
        "Тикер", "Последняя сделка", "Изм. к закрытию", 
        "Макс. за день", "Мин. за день", "Объем торгов (контр.)", 
        "Число сделок", "Открытых позиций"
    ]

    # Функция для окрашивания процентов
    def color_change(val):
        if pd.isna(val): return ''
        if val > 0: return 'color: #16a34a; font-weight: 600;'
        elif val < 0: return 'color: #dc2626; font-weight: 600;'
        return ''

    # Форматирование (заменяем точки на запятые, тысячи на пробелы)
    styled_df = out.style.map(color_change, subset=["Изм. к закрытию"]).format({
        "Последняя сделка": lambda x: f"{x:,.4f}".replace(",", " ").replace(".", ",") if pd.notna(x) else "-",
        "Изм. к закрытию": lambda x: f"{x:+.2f}%".replace(".", ",") if pd.notna(x) else "-",
        "Макс. за день": lambda x: f"{x:,.4f}".replace(",", " ").replace(".", ",") if pd.notna(x) else "-",
        "Мин. за день": lambda x: f"{x:,.4f}".replace(",", " ").replace(".", ",") if pd.notna(x) else "-",
        "Объем торгов (контр.)": lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "-",
        "Число сделок": lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "-",
        "Открытых позиций": lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "-",
    })

    st.dataframe(
        styled_df, 
        use_container_width=True, 
        hide_index=True,
        height=400
    )
