from __future__ import annotations
import pandas as pd
import streamlit as st

import rules
from core import charts, state
from core.calc import get_instrument, plan_trade
from core.config import DEFAULT_TOOLS, DIRECTIONS, TF_SPEC, TOOLS, TRADE_TYPES, TREND_VALUES
from core.market import fetch_moex_candles
from ui.theme import cards, fragment, money, num, seg

def render_trade_planner(*, ticker, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, deposit=75000.0, risk_pct=1.0, rr_ratio=3.0, commission="Т-Инвестиции", strategy="Зигзаг тенденции", mobile=False):
    inst = get_instrument(ticker, iss_df=iss_df, ims_df=ims_df, go_df=go_df, api_df=api_df, md_df=md_df, margin_type=state.g("margin_type"))
    tdata = state.ticker(ticker)
    _header(inst, tdata, mobile)
    _market_block(ticker, tdata, strategy, mobile)
    _chart_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission)
    _deal_block(ticker, inst, tdata, deposit, risk_pct, rr_ratio, commission, mobile)

def _header(inst, tdata, mobile):
    chg = inst.change_pct
    cards([
        (inst.name, num(inst.price), "ok" if chg >= 0 else "bad"),
        ("Изм. за день", f"{chg:+.2f}%".replace(".", ","), "ok" if chg >= 0 else "bad"),
        ("Шаг / ст. шага", f"{num(inst.min_step, 4)} / {num(inst.step_price)}", ""),
        ("1 пункт", money(inst.point_value), ""),
        ("ГО LONG / SHORT", f"{num(inst.margin_long, 0)} / {num(inst.margin_short, 0)}", ""),
        ("Экспирация", str(inst.expiry)[:10], ""),
    ])
    st.caption(f"Открытый интерес: {num(inst.open_interest, 0)} контр. · Стоимость контракта: {money(inst.notional)}")

@fragment
def _market_block(ticker, tdata, strategy, mobile):
    m = tdata["market"]
    with st.expander("📊 Состояние рынка и правило входа", expanded=not mobile):
        c = st.columns(1 if mobile else 4)
        with c[0]: m["trend"] = seg("Тренд", TREND_VALUES, key=f"m_tr_{ticker}", default=m["trend"]) or m["trend"]
        with c[1 % len(c)]: m["wave"] = seg("Волна", TREND_VALUES, key=f"m_wv_{ticker}", default=m["wave"]) or m["wave"]
        with c[2 % len(c)]: m["tendency"] = seg("Тенденция", TREND_VALUES, key=f"m_td_{ticker}", default=m["tendency"]) or m["tendency"]
        with c[3 % len(c)]: m["trade_type"] = seg("Тип сделки", TRADE_TYPES, key=f"m_tt_{ticker}", default=m.get("trade_type", "трендовая")) or "трендовая"

        found = None
        for d in DIRECTIONS:
            r = rules.lookup(m["trend"], m["wave"], m["tendency"], m["trade_type"], d)
            if r:
                found = r; break
        if found:
            tdata["deal"]["direction"] = found["direction"]
            if found["is_forbidden"]: st.error(f"🚫 {found['direction']} — не торгуется: {found['description']}")
            else: st.success(f"✅ Рекомендация: **{found['direction']}** · {found['description']}")
        else: st.info("Для данной комбинации правило не найдено.")
        st.caption(f"Стратегия: {strategy}")
    state.autosave()

@fragment
def _chart_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission):
    st.markdown("#### 📈 Разметка графика")
    c1, c2 = st.columns([1, 1])
    with c1: tf = seg("Таймфрейм", list(TF_SPEC), key=f"tf_{ticker}", default="H1", fmt=lambda x: TF_SPEC[x]["label"]) or "H1"
    with c2: tool = seg("Инструмент", list(TOOLS), key=f"tool_{ticker}_{tf}", default=DEFAULT_TOOLS.get(tf, "zigzag"), fmt=lambda x: TOOLS[x]) or "zigzag"

    spec = TF_SPEC[tf]
    with st.spinner("Загрузка свечей…"):
        df = fetch_moex_candles(ticker, spec["interval"], spec["days"])
    if df.empty:
        st.warning("MOEX не отдал свечи по этому инструменту.")
        return

    bars = st.slider("Свечей на экране", 40, min(len(df), 600), min(spec["bars"], len(df)), step=20, key=f"bars_{ticker}_{tf}")
    view = df.tail(bars)

    chart_key = f"chart_{ticker}_{tf}"
    click = charts.capture_click(chart_key)
    if click:
        x, y = click
        y = inst.round_price(y)
        if tool == "levels":
            lv = tdata["charts"][tf]["levels"]
            if not any(abs(v - y) < inst.min_step for v in lv):
                lv.append(y)
                tdata["charts"][tf]["levels"] = sorted(lv)
        else:
            tdata["charts"][tf][tool].append([x, y])
        st.session_state[f"last_click_{ticker}"] = y
        state.autosave(force=True)

    fig = charts.build_figure(view, tf=tf, mobile=mobile, title=f"{ticker} · {spec['label']}")
    x_left, x_right = view.index[0], view.index[-1]
    tools_data = tdata["charts"][tf]
    charts.draw_levels(fig, tools_data["levels"], x_left, x_right)
    charts.draw_channel(fig, tools_data["channel"], x_right)
    charts.draw_fib(fig, tools_data["fib"], x_left, x_right)
    charts.draw_zigzag(fig, tools_data["zigzag"])

    deal = tdata["deal"]
    if deal.get("sl") or deal.get("entries"):
        plan = plan_trade(inst, direction=deal["direction"], entries=deal["entries"], sl=deal.get("sl"), tp=deal.get("tp"), deposit=deposit, risk_pct=risk_pct, rr_ratio=rr_ratio, tariff=commission, max_margin_util=state.g("max_margin_util", 50.0))
        charts.draw_deal(fig, plan, x_left, x_right)

    st.plotly_chart(fig, use_container_width=True, key=chart_key, on_select="rerun", selection_mode="points", config=charts.PLOT_CONFIG)
    st.caption("Тап по свече = точка (привязка к ближайшему High/Low/Close). Двойной тап — сброс масштаба.")

    b1, b2, b3, b4 = st.columns(4)
    cur = tools_data[tool]
    if b1.button("↩︎ Отменить", key=f"undo_{ticker}_{tf}_{tool}", use_container_width=True, disabled=not cur):
        cur.pop(); state.autosave(force=True); st.rerun(scope="fragment")
    if b2.button("🗑 Очистить", key=f"clr_{ticker}_{tf}_{tool}", use_container_width=True, disabled=not cur):
        tools_data[tool] = []; state.autosave(force=True); st.rerun(scope="fragment")
    if b3.button("⚡ Авто-зигзаг", key=f"auto_{ticker}_{tf}", use_container_width=True):
        tools_data["zigzag"] = charts.auto_zigzag(view, depth_pct=1.0 if tf == "M10" else 2.0)
        state.autosave(force=True); st.rerun(scope="fragment")
    with b4.popover("＋ Точка вручную", use_container_width=True):
        p = st.number_input("Цена", value=float(inst.price or 0), step=float(inst.min_step or 0.01), format="%.6f", key=f"mp_{ticker}_{tf}_{tool}")
        if st.button("Добавить", key=f"mpb_{ticker}_{tf}_{tool}", use_container_width=True):
            if tool == "levels": tools_data["levels"] = sorted(set(tools_data["levels"] + [float(p)]))
            else: tools_data[tool].append([str(view.index[-1]), float(p)])
            state.autosave(force=True); st.rerun(scope="fragment")

    if cur:
        with st.expander(f"Точки «{TOOLS[tool]}» ({len(cur)})", expanded=False):
            if tool == "levels":
                ed = st.data_editor(pd.DataFrame({"Цена": cur}), num_rows="dynamic", use_container_width=True, hide_index=True, key=f"ed_lv_{ticker}_{tf}")
                tools_data["levels"] = sorted({float(v) for v in ed["Цена"].dropna().tolist()})
            else:
                ed = st.data_editor(pd.DataFrame(cur, columns=["Время", "Цена"]), num_rows="dynamic", use_container_width=True, hide_index=True, key=f"ed_pt_{ticker}_{tf}_{tool}")
                tools_data[tool] = [[str(t), float(p)] for t, p in ed.dropna().itertuples(index=False)]
            state.autosave()

@fragment
def _deal_block(ticker, inst, tdata, deposit, risk_pct, rr_ratio, commission, mobile):
    st.markdown("#### 🎯 Параметры сделки")
    deal = tdata["deal"]
    last_click = st.session_state.get(f"last_click_{ticker}")

    c = st.columns(1 if mobile else 3)
    with c[0]: deal["direction"] = seg("Направление", DIRECTIONS, key=f"dir_{ticker}", default=deal.get("direction", "LONG")) or "LONG"
    with c[1 % len(c)]:
        deal["sl"] = st.number_input("Стоп-лосс", value=float(deal.get("sl") or 0.0), step=float(inst.min_step or 0.01), format="%.6f", key=f"sl_{ticker}") or None
        if last_click and st.button("⤵︎ SL = последний клик", key=f"slc_{ticker}", use_container_width=True):
            deal["sl"] = float(last_click); st.session_state[f"sl_{ticker}"] = float(last_click); state.autosave(force=True); st.rerun(scope="fragment")
    with c[2 % len(c)]:
        deal["tp"] = st.number_input("Тейк-профит (0 = авто по R:R)", value=float(deal.get("tp") or 0.0), step=float(inst.min_step or 0.01), format="%.6f", key=f"tp_{ticker}") or None

    entries_df = pd.DataFrame(deal["entries"] or [{"price": inst.price, "qty": 0, "note": ""}])
    ed = st.data_editor(entries_df.rename(columns={"price": "Цена", "qty": "Кол-во", "note": "Комментарий"}), num_rows="dynamic", use_container_width=True, hide_index=True, column_config={"Цена": st.column_config.NumberColumn(format="%.6f", step=inst.min_step), "Кол-во": st.column_config.NumberColumn(format="%d", min_value=0, step=1)}, key=f"entries_{ticker}")
    deal["entries"] = [{"price": float(r["Цена"] or 0), "qty": int(r["Кол-во"] or 0), "note": str(r["Комментарий"] or "")} for _, r in ed.iterrows() if pd.notna(r["Цена"])]

    plan = plan_trade(inst, direction=deal["direction"], entries=deal["entries"], sl=deal.get("sl"), tp=deal.get("tp"), deposit=deposit, risk_pct=risk_pct, rr_ratio=rr_ratio, tariff=commission, max_margin_util=state.g("max_margin_util", 50.0))

    rr_ok = "ok" if plan["rr"] >= rr_ratio else ("warn" if plan["rr"] >= 1 else "bad")
    cards([
        ("Средний вход", num(plan["entry"]), ""), ("Рекоменд. объём", f'{plan["qty_recommended"]} контр.', "ok"),
        ("Фактический объём", f'{plan["qty"]} контр.', ""), ("Риск", money(plan["risk_rub"]), "bad"),
        ("Риск, % депо", num(plan["risk_pct_fact"]) + " %", "bad" if plan["risk_pct_fact"] > risk_pct else "ok"),
        ("Потенциал", money(plan["reward_rub"]), "ok"), ("R:R", f'1 : {num(plan["rr"])}', rr_ok),
        ("ГО под позицию", money(plan["margin_total"]), ""), ("ГО, % депо", num(plan["margin_pct"]) + " %", "warn" if plan["margin_pct"] > state.g("max_margin_util", 50) else ""),
        ("Безубыток", num(plan["breakeven"]), ""), ("Комиссия (round-trip)", money(plan["fee_per_contract"] * max(plan["qty"], 1)), ""), ("Тейк (расч.)", num(plan["tp"] or 0), ""),
    ])
    for w in plan["warnings"]: st.warning(w, icon="⚠️")

    deal_note = st.text_area("Заметка по сделке", value=tdata.get("note", ""), key=f"note_{ticker}", height=70)
    tdata["note"] = deal_note
    state.autosave()
