import streamlit as st
import pandas as pd
from datetime import datetime
from data import get_margin

TARIFFS = {
    "Финам СТАНДАРТНЫЙ ФОРТС": {"type": "fixed", "broker_fee": 0.45, "clearing_fee": 4.65, "min_fee": 0.01},
    "Т-Инвестиции ИНВЕСТОР": {"type": "percent", "broker_percent": 0.001, "clearing_fee": 0.0, "min_fee": 0.01},
    "Без комиссии брокера (только биржа)": {"type": "fixed", "broker_fee": 0.0, "clearing_fee": 0.0, "min_fee": 0.0}
}

def render_screener(*, iss_df, go_df=None, deposit=0.0, margin_type="КСУР"):
    st.subheader("🔍 Скринер фьючерсов MOEX")

    t1, t2 = st.columns([2, 3])
    with t1:
        selected_tariff = st.selectbox("Тариф брокера", list(TARIFFS.keys()), index=0, key="scr_tariff")
    with t2:
        st.write("")
        st.caption("Комиссии рассчитываются для покупки и продажи через торговые программы.")

    t_conf = TARIFFS[selected_tariff]

    if iss_df.empty:
        st.info("Нет данных MOEX ISS — проверьте подключение.")
        return

    df = iss_df.copy()

    # ============ КОМИССИИ ============
    if t_conf["type"] == "fixed":
        df["Commission_1"] = t_conf["broker_fee"] + df["BUYSELLFEE"]
        df["Commission_addr"] = t_conf["broker_fee"]
        df["Commission_clear"] = t_conf["clearing_fee"] + df["BUYSELLFEE"]
    elif t_conf["type"] == "percent":
        raw_broker_fee = df["Notional"] * t_conf["broker_percent"]
        fee_candidates = pd.DataFrame({"raw": raw_broker_fee, "exchange": df["BUYSELLFEE"], "min": t_conf["min_fee"]})
        df["Commission_1"] = fee_candidates.max(axis=1)
        df["Commission_addr"] = df["Commission_1"]
        df["Commission_clear"] = t_conf["clearing_fee"] + df["BUYSELLFEE"]

    # ============ ГО по выбранному тарифу ============
    def _margin_for_ticker(t):
        if go_df is None or go_df.empty:
            return 0.0
        try:
            return float(get_margin(go_df, t, margin_type, "LONG"))
        except Exception:
            return 0.0

    df["TariffMargin"] = df["SECID"].apply(_margin_for_ticker)
    df["MarginUsed"] = df["TariffMargin"].where(df["TariffMargin"] > 0, df["INITIALMARGIN"])

    def _max_contracts(m, dep):
        try:
            m = float(m); dep = float(dep)
            if m <= 0 or dep <= 0:
                return 0
            return int(dep // m)
        except Exception:
            return 0

    df["MaxContracts"] = df["MarginUsed"].apply(lambda m: _max_contracts(m, deposit))

    if go_df is None or go_df.empty:
        st.warning("Данные ГО из Google Sheets недоступны — используется начальное ГО из MOEX ISS.")

    # ============ ФИЛЬТРЫ ============
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

    col_fit, col_info = st.columns([2, 3])
    with col_fit:
        only_fitting = st.checkbox(
            "Только помещающиеся в депозит",
            value=False,
            key="scr_fit",
            help=f"Скрыть контракты, на которые не хватает депозита ({deposit:,.0f} ₽) при выбранном типе ГО ({margin_type}).",
        )
    with col_info:
        st.caption(f"Тип ГО: **{margin_type}** · Депозит: **{deposit:,.0f} ₽**")

    view = df.copy()
    if search:
        s = search.strip().upper()
        view = view[view["SECID"].str.upper().str.contains(s, na=False) | view["SHORTNAME"].str.upper().str.contains(s, na=False)]
    if asset_pick:
        view = view[view["ASSETCODE"].isin(asset_pick)]
    if exp_pick:
        view = view[view["LASTTRADEDATE"].isin(exp_pick)]
    if only_traded:
        view = view[view["VALTODAY"].fillna(0) > 0]
    if only_fitting:
        view = view[view["MaxContracts"] >= 1]

    if view.empty:
        st.warning("По заданным фильтрам инструментов не найдено.")
        return

    # ============ ФРОНТ-МЕСЯЦЫ (по VALTODAY) ============
    main_tickers = view.sort_values("VALTODAY", ascending=False).drop_duplicates("ASSETCODE")["SECID"].tolist()

    # ============ ВЫВОД ============
    out = view.rename(columns={
        "SECID": "Тикер", "SHORTNAME": "Краткое наименование", "LAST": "Текущая цена",
        "Notional": "Стоимость контракта", "LOTVOLUME": "Доступных лотов", "MINSTEP": "Шаг цены",
        "LASTTRADEDATE": "Дата экспирации", "ASSETCODE": "Код актива", "OPENPOSITION": "Открытых позиций",
        "LOTSIZE": "Лот", "INITIALMARGIN": "ГО (ISS)",
        "MarginUsed": "ГО по тарифу", "MaxContracts": "Макс. контрактов",
        "HIGH": "Верхний лимит", "LOW": "Нижний лимит", "STEPPRICE": "Стоимость шага цены",
        "PREVSETTLEPRICE": "Расчетная цена", "PREVPRICE": "Предыдущая цена",
        "Updated": "Дата", "Commission_1": "Комиссия на 1 сделку",
        "Commission_addr": "Комиссия на адресную сделку", "Commission_clear": "Клиринговая комиссия"
    })[[
        "Тикер", "Краткое наименование", "Текущая цена", "Стоимость контракта",
        "ГО (ISS)", "ГО по тарифу", "Макс. контрактов",
        "Доступных лотов", "Шаг цены", "Дата экспирации", "Код актива",
        "Открытых позиций", "Лот", "Верхний лимит", "Нижний лимит", "Стоимость шага цены",
        "Расчетная цена", "Предыдущая цена", "Дата",
        "Комиссия на 1 сделку", "Комиссия на адресную сделку", "Клиринговая комиссия"
    ]]

    def _row_style(row):
        # приоритет: главный контракт (зелёный) > не помещается в депозит (красный)
        if row["Тикер"] in main_tickers:
            return ["background-color: #198754; color: white; font-weight: bold"] * len(row)
        if row["Макс. контрактов"] == 0:
            return ["background-color: #f8d7da; color: #842029"] * len(row)
        return [""] * len(row)

    styled = out.style.apply(_row_style, axis=1).format({
        "Текущая цена": "{:,.2f}",
        "Стоимость контракта": "{:,.0f} ₽",
        "ГО (ISS)": "{:,.0f} ₽",
        "ГО по тарифу": "{:,.0f} ₽",
        "Макс. контрактов": "{:,.0f}",
        "Доступных лотов": "{:,.0f}",
        "Открытых позиций": "{:,.0f}",
        "Лот": "{:,.0f}",
        "Шаг цены": "{:,.6g}",
        "Стоимость шага цены": "{:,.2f}",
        "Предыдущая цена": "{:,.2f}",
        "Расчетная цена": "{:,.2f}",
        "Верхний лимит": "{:,.2f}",
        "Нижний лимит": "{:,.2f}",
        "Комиссия на 1 сделку": "{:,.2f} ₽",
        "Комиссия на адресную сделку": "{:,.2f} ₽",
        "Клиринговая комиссия": "{:,.2f} ₽",
    }, na_rep="—")

    st.dataframe(
        styled, use_container_width=True, hide_index=True, height=800,
        column_config={
            "Тикер": st.column_config.TextColumn(width="small"),
            "Краткое наименование": st.column_config.TextColumn(width="medium"),
            "Дата": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
            "ГО по тарифу": st.column_config.NumberColumn(help="ГО по выбранному типу риска из Google Sheets"),
            "Макс. контрактов": st.column_config.NumberColumn(help="Сколько контрактов помещается на депозит при выбранном ГО"),
        },
    )

    st.caption(
        "🟢 — самый торгуемый контракт по ASSETCODE (по VALTODAY)  ·  "
        "🔴 — ГО превышает депозит (не хватает на 1 контракт)"
    )

    fit_count = int((view["MaxContracts"] >= 1).sum())
    total_count = len(view)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Инструментов", total_count)
    c2.metric("Помещается на депозит", f"{fit_count} / {total_count}")
    c3.metric("Максимальный VALTODAY", f"{view['VALTODAY'].max():,.0f} ₽" if not view.empty else "—")
    c4.metric("Обновлено", datetime.now().strftime("%H:%M:%S"))
