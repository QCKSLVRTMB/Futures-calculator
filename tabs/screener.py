from __future__ import annotations
import pandas as pd
import streamlit as st
from core.calc import build_instruments

def render_screener(*, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, deposit=75000.0, margin_type="КСУР", commission="Т-Инвестиции", mobile=False):
    st.subheader("Скринер фьючерсов MOEX")
    
    if iss_df is None or iss_df.empty:
        st.warning("Нет данных MOEX.")
        return

    # Строим таблицу инструментов с учетом категории риска (как в калькуляторе)
    instruments = build_instruments(iss_df, ims_df, go_df, api_df, md_df, margin_type)
    if not instruments:
        st.warning("Нет данных для отображения.")
        return

    # Собираем данные в список словарей
    rows = []
    for ticker, inst in instruments.items():
        # Считаем, сколько контрактов можно купить/продать на депозит
        qty_long = int(deposit // inst.margin_long) if inst.margin_long > 0 else 0
        qty_short = int(deposit // inst.margin_short) if inst.margin_short > 0 else 0
        
        rows.append({
            "Тикер": ticker,
            "Код актива": inst.asset_code,
            "Название": inst.name,
            "Цена": inst.price,
            "Изм. %": inst.change_pct,
            "ГО Лонг": inst.margin_long,
            "ГО Шорт": inst.margin_short,
            "Дост. Лонг": qty_long,
            "Дост. Шорт": qty_short,
            "ОИ": inst.open_interest,
            "Экспирация": inst.expiry,
        })
    
    df = pd.DataFrame(rows)
    
    # === БЛОК ФИЛЬТРОВ ===
    st.markdown("### Фильтры")
    f1, f2, f3, f4 = st.columns(4)
    
    with f1:
        only_fitting = st.checkbox("Помещающиеся в депо", value=False, help="Скрыть инструменты, на которые не хватает депозита")
    with f2:
        min_oi = st.number_input("Мин. ОИ", min_value=0, value=0, step=100, help="Минимальный открытый интерес (шт. контрактов)")
    with f3:
        min_price = st.number_input("Мин. Цена", min_value=0.0, value=0.0, step=100.0, help="Минимальная стоимость контракта")
    with f4:
        only_near = st.checkbox("Только ближайшие", value=True, help="Оставить только ближайшие к экспирации контракты для каждого актива")

    # Применяем фильтры
    if only_fitting:
        df = df[(df["ГО Лонг"] <= deposit) | (df["ГО Шорт"] <= deposit)]
    if min_oi > 0:
        df = df[df["ОИ"] >= min_oi]
    if min_price > 0:
        df = df[df["Цена"] >= min_price]
    
    if only_near:
        # Преобразуем строки экспирации в datetime для корректной сортировки
        df["_exp_dt"] = pd.to_datetime(df["Экспирация"], errors="coerce")
        # Оставляем по одному контракту (с самой ранней датой) на каждый базовый актив
        df = df.sort_values("_exp_dt").groupby("Код актива", as_index=False).first()
        df = df.drop(columns=["_exp_dt"])

    # Убираем служебную колонку из вывода
    df = df.drop(columns=["Код актива"])

    # === ВЫВОД ТАБЛИЦЫ ===
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Цена": st.column_config.NumberColumn(format="%.2f"),
            "Изм. %": st.column_config.NumberColumn(format="%+.2f%%"),
            "ГО Лонг": st.column_config.NumberColumn(format="%.0f ₽"),
            "ГО Шорт": st.column_config.NumberColumn(format="%.0f ₽"),
            "Дост. Лонг": st.column_config.NumberColumn(format="%d шт."),
            "Дост. Шорт": st.column_config.NumberColumn(format="%d шт."),
            "ОИ": st.column_config.NumberColumn(format="%d"),
        }
    )
    st.caption(f"Найдено {len(df)} инструментов. Категория риска: {margin_type}")
