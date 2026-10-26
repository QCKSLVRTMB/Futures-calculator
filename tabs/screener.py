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

# Известные коды базовых активов для эвристики классификации
ASSET_BA_MAP = {
    "RTS": "Индекс", "MIX": "Индекс", "MXI": "Индекс", "IMOEX": "Индекс",
    "RGBI": "Индекс", "RVI": "Индекс", "MXM": "Индекс", "SPYF": "Индекс",
    "SI": "Валюта", "EU": "Валюта", "CNY": "Валюта", "USD": "Валюта",
    "EUR": "Валюта", "GBP": "Валюта", "ED": "Валюта", "USDRUB": "Валюта",
    "BR": "Товар", "GD": "Товар", "PT": "Товар", "PD": "Товар",
    "SV": "Товар", "GOLD": "Товар", "SILV": "Товар", "NG": "Товар",
    "RUIBS": "Ставка", "RUONIA": "Ставка",
}


# ============ ЕДИНЫЙ ФОРМАТ ЧИСЕЛ ============
def _fmt_money(v):
    """Денежный формат: 19747,62 ₽ (без разделителей тысяч, запятая, 2 знака)"""
    try:
        return f"{float(v):.2f}".replace(".", ",") + " ₽"
    except Exception:
        return str(v)


def _fmt_price(v):
    """Цена: 19747,62 (без разделителей тысяч, запятая, 2 знака)"""
    try:
        return f"{float(v):.2f}".replace(".", ",")
    except Exception:
        return str(v)


def _fmt_int(v):
    """Целое число: 19748 (без разделителей)"""
    try:
        return f"{int(round(float(v)))}"
    except Exception:
        return str(v)


def _fmt_step(v):
    """Шаг цены: 0,01 / 1 / 10 — без хвостовых нулей, запятая"""
    try:
        v = float(v)
        if v == int(v):
            return f"{int(v)}"
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    except Exception:
        return str(v)


def _classify_ba_type(group, asset_code):
    """Тип БА: Индекс / Акция / Валюта / Товар / Ставка / Фонд / Прочее."""
    g = str(group).lower() if group else ""
    a = str(asset_code).upper() if asset_code else ""

    if "индекс" in g or "index" in g:
        return "Индекс"
    if "валют" in g or "currency" in g or "forex" in g:
        return "Валюта"
    if "товар" in g or "commodit" in g:
        return "Товар"
    if "акци" in g or "stock" in g or "share" in g or "equity" in g:
        return "Акция"
    if "ставк" in g or "interest" in g or "rate" in g:
        return "Ставка"
    if "фонд" in g or "fund" in g:
        return "Фонд"

    if a in ASSET_BA_MAP:
        return ASSET_BA_MAP[a]

    return "Прочее"


def _classify_futures_type(delivery_type, group, asset_code):
    """Тип фьючерсов: Поставочный / Расчётный."""
    dt = str(delivery_type).lower() if delivery_type else ""

    if "deliver" in dt or "постав" in dt:
        return "Поставочный"
    if "cash" in dt or "расчет" in dt or "settle" in dt or "безнал" in dt:
        return "Расчётный"

    ba_type = _classify_ba_type(group, asset_code)
    if ba_type in ("Акция", "Товар", "Фонд"):
        return "Поставочный"
    return "Расчётный"


def render_screener(*, iss_df, go_df=None, ims_df=None, deposit=0.0, margin_type="КСУР", commission="Т-Инвестиции"):
    st.subheader("🔍 Скринер фьючерсов MOEX")

    t_conf = TARIFF_CONFIGS.get(commission, TARIFF_CONFIGS["Т-Инвестиции"])

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

    long_list, short_list = [], []
    for t in df["SECID"]:
        l, s = _margin_from_ims(t)
        if l <= 0 or s <= 0:
            l2, s2 = _margin_fallback(t)
            l = l if l > 0 else l2
            s = s if s > 0 else s2
        long_list.append(l)
        short_list.append(s)

    df["MarginLong"]  = long_list
    df["MarginShort"] = short_list
    df["MarginUsed"]  = df[["MarginLong", "MarginShort"]].min(axis=1)

    def _max_contracts(m, dep):
        try:
            m = float(m); dep = float(dep)
            if m <= 0 or dep <= 0:
                return 0
            return int(dep // m)
        except Exception:
            return 0

    df["MaxContracts"] = df["MarginUsed"].apply(lambda m: _max_contracts(m, deposit))

    # ============ КЛАССИФИКАЦИЯ ============
    df["BAType"] = df.apply(lambda r: _classify_ba_type(r.get("GROUP", ""), r.get("ASSETCODE", "")), axis=1)
    df["FuturesType"] = df.apply(lambda r: _classify_futures_type(r.get("DELIVERYTYPE", ""), r.get("GROUP", ""), r.get("ASSETCODE", "")), axis=1)

    # ============ Инфо-строка ============
    ims_source_ok = ims_has_buy and ims_has_sell
    sample_ticker = df.iloc[0]["SECID"] if len(df) else "—"
    sample_row = ims_df[ims_df["SECID"] == sample_ticker] if (ims_df is not None and not ims_df.empty and "SECID" in ims_df.columns) else pd.DataFrame()
    sample_text = ""
    if not sample_row.empty and ims_source_ok:
        try:
            sample_text = (
                f" · пример {sample_ticker}: "
                f"{_fmt_money(sample_row.iloc[0][buy_col])} / {_fmt_money(sample_row.iloc[0][sell_col])}"
            )
        except Exception:
            sample_text = ""

    if ims_source_ok:
        st.caption(
            f"Тариф: **{commission}** · Тип ГО: **{margin_type}** · Депозит: **{_fmt_money(deposit)}** · "
            f"Источник ГО: IMS (`{buy_col}` / `{sell_col}`){sample_text}"
        )
    else:
        st.caption(
            f"Тариф: **{commission}** · Тип ГО: **{margin_type}** · Депозит: **{_fmt_money(deposit)}** · "
            f"Источник ГО: Google Sheets / INITIALMARGIN"
        )

    # ============ ФИЛЬТРЫ (ряд 1: 3 колонки) ============
    f1, f2, f3 = st.columns([2, 2, 2])
    with f1:
        search = st.text_input("Поиск по тикеру / имени", "", key="scr_search")
    with f2:
        ba_types = sorted(df["BAType"].dropna().unique().tolist())
        ba_pick = st.multiselect(
            f"Тип БА ({len(ba_types)})",
            ba_types, default=[], key="scr_ba_type",
            help="Индекс / Акция / Валюта / Товар / Ставка / Фонд / Прочее. Можно выбрать несколько",
        )
    with f3:
        fut_types = sorted(df["FuturesType"].dropna().unique().tolist())
        fut_pick = st.multiselect(
            f"Тип фьючерсов ({len(fut_types)})",
            fut_types, default=[], key="scr_fut_type",
            help="Поставочный / Расчётный. Можно выбрать несколько",
        )

    # ============ ФИЛЬТРЫ (ряд 2: 3 колонки) ============
    f1, f2, f3 = st.columns([2, 2, 2])
    with f1:
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
    with f2:
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
    with f3:
        only_traded = st.checkbox("Только торгуемые", value=True, key="scr_traded")
        only_fitting = st.checkbox(
            "Только помещающиеся в депозит",
            value=False,
            key="scr_fit",
            help=f"Скрыть контракты, на которые не хватает депозита ({_fmt_money(deposit)}) при выбранном типе ГО ({margin_type}).",
        )
        only_nearest = st.checkbox(
            "Только ближайшие контракты",
            value=True,
            key="scr_nearest",
            help="Оставить по одному контракту на каждый базовый актив — с минимальной датой экспирации.",
        )

    # ============ ПРИМЕНЕНИЕ ФИЛЬТРОВ ============
    view = df.copy()
    if search:
        s = search.strip().upper()
        view = view[view["SECID"].str.upper().str.contains(s, na=False) | view["SHORTNAME"].str.upper().str.contains(s, na=False)]
    if ba_pick:
        view = view[view["BAType"].isin(ba_pick)]
    if fut_pick:
        view = view[view["FuturesType"].isin(fut_pick)]
    if asset_pick:
        view = view[view["ASSETCODE"].isin(asset_pick)]
    if exp_pick:
        view = view[view["LASTTRADEDATE"].isin(exp_pick)]
    if only_traded:
        view = view[view["VALTODAY"].fillna(0) > 0]

    if only_nearest and not view.empty:
        mask_valid = view["ASSETCODE"].fillna("").astype(str) != ""
        if mask_valid.any():
            sub = view.loc[mask_valid].copy()
            sub["_MIN_EXP"] = sub.groupby("ASSETCODE")["LASTTRADEDATE"].transform("min")
            nearest = sub[sub["LASTTRADEDATE"] == sub["_MIN_EXP"]].drop(columns=["_MIN_EXP"])
            others = view.loc[~mask_valid]
            view = pd.concat([nearest, others], ignore_index=False)

    if only_fitting:
        view = view[view["MaxContracts"] >= 1]

    total_before = len(df)
    total_after = len(view)

    filter_desc = []
    if search:
        filter_desc.append(f"поиск «{search}»")
    if ba_pick:
        filter_desc.append(f"тип БА: {', '.join(ba_pick)}")
    if fut_pick:
        filter_desc.append(f"тип фьючерсов: {', '.join(fut_pick)}")
    if asset_pick:
        filter_desc.append(f"активы: {len(asset_pick)}")
    if exp_pick:
        filter_desc.append(f"экспираций: {len(exp_pick)}")
    if only_nearest:
        filter_desc.append("только ближайшие контракты")
    filter_text = " · ".join(filter_desc) if filter_desc else "без дополнительных фильтров"

    st.caption(f"**Показано {total_after} из {total_before}** · {filter_text}")

    if view.empty:
        st.warning("По заданным фильтрам инструментов не найдено.")
        return

    # ============ ФРОНТ-МЕСЯЦЫ ============
    main_tickers = view.sort_values("VALTODAY", ascending=False).drop_duplicates("ASSETCODE")["SECID"].tolist()

    # ============ ВЫВОД ============
    out = view.rename(columns={
        "SECID": "Тикер", "SHORTNAME": "Краткое наименование", "LAST": "Текущая цена",
        "BAType": "Тип БА", "FuturesType": "Тип фьючерсов",
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
        "Тикер", "Краткое наименование", "Тип БА", "Тип фьючерсов",
        "Текущая цена", "Стоимость контракта",
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
        # ---- ДЕНЬГИ ----
        "Стоимость контракта": _fmt_money,
        "ГО (ISS sec)":        _fmt_money,
        "ГО LONG":             _fmt_money,
        "ГО SHORT":            _fmt_money,
        "ГО (min)":            _fmt_money,
        "Стоимость шага цены": _fmt_money,
        "Комиссия на 1 сделку":      _fmt_money,
        "Комиссия на адресную сделку": _fmt_money,
        "Клиринговая комиссия":      _fmt_money,
        # ---- ЦЕНЫ ----
        "Текущая цена":   _fmt_price,
        "Верхний лимит":  _fmt_price,
        "Нижний лимит":   _fmt_price,
        "Расчетная цена": _fmt_price,
        "Предыдущая цена": _fmt_price,
        # ---- ЦЕЛЫЕ ----
        "Макс. контрактов":  _fmt_int,
        "Доступных лотов":   _fmt_int,
        "Открытых позиций":  _fmt_int,
        "Лот":               _fmt_int,
        # ---- ШАГ ----
        "Шаг цены": _fmt_step,
    }, na_rep="—")

    st.dataframe(
        styled, use_container_width=True, hide_index=True, height=800,
        column_config={
            "Тикер": st.column_config.TextColumn(width="small"),
            "Краткое наименование": st.column_config.TextColumn(width="medium"),
            "Тип БА": st.column_config.TextColumn(width="small"),
            "Тип фьючерсов": st.column_config.TextColumn(width="small"),
            "Дата": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm"),
            "ГО LONG": st.column_config.NumberColumn(help=f"ГО на покупку по уровню {margin_type}"),
            "ГО SHORT": st.column_config.NumberColumn(help=f"ГО на продажу по уровню {margin_type}"),
            "ГО (min)": st.column_config.NumberColumn(help="min(ГО LONG, ГО SHORT) — используется для расчёта"),
            "Макс. контрактов": st.column_config.NumberColumn(help="Депозит / ГО (min)"),
        },
    )

    st.caption(
        "🟢 — самый торгуемый контракт по ASSETCODE (по VALTODAY)  ·  "
        "🔴 — ГО превышает депозит (не хватает на 1 контракт)"
    )

    # ============ МЕТРИКИ ============
    fit_count = int((view["MaxContracts"] >= 1).sum())
    unique_assets = view["ASSETCODE"].nunique()
    unique_exps = view["LASTTRADEDATE"].nunique()
    max_valtoday = view["VALTODAY"].max() if not view.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Показано", f"{total_after} из {total_before}")
    c2.metric("Помещается на депозит", f"{fit_count} / {total_after}")
    c3.metric("Уникальных активов", unique_assets)
    c4.metric("Экспираций", unique_exps)

    st.caption(f"Максимальный VALTODAY: {_fmt_money(max_valtoday)} · Обновлено: {datetime.now().strftime('%H:%M:%S')}")
