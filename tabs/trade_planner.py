import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

from data import vlookup, to_float, get_margin, fetch_moex_candles, load_trend_cache, save_trend_cache

INTERVALS = {
    "D1":  {"interval": 24, "days_back": 250, "is_intraday": False},
    "H1":  {"interval": 60, "days_back": 30,  "is_intraday": True},
    "M10": {"interval": 10, "days_back": 30,  "is_intraday": True},
}

def _div(a, b, default=0.0):
    return a / b if b else default

def fmt_ru(value, decimals=2, suffix=""):
    if value is None:
        return "—"
    try:
        formatted = f"{value:,.{decimals}f}"
        formatted = formatted.replace(",", "_T_").replace(".", ",").replace("_T_", " ")
        return f"{formatted}{suffix}"
    except Exception:
        return str(value)

def _is_mobile():
    return bool(st.session_state.get("sb_mobile", False))

def _metric_card_html(label, value, color=None):
    color_style = f"color:{color};" if color else "color:#111827;"
    return (
        '<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;'
        'padding:14px 16px;box-sizing:border-box;">'
        f'<div style="font-size:13px;color:#6b7280;margin-bottom:8px;font-weight:500;">{label}</div>'
        f'<div style="font-size:22px;font-weight:700;line-height:1.15;{color_style}">{value}</div>'
        '</div>'
    )

def _render_metric_cards(items, cols_per_row=4):
    cards = "".join(_metric_card_html(it["label"], it["value"], it.get("color")) for it in items)
    if _is_mobile():
        html = f'<div style="display:flex;flex-direction:column;gap:10px;margin:10px 0;">{cards}</div>'
    else:
        html = (f'<div style="display:grid;grid-template-columns:repeat({cols_per_row},1fr);'
                f'gap:12px;margin:12px 0;">{cards}</div>')
    st.markdown(html, unsafe_allow_html=True)

def _verdict_bg(verdict_ru):
    return {"СИЛЬНЫЙ": "#0d6efd", "СЛАБЫЙ": "#6c757d",
            "НОРМАЛЬНЫЙ": "#17a2b8", "БАЗОВЫЙ": "#6c757d"}.get(verdict_ru, "#6c757d")

def _pullback_bg(verdict_ru):
    return {"СИЛЬНЫЙ": "#198754", "СЛАБЫЙ": "#dc3545",
            "НОРМАЛЬНЫЙ": "#fd7e14"}.get(verdict_ru, "#6c757d")

def _render_breakout_cards(breakouts, decimals):
    breakout_map = {"strong": "СИЛЬНЫЙ", "weak": "СЛАБЫЙ", "normal": "НОРМАЛЬНЫЙ", "base": "БАЗОВЫЙ"}
    pullback_map = {"strong": "СИЛЬНЫЙ", "weak": "СЛАБЫЙ", "normal": "НОРМАЛЬНЫЙ"}
    for b in breakouts:
        trend_up = b["trend"] == "up"
        border_color = "#0d6efd" if trend_up else "#dc3545"
        trend_label = "Пробой вверх" if trend_up else "Пробой вниз"
        b_v = breakout_map.get(b["breakout_verdict"], "-")
        b_bg = _verdict_bg(b_v)
        pullback_html = ""
        if b["has_pullback"]:
            p_v = pullback_map.get(b["pullback_verdict"], "-")
            p_bg = _pullback_bg(p_v)
            pullback_html = (
                '<div style="margin-top:10px;padding-top:10px;border-top:1px dashed #e5e7eb;">'
                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                '<span style="font-size:13px;color:#6b7280;font-weight:500;">Откат</span>'
                f'<span style="background:{p_bg};color:#fff;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;">{p_v}</span>'
                '</div>'
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;font-size:13px;">'
                f'<div><span style="color:#6b7280;">Цена (E):</span> <b>{b["pullback_price"]:.{decimals}f}</b></div>'
                f'<div><span style="color:#6b7280;">Ретр.:</span> <b>{b["retracement_pct"]:.1f}%</b></div>'
                '</div></div>'
            )
        card = (
            f'<div style="background:#fff;border:1px solid #e5e7eb;border-left:4px solid {border_color};'
            'border-radius:12px;padding:14px 16px;margin-bottom:10px;">'
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            f'<span style="font-weight:600;color:#111827;">{trend_label}</span>'
            f'<span style="background:{b_bg};color:#fff;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600;">{b_v}</span>'
            '</div>'
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;font-size:13px;">'
            f'<div><span style="color:#6b7280;">Уровень:</span> <b>{b["resistance_price"]:.{decimals}f}</b></div>'
            f'<div><span style="color:#6b7280;">Пик (D):</span> <b>{b["peak_price"]:.{decimals}f}</b></div>'
            f'<div><span style="color:#6b7280;">Δ Пробоя:</span> <b>{b["breakout_magnitude"]:.{decimals}f}</b></div>'
            f'<div><span style="color:#6b7280;">Бар/Vol:</span> <b>{b["breakout_bars"]} / {b["breakout_volume"]:,.0f}</b></div>'
            f'</div>{pullback_html}</div>'
        )
        st.markdown(card, unsafe_allow_html=True)

def calc_commission(price, multiplier, tariff):
    notional = price * multiplier
    if tariff == "Т-Инвестиции":
        return max(notional * 0.001, 0.01)
    elif tariff == "Финам СТАНДАРТНЫЙ ФОРТС":
        return 0.45
    return 0.0

def calculate_breakout_metrics(df, resistance_price, start_time, end_time, is_up=True):
    df_period = df.loc[start_time:end_time]
    if df_period.empty:
        return 0, 0, start_time
    if is_up:
        breakout_bars = df_period[df_period['High'] > resistance_price]
    else:
        breakout_bars = df_period[df_period['Low'] < resistance_price]
    if not breakout_bars.empty:
        breakout_time = breakout_bars.index[0]
    else:
        breakout_time = start_time
    df_active = df.loc[breakout_time:end_time]
    return len(df_active), df_active['Volume'].sum(), breakout_time

def analyze_manual_zigzag(pts, df):
    if len(pts) < 4:
        return []
    breakouts = []
    for i in range(3, len(pts)):
        p_a, p_b, p_c, p_d = pts[i-3], pts[i-2], pts[i-1], pts[i]
        a_time, a_price = p_a
        b_time, b_price = p_b
        c_time, c_price = p_c
        d_time, d_price = p_d
        if a_price < b_price and a_price < c_price < b_price and d_price > b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=True)
            breakout_magnitude = d_price - b_price
            has_pullback = False
            e_time = e_price = None
            retracement_pct = None
            pullback_verdict = None
            if i + 1 < len(pts):
                e_time, e_price = pts[i+1]
                if e_price < d_price:
                    has_pullback = True
                    if breakout_magnitude > 0:
                        retracement_pct = (d_price - e_price) / breakout_magnitude * 100
                    if e_price > b_price: pullback_verdict = "strong"
                    elif e_price < b_price: pullback_verdict = "weak"
                    else: pullback_verdict = "normal"
            breakouts.append({
                "trend": "up", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "breakout_magnitude": breakout_magnitude, "breakout_bars": bars,
                "breakout_volume": vol, "has_pullback": has_pullback,
                "pullback_time": e_time, "pullback_price": e_price,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict,
            })
        elif a_price > b_price and b_price < c_price < a_price and d_price < b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=False)
            breakout_magnitude = b_price - d_price
            has_pullback = False
            e_time = e_price = None
            retracement_pct = None
            pullback_verdict = None
            if i + 1 < len(pts):
                e_time, e_price = pts[i+1]
                if e_price > d_price:
                    has_pullback = True
                    if breakout_magnitude > 0:
                        retracement_pct = (e_price - d_price) / breakout_magnitude * 100
                    if e_price < b_price: pullback_verdict = "strong"
                    elif e_price > b_price: pullback_verdict = "weak"
                    else: pullback_verdict = "normal"
            breakouts.append({
                "trend": "down", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "breakout_magnitude": breakout_magnitude, "breakout_bars": bars,
                "breakout_volume": vol, "has_pullback": has_pullback,
                "pullback_time": e_time, "pullback_price": e_price,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict,
            })
    for i, brk in enumerate(breakouts):
        if i == 0:
            brk['breakout_verdict'] = "base"
            brk['breakout_ratio'] = None
        else:
            prev_mag = breakouts[i-1]['breakout_magnitude']
            curr_mag = brk['breakout_magnitude']
            if prev_mag > 0:
                ratio = curr_mag / prev_mag
                brk['breakout_ratio'] = ratio
                if ratio >= 1.15: brk['breakout_verdict'] = "strong"
                elif ratio <= 0.85: brk['breakout_verdict'] = "weak"
                else: brk['breakout_verdict'] = "normal"
            else:
                brk['breakout_verdict'] = "normal"
                brk['breakout_ratio'] = None
    return breakouts


# ============ КЛАСТЕРЫ ОБЪЁМОВ ============
def find_volume_cluster_zones(df_h1, threshold_mult=3.0, window=20):
    """
    Возвращает список зон, построенных по H1-барам с аномальным объёмом
    (те, что в объёмной панели H1 красятся в зелёный).

    Для каждого бара:
    - бычий (close > open): зона = [low, close]  (как уровень покупок);
    - медвежий (close <= open): зона = [close, high]  (как уровень продаж).

    Каждая зона потом продлевается в обе стороны на графике и рисуется
    полупрозрачным прямоугольником. Наложения копят альфу — где больше
    наложений, там цвет ярче.
    """
    if df_h1 is None or df_h1.empty or 'Volume' not in df_h1.columns:
        return []

    volumes = df_h1['Volume'].values
    rolling_avg = pd.Series(volumes).rolling(window=window, min_periods=5).mean().shift(1)

    zones = []
    for i in range(len(df_h1)):
        avg = rolling_avg.iloc[i]
        if pd.isna(avg) or avg <= 0:
            continue
        if volumes[i] <= avg * threshold_mult:
            continue

        row = df_h1.iloc[i]
        is_buy = float(row['Close']) > float(row['Open'])
        if is_buy:
            y_low = float(row['Low'])
            y_high = float(row['Close'])
        else:
            y_low = float(row['Close'])
            y_high = float(row['High'])

        if y_high > y_low:
            zones.append({
                "time": df_h1.index[i],
                "low": y_low,
                "high": y_high,
                "volume": float(volumes[i]),
                "is_buy": is_buy,
            })
    return zones


def draw_chart(df_chart, title="", is_intraday=False, decimals=0, is_h1=False, is_m10=False, is_d1=False, ticker="", d1_pts=None, d1_fib_pts=None, h1_tend_pts=None, h1_fib_pts=None, m10_zig_pts=None, h1_levels=None, strategy="Зигзаг тенденции", zoom_start_time=None, show_rr=True, show_levels=True, volume_clusters=None):
    if df_chart.empty:
        return None, []

    if zoom_start_time is not None:
        try:
            z_time = pd.to_datetime(zoom_start_time)
            filtered_df = df_chart.loc[z_time:]
            if len(filtered_df) < 10:
                df_chart = df_chart.tail(150).copy()
            else:
                df_chart = filtered_df.copy()
        except Exception:
            df_chart = df_chart.tail(150).copy()
    else:
        df_chart = df_chart.tail(150).copy()

    tick_fmt = f".{decimals}f"

    if is_intraday:
        time_buffer = pd.Timedelta(hours=12) if is_h1 else pd.Timedelta(hours=2)
    else:
        time_buffer = pd.Timedelta(days=10)
    dt_end = df_chart.index[-1] + time_buffer

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.8, 0.2])

    fig.add_trace(go.Ohlc(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
        low=df_chart['Low'], close=df_chart['Close'],
        increasing_line_color='black', decreasing_line_color='black',
        increasing_line_width=1.5, decreasing_line_width=1.5,
        name='Рынок'
    ), row=1, col=1)

    # ============ КЛАСТЕРЫ ОБЪЁМОВ ============
    if volume_clusters:
        try:
            chart_start = df_chart.index[0]
        except Exception:
            chart_start = None
        if chart_start is not None:
            for zone in volume_clusters:
                try:
                    y_low = float(zone["low"])
                    y_high = float(zone["high"])
                    if y_high <= y_low:
                        continue
                    fig.add_shape(
                        type="rect",
                        x0=chart_start, x1=dt_end,
                        y0=y_low, y1=y_high,
                        fillcolor="rgba(255, 140, 0, 0.15)",
                        line=dict(width=0),
                        layer="below",
                        xref="x", yref="y", row=1, col=1,
                    )
                except Exception:
                    continue

    if show_levels and h1_levels:
        for lvl in h1_levels:
            try:
                if not isinstance(lvl, dict): continue
                t_start = pd.to_datetime(lvl["time"])
                if lvl["is_buy"]:
                    y_bottom = float(lvl["low"]); y_top = float(lvl["close"])
                    zone_color = "rgba(128, 0, 128, 0.1)"
                    label_bg = "rgba(128, 0, 128, 0.95)"; label_fg = "white"
                else:
                    y_bottom = float(lvl["close"]); y_top = float(lvl["high"])
                    zone_color = "rgba(255, 105, 180, 0.1)"
                    label_bg = "rgba(255, 105, 180, 0.95)"; label_fg = "black"

                fig.add_shape(type="rect", x0=t_start, x1=dt_end, y0=y_bottom, y1=y_top,
                    fillcolor=zone_color, line=dict(width=0), layer="below",
                    xref="x", yref="y", row=1, col=1)

                fig.add_annotation(x=0.99, y=y_top, xref="x domain", yref="y",
                    text=f" {y_top:.{decimals}f} ", showarrow=False, xanchor="right", yanchor="middle",
                    bgcolor=label_bg, font=dict(color=label_fg, size=9, weight="bold"),
                    bordercolor="black", borderwidth=1, borderpad=1)
                fig.add_annotation(x=0.99, y=y_bottom, xref="x domain", yref="y",
                    text=f" {y_bottom:.{decimals}f} ", showarrow=False, xanchor="right", yanchor="middle",
                    bgcolor=label_bg, font=dict(color=label_fg, size=9, weight="bold"),
                    bordercolor="black", borderwidth=1, borderpad=1)
            except Exception:
                continue

    if d1_pts and len(d1_pts) == 3:
        t1, p1 = d1_pts[0]; t2, p2 = d1_pts[1]; t3, p3 = d1_pts[2]
        x1_ts = pd.to_datetime(t1); x2_ts = pd.to_datetime(t2); x3_ts = pd.to_datetime(t3)
        time1 = x1_ts.timestamp(); time2 = x2_ts.timestamp(); time3 = x3_ts.timestamp()
        dt_12 = time2 - time1 if time2 != time1 else 1
        slope_time = (p2 - p1) / dt_12
        time_end = dt_end.timestamp()
        y_ray1_end = slope_time * (time_end - time1) + p1
        y_ray2_end = slope_time * (time_end - time3) + p3
        fig.add_shape(type="line", x0=x1_ts, y0=p1, x1=dt_end, y1=y_ray1_end, line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1)
        fig.add_shape(type="line", x0=x3_ts, y0=p3, x1=dt_end, y1=y_ray2_end, line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1)
        fig.add_trace(go.Scatter(x=[t1, t2, t3], y=[p1, p2, p3], mode='markers',
            marker=dict(color='blue', size=10), name='Точки канала D1', showlegend=False), row=1, col=1)

    if d1_fib_pts and len(d1_fib_pts) == 2:
        t1, p1 = d1_fib_pts[0]; t2, p2 = d1_fib_pts[1]
        mid_price = (p1 + p2) / 2
        x1_ts = pd.to_datetime(t1)
        fig.add_shape(type="line", x0=x1_ts, y0=mid_price, x1=dt_end, y1=mid_price,
            line=dict(color="blue", width=2, dash="dash"), xref="x", yref="y", row=1, col=1)
        fig.add_annotation(x=dt_end, y=mid_price, text="0.5 D1", showarrow=False,
            xanchor="left", font=dict(color="blue", size=10), row=1, col=1)

    if h1_fib_pts and len(h1_fib_pts) == 2:
        t1, p1 = h1_fib_pts[0]; t2, p2 = h1_fib_pts[1]
        mid_price = (p1 + p2) / 2
        x1_ts = pd.to_datetime(t1)
        fig.add_shape(type="line", x0=x1_ts, y0=mid_price, x1=dt_end, y1=mid_price,
            line=dict(color="green", width=2, dash="dash"), xref="x", yref="y", row=1, col=1)
        fig.add_annotation(x=dt_end, y=mid_price, text="0.5 H1", showarrow=False,
            xanchor="left", font=dict(color="green", size=10), row=1, col=1)

    if h1_tend_pts:
        mx = [p[0] for p in h1_tend_pts]; my = [p[1] for p in h1_tend_pts]
        fig.add_trace(go.Scatter(x=mx, y=my, mode='lines+markers',
            marker=dict(size=8, color='green', symbol='circle'),
            line=dict(color='green', width=3), name='Тенденция (H1)'), row=1, col=1)

    if (is_h1 or is_m10) and m10_zig_pts:
        mx = [p[0] for p in m10_zig_pts]; my = [p[1] for p in m10_zig_pts]
        fig.add_trace(go.Scatter(x=mx, y=my, mode='lines+markers',
            marker=dict(size=8, color='red', symbol='circle'),
            line=dict(color='red', width=3), name='Зигзаг (M10)'), row=1, col=1)

    if show_rr and h1_tend_pts and len(h1_tend_pts) >= 2:
        if strategy == "Зигзаг тенденции":
            t_c, p_c = h1_tend_pts[-2]; t_d, p_d = h1_tend_pts[-1]
        else:
            t_c, p_c = h1_tend_pts[0]; t_d, p_d = h1_tend_pts[-1]
        low = min(p_c, p_d); high = max(p_c, p_d); diff = high - low
        if diff > 0:
            y1_start, y1_end = low, low + diff/3
            y3_start, y3_end = low + 2*diff/3, high
            if p_d > p_c:
                color_bottom = "rgba(0, 128, 0, 0.1)"; color_top = "rgba(255, 0, 0, 0.1)"
            else:
                color_bottom = "rgba(255, 0, 0, 0.1)"; color_top = "rgba(0, 128, 0, 0.1)"
            fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=y1_start, y1=y1_end,
                fillcolor=color_bottom, line=dict(width=0), layer="below", xref="x", yref="y", row=1, col=1)
            fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=y3_start, y1=y3_end,
                fillcolor=color_top, line=dict(width=0), layer="below", xref="x", yref="y", row=1, col=1)

    breakouts = []
    if is_h1 and h1_tend_pts:
        breakouts = analyze_manual_zigzag(h1_tend_pts, df_chart)
        drawn_coords = set()
        for brk in breakouts:
            line_color_breakout = "#0d6efd"; line_color_pullback = "#fd7e14"
            verdict = brk['breakout_verdict']; ratio = brk['breakout_ratio']
            if verdict == "strong": breakout_bg = "rgba(13, 110, 253, 0.9)"
            elif verdict == "weak": breakout_bg = "rgba(108, 117, 125, 0.9)"
            elif verdict == "normal": breakout_bg = "rgba(23, 162, 184, 0.9)"
            else: breakout_bg = "rgba(13, 110, 253, 0.9)"
            ratio_text = f" (x{ratio:.1f})" if ratio else ""
            verdict_map = {"strong": "СИЛЬНЫЙ", "weak": "СЛАБЫЙ", "normal": "НОРМАЛЬНЫЙ", "base": "БАЗОВЫЙ"}
            v_text = verdict_map.get(verdict, "")
            breakout_text = f"Δ: {brk['breakout_magnitude']:.{decimals}f}{ratio_text}<br>Бар: {brk['breakout_bars']}<br>Vol: {brk['breakout_volume']:,.0f}<br>Оценка: <b>{v_text}</b>"
            peak_key = (brk['peak_time'], brk['peak_price'])
            if peak_key not in drawn_coords:
                fig.add_annotation(x=brk['peak_time'], y=brk['peak_price'], text=breakout_text,
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_breakout,
                    ax=40, ay=-40, bgcolor=breakout_bg, font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3, row=1, col=1)
                drawn_coords.add(peak_key)
            res_key = (brk['resistance_time'], brk['resistance_price'])
            if res_key not in drawn_coords:
                fig.add_annotation(x=brk['resistance_time'], y=brk['resistance_price'], text=breakout_text,
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_breakout,
                    ax=-40, ay=40, bgcolor=breakout_bg, font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3, row=1, col=1)
                drawn_coords.add(res_key)
            fig.add_shape(type="line", x0=brk['resistance_time'], y0=brk['resistance_price'],
                x1=brk['breakout_time'], y1=brk['resistance_price'],
                line=dict(color=line_color_breakout, width=2), xref="x", yref="y", row=1, col=1)
            fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['resistance_price'],
                x1=brk['breakout_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), xref="x", yref="y", row=1, col=1)
            fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['peak_price'],
                x1=brk['peak_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), xref="x", yref="y", row=1, col=1)
            mid_y_breakout = brk['resistance_price'] + (brk['peak_price'] - brk['resistance_price']) / 2
            fig.add_annotation(x=brk['breakout_time'], y=mid_y_breakout,
                text=f"Δ: {brk['breakout_magnitude']:.{decimals}f}", showarrow=False,
                xanchor="right", xshift=-5,
                font=dict(color=line_color_breakout, size=11, weight="bold"), row=1, col=1)
            if brk['has_pullback']:
                p_verdict = brk['pullback_verdict']
                if p_verdict == "strong": pullback_bg = "rgba(25, 135, 84, 0.9)"
                elif p_verdict == "weak": pullback_bg = "rgba(220, 53, 69, 0.9)"
                else: pullback_bg = "rgba(253, 126, 20, 0.9)"
                p_verdict_map = {"strong": "СИЛЬНЫЙ", "weak": "СЛАБЫЙ", "normal": "НОРМАЛЬНЫЙ"}
                p_v_text = p_verdict_map.get(p_verdict, "")
                pullback_text = f"Откат: {brk['retracement_pct']:.1f}%<br>Оценка: <b>{p_v_text}</b>"
                pull_key = (brk['pullback_time'], brk['pullback_price'])
                if pull_key not in drawn_coords:
                    fig.add_annotation(x=brk['pullback_time'], y=brk['pullback_price'], text=pullback_text,
                        showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_pullback,
                        ax=0, ay=40, bgcolor=pullback_bg, font=dict(color="white", size=10),
                        bordercolor="black", borderwidth=1, borderpad=3, row=1, col=1)
                    drawn_coords.add(pull_key)
                fig.add_shape(type="line", x0=brk['peak_time'], y0=brk['peak_price'],
                    x1=brk['peak_time'], y1=brk['pullback_price'],
                    line=dict(color=line_color_pullback, width=2, dash="dot"), xref="x", yref="y", row=1, col=1)
                fig.add_shape(type="line", x0=brk['peak_time'], y0=brk['pullback_price'],
                    x1=brk['pullback_time'], y1=brk['pullback_price'],
                    line=dict(color=line_color_pullback, width=2), xref="x", yref="y", row=1, col=1)
                mid_y_pullback = brk['pullback_price'] + (brk['peak_price'] - brk['pullback_price']) / 2
                fig.add_annotation(x=brk['peak_time'], y=mid_y_pullback,
                    text=f"{brk['retracement_pct']:.1f}%", showarrow=False,
                    xanchor="right", xshift=-5,
                    font=dict(color=line_color_pullback, size=11, weight="bold"), row=1, col=1)

    if 'Volume' in df_chart.columns:
        colors = ['gray'] * len(df_chart)
        volumes = df_chart['Volume'].values
        times = df_chart.index
        for i in range(2, len(df_chart)):
            if volumes[i] > volumes[i-1] and volumes[i] > volumes[i-2]: colors[i] = 'black'
        if is_h1:
            for i in range(len(df_chart)):
                if times[i].hour == 10 and times[i].minute == 0:
                    prev_10s = []
                    for j in range(i-1, -1, -1):
                        if times[j].hour == 10 and times[j].minute == 0:
                            prev_10s.append(volumes[j])
                            if len(prev_10s) == 2: break
                    if len(prev_10s) == 2:
                        if volumes[i] > prev_10s[0] and volumes[i] > prev_10s[1]: colors[i] = 'black'
        if is_m10 or is_h1 or is_d1:
            vol_series = pd.Series(volumes)
            rolling_avg = vol_series.rolling(window=20, min_periods=5).mean().shift(1)
            anomaly_color = 'red' if is_m10 else ('green' if is_h1 else 'blue')
            if anomaly_color:
                for i in range(len(volumes)):
                    if pd.notna(rolling_avg.iloc[i]) and rolling_avg.iloc[i] > 0:
                        if volumes[i] > rolling_avg.iloc[i] * 3.0: colors[i] = anomaly_color
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
            marker_color=colors, name='Объем'), row=2, col=1)

    chart_height = 450 if _is_mobile() else 700
    fig.update_layout(title=title, height=chart_height, margin=dict(l=10, r=10, t=50, b=50),
        plot_bgcolor='white', paper_bgcolor='white', xaxis_rangeslider_visible=False, showlegend=False,
        hovermode='closest', spikedistance=-1)

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday: rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))
    if len(df_chart) > 1:
        if is_intraday:
            first_day = df_chart.index[0].normalize()
            snap_start = first_day + pd.Timedelta(hours=7)
            if snap_start > df_chart.index[0]: snap_start -= pd.Timedelta(days=1)
            x_range = [snap_start, dt_end]
        else: x_range = [df_chart.index[0] - pd.Timedelta(days=1), dt_end]
    else: x_range = None
    y_min = df_chart['Low'].min(); y_max = df_chart['High'].max()
    y_padding = (y_max - y_min) * 0.10
    y_range = [y_min - y_padding, y_max + y_padding]

    fig.update_xaxes(showgrid=True, gridcolor='lightgray', rangebreaks=rangebreaks, range=x_range,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash')
    fig.update_yaxes(showgrid=True, gridcolor='lightgray', side='right', tickformat=tick_fmt,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash', range=y_range, row=1, col=1)
    fig.update_yaxes(showgrid=True, gridcolor='lightgray', side='right',
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash', row=2, col=1)
    return fig, breakouts


def render_trade_planner(*, ticker, api_df, go_df, md_df, iss_df, deposit, risk_pct, rr_ratio, commission, strategy):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"Позиция: {ticker}")

    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty and "SECID" in iss_df.columns else pd.DataFrame()
    if not iss_row.empty:
        market = to_float(iss_row.iloc[0].get("LAST", 0)) or to_float(iss_row.iloc[0].get("PREVSETTLEPRICE", 0))
        decimals = int(to_float(iss_row.iloc[0].get("DECIMALS", 0)))
    else:
        market = 100000.0; decimals = 0

    margin_type = st.session_state.get("margin_type", "КСУР")
    margin_per_contract = get_margin(go_df, ticker, margin_type, "LONG")
    if margin_per_contract == 0 and not iss_row.empty:
        margin_per_contract = to_float(iss_row.iloc[0].get("INITIALMARGIN", 0))
    if margin_per_contract == 0: margin_per_contract = 25000.0

    step_price = to_float(vlookup(api_df, ticker, 6)) or 10.0
    step_cost = to_float(vlookup(api_df, ticker, 17)) or 16.2
    multiplier = _div(step_cost, step_price)

    cache = load_trend_cache()
    ticker_cache = cache.get(ticker, {})

    pts_keys = {
        "d1_chan": f"manual_channel_{ticker}_D1", "d1_fib": f"manual_fib_{ticker}_D1",
        "h1_tend": f"manual_tend_{ticker}_H1", "h1_fib": f"manual_fib_{ticker}_H1",
        "m10_zig": f"manual_zig_{ticker}_M10", "h1_levels": f"manual_levels_{ticker}_H1",
    }
    cache_keys = {
        "d1_chan": "d1_manual_pts", "d1_fib": "d1_fib_pts",
        "h1_tend": "h1_tend_pts", "h1_fib": "h1_fib_pts",
        "m10_zig": "m10_zig_pts", "h1_levels": "h1_levels",
    }

    for k, skey in pts_keys.items():
        if skey not in st.session_state:
            cached_pts = ticker_cache.get(cache_keys[k], [])
            if k == "h1_levels": st.session_state[skey] = cached_pts if isinstance(cached_pts, list) else []
            else: st.session_state[skey] = [(pd.to_datetime(t), float(p)) for t, p in cached_pts]

    for k in pts_keys.keys():
        undo_k = f"undo_{k}_{ticker}"; redo_k = f"redo_{k}_{ticker}"; deb_k = f"debounce_{k}_{ticker}"
        if undo_k not in st.session_state: st.session_state[undo_k] = []
        if redo_k not in st.session_state: st.session_state[redo_k] = []
        if deb_k not in st.session_state: st.session_state[deb_k] = 0.0

    h1_pts = st.session_state.get(pts_keys["h1_tend"], [])
    d1_pts = st.session_state.get(pts_keys["d1_chan"], [])
    h1_levels = st.session_state.get(pts_keys["h1_levels"], [])

    p_a, p_b, p_c, p_d = None, None, None, None
    if len(h1_pts) >= 4:
        p_a = h1_pts[-4][1]; p_b = h1_pts[-3][1]; p_c = h1_pts[-2][1]; p_d = h1_pts[-1][1]

    with st.expander("Техническая аналитика графика", expanded=False):
        st.markdown("**Последние 4 точки Тенденции (H1):**")
        c1, c2, c3, c4 = st.columns(4)
        val_a = f"{p_a:.{decimals}f}" if p_a is not None else "-"
        val_b = f"{p_b:.{decimals}f}" if p_b is not None else "-"
        val_c = f"{p_c:.{decimals}f}" if p_c is not None else "-"
        val_d = f"{p_d:.{decimals}f}" if p_d is not None else "-"
        c1.metric("Точка 1", val_a); c2.metric("Точка 2", val_b)
        c3.metric("Точка 3", val_c); c4.metric("Точка 4", val_d)

    st.markdown("#### Графики рынка (MOEX ISS)")
    st.markdown("""
        <style>
        .js-plotly-plot .plotly .draglayer {
            cursor: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='4' fill='red'/%3E%3C/svg%3E") 8 8, crosshair !important;
        }
        </style>
    """, unsafe_allow_html=True)

    chart_tabs = st.tabs(["D1 (Дни)", "H1 (Часы)", "M10 (10 минут)"])

    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            is_d1 = (tf_name == "D1"); is_h1 = (tf_name == "H1"); is_m10 = (tf_name == "M10")

            if _is_mobile():
                c_tools = st.container()
                c_toggles = st.container()
            else:
                c_tools, c_toggles = st.columns([2, 2])

            with c_tools:
                if is_d1:
                    active_tool = st.radio("Инструмент (D1)", ["Нет", "D1: Канал", "D1: Уровень 1/2"], horizontal=True, key=key("active_tool_d1"))
                    active_k = {"D1: Канал": "d1_chan", "D1: Уровень 1/2": "d1_fib"}.get(active_tool)
                elif is_h1:
                    active_tool = st.radio("Инструмент (H1)", ["Нет", "H1: Тенденция", "H1: Уровень 1/2", "Уровни покупателя/продавца"], horizontal=True, key=key("active_tool_h1"))
                    active_k = {"H1: Тенденция": "h1_tend", "H1: Уровень 1/2": "h1_fib", "Уровни покупателя/продавца": "h1_levels"}.get(active_tool)
                else:
                    active_tool = st.radio("Инструмент (M10)", ["Нет", "M10: Зигзаг"], horizontal=True, key=key("active_tool_m10"))
                    active_k = "m10_zig" if active_tool == "M10: Зигзаг" else None

            # ============ Переключатели (сетка 2×2) ============
            with c_toggles:
                if _is_mobile():
                    show_tools = st.toggle("Показать графику", value=True, key=key(f"show_tools_{tf_name}"))
                    show_rr = st.toggle("Зоны RR", value=True, key=key(f"show_rr_{tf_name}"))
                    show_levels = st.toggle("Уровни покуп/продаж", value=True, key=key(f"show_levels_{tf_name}"))
                    show_clusters = st.toggle("Кластеры", value=False, key=key(f"show_clusters_{tf_name}"))
                else:
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        show_tools = st.toggle("Показать графику", value=True, key=key(f"show_tools_{tf_name}"))
                        show_rr = st.toggle("Зоны RR", value=True, key=key(f"show_rr_{tf_name}"))
                    with col_t2:
                        show_levels = st.toggle("Уровни покуп/продаж", value=True, key=key(f"show_levels_{tf_name}"))
                        show_clusters = st.toggle("Кластеры", value=False, key=key(f"show_clusters_{tf_name}"))

            # ============ Данные кластеров ============
            clusters_data = []
            if show_clusters:
                try:
                    h1_for_clusters = fetch_moex_candles(ticker, interval=60, days_back=30)
                    if h1_for_clusters is not None and not h1_for_clusters.empty:
                        clusters_data = find_volume_cluster_zones(h1_for_clusters)
                        if clusters_data:
                            st.caption(
                                f"Аномальных баров H1: **{len(clusters_data)}** · "
                                f"чем ярче зона, тем больше наложений"
                            )
                        else:
                            st.caption("Аномальных баров не обнаружено (нет объёмов > 3× среднего)")
                    else:
                        st.caption("Недостаточно данных H1 для расчёта кластеров")
                except Exception as e:
                    st.warning(f"Не удалось рассчитать кластеры: {e}")

            if active_k and show_tools:
                if active_k == "d1_chan": max_pts = 3
                elif "fib" in active_k: max_pts = 2
                else: max_pts = None

                active_skey = pts_keys[active_k]
                active_undo = f"undo_{active_k}_{ticker}"
                active_redo = f"redo_{active_k}_{ticker}"
                active_deb = f"debounce_{active_k}_{ticker}"

                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    if st.button("Отменить", key=f"undo_btn_{active_k}_{ticker}"):
                        if len(st.session_state[active_undo]) > 0:
                            prev = st.session_state[active_undo].pop()
                            st.session_state[active_redo].append(st.session_state[active_skey].copy())
                            st.session_state[active_skey] = prev
                            st.session_state[active_deb] = 0.0
                            st.rerun()
                with col2:
                    if st.button("Повторить", key=f"redo_btn_{active_k}_{ticker}"):
                        if len(st.session_state[active_redo]) > 0:
                            nxt = st.session_state[active_redo].pop()
                            st.session_state[active_undo].append(st.session_state[active_skey].copy())
                            st.session_state[active_skey] = nxt
                            st.session_state[active_deb] = 0.0
                            st.rerun()
                with col3:
                    if st.button("Очистить", key=f"clear_btn_{active_k}_{ticker}"):
                        st.session_state[active_undo].append(st.session_state[active_skey].copy())
                        st.session_state[active_redo] = []
                        st.session_state[active_skey] = []
                        st.session_state[active_deb] = 0.0
                        st.rerun()

                # ============ Подсказка по направлению для зигзагов ============
                if active_k in ["h1_tend", "m10_zig"]:
                    pts_now = st.session_state.get(active_skey, [])
                    if not isinstance(pts_now, list):
                        pts_now = []
                    if len(pts_now) == 0:
                        st.caption(
                            "🖱️ **Первый клик**: ближе к вершине бара → поставится **High** (максимум), "
                            "ближе к основанию → **Low** (минимум)."
                        )
                    elif len(pts_now) == 1:
                        st.caption(
                            "🖱️ **Второй клик**: кликните **выше** первой точки → максимум, "
                            "**ниже** → минимум."
                        )
                    else:
                        last_y = pts_now[-1][1]
                        prev_y = pts_now[-2][1]
                        next_dir = "**Low** (минимум)" if last_y > prev_y else "**High** (максимум)"
                        st.caption(f"🖱️ Точек: **{len(pts_now)}** · Следующая: {next_dir}")

            df_candles = fetch_moex_candles(ticker, interval=cfg["interval"], days_back=cfg["days_back"])
            if df_candles.empty:
                st.info(f"Нет данных для {tf_name}.")
                continue

            zoom_start = None
            if tf_name == "H1" and len(d1_pts) == 3: zoom_start = d1_pts[1][0]
            elif tf_name == "M10" and len(h1_pts) >= 4: zoom_start = h1_pts[-4][0]

            last_ts = df_candles.index[-1]
            st.caption(f"Последняя свеча: **{last_ts.strftime('%d.%m.%Y %H:%M')}**  ·  Свечей: {len(df_candles)}")

            try:
                d1_fib = st.session_state.get(pts_keys["d1_fib"], [])
                h1_fib = st.session_state.get(pts_keys["h1_fib"], [])
                m10_zig = st.session_state.get(pts_keys["m10_zig"], [])

                if not show_tools:
                    d1_pts_view = None; d1_fib_view = None; h1_tend_view = None; h1_fib_view = None; m10_zig_view = None; h1_levels_view = None
                else:
                    d1_pts_view = d1_pts; d1_fib_view = d1_fib; h1_tend_view = h1_pts; h1_fib_view = h1_fib; m10_zig_view = m10_zig; h1_levels_view = h1_levels

                fig, breakouts = draw_chart(df_candles, title=f"{ticker} — {tf_name}",
                    is_intraday=cfg["is_intraday"], decimals=decimals, is_h1=is_h1, is_m10=is_m10, is_d1=is_d1,
                    ticker=ticker, d1_pts=d1_pts_view, d1_fib_pts=d1_fib_view,
                    h1_tend_pts=h1_tend_view, h1_fib_pts=h1_fib_view, m10_zig_pts=m10_zig_view,
                    h1_levels=h1_levels_view, strategy=strategy, zoom_start_time=zoom_start,
                    show_rr=show_rr, show_levels=show_levels, volume_clusters=clusters_data)

                if fig:
                    if active_k and show_tools:
                        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key=f"plot_{ticker}_{tf_name}")
                        now = time.time()
                        last_debounce = st.session_state.get(active_deb, 0.0)

                        if event and event["selection"]["points"] and (now - last_debounce > 0.5):
                            st.session_state[active_deb] = now
                            pt = event["selection"]["points"][0]
                            clicked_time = pd.to_datetime(pt["x"])
                            clicked_y = pt["y"]

                            df_view = df_candles.copy()
                            idx = df_view.index.get_indexer([clicked_time], method='nearest')[0]
                            bar = df_view.iloc[idx]

                            pts = st.session_state[active_skey]
                            if not isinstance(pts, list): pts = []

                            if active_k == "h1_levels":
                                new_level = {"time": str(bar.name), "open": float(bar['Open']),
                                             "high": float(bar['High']), "low": float(bar['Low']),
                                             "close": float(bar['Close']),
                                             "is_buy": bool(bar['Close'] > bar['Open'])}
                                new_pts = pts + [new_level]
                                st.session_state[active_undo].append(pts.copy())
                                st.session_state[active_redo] = []
                                st.session_state[active_skey] = new_pts
                                st.rerun()
                            else:
                                new_pts = pts.copy()
                                if max_pts is None or len(new_pts) < max_pts:
                                    if active_k in ["h1_tend", "m10_zig"]:
                                        if new_pts and new_pts[-1][0] == bar.name:
                                            # клик по тому же бару — переключаем High ↔ Low
                                            last_y = new_pts[-1][1]
                                            snapped_y = float(bar['Low']) if np.isclose(last_y, bar['High']) else float(bar['High'])
                                            new_pts[-1] = (bar.name, snapped_y)
                                        elif not new_pts:
                                            # первая точка: направление по позиции клика на баре
                                            snapped_y = (
                                                float(bar['High'])
                                                if abs(clicked_y - bar['High']) <= abs(clicked_y - bar['Low'])
                                                else float(bar['Low'])
                                            )
                                            new_pts.append((bar.name, snapped_y))
                                        elif len(new_pts) == 1:
                                            # вторая точка: по позиции клика относительно первой
                                            snapped_y = float(bar['High']) if clicked_y > new_pts[0][1] else float(bar['Low'])
                                            new_pts.append((bar.name, snapped_y))
                                        else:
                                            # последующие: авто-чередование High ↔ Low
                                            last_time, last_y = new_pts[-1]
                                            is_last_high = np.isclose(last_y, df_view.loc[last_time, 'High'])
                                            snapped_y = float(bar['Low']) if is_last_high else float(bar['High'])
                                            new_pts.append((bar.name, snapped_y))
                                    elif active_k == "d1_chan":
                                        if len(new_pts) == 0:
                                            snapped_y = float(bar['High']) if abs(clicked_y - bar['High']) < abs(clicked_y - bar['Low']) else float(bar['Low'])
                                            new_pts.append((bar.name, snapped_y))
                                        elif len(new_pts) == 1:
                                            if clicked_y > new_pts[0][1]:
                                                new_pts[0] = (new_pts[0][0], float(df_view.loc[new_pts[0][0], 'Low']))
                                                snapped_y = float(bar['Low'])
                                            else:
                                                new_pts[0] = (new_pts[0][0], float(df_view.loc[new_pts[0][0], 'High']))
                                                snapped_y = float(bar['High'])
                                            new_pts.append((bar.name, snapped_y))
                                        elif len(new_pts) == 2:
                                            snapped_y = float(bar['High']) if new_pts[1][1] > new_pts[0][1] else float(bar['Low'])
                                            new_pts.append((bar.name, snapped_y))
                                    elif active_k in ["d1_fib", "h1_fib"]:
                                        if len(new_pts) == 0:
                                            snapped_y = float(bar['High']) if abs(clicked_y - bar['High']) < abs(clicked_y - bar['Low']) else float(bar['Low'])
                                            new_pts.append((bar.name, snapped_y))
                                        elif len(new_pts) == 1:
                                            if clicked_y > new_pts[0][1]:
                                                new_pts[0] = (new_pts[0][0], float(df_view.loc[new_pts[0][0], 'Low']))
                                                snapped_y = float(bar['High'])
                                            else:
                                                new_pts[0] = (new_pts[0][0], float(df_view.loc[new_pts[0][0], 'High']))
                                                snapped_y = float(bar['Low'])
                                            new_pts.append((bar.name, snapped_y))
                                    if new_pts != pts:
                                        st.session_state[active_undo].append(pts.copy())
                                        st.session_state[active_redo] = []
                                        st.session_state[active_skey] = new_pts
                                        st.rerun()
                    else:
                        st.plotly_chart(fig, use_container_width=True)

                    if is_h1 and breakouts and show_tools:
                        st.markdown("---")
                        st.markdown("#### Анализ пробоев и откатов H1")
                        if _is_mobile():
                            _render_breakout_cards(breakouts, decimals)
                        else:
                            df_metrics = pd.DataFrame([{
                                "Направление": "Вверх" if b["trend"] == "up" else "Вниз",
                                "Уровень сопр.": b["resistance_price"],
                                "Пик (D)": b["peak_price"],
                                "Δ Пробоя": b["breakout_magnitude"],
                                "Оценка пробоя": {"strong": "Сильный", "weak": "Слабый", "normal": "Нормальный", "base": "Базовый"}.get(b["breakout_verdict"], "-"),
                                "Откат (E)": b["pullback_price"] if b["has_pullback"] else "-",
                                "Ретр. %": f"{b['retracement_pct']:.1f}%" if b["has_pullback"] else "-",
                                "Оценка отката": {"strong": "Сильный", "weak": "Слабый", "normal": "Нормальный"}.get(b["pullback_verdict"], "-") if b["has_pullback"] else "-"
                            } for b in breakouts])
                            st.dataframe(df_metrics, use_container_width=True, hide_index=True, column_config={
                                "Уровень сопр.": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Пик (D)": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Δ Пробоя": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Откат (E)": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                            })
            except Exception as e:
                st.error(f"Не удалось отрисовать график {tf_name}: {e}")

    # ========== КАЛЬКУЛЯТОР СДЕЛКИ ==========
    st.markdown("---")
    st.markdown("## Калькулятор сделки")

    cached_dir = ticker_cache.get("direction", "LONG")
    dir_idx = 0 if cached_dir == "LONG" else (1 if cached_dir == "SHORT" else 0)
    direction = st.radio("Направление торговли", ["LONG", "SHORT"], horizontal=True,
                         index=dir_idx, key=key("dir"))

    h1_trend_dir = None
    if len(h1_pts) >= 2:
        last_move = h1_pts[-1][1] - h1_pts[-2][1]
        if last_move > 0: h1_trend_dir = "up"
        elif last_move < 0: h1_trend_dir = "down"

    if h1_trend_dir is None:
        st.info("Нарисуйте минимум 2 точки H1: Тенденции для определения тренда")
    else:
        is_trend_trade = (h1_trend_dir == "up" and direction == "LONG") or (h1_trend_dir == "down" and direction == "SHORT")
        if is_trend_trade: st.success(f"### Трендовая сделка ({direction})")
        else: st.error(f"### Контртрендовая сделка ({direction})")

    st.markdown("### Точки входа")
    entries_raw_key = key("entries_raw")
    if entries_raw_key not in st.session_state:
        cached_entries = ticker_cache.get("entries", [])
        if cached_entries and isinstance(cached_entries, list):
            try:
                df_cached = pd.DataFrame(cached_entries)
                if "Цена входа" in df_cached.columns and "Контрактов" in df_cached.columns:
                    st.session_state[entries_raw_key] = df_cached[["Цена входа", "Контрактов"]].copy()
                else:
                    st.session_state[entries_raw_key] = pd.DataFrame({"Цена входа": [float(market)], "Контрактов": [1]})
            except Exception:
                st.session_state[entries_raw_key] = pd.DataFrame({"Цена входа": [float(market)], "Контрактов": [1]})
        else:
            st.session_state[entries_raw_key] = pd.DataFrame({"Цена входа": [float(market)], "Контрактов": [1]})

    df_for_editor = st.session_state[entries_raw_key].copy()
    df_for_editor["Цена входа"] = df_for_editor["Цена входа"].fillna(0.0)
    df_for_editor["Контрактов"] = df_for_editor["Контрактов"].fillna(0)
    df_for_editor["Стоимость позиции"] = df_for_editor["Цена входа"] * df_for_editor["Контрактов"] * multiplier
    df_for_editor["ГО в ₽"] = df_for_editor["Контрактов"] * margin_per_contract
    df_for_editor["ГО в %"] = (df_for_editor["ГО в ₽"] / deposit * 100) if deposit > 0 else 0.0

    if _is_mobile():
        editor_view = df_for_editor[["Цена входа", "Контрактов", "Стоимость позиции", "ГО в ₽"]]
        column_config = {
            "Цена входа": st.column_config.NumberColumn(format=f"%.{decimals}f", min_value=0.0),
            "Контрактов": st.column_config.NumberColumn(min_value=0, step=1),
            "Стоимость позиции": st.column_config.NumberColumn(format="%.2f ₽", disabled=True),
            "ГО в ₽": st.column_config.NumberColumn(format="%.2f ₽", disabled=True),
        }
    else:
        editor_view = df_for_editor
        column_config = {
            "Цена входа": st.column_config.NumberColumn(format=f"%.{decimals}f", min_value=0.0),
            "Контрактов": st.column_config.NumberColumn(min_value=0, step=1),
            "Стоимость позиции": st.column_config.NumberColumn(format="%.2f ₽", disabled=True),
            "ГО в ₽": st.column_config.NumberColumn(format="%.2f ₽", disabled=True),
            "ГО в %": st.column_config.NumberColumn(format="%.2f%%", disabled=True),
        }

    edited_entries = st.data_editor(editor_view, num_rows="dynamic", use_container_width=True,
        column_config=column_config, key=key("entries_editor"))
    st.session_state[entries_raw_key] = edited_entries[["Цена входа", "Контрактов"]].copy()

    valid_entries = edited_entries[(edited_entries["Цена входа"] > 0) & (edited_entries["Контрактов"] > 0)]

    if valid_entries.empty:
        st.warning("Добавьте хотя бы одну точку входа (цена > 0 и контрактов > 0)")
    else:
        total_contracts = int(valid_entries["Контрактов"].sum())
        avg_entry = (valid_entries["Цена входа"] * valid_entries["Контрактов"]).sum() / total_contracts
        margin_used = total_contracts * margin_per_contract
        margin_pct = _div(margin_used, deposit) * 100
        position_value = avg_entry * multiplier * total_contracts
        leverage = _div(position_value, margin_used)

        st.markdown("### Уровни SL и TP")
        cached_sl = ticker_cache.get("sl_price", None)
        cached_tp = ticker_cache.get("tp_price", None)
        sl_default = float(cached_sl) if cached_sl is not None else float(market)
        tp_default = float(cached_tp) if cached_tp is not None else float(market)

        if _is_mobile():
            sl_price = st.number_input("SL (Стоп-лосс)", value=sl_default, step=float(step_price), key=key("sl_price"), format=f"%.{decimals}f")
            tp_price = st.number_input("TP (Тейк-профит)", value=tp_default, step=float(step_price), key=key("tp_price"), format=f"%.{decimals}f")
        else:
            col_sl, col_tp = st.columns(2)
            sl_price = col_sl.number_input("SL (Стоп-лосс)", value=sl_default, step=float(step_price), key=key("sl_price"), format=f"%.{decimals}f")
            tp_price = col_tp.number_input("TP (Тейк-профит)", value=tp_default, step=float(step_price), key=key("tp_price"), format=f"%.{decimals}f")

        comm_entry = calc_commission(avg_entry, multiplier, commission)
        comm_sl = calc_commission(sl_price, multiplier, commission)
        comm_tp = calc_commission(tp_price, multiplier, commission)

        total_comm_entry = comm_entry * total_contracts
        total_comm_sl = comm_sl * total_contracts
        total_comm_tp = comm_tp * total_contracts

        if direction == "LONG":
            gross_profit = (tp_price - avg_entry) * multiplier * total_contracts
            gross_loss = (avg_entry - sl_price) * multiplier * total_contracts
        else:
            gross_profit = (avg_entry - tp_price) * multiplier * total_contracts
            gross_loss = (sl_price - avg_entry) * multiplier * total_contracts

        net_profit = gross_profit - total_comm_entry - total_comm_tp
        net_loss = gross_loss + total_comm_entry + total_comm_sl

        actual_rr = _div(abs(net_profit), abs(net_loss)) if net_loss > 0 else 0

        risk_budget = deposit * (risk_pct / 100)
        loss_per_contract = abs(net_loss / total_contracts) if total_contracts > 0 else 1
        max_contracts_by_risk = int(risk_budget / loss_per_contract) if loss_per_contract > 0 else 0

        st.markdown("### Результаты")
        results_items = [
            {"label": "Средний вход", "value": fmt_ru(avg_entry, decimals)},
            {"label": "Всего контрактов", "value": f"{total_contracts}"},
            {"label": "Стоимость позиции", "value": fmt_ru(position_value, 2, " ₽")},
            {"label": "Плечо", "value": fmt_ru(leverage, 1, "x")},
            {"label": "ГО в рублях", "value": fmt_ru(margin_used, 2, " ₽")},
            {"label": "ГО от счета", "value": fmt_ru(margin_pct, 2, "%")},
            {"label": "Комиссия (вход+выход)", "value": fmt_ru(total_comm_entry + total_comm_sl, 2, " ₽")},
            {"label": "Макс. контрактов", "value": f"{max_contracts_by_risk}"},
            {"label": "Чистый убыток (SL)", "value": f"−{fmt_ru(abs(net_loss), 2, ' ₽')}", "color": "#d32f2f"},
            {"label": "Чистая прибыль (TP)", "value": f"+{fmt_ru(abs(net_profit), 2, ' ₽')}", "color": "#2e7d32"},
            {"label": "RR факт", "value": f"1:{fmt_ru(actual_rr, 2)}" if actual_rr > 0 else "—"},
            {"label": "Бюджет риска", "value": fmt_ru(risk_budget, 2, " ₽")},
        ]
        _render_metric_cards(results_items, cols_per_row=4)

        if abs(net_loss) > risk_budget:
            st.error(f"⛔ **Превышен допустимый риск!** Убыток по стопу ({fmt_ru(abs(net_loss), 2, ' ₽')}) больше бюджета риска ({fmt_ru(risk_budget, 2, ' ₽')}). Сократите количество контрактов до {max_contracts_by_risk}.")
        else:
            st.success(f"✅ Риск в норме. Убыток ({fmt_ru(abs(net_loss), 2, ' ₽')}) не превышает бюджет ({fmt_ru(risk_budget, 2, ' ₽')}).")

        if actual_rr > 0:
            if actual_rr >= rr_ratio:
                st.success(f"✅ RR соответствует норме (≥ 1:{fmt_ru(rr_ratio, 2)})")
            else:
                st.warning(f"⚠️ RR ниже нормы (факт 1:{fmt_ru(actual_rr, 2)}, требуется 1:{fmt_ru(rr_ratio, 2)})")

    # ========== СОХРАНЕНИЕ В JSON ==========
    entries_for_save = []
    if entries_raw_key in st.session_state:
        try:
            entries_for_save = st.session_state[entries_raw_key].to_dict("records")
        except Exception:
            entries_for_save = []

    final_state = {
        "d1_manual_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["d1_chan"], [])],
        "d1_fib_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["d1_fib"], [])],
        "h1_tend_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["h1_tend"], [])],
        "h1_fib_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["h1_fib"], [])],
        "m10_zig_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["m10_zig"], [])],
        "h1_levels": st.session_state.get(pts_keys["h1_levels"], []),
        "entries": entries_for_save,
        "sl_price": st.session_state.get(key("sl_price"), None),
        "tp_price": st.session_state.get(key("tp_price"), None),
        "direction": st.session_state.get(key("dir"), None),
    }
    clean_state = {k: v for k, v in final_state.items() if v is not None}
    if clean_state != ticker_cache:
        save_trend_cache(ticker, clean_state)
