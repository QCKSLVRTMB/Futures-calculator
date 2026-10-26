from __future__ import annotations
import pandas as pd
import streamlit as st
import time

import rules
from core import charts, state
from core.calc import get_instrument, plan_trade, analyze_manual_zigzag, find_volume_clusters
from core.config import DIRECTIONS, INTERVALS, TOOLS
from core.market import fetch_moex_candles
from ui.theme import cards, fragment, money, num, seg

def render_trade_planner(*, ticker, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, deposit=75000.0, risk_pct=1.0, rr_ratio=3.0, commission="Т-Инвестиции", strategy="Зигзаг тенденции", mobile=False):
    inst = get_instrument(ticker, iss_df=iss_df, ims_df=ims_df, go_df=go_df, api_df=api_df, md_df=md_df, margin_type=state.g("margin_type"))
    tdata = state.ticker(ticker)
    _header(inst, tdata, mobile)
    _chart_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy)
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
def _chart_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy):
    st.markdown("#### 📈 Графики рынка")
    
    chart_tabs = st.tabs([cfg["label"] for cfg in INTERVALS.values()])
    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy)

def _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy):
    # Распределение инструментов по ТФ (как в вашем коде)
    if tf_name == "D1": available_tools = ["channel", "fib_d1"]
    elif tf_name == "H1": available_tools = ["zigzag", "fib_h1"]
    else: available_tools = ["zigzag"]  # На M10 только зигзаг
    
    c1, c2 = st.columns([1, 1])
    with c1: tool = seg("Инструмент", available_tools, key=f"tool_{ticker}_{tf_name}", default=available_tools[0], fmt=lambda x: TOOLS[x]) or available_tools[0]
    with c2:
        if mobile: 
            show_rr = st.toggle("Зоны RR", value=True, key=f"rr_{ticker}_{tf_name}")
            show_clusters = st.toggle("Кластеры", value=False, key=f"clu_{ticker}_{tf_name}") if tf_name == "H1" else False
        else:
            cc1, cc2 = st.columns(2)
            show_rr = cc1.toggle("Зоны RR", value=True, key=f"rr_{ticker}_{tf_name}")
            show_clusters = cc2.toggle("Кластеры", value=False, key=f"clu_{ticker}_{tf_name}") if tf_name == "H1" else False

    df = fetch_moex_candles(ticker, cfg["interval"], cfg["days_back"])
    if df.empty:
        st.warning("Нет данных MOEX.")
        return

    view = df.tail(150).copy()
    chart_key = f"chart_{ticker}_{tf_name}"
    click = charts.capture_click(chart_key)

    # Маппинг старых ключей стейта на новую структуру
    chart_data = tdata["charts"][tf_name]
    if tf_name == "D1": target_tool = "channel" if tool == "channel" else "fib"
    elif tf_name == "H1": target_tool = "zigzag" if tool == "zigzag" else "fib"
    else: target_tool = "zigzag"
    
    pts = chart_data[target_tool]

    if click:
        x, y = click
        y = inst.round_price(y)
        bar = view.iloc[view.index.get_indexer([pd.to_datetime(x)], method='nearest')[0]]
        
        new_pts = pts.copy()
        max_pts = 3 if tool == "channel" else (None if "zigzag" in tool else 2)
        
        if max_pts is None or len(new_pts) < max_pts:
            if "zigzag" in tool:
                if new_pts and pd.to_datetime(new_pts[-1][0]) == bar.name:
                    last_y = new_pts[-1][1]
                    new_pts[-1] = [str(bar.name), float(bar['Low']) if last_y == bar['High'] else float(bar['High'])]
                elif not new_pts:
                    current_price = view.iloc[-1]['Close']
                    snapped_y = float(bar['Low']) if (bar['High']+bar['Low'])/2 < current_price else float(bar['High'])
                    new_pts.append([str(bar.name), snapped_y])
                elif len(new_pts) == 1:
                    snapped_y = float(bar['High']) if y > new_pts[0][1] else float(bar['Low'])
                    new_pts.append([str(bar.name), snapped_y])
                else:
                    is_last_high = new_pts[-1][1] == view.loc[pd.to_datetime(new_pts[-1][0]), 'High']
                    snapped_y = float(bar['Low']) if is_last_high else float(bar['High'])
                    new_pts.append([str(bar.name), snapped_y])
                    
            elif tool == "channel":
                if len(new_pts) == 0:
                    # Клик 1: запоминаем координату клика, тип определится на клике 2
                    new_pts.append([str(bar.name), y])
                elif len(new_pts) == 1:
                    # Клик 2: определяем направление по взаимному расположению кликов
                    first_bar_name = pd.to_datetime(new_pts[0][0])
                    if y > new_pts[0][1]:
                        # Восходящий канал → обе точки LOW
                        new_pts[0] = [new_pts[0][0], float(view.loc[first_bar_name, 'Low'])]
                        new_pts.append([str(bar.name), float(bar['Low'])])
                    else:
                        # Нисходящий канал → обе точки HIGH
                        new_pts[0] = [new_pts[0][0], float(view.loc[first_bar_name, 'High'])]
                        new_pts.append([str(bar.name), float(bar['High'])])
                elif len(new_pts) == 2:
                    # Клик 3: противоположный экстремум
                    if new_pts[1][1] > new_pts[0][1]:
                        # Восходящий канал → точка 3 = HIGH
                        new_pts.append([str(bar.name), float(bar['High'])])
                    else:
                        # Нисходящий канал → точка 3 = LOW
                        new_pts.append([str(bar.name), float(bar['Low'])])
                        
            else:  # fib
                if len(new_pts) == 0: 
                    new_pts.append([str(bar.name), float(bar['High']) if abs(y-bar['High'])<abs(y-bar['Low']) else float(bar['Low'])])
                elif len(new_pts) == 1:
                    if y > new_pts[0][1]:
                        new_pts[0] = [new_pts[0][0], float(view.loc[pd.to_datetime(new_pts[0][0]), 'Low'])]
                        new_pts.append([str(bar.name), float(bar['High'])])
                    else:
                        new_pts[0] = [new_pts[0][0], float(view.loc[pd.to_datetime(new_pts[0][0]), 'High'])]
                        new_pts.append([str(bar.name), float(bar['Low'])])
            
            if new_pts != pts:
                chart_data[target_tool] = new_pts
                state.autosave(force=True)

    fig = charts.build_figure(view, tf_name=tf_name, title=f"{ticker} — {tf_name}", decimals=inst.decimals, mobile=mobile)
    x_left, x_right = view.index[0], view.index[-1]

    # Отрисовка (используем все сохраненные данные, независимо от выбранного инструмента)
    d1_pts = tdata["charts"]["D1"]["channel"]
    d1_fib = tdata["charts"]["D1"]["fib"]
    h1_zig = tdata["charts"]["H1"]["zigzag"]
    h1_fib = tdata["charts"]["H1"]["fib"]
    m10_zig = tdata["charts"]["M10"]["zigzag"]

    if show_clusters and tf_name == "H1":
        clusters = find_volume_clusters(view)
        charts.draw_clusters(fig, clusters, x_left, x_right)
        st.caption(f"Аномальных баров H1: {len(clusters)}")

    if d1_pts: charts.draw_channel(fig, d1_pts, x_right)
    if d1_fib: charts.draw_fib(fig, d1_fib, x_left, x_right, "blue", "0.5 D1")
    if h1_fib: charts.draw_fib(fig, h1_fib, x_left, x_right, "green", "0.5 H1")
    
    if h1_zig: charts.draw_zigzag(fig, h1_zig, "#26a69a", "Тенденция (H1)")
    if m10_zig and (tf_name in ["H1", "M10"]): charts.draw_zigzag(fig, m10_zig, "#ef5350", "Зигзаг (M10)")

    if h1_zig and tf_name == "H1":
        if show_rr: charts.draw_rr_zones(fig, h1_zig, strategy)
        breakouts = analyze_manual_zigzag(h1_zig, view)
        charts.draw_breakouts(fig, breakouts, inst.decimals)
        if breakouts:
            st.markdown("##### Анализ пробоев и откатов H1")
            df_metrics = pd.DataFrame([{
                "Направление": "Вверх" if b["trend"] == "up" else "Вниз",
                "Δ Пробоя": b["delta"], "Бар/Vol": f"{b['bars']} / {b['volume']:,.0f}",
                "Ретр. %": f"{b.get('retracement_pct', 0):.1f}%" if b["pullback_time"] else "-",
            } for b in breakouts])
            st.dataframe(df_metrics, use_container_width=True, hide_index=True)

    st.plotly_chart(fig, use_container_width=True, key=chart_key, on_select="rerun", selection_mode="points", config=charts.PLOT_CONFIG)

    b1, b2, b3 = st.columns(3)
    if b1.button("↩︎ Отменить", key=f"undo_{ticker}_{tf_name}", use_container_width=True):
        if chart_data[target_tool]: chart_data[target_tool].pop(); state.autosave(force=True); st.rerun(scope="fragment")
    if b2.button("🗑 Очистить", key=f"clr_{ticker}_{tf_name}", use_container_width=True):
        chart_data[target_tool] = []; state.autosave(force=True); st.rerun(scope="fragment")

@fragment
def _deal_block(ticker, inst, tdata, deposit, risk_pct, rr_ratio, commission, mobile):
    st.markdown("#### 🎯 Параметры сделки")
    deal = tdata["deal"]
    h1_zig = tdata["charts"]["H1"]["zigzag"]
    
    p_a = h1_zig[-4][1] if len(h1_zig) >= 4 else None
    p_b = h1_zig[-3][1] if len(h1_zig) >= 4 else None
    p_c = h1_zig[-2][1] if len(h1_zig) >= 4 else None
    
    if not all([p_a, p_b, p_c]):
        st.info("Для расчёта сделки нужно минимум 4 точки зигзага на H1.")
        return

    c = st.columns(1 if mobile else 3)
    with c[0]: deal["direction"] = seg("Направление", DIRECTIONS, key=f"dir_{ticker}", default=deal.get("direction", "LONG")) or "LONG"
    with c[1 % len(c)]:
        deal["sl"] = st.number_input("Стоп-лосс", value=float(deal.get("sl") or 0.0), step=float(inst.min_step or 0.01), format="%.6f", key=f"sl_{ticker}") or None
    with c[2 % len(c)]:
        deal["tp"] = st.number_input("Тейк-профит", value=float(deal.get("tp") or 0.0), step=float(inst.min_step or 0.01), format="%.6f", key=f"tp_{ticker}") or None

    # Логика из вашего старого кода
    avg_entry = p_c
    sl_price = p_a if deal["direction"] == "LONG" else p_b
    sl_points = abs(avg_entry - sl_price)
    tp_price = avg_entry + (sl_points * rr_ratio) if deal["direction"] == "LONG" else avg_entry - (sl_points * rr_ratio)
    
    plan = plan_trade(inst, direction=deal["direction"], entries=[{"price": avg_entry, "qty": 1}], sl=sl_price, tp=tp_price, deposit=deposit, risk_pct=risk_pct, rr_ratio=rr_ratio, tariff=commission, max_margin_util=state.g("max_margin_util", 50.0))

    cards([
        ("Вход (C)", num(avg_entry), ""), ("SL (A/B)", num(sl_price), "bad"),
        ("TP", num(tp_price), "ok"), ("Рекоменд. объём", f'{plan["qty_recommended"]} контр.', ""),
        ("Риск", money(plan["risk_rub"]), "bad"), ("Потенциал", money(plan["reward_rub"]), "ok"),
        ("R:R", f'1 : {num(plan["rr"])}', "ok" if plan["rr"] >= rr_ratio else "warn"),
    ])
    state.autosave()
