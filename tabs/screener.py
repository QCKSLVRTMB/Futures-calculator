import streamlit as st
import pandas as pd
import requests
from datetime import datetime

MOEX_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities.json?iss.meta=off&iss.only=securities,marketdata"

TARIFFS = {
    "Финам СТАНДАРТНЫЙ ФОРТС": {"type": "fixed", "broker_fee": 0.45, "clearing_fee": 4.65, "min_fee": 0.01},
    "Т-Инвестиции ИНВЕСТОР": {"type": "percent", "broker_percent": 0.001, "clearing_fee": 0.0, "min_fee": 0.01},
    "Без комиссии брокера (только биржа)": {"type": "fixed", "broker_fee": 0.0, "clearing_fee": 0.0, "min_fee": 0.0}
}

@st.cache_data(ttl=30, show_spinner="Загрузка данных MOEX ISS…")
def fetch_moex_forts() -> pd.DataFrame:
    try:
        r = requests.get(MOEX_URL, timeout=15)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        st.error(f"Ошибка MOEX ISS: {e}")
        return pd.DataFrame()

    sec = pd.DataFrame(js["securities"]["data"], columns=js["securities"]["columns"])
    mkt = pd.DataFrame(js["marketdata"]["data"], columns=js["marketdata"]["columns"])

    sec = sec[["SECID", "SHORTNAME", "ASSETCODE", "LOTSIZE", "MINSTEP", "STEPPRICE", "LASTTRADEDATE", "INITIALMARGIN", "PREVPRICE", "PREVSETTLEPRICE", "BUYSELLFEE"]]
    mkt = mkt[["SECID", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW", "UPDATETIME"]]

    df = sec.merge(mkt, on="SECID", how="left")
    
    for col in ["BUYSELLFEE", "LAST", "VALTODAY", "OPENPOSITION", "HIGH", "LOW", "INITIALMARGIN", "STEPPRICE", "MINSTEP", "PREVPRICE", "PREVSETTLEPRICE"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    price_for_notional = df["LAST"].where(df["LAST"] > 0, df["PREVSETTLEPRICE"])
    multiplier = df["STEPPRICE"] / df["MINSTEP"].replace(0, 1)
    df["Notional"] = price_for_notional * multiplier
    df["Updated"] = pd.to_datetime(df["UPDATETIME"], errors="coerce")
    return df

def highlight_main(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    main_secids = df.sort_values("VALTODAY", ascending=False).drop_duplicates("ASSETCODE")["SECID"].tolist()
    def _row_style(row):
        if row["SECID"] in main_secids:
            return ["background-color: #198754; color: white; font-weight: bold"] * len(row)
        return [""] * len(row)
    return df.style.apply(_row_style, axis=1)

def render_screener():
    st.subheader("🔍 Скринер фьючерсов MOEX")
    t1, t2 = st.columns([2, 3])
    with t1:
        selected_tariff = st.selectbox("Тариф брокера", list(TARIFFS.keys()), index=0, key="scr_tariff")
    with t2:
        st.write("") 
        st.caption("Комиссии рассчитываются для покупки и продажи через торговые программы.")
    
    t_conf = TARIFFS[selected_tariff]
    df = fetch_moex_forts()
    if df.empty:
        st.info("Нет данных MOEX ISS.")
        return

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

    view = df.copy()
    if search:
        s = search.strip().upper()
        view = view[view["SECID"].str.upper().str.contains(s, na=False) | view["SHORTNAME"].str.upper().str.contains(s, na=False)]
    if asset_pick: view = view[view["ASSETCODE"].isin(asset_pick)]
    if exp_pick: view = view[view["LASTTRADEDATE"].isin(exp_pick)]
    if only_traded: view = view[view["VALTODAY"].fillna(0) > 0]

    out = view.rename(columns={
        "SECID": "Тикер", "SHORTNAME": "Краткое наименование", "LAST": "Текущая цена", "Notional": "Стоимость контракта", "LOTSIZE": "Доступных лотов", "MINSTEP": "Шаг цены", "LASTTRADEDATE": "Дата экспирации", "ASSETCODE": "Код актива", "OPENPOSITION": "Открытых позиций", "LOTSIZE": "Лот", "INITIALMARGIN": "Гарантийное обеспечение", "HIGH": "Верхний лимит", "LOW": "Нижний лимит", "STEPPRICE": "Стоимость шага цены", "PREVSETTLEPRICE": "Расчетная цена", "PREVPRICE": "Предыдущая цена", "Updated": "Дата", "Commission_1": "Комиссия на 1 сделку", "Commission_addr": "Комиссия на адресную сделку", "Commission_clear": "Клиринговая комиссия"
    })[["Тикер", "Краткое наименование", "Текущая цена", "Стоимость контракта", "Доступных лотов", "Шаг цены", "Дата экспирации", "Код актива", "Открытых позиций", "Лот", "Гарантийное обеспечение", "Верхний лимит", "Нижний лимит", "Стоимость шага цены", "Расчетная цена", "Предыдущая цена", "Дата", "Комиссия на 1 сделку", "Комиссия на адресную сделку", "Клиринговая комиссия"]]

    styled = highlight_main(view).format({
        "LAST": "{:,.2f}", "Notional": "{:,.0f} ₽", "INITIALMARGIN": "{:,.0f} ₽", "STEPPRICE": "{:,.2f}", "PREVPRICE": "{:,.2f}", "PREVSETTLEPRICE": "{:,.2f}", "HIGH": "{:,.2f}", "LOW": "{:,.2f}", "VALTODAY": "{:,.0f}", "OPENPOSITION": "{:,.0f}", "Commission_1": "{:,.2f} ₽", "Commission_addr": "{:,.2f} ₽", "Commission_clear": "{:,.2f} ₽"
    }, na_rep="—")

    st.dataframe(styled, use_container_width=True, hide_index=True, height=800, column_config={"Тикер": st.column_config.TextColumn(width="small"), "Краткое наименование": st.column_config.TextColumn(width="medium"), "Дата": st.column_config.DatetimeColumn(format="DD.MM.YYYY HH:mm")})

    c1, c2, c3 = st.columns(3)
    c1.metric("Инструментов", len(view))
    c2.metric("Максимальный VALTODAY", f"{view['VALTODAY'].max():,.0f} ₽" if not view.empty else "—")
    c3.metric("Обновлено", datetime.now().strftime("%H:%M:%S"))
