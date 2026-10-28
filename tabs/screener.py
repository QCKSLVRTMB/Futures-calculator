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
    
    col1, col2, col3 = st.columns(3)
    with col1:
        only_fitting = st.checkbox("Помещающиеся в депо", value=False, help="Скрыть инструменты, на которые не хватает депозита")
    with col2:
        min_oi = st.number_input("Мин. ОИ", min_value=0, value=0, step=100, help="Минимальный открытый интерес (шт. контрактов)")
    with col3:
        min_price = st.number_input("Мин. Цена", min_value=0.0, value=0.0, step=100.0, help="Минимальная стоимость контракта")

    col4, col5 = st.columns([1, 1])
    with col4:
        only_near = st.checkbox("Только ближайшие", value=True, help="Оставить только ближайшие к экспирации контракты для каждого актива")
    
    with col5:
        # Определяем максимальное ГО для ползунка
        max_go_val = int(df["ГО Лонг"].max()) if not df.empty and df["ГО Лонг"].max() > 0 else 100000
        step_val = max(100, max_go_val // 100)
        
        # Инициализация и защита от выхода за пределы при смене фильтров
        if "go_limit_filter" not in st.session_state or st.session_state.go_limit_filter > max_go_val:
            st.session_state.go_limit_filter = max_go_val

        # Коллбэки для синхронизации
        def _update_slider():
            st.session_state.go_limit_filter = st.session_state.go_num
            
        def _update_num():
            st.session_state.go_limit_filter = st.session_state.go_slider

        # Две колонки: слайдер шире, поле ввода уже
        c_go1, c_go2 = st.columns([3, 1])
        with c_go1:
            st.slider(
                "Макс. ГО (руб.)", 
                min_value=0, 
                max_value=max_go_val, 
                step=step_val, 
                key="go_slider", 
                on_change=_update_num,
                value=st.session_state.go_limit_filter
            )
        with c_go2:
            # Добавляем отступ сверху, чтобы выровнять с ползунком
            st.write("") 
            st.number_input(
                "ГО, ₽", 
                min_value=0, 
                max_value=max_go_val, 
                step=step_val, 
                key="go_num", 
                on_change=_update_slider,
                value=st.session_state.go_limit_filter,
                label_visibility="collapsed"
            )

    # Применяем фильтры
    if only_fitting:
        df = df[(df["ГО Лонг"] <= deposit) | (df["ГО Шорт"] <= deposit)]
    if min_oi > 0:
        df = df[df["ОИ"] >= min_oi]
    if min_price > 0:
        df = df[df["Цена"] >= min_price]
    
    # Фильтр по максимальному ГО
    go_limit = st.session_state.go_limit_filter
    if go_limit < max_go_val:
        df = df[(df["ГО Лонг"] <= go_limit) & (df["ГО Шорт"] <= go_limit)]
    
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
