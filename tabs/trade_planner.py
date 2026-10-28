from __future__ import annotations
import pandas as pd
import streamlit as st
import time

import rules
from core import charts, state
from core.calc import get_instrument, plan_trade, analyze_manual_zigzag, calculate_volume_profile
from core.config import DIRECTIONS, INTERVALS, TOOLS
from core.market import fetch_moex_candles
from ui.theme import kv_data, fragment, money, num, seg, format_date

def render_trade_planner(*, ticker, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, deposit=75000.0, risk_pct=1.0, rr_ratio=3.0, commission="Т-Инвестиции", strategy="Зигзаг тенденции", mobile=False):
    inst = get_instrument(ticker, iss_df=iss_df, ims_df=ims_df, go_df=go_df, api_df=api_df, md_df=md_df, margin_type=state.g("margin_type"))
    tdata = state.ticker(ticker)
    _header(inst, tdata, mobile)
    _trade_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy)

def _header(inst, tdata, mobile):
    chg = inst.change_pct
    items = [
        ("Название", inst.name, ""),
        ("Цена", num(inst.price), "ok" if chg >= 0 else "bad"),
        ("Изм. за день", f"{chg:+.2f}%".replace(".", ","), "ok" if chg >= 0 else "bad"),
        ("Шаг / ст. шага", f"{num(inst.min_step, 4)} / {num(inst.step_price)}", ""),
        ("1 пункт", money(inst.point_value), ""),
        ("ГО LONG / SHORT", f"{num(inst.margin_long, 0)} / {num(inst.margin_short, 0)}", ""),
        ("Экспирация", format_date(inst.expiry), ""),
        ("Открытый интерес", f"{num(inst.open_interest, 0)} контр.", ""),
        ("Стоимость контракта", money(inst.notional), ""),
    ]
    kv_data(items, mobile=mobile)

@fragment
def _trade_block(ticker, inst, tdata, mobile, deposit, risk_pct, rr_ratio, commission, strategy):
    deal = tdata["deal"]
    
    st.markdown("#### Параметры сделки")
    c = st.columns(1 if mobile else 3)
    with c[0]:
        deal["direction"] = seg("Направление", DIRECTIONS, key=f"dir_{ticker}", default=deal.get("direction", "LONG")) or "LONG"
    
    fmt = f"%.{inst.decimals}f"
    
    with c[1 % len(c)]:
        deal["sl"] = st.number_input("Стоп-лосс", value=float(deal.get("sl") or 0.0), step=float(inst.min_step or 0.01), format=fmt, key=f"sl_{ticker}") or None
    with c[2 % len(c)]:
        deal["tp"] = st.number_input("Тейк-профит (0 = авто)", value=float(deal.get("tp") or 0.0), step=float(inst.min_step or 0.01), format=fmt, key=f"tp_{ticker}") or None

    # === CSS СТИЛИ ДЛЯ ЦВЕТОВ ===
    st.markdown(
        f"""
        <style>
        /* SL - красный */
        .st-key-sl_{ticker} input {{
            color: #ef5350 !important;
            -webkit-text-fill-color: #ef5350 !important;
            font-weight: bold;
        }}
        /* TP - зеленый */
        .st-key-tp_{ticker} input {{
            color: #26a69a !important;
            -webkit-text-fill-color: #26a69a !important;
            font-weight: bold;
        }}
        /* ТВХ (таблица) - синий */
        .st-key-entries_{ticker} div[data-testid="stDataFrame"] {{
            border: 2px solid #1976D2 !important;
            border-radius: 0.5rem !important;
        }}
        .st-key-entries_{ticker} input {{
            color: #1976D2 !important;
            -webkit-text-fill-color: #1976D2 !important;
            font-weight: bold;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

    if "entries" not in deal or not deal["entries"]:
        deal["entries"] = [{"price": inst.price, "qty": 0}]
    
    entries_df = pd.DataFrame(deal["entries"])
    ed = st.data_editor(
        entries_df, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "price": st.column_config.NumberColumn("Цена входа", format=fmt, step=inst.min_step),
            "qty": st.column_config.NumberColumn("Кол-во (0 = авто)", min_value=0, step=1)
        },
        key=f"entries_{ticker}"
    )
    deal["entries"] = [{"price": float(r["price"]), "qty": int(r["qty"])} for _, r in ed.iterrows() if pd.notna(r["price"])]

    plan = plan_trade(inst, direction=deal["direction"], entries=deal["entries"], sl=deal.get("sl"), tp=deal.get("tp"), deposit=deposit, risk_pct=risk_pct, rr_ratio=rr_ratio, tariff=commission, max_margin_util=state.g("max_margin_util", 50.0))

    st.markdown("#### Графики рынка")
    
    # === ГЛОБАЛЬНЫЕ НАСТРОЙКИ КЛАСТЕРОВ ===
    show_clusters = st.toggle("Кластеры объемов (M10)", value=False, key=f"clu_{ticker}", help="Анализ объемов M10 от 2-й точки канала D1 до текущего бара. Отображается на всех таймфреймах.")
    clusters_data = []
    cluster_start_time = None
    
    if show_clusters:
        c1, c2 = st.columns([1, 2])
        with c1:
            overlap_pct = st.slider("Порог отсечения", min_value=10, max_value=100, value=50, step=5, key=f"clu_bins_{ticker}", help="10 = показать все зоны, 100 = только максимальный объём (POC)")
        with c2:
            d1_pts = tdata["charts"]["D1"]["channel"]
            if len(d1_pts) == 3:
                cluster_start_time = pd.to_datetime(d1_pts[2][0])
                st.caption(f"Анализ M10 от {cluster_start_time.strftime('%d.%m.%Y %H:%M')}")
            else:
                st.caption("Для кластеров нужен канал на D1 (3 точки)")

        if cluster_start_time:
            df_m10 = fetch_moex_candles(ticker, interval=10, days_back=60)
            if not df_m10.empty:
                df_m10_filtered = df_m10.loc[cluster_start_time:]
                clusters_data = calculate_volume_profile(df_m10_filtered, tf_name="M10", threshold_pct=overlap_pct)
            else:
                st.caption("Нет данных M10 для анализа")
    # =====================================

    chart_tabs = st.tabs([cfg["label"] for cfg in INTERVALS.values()])
    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, plan, strategy, clusters_data, cluster_start_time)

    if plan:
        st.markdown("#### Результаты расчета")

        sl_wrong = plan["sl"] > 0 and (
            (deal["direction"] == "LONG" and plan["sl"] >= plan["entry"]) or
            (deal["direction"] == "SHORT" and plan["sl"] <= plan["entry"])
        )
        tp_wrong = plan["tp"] is not None and plan["tp"] > 0 and (
            (deal["direction"] == "LONG" and plan["tp"] <= plan["entry"]) or
            (deal["direction"] == "SHORT" and plan["tp"] >= plan["entry"])
        )
        risk_fail = plan["risk_rub"] > plan["risk_budget"]
        profit_fail = plan["reward_rub"] <= 0
        rr_fail = plan["rr"] < rr_ratio
        qty_fail = (
            plan["qty"] == 0 or
            (plan["qty_by_risk"] > 0 and plan["qty"] > plan["qty_by_risk"]) or
            (plan["qty_by_margin"] > 0 and plan["qty"] > plan["qty_by_margin"])
        )

        items = [
            ("Максимально допустимый риск (руб.)", money(plan["risk_budget"]), ""),
            ("ТВХ", num(plan["entry"]), ""),
            ("Стоп-лосс (SL)", num(plan["sl"]), "fail" if sl_wrong else ""),
            
            # Новые параметры по расчету
            ("Минимальный TP (с учетом комиссий)", num(plan["min_tp"]), "ok" if not tp_wrong else ""),
            ("Целевая прибыль (RR x Риск)", money(plan["target_profit_rub"]), "ok"),
            
            ("Тейк-профит (TP)", num(plan["tp"]) if plan["tp"] else "—", "fail" if tp_wrong else ""),
            ("Доступно контрактов", f'{plan["qty_recommended"]} шт.', "fail" if qty_fail else ""),
            ("Риск в сделке", money(plan["risk_rub"]), "fail" if risk_fail else "ok"),
            ("Прибыль в сделке", money(plan["reward_rub"]), "fail" if profit_fail else "ok"),
            ("R:R факт", f'1 : {num(plan["rr"])}', "fail" if rr_fail else "ok"),
            ("ГО", money(plan["margin_total"]), ""),
            ("Комиссия", money(plan["fee_per_contract"] * plan["qty"]), ""),
            ("Безубыток", num(plan["breakeven"]), ""),
        ]
        kv_data(items, mobile=mobile)

        st.caption(f"Стоимость позиции: {money(plan['notional'])} · Плечо: {num(plan['leverage'], 1)}x")
        for w in plan["warnings"]: st.warning(w)
            
    state.autosave()

def snap_points(pts, df):
    if not pts or df.empty: return pts
    snapped = []
    for p_str, p_val in pts:
        try:
            t = pd.to_datetime(p_str)
        except Exception:
            snapped.append([p_str, p_val])
            continue
        
        tol = 1e-4 * max(abs(p_val), 1.0)
        mask_high = (df['High'] - p_val).abs() <= tol
        mask_low = (df['Low'] - p_val).abs() <= tol
        matching_indices = df.index[mask_high | mask_low]
        
        if len(matching_indices) > 0:
            idx = matching_indices.get_indexer([t], method='nearest')[0]
            snapped.append([str(matching_indices[idx]), p_val])
        else:
            idx = df.index.get_indexer([t], method='nearest')[0]
            if idx >= 0:
                bar = df.iloc[idx]
                is_high = abs(p_val - bar['High']) <= abs(p_val - bar['Low'])
                start = max(0, idx - 1000)
                end = min(len(df) - 1, idx + 1000)
                sub_df = df.iloc[start:end+1]
                if is_high: exact_idx = (sub_df['High'] - p_val).abs().idxmin()
                else: exact_idx = (sub_df['Low'] - p_val).abs().idxmin()
                snapped.append([str(exact_idx), p_val])
            else:
                snapped.append([p_str, p_val])
    return snapped

def _render_tf_chart(ticker, tf_name, cfg, inst, tdata, mobile, plan, strategy, clusters_data=None, cluster_start_time=None):
    if tf_name == "D1": available_tools = ["channel", "fib_d1"]
    elif tf_name == "H1": available_tools = ["zigzag", "fib_h1"]
    else: available_tools = ["zigzag"]

    c1, c2 = st.columns([1, 1])
    with c1:
        tool = seg("Инструмент", available_tools, key=f"tool_{ticker}_{tf_name}", default=available_tools[0], fmt=lambda x: TOOLS[x]) or available_tools[0]
    with c2:
        # 2 колонки, по 2 элемента в каждой
        cc1, cc2 = st.columns(2)
        show_tools = cc1.toggle("Разметка", value=True, key=f"tools_{ticker}_{tf_name}")
        show_position = cc1.toggle("Позиция", value=True, key=f"pos_{ticker}_{tf_name}")
        show_rr = cc2.toggle("Зоны RR", value=True, key=f"rr_{ticker}_{tf_name}")
        show_info = cc2.toggle("Информация", value=True, key=f"info_{ticker}_{tf_name}")

    chart_data = tdata["charts"][tf_name]
    if tf_name == "D1": target_tool = "channel" if tool == "channel" else "fib"
    elif tf_name == "H1": target_tool = "zigzag" if tool == "zigzag" else "fib"
    else: target_tool = "zigzag"

    b1, b2 = st.columns(2)
    if b1.button("Отменить", key=f"undo_{ticker}_{tf_name}", use_container_width=True):
        if chart_data[target_tool]: chart_data[target_tool].pop(); state.autosave(force=True); st.rerun(scope="fragment")
    if b2.button("Очистить", key=f"clr_{ticker}_{tf_name}", use_container_width=True):
        chart_data[target_tool] = []; state.autosave(force=True); st.rerun(scope="fragment")

    df = fetch_moex_candles(ticker, cfg["interval"], cfg["days_back"])
    if df.empty:
        st.warning("Нет данных MOEX.")
        return

    d1_pts = tdata["charts"]["D1"]["channel"]
    h1_zig = tdata["charts"]["H1"]["zigzag"]

    zoom_start = None
    if tf_name == "H1" and len(d1_pts) == 3: zoom_start = d1_pts[2][0]
    elif tf_name in ["M10", "M1"] and len(h1_zig) >= 4: zoom_start = h1_zig[-4][0]

    default_bars = 1500 if tf_name == "M1" else 150

    if zoom_start:
        try:
            z_time = pd.to_datetime(zoom_start)
            filtered_df = df.loc[z_time:]
            view = df.tail(default_bars).copy() if len(filtered_df) < 10 else filtered_df.copy()
        except Exception:
            view = df.tail(default_bars).copy()
    else:
        view = df.tail(default_bars).copy()

    chart_key = f"chart_{ticker}_{tf_name}"
    click = charts.capture_click(chart_key)
    pts = chart_data[target_tool]

    if click:
        x, y = click
        y = inst.round_price(y)
        bar = view.iloc[view.index.get_indexer([pd.to_datetime(x)], method='nearest')[0]]
        new_pts = pts.copy()
        max_pts = 3 if tool == "channel" else (None if "zigzag" in tool else 2)

        if max_pts is None or len(new_pts) < max_pts:
            if tool == "channel":
                if len(new_pts) == 0: new_pts.append([str(bar.name), y])
                elif len(new_pts) == 1:
                    first_time = pd.to_datetime(new_pts[0][0])
                    second_time = pd.to_datetime(bar.name)
                    if first_time <= second_time: t_start, p_start, t_end, p_end = first_time, new_pts[0][1], second_time, y
                    else: t_start, p_start, t_end, p_end = second_time, y, first_time, new_pts[0][1]
                    is_up = p_end > p_start
                    view_period = view.loc[t_start:t_end]
                    if view_period.empty: return
                    if is_up:
                        y_start, y_end = float(view.loc[t_start, 'Low']), float(view.loc[t_end, 'Low'])
                        t_mid = view_period['High'].idxmax()
                        y_mid = float(view_period.loc[t_mid, 'High'])
                    else:
                        y_start, y_end = float(view.loc[t_start, 'High']), float(view.loc[t_end, 'High'])
                        t_mid = view_period['Low'].idxmin()
                        y_mid = float(view_period.loc[t_mid, 'Low'])
                    new_pts = [[str(t_start), y_start], [str(t_mid), y_mid], [str(t_end), y_end]]
            elif "zigzag" in tool:
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
                st.rerun(scope="fragment")

    if tf_name == "D1":
        d1_pts_s = snap_points(d1_pts, view)
        d1_fib_s = snap_points(tdata["charts"]["D1"]["fib"], view)
        h1_zig_s, h1_fib_s = h1_zig, tdata["charts"]["H1"]["fib"]
        m10_zig_s, m1_zig_s = tdata["charts"]["M10"]["zigzag"], tdata["charts"]["M1"]["zigzag"]
    elif tf_name == "H1":
        d1_pts_s, d1_fib_s = d1_pts, tdata["charts"]["D1"]["fib"]
        h1_zig_s = snap_points(h1_zig, view)
        h1_fib_s = snap_points(tdata["charts"]["H1"]["fib"], view)
        m10_zig_s, m1_zig_s = tdata["charts"]["M10"]["zigzag"], tdata["charts"]["M1"]["zigzag"]
    elif tf_name == "M10":
        d1_pts_s, d1_fib_s = d1_pts, tdata["charts"]["D1"]["fib"]
        h1_zig_s, h1_fib_s = h1_zig, tdata["charts"]["H1"]["fib"]
        m10_zig_s = snap_points(tdata["charts"]["M10"]["zigzag"], view)
        m1_zig_s = tdata["charts"]["M1"]["zigzag"]
    else:
        d1_pts_s, d1_fib_s = d1_pts, tdata["charts"]["D1"]["fib"]
        h1_zig_s, h1_fib_s = h1_zig, tdata["charts"]["H1"]["fib"]
        m10_zig_s = tdata["charts"]["M10"]["zigzag"]
        m1_zig_s = snap_points(tdata["charts"]["M1"]["zigzag"], view)

    fig = charts.build_figure(view, tf_name=tf_name, title=f"{ticker} — {tf_name}", decimals=inst.decimals, mobile=mobile, show_info=show_info)

    time_buffer = pd.Timedelta(days=10) if tf_name == "D1" else (pd.Timedelta(hours=12) if tf_name == "H1" else pd.Timedelta(hours=2))
    x_left = view.index[0]
    x_right = view.index[-1] + time_buffer

    if clusters_data and cluster_start_time:
        charts.draw_clusters(fig, clusters_data, x_left, x_right)

    if show_tools:
        if d1_pts_s: charts.draw_channel(fig, d1_pts_s, x_right)
        if d1_fib_s: charts.draw_fib(fig, d1_fib_s, x_left, x_right, "blue", "0.5 D1")
        if h1_fib_s: charts.draw_fib(fig, h1_fib_s, x_left, x_right, "green", "0.5 H1")

        if h1_zig_s: charts.draw_zigzag(fig, h1_zig_s, "#26a69a", "Тенденция (H1)")
        if m10_zig_s and tf_name in ["H1", "M10", "M1"]: charts.draw_zigzag(fig, m10_zig_s, "#ef5350", "Зигзаг (M10)")
        if m1_zig_s and tf_name == "M1": charts.draw_zigzag(fig, m1_zig_s, "#ef5350", "Зигзаг (M1)")

    if h1_zig_s and tf_name == "H1":
        breakouts = analyze_manual_zigzag(h1_zig_s, view)
        charts.draw_breakouts(fig, breakouts, inst.decimals)
        
        if show_rr and breakouts:
            last_b = breakouts[-1]
            charts.draw_rr_zones(fig, last_b["pullback_setup_time"], last_b["pullback_setup_price"], last_b["peak_time"], last_b["peak_price"], strategy)

        if breakouts:
            st.markdown("##### Анализ пробоев и откатов H1")
            df_metrics = pd.DataFrame([{
                "Направление": "Вверх" if b["trend"] == "up" else "Вниз",
                "Уровень B": b["resistance_price"],
                "Пробой Δ": b["delta"],
                "Пробой %": f"{b['breakout_pct']:.1f}%",
                "Бары (П/О)": f"{b['bars']} / {b['retr_bars']}",
                "Объем (П/О)": f"{b['volume']:,.0f} / {b['retr_vol']:,.0f}",
                "Оценка пробоя": {"strong": "Сильный", "weak": "Слабый", "normal": "Нормальный"}.get(b.get("breakout_verdict"), "-"),
                "Откат E": b["e_price"] if b["has_pullback"] else "-",
                "E vs 0.5": b["e_vs_b"] if b["has_pullback"] else "-",
                "Откат %": f"{b['retracement_pct']:.1f}%" if b["has_pullback"] else "-",
                # ИСПРАВЛЕНА ТАБЛИЦА:
                "Оценка отката": {"Слабый": "Слабый (тренд сильный)", "Сильный": "Сильный (тренд слабый)", "Нормальный": "Нормальный"}.get(b.get("pullback_verdict"), "-") if b["has_pullback"] else "-"
            } for b in breakouts])
            st.dataframe(df_metrics, use_container_width=True, hide_index=True)

    if plan and show_position:
        charts.draw_trade_visuals(fig, plan, x_left, x_right, inst.decimals)

    st.plotly_chart(fig, use_container_width=True, key=chart_key, on_select="rerun", selection_mode="points", config=charts.PLOT_CONFIG)
    st.caption(f"Диапазон отображения: {view.index[0].strftime('%d.%m.%Y %H:%M')} – {view.index[-1].strftime('%d.%m.%Y %H:%M')} · Баров: {len(view)}")
