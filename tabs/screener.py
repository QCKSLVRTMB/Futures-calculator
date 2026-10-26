import streamlit as st
import pandas as pd
from datetime import datetime
from data import get_margin

# Конфиги тарифов — ключами служат ярлыки из sidebar
TARIFF_CONFIGS = {
    "Т-Инвестиции": {"type": "percent", "broker_percent": 0.001, "clearing_fee": 0.0, "min_fee": 0.01},
    "Финам СТАНДАРТНЫЙ ФОРТС": {"type": "fixed", "broker_fee": 0.45, "clearing_fee": 4.65, "min_fee": 0.01},
    "Без комиссии": {"type": "fixed", "broker_fee": 0.0, "clearing_fee": 0.0, "min_fee": 0.0},
}

# Маппинг уровня риска → колонки IMS (LONG, SHORT)
IMS_MARGIN_MAP = {
    "НАЧ. ГО": ("IM_BUY", "IM_SELL"),
    "КНУР":    ("IM_BUY_LRC", "IM_SELL_LRC"),
    "КСУР":    ("IM_BUY_MRC", "IM_SELL_MRC"),
    "КПУР":    ("IM_BUY_HRC", "IM_SELL_HRC"),
    "КОУР":    ("IM_BUY_ERC", "IM_SELL_ERC"),
}


def render_screener(*, iss_df, go_df=None, ims_df=None, deposit=0.0, margin_type="КСУР", commission="Т-Инвестиции"):
    st.subheader("🔍 Скринер фьючерсов MOEX")

    t_conf = TARIFF_CONFIGS.get(commission, TARIFF_CONFIGS["Т-Инвестиции"])

    if iss_df.empty:
        st.info("Нет данных MOEX ISS — проверьте подключение.")
        return

    df = iss_df.copy()

    # ============ КОМИССИИ (из тарифа, выбранного в sidebar) ============
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

    # ============ ГО LONG/SHORT из IMS ============
    buy_col, sell_col = IMS_MARGIN_MAP.get(margin_type, ("IM_BUY", "IM_SELL"))

    ims_has_buy = ims_df is not None and not ims_df.empty and buy_col in ims_df.columns
    ims_has_sell = ims_df is not None and not ims_df.empty and sell_col in ims_df.columns

    def _margin_from_ims(ticker):
        if not (ims_has_buy and ims_has_sell):
            return 0.0, 0.0
        row = ims_df[ims_df["SECID"] == ticker]
        if row.empty:
            return 0.0, 0.0
        row = row.iloc[0]
        try:
            long_m = float(row.get(buy_col, 0) or 0)
            short_m = float(row.get(sell_col, 0) or 0)
        except (ValueError, TypeError):
            return 0.0, 0.0
        return long_m, short_m

    def _margin_fallback(ticker):
        # fallback: Google Sheets -> INITIALMARGIN
        long_m = short_m = 0.0
        if go_df is not None and not go_df.empty:
            try:
                long_m = float(get_margin(go_df, ticker, margin_type, "LONG"))
                short_m = float(get_margin(go_df, ticker, margin_type, "SHORT"))
            except Exception:
                pass
        if long_m <= 0 or short_m <= 0:
            iss_row = iss_df[iss_df["SECID"] == ticker]
            if not iss_row.empty:
                init_m = float(iss_row.iloc[0].get("INITIALMARGIN", 0) or 0)
                if long_m <= 0: long_m = init_m
                if short_m <= 0: short_m = init_m
        return long_m, short_m

    long_list, short_list, source_list = [], [], []
    for t in df["SECID"]:
        l, s = _margin_from_ims(t)
        if l > 0 and s > 0:
            source_list.append("IMS")
        else:
            l2, s2 = _margin_fallback(t)
            l = l if l > 0 else l2
            s = s if s > 0 else s2
            source_list.append("FALLBACK")
        long_list.append(l)
        short_list.append(s)

    df["MarginLong"]  = long_list
    df["MarginShort"] = short_list
    df["MarginUsed"]  = df[["MarginLong", "MarginShort"]].min(axis=1)
    df["MarginSrc"]   = source_list

    def _max_contracts(m, dep):
        try:
            m = float(m); dep = float(dep)
            if m <= 0 or dep <= 0:
                return 0
            return int(dep // m)
        except Exception:
            return 0

    df["MaxContracts"] = df["MarginUsed"].apply(lambda m: _max_contracts(m, deposit))

    # ============ Инфо-строка об источнике ГО ============
    ims_source_ok = ims_has_buy and ims_has_sell
    sample_ticker = df.iloc[0]["SECID"] if len(df) else "—"
    sample_row = ims_df[ims_df["SECID"] == sample_ticker] if (ims_df is not None and not ims_df.empty and "SECID" in ims_df.columns) else pd.DataFrame()
    sample_text = ""
    if not sample_row.empty and ims_source_ok:
        try:
            sample_text = f" · пример {sample_ticker}: {float(sample_row.iloc[0][buy_col]):,.0f} / {float(sample_row.iloc[0][sell_col]):,.0f} ₽"
        except Exception:
            sample_text = ""

    if ims_source_ok:
        st.caption(
            f"Тариф: **{commission}** · Тип ГО: **{margin_type}** · Депозит: **{deposit:,.0f} ₽** · "
            f"Источник ГО: IMS (`{buy_col}` / `{sell_col}`){sample_text}"
        )
    else:
        missing = []
        if not ims_has_buy: missing.append(buy_col)
        if not ims_has_sell: missing.append(sell_col)
        st.warning(
            f"В IMS нет колонок `{', '.join(missing)}` для уровня **{margin_type}** — "
            f"используется fallback (Google Sheets / INITIALMARGIN из ISS). "
            f"ГО для разных уровней может совпадать. Нажмите «Обновить данные» в sidebar, "
            f"чтобы перезагрузить IMS, или выберите другой тип ГО."
        )

    if ims_df is None or ims_df.empty:
        st.info("Данные ГО (IMS) недоступны — используется Google Sheets / INITIALMARGIN.")

    # ============ ФИЛЬТРЫ ============
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        search = st.text_input("Поиск по тикеру / имени", "", key="scr_search")
    with f2:
        assets = sorted(df["ASSETCODE"].dropna().unique().tolist())
        asset_pick = st.multiselect(
            f"Код актива ({len(assets)})",
            assets, default=[], key="scr_asset",
            help="Можно выбрать несколько активов одновременно",
        )
        if asset_pick:
            c_l, c_r = st.columns([3, 1])
            with c_l:
                st.caption(f"Выбрано: {len(asset_pick)} из {len(assets)}")
            with c_r:
                if st.button("Сброс", key="scr_asset_reset", use_container_width=True):
                    st.session_state["scr_asset"] = []
                    st.rerun()
    with f3:
        exp_dates = sorted(df["LASTTRADEDATE"].dropna().unique().tolist())
        exp_pick = st.multiselect(
            f"Экспирация ({len(exp_dates)})",
            exp_dates, default=[], key="scr_exp",
            help="Можно выбрать несколько дат экспирации одновременно",
        )
        if exp_pick:
            c_l, c_r = st.columns([3, 1])
            with c_l:
                st.caption(f"Выбрано: {len(exp_pick)} из {len(exp_dates)}")
            with c_r:
                if st.button("Сброс", key="scr_exp_reset", use_container_width=True):
                    st.session_state["scr_exp"] = []
                    st.rerun()
    with f4:
        only_traded = st.checkbox("Только торгуемые", value=True, key="scr_traded")

    col_fit, _ = st.columns([2, 3])
    with col_fit:
        only_fitting = st.checkbox(
            "Только помещающиеся в депозит",
            value=False,
            key="scr_fit",
            help=f"Скрыть контракты, на которые не хватает депозита ({deposit:,.0f} ₽) при выбранном типе ГО ({margin_type}).",
        )

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

    # ============ ФРОНТ-МЕСЯЦЫ ============
    main_tickers = view.sort_values("VALTODAY", ascending=False).drop_duplicates("ASSETCODE")["SECID"].tolist()

    # ============ ВЫВОД ============
    out = view.rename(columns={
        "SECID": "Тикер", "SHORTNAME": "Краткое наименование", "LAST": "Текущая цена",
        "Notional": "Стоимость контракта", "LOTVOLUME": "Доступных лотов", "MINSTEP": "Шаг цены",
        "LASTTRADEDATE": "Дата экспирации", "ASSETCODE": "Код актива", "OPENPOSITION": "Открытых позиций",
        "LOTSIZE": "Лот", "INITIALMARGIN": "ГО (ISS sec)",
        "MarginLong": "ГО LONG", "MarginShort": "ГО SHORT",
        "MarginUsed": "ГО (min)", "MaxContracts": "Макс. контрактов",
        "HIGH": "Верхний лимит", "LOW": "Нижний лимит", "STEPPRICE": "Стоимость шага цены",
        "PREVSETTLEPRICE": "Расчетная цена", "PREVPRICE": "Предыдущая цена",
        "Updated": "Дата", "Commission_1": "Комиссия на 1 сделку",
        "Commission_addr": "Комиссия на адресную сделку", "Commission_clear": "Клиринговая комиссия"
    })[[
        "Тикер", "Краткое наименование", "Текущая цена", "Стоимость контракта",
        "ГО (ISS sec)", "ГО LONG", "ГО SHORT", "ГО (min)", "Макс. контрактов",
        "Доступных лотов", "Шаг цены", "Дата экспирации", "Код актива",
        "Открытых позиций", "Лот", "Верхний лимит", "Нижний лимит", "Стоимость шага цены",
        "Расчетная цена", "Предыдущая цена", "Дата",
        "Комиссия на 1 сделку", "Комиссия на адресную сделку", "Клиринговая комиссия"
    ]]

    def _row_style(row):
        if row["Тикер"] in main_tickers:
            return ["background-color: #198754; color: white; font-weight: bold"] * len(row)
        if row["Макс. контрактов"] == 0:
            return ["background-color: #f8d7da; color: #842029"] * len(row)
        return [""] * len(row)

    styled = out.style.apply(_row_style, axis=1).format({
        "Текущая цена": "{:,.2f}",
        "Стоимость контракта": "{:,.0f} ₽",
        "ГО (ISS sec)": "{:,.0f} ₽",
        "ГО LONG": "{:,.0f} ₽",
        "ГО SHORT": "{:,.0f} ₽",
        "ГО (min)": "{:,.0f} ₽",
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
            "ГО LONG": st.column_config.NumberColumn(help=f"ГО на покупку из IMS ({buy_col}) по уровню {margin_type}"),
            "ГО SHORT": st.column_config.NumberColumn(help=f"ГО на продажу из IMS ({sell_col}) по уровню {margin_type}"),
            "ГО (min)": st.column_config.NumberColumn(help="min(ГО LONG, ГО SHORT) — используется для расчёта"),
            "Макс. контрактов": st.column_config.NumberColumn(help="Депозит / ГО (min)"),
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
