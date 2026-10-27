from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import datetime
from core.config import IMS_MARGIN_MAP, TARIFF_CONFIGS
from ui.theme import format_date

LIQUIDITY_ORDER = ["Высокая", "Средняя", "Низкая", "Очень низкая", "Нет открытых позиций"]

def _fmt_money(v):
    try: return f"{float(v):.2f}".replace(".", ",") + " ₽"
    except Exception: return str(v)

def _fmt_int(v):
    try: return f"{int(round(float(v)))}"
    except Exception: return str(v)

def _liquidity_rating(oi):
    try: v = float(oi)
    except: return "Нет открытых позиций"
    if v >= 500_000: return "Высокая"
    if v >= 100_000: return "Средняя"
    if v >= 10_000: return "Низкая"
    if v > 0: return "Очень низкая"
    return "Нет открытых позиций"

def render_screener(*, iss_df, go_df=None, ims_df=None, deposit=0.0, margin_type="КСУР", commission="Т-Инвестиции", mobile=False):
    st.subheader("Скринер фьючерсов MOEX")
    t_conf = TARIFF_CONFIGS.get(commission, TARIFF_CONFIGS["Т-Инвестиции"])
    if iss_df.empty: return

    df = iss_df.copy()

    if t_conf["type"] == "fixed":
        df["Commission_1"] = t_conf["broker_fee"] + df["BUYSELLFEE"]
    elif t_conf["type"] == "percent":
        df["Commission_1"] = df["Notional"].apply(lambda x: max(x * t_conf["broker_percent"], t_conf["min_fee"])) + df["BUYSELLFEE"]

    buy_col, sell_col = IMS_MARGIN_MAP.get(margin_type, ("IM_BUY", "IM_SELL"))
    ims_has = ims_df is not None and not ims_df.empty and buy_col in ims_df.columns

    def _margin(t):
        if ims_has:
            r = ims_df[ims_df["SECID"] == t]
            if not r.empty:
                try: return float(r.iloc[0].get(buy_col, 0) or 0), float(r.iloc[0].get(sell_col, 0) or 0)
                except: pass
        return 0.0, 0.0

    long_list, short_list = [], []
    for t in df["SECID"]:
        l, s = _margin(t)
        long_list.append(l); short_list.append(s)
    df["MarginLong"], df["MarginShort"] = long_list, short_list
    df["MarginUsed"] = df[["MarginLong", "MarginShort"]].min(axis=1)
    df["MaxContracts"] = df["MarginUsed"].apply(lambda m: int(deposit // m) if m > 0 else 0)
    df["Liquidity"] = df["OPENPOSITION"].apply(_liquidity_rating)
    df["BAType"] = df["ASSETCODE"].apply(lambda x: "Акция" if x.isalpha() else "Индекс")
    df["FuturesType"] = "Расчётный"

    st.caption(f"Тариф: **{commission}** · Тип ГО: **{margin_type}** · Депозит: **{_fmt_money(deposit)}**")

    f1, f2, f3 = st.columns(3)
    search = f1.text_input("Поиск", key="scr_search")
    assets = f2.multiselect("Актив", sorted(df["ASSETCODE"].dropna().unique()), key="scr_asset")
    liq_pick = f3.multiselect("Ликвидность", [l for l in LIQUIDITY_ORDER if l in df["Liquidity"].unique()], key="scr_liq")

    f4, f5, f6 = st.columns(3)
    only_traded = f4.checkbox("Только торгуемые", value=True, key="scr_traded")
    only_fit = f5.checkbox("Помещающиеся в депо", value=False, key="scr_fit")
    only_near = f6.checkbox("Только ближайшие", value=True, key="scr_near")

    view = df.copy()
    if search: view = view[view["SECID"].str.contains(search.upper())]
    if assets: view = view[view["ASSETCODE"].isin(assets)]
    if liq_pick: view = view[view["Liquidity"].isin(liq_pick)]
    if only_traded: view = view[view["VALTODAY"] > 0]
    if only_fit: view = view[view["MaxContracts"] >= 1]
    if only_near and not view.empty:
        view = view.sort_values("LASTTRADEDATE").drop_duplicates("ASSETCODE")

    if view.empty:
        st.warning("Не найдено.")
        return

    out = view[["SECID", "SHORTNAME", "LAST", "MarginLong", "MarginShort", "MaxContracts", "Liquidity", "LASTTRADEDATE", "Commission_1"]].rename(columns={
        "SECID": "Тикер", "SHORTNAME": "Имя", "LAST": "Цена", "MarginLong": "ГО LONG", "MarginShort": "ГО SHORT", "MaxContracts": "Макс.", "Liquidity": "Ликвидность", "LASTTRADEDATE": "Экспирация", "Commission_1": "Комиссия"
    })
    
    # Форматируем колонку с экспирацией
    out["Экспирация"] = out["Экспирация"].apply(format_date)

    st.dataframe(out, use_container_width=True, hide_index=True)
    st.caption(f"Показано: {len(view)} из {len(df)}")
