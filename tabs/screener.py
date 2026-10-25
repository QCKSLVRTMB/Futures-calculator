import streamlit as st
import pandas as pd
from datetime import datetime
from data import fetch_moex_forts

TARIFFS = {
    "Финам СТАНДАРТНЫЙ ФОРТС": {
        "type": "fixed", "broker_fee": 0.45, "clearing_fee": 4.65, "min_fee": 0.01,
    },
    "Т-Инвестиции ИНВЕСТОР": {
        "type": "percent", "broker_percent": 0.001, "clearing_fee": 0.0, "min_fee": 0.01,
    },
    "Без комиссии брокера (только биржа)": {
        "type": "fixed", "broker_fee": 0.0, "clearing_fee": 0.0, "min_fee": 0.0,
    },
}

def render_screener():
    st.subheader("🔍 Скринер фьючерсов MOEX")

    # ---------- Выбор тарифа ----------
    t1, t2 = st.columns([2, 3])
    with t1:
        selected_tariff = st.selectbox(
            "Тариф брокера", list(TARIFFS.keys()), index=0, key="scr_tariff"
        )
    with t2:
        st.write("")
        st.caption("Комиссии рассчитываются для покупки и продажи через торговые программы.")

    t_conf = TARIFFS[selected_tariff]

    # ---------- Загрузка данных ----------
    df = fetch_moex_forts()
    if df.empty:
        st.info("Нет данных MOEX ISS — проверьте подключение.")
        return

    # ---------- Расчёт комиссий ----------
    if t_conf["type"] == "fixed":
        df["Commission_1"] = t_conf["broker_fee"] + df["BUYSELLFEE"]
        df["Commission_addr"] = t_conf["broker_fee"]
        df["Commission_clear"] = t_conf["clearing_fee"] + df["BUYSELLFEE"]
    elif t_conf["type"] == "percent":
        raw_broker_fee = df["Notional"] * t_conf["broker_percent"]
        fee_candidates = pd.DataFrame({
            "raw":      raw_broker_fee,
            "exchange": df["BUYSELLFEE"],
            "min":      t_conf["min_fee"],
        })
        df["Commission_1"] = fee_candidates.max(axis=1)
        df["Commission_addr"] = df["Commission_1"]
        df["Commission_clear"] = t_conf["clearing_fee"] + df["BUYSELLFEE"]

    # ---------- Фильтры ----------
    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    with f1:
        search = st.text_input("Поиск по тикеру / имени", "", key="scr_search")
    with f2:
        assets = sorted(df["ASSETCODE"].dropna().unique().tolist())
        asset_pick = st.multiselect("Код актива", assets, default=[], key="scr_asset")
    with f3:
        exp_dates = sorted(df["LASTTRADEDATE"].dropna().unique().tolist())
        exp_pick = st.multiselect("Экспирация", exp_dates, default=[], key="scr_exp")
    with f4:
        only_traded = st.checkbox("Только торгуемые", value=True, key="scr_traded")

    # ---------- Применение фильтров ----------
    view = df.copy()
    if search:
        s = search.strip().upper()
        view = view[
            view["SECID"].str.upper().str.contains(s, na=False) |
            view["SHORTNAME"].str.upper().str.contains(s, na=False)
        ]
    if asset_pick:
        view = view[view["ASSETCODE"].isin(asset_pick)]
    if exp_pick:
        view = view[view["LASTTRADEDATE"].isin(exp_pick)]
    if only_traded:
        view = view[view["VALTODAY"].fillna(0) > 0]

    if view.empty:
        st.warning("По заданным фильтрам инструментов не найдено.")
        return

    # ---------- Формирование столбцов ----------
    out = view.rename(columns={
        "SECID":           "Тикер",
        "SHORTNAME":       "Краткое наименование",
        "LAST":            "Текущая цена",
        "Notional":        "Стоимость контракта",
        "LOTVOLUME":       "Доступных лотов",
        "MINSTEP":         "Шаг цены",
        "LASTTRADEDATE":   "Дата экспирации",
        "ASSETCODE":       "Код актива",
        "OPENPOSITION":    "Открытых позиций",
        "LOTSIZE":         "Лот",
        "INITIALMARGIN":   "Гарантийное обеспечение",
        "HIGH":            "Верхний лимит",
        "LOW":             "Нижний лимит",
        "STEPPRICE":       "Стоимость шага цены",
        "PREVSETTLEPRICE": "Расчетная цена",
        "PREVPRICE":       "Предыдущая цена",
        "Updated":         "Дата",
        "Commission_1":    "Комиссия на 1 сделку",
        "Commission_addr": "Комиссия на адресную сделку",
        "Commission_clear":"Клиринговая комиссия",
    })[[
        "Тикер", "Краткое наименование", "Текущая цена", "Стоимость контракта",
        "Доступных лотов", "Шаг цены", "Дата экспирации", "Код актива",
        "Открытых позиций", "Лот", "Гарантийное обеспечение", "Верхний лимит",
        "Нижний лимит", "Стоимость шага цены", "Расчетная цена", "Предыдущая цена",
        "Дата", "Комиссия на 1 сделку", "Комиссия на адресную сделку",
        "Клиринговая комиссия",
    ]]

    # ---------- Подсветка главного контракта по каждому активу ----------
    main_tickers = (
        view.sort_values("VALTODAY", ascending=False)
            .drop_duplicates("ASSETCODE")["SECID"]
            .tolist()
    )

    def _row_style(row):
        if row["Тикер"] in main_tickers:
            return ["background-color: #198754; color: white; font-weight: bold"] * len(row)
        return [""] * len(row)

    # ---------- Форматирование ----------
    styled = out.style.apply(_row_style, axis=1).format(
        {
            "Текущая цена":                "{:,.2f}",
            "Стоимость контракта":         "{:,.0f} ₽",
            "Гарантийное обеспечение":     "{:,.0f} ₽",
            "Стоимость шага цены":         "{:,.2f}",
            "Предыдущая цена":             "{:,.2f}",
            "Расчетная цена":              "{:,.2f}",
            "Верхний лимит":               "{:,.2f}",
            "Нижний лимит":                "{:,.2f}",
            "Открытых позиций":            "{:,.0f}",
            "Доступных лотов":             "{:,.0f}",
            "Лот":                         "{:,.0f}",
            "Шаг цены":                    "{:,.6g}",
            "Комиссия на 1 сделку":        "{:,.2f} ₽",
            "Комиссия на адресную сделку": "{:,.2f} ₽",
            "Клиринговая комиссия":        "{:,.2f} ₽",
        },
        na_rep="—",
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=800,
        column_config={
            "Тикер":                st.column_config.TextColumn(width="small"),
            "Краткое наименование": st.column_config.TextColumn(width="medium"),
            "Дата":                 st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
        },
    )

    # ---------- Итоги ----------
    c1, c2, c3 = st.columns(3)
    c1.metric("Инструментов", len(view))
    c2.metric(
        "Максимальный VALTODAY",
        f"{view['VALTODAY'].max():,.0f} ₽" if not view.empty else "—",
    )
    c3.metric("Обновлено", datetime.now().strftime("%H:%M:%S"))
