from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Цвета разметки (Light theme)
GREEN  = "#26a69a"
RED    = "#ef5350"
BLUE   = "#1976D2"
ORANGE = "#FB8C00"
PURPLE = "#7B1FA2"
BAR_LINE_COLOR = "#000000"


def _ts(x) -> pd.Timestamp: 
    return pd.to_datetime(x)

def sort_points(points: list) -> list: 
    return sorted((p for p in points if p), key=lambda p: _ts(p[0]))


def auto_zigzag(df: pd.DataFrame, depth_pct: float = 1.5) -> list:
    if df.empty: return []
    highs, lows, idx = df["High"].to_numpy(), df["Low"].to_numpy(), df.index
    pts, trend = [], 0
    piv_i, piv_v = 0, lows[0]
    for i in range(1, len(df)):
        if trend >= 0 and highs[i] > piv_v: piv_i, piv_v, trend = i, highs[i], 1
        elif trend <= 0 and lows[i] < piv_v: piv_i, piv_v, trend = i, lows[i], -1
        thr = piv_v * depth_pct / 100.0
        if trend == 1 and lows[i] < piv_v - thr:
            pts.append([str(idx[piv_i]), float(piv_v)]); piv_i, piv_v, trend = i, lows[i], -1
        elif trend == -1 and highs[i] > piv_v + thr:
            pts.append([str(idx[piv_i]), float(piv_v)]); piv_i, piv_v, trend = i, highs[i], 1
    pts.append([str(idx[piv_i]), float(piv_v)])
    return pts


# ============ ОБЕРТКИ ДЛЯ row=1 ============
def _line(fig, x0, y0, x1, y1, color, dash=None, width=2, name=None, show=False):
    fig.add_trace(
        go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                   line=dict(color=color, width=width, dash=dash),
                   name=name or "", showlegend=show, hoverinfo="skip"),
        row=1, col=1
    )

def _annot(fig, x, y, text, **kwargs):
    fig.add_annotation(x=x, y=y, text=text, row=1, col=1, **kwargs)

def _shape(fig, **kwargs):
    fig.add_shape(row=1, col=1, **kwargs)


# ============ ИНСТРУМЕНТЫ ============
def draw_channel(fig, pts, x_right):
    """
    Рисует канал по 3 точкам: A (левая), B (средняя), C (правая).
    Точки всегда идут в хронологическом порядке (слева направо).
    """
    if len(pts) < 3: return

    t_a, y_a = pts[0][:2]
    t_b, y_b = pts[1][:2]
    t_c, y_c = pts[2][:2]

    x_a, x_c = _ts(t_a), _ts(t_c)

    # Базовая линия (через A и C)
    dt = (x_c - x_a).total_seconds() or 1
    k = (y_c - y_a) / dt

    # Продлеваем вправо
    y_c_ext = y_a + k * (_ts(x_right) - x_a).total_seconds()

    fig.add_shape(type="line", x0=x_a, y0=y_a, x1=x_right, y1=y_c_ext,
                  line=dict(color="blue", width=2), row=1, col=1)

    # Параллельная линия (через B)
    off = y_b - (y_a + k * (_ts(t_b) - x_a).total_seconds())
    fig.add_shape(type="line", x0=x_a, y0=y_a + off, x1=x_right, y1=y_c_ext + off,
                  line=dict(color="blue", width=2), row=1, col=1)

    # Заливка между линиями
    fig.add_trace(
        go.Scatter(x=[x_a, x_right, x_right, x_a],
                   y=[y_a, y_c_ext, y_c_ext + off, y_a + off],
                   fill="toself", fillcolor="rgba(25,118,210,0.08)",
                   line=dict(width=0), hoverinfo="skip", showlegend=False),
        row=1, col=1
    )

    # Маркеры A, B, C
    fig.add_trace(go.Scatter(
        x=[x_a, _ts(t_b), x_c], 
        y=[y_a, y_b, y_c], 
        mode='markers+text', 
        marker=dict(color='blue', size=10), 
        text=["A", "B", "C"], 
        textposition="top center", 
        showlegend=False
    ), row=1, col=1)


def draw_fib(fig, pts, x_left, x_right, color, label):
    pts = sort_points(pts)
    if len(pts) < 2: return
    y0, y1 = float(pts[0][1]), float(pts[1][1])
    mid_price = (y0 + y1) / 2
    fig.add_shape(type="line", x0=x_left, y0=mid_price, x1=x_right, y1=mid_price,
                  line=dict(color=color, width=2, dash="dash"), row=1, col=1)
    _annot(fig, x=x_right, y=mid_price, text=label,
           showarrow=False, xanchor="left", font=dict(color=color, size=10))


def draw_zigzag(fig, pts, color, name):
    pts = sort_points(pts)
    if len(pts) < 2: return
    xs = [_ts(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    fig.add_trace(
        go.Scatter(x=xs, y=ys, mode="lines+markers",
                   line=dict(color=color, width=3),
                   marker=dict(size=8, color=color), name=name),
        row=1, col=1
    )


def draw_levels(fig, levels, x_left, x_right):
    for y in levels or []:
        _line(fig, x_left, y, x_right, y, "#546E7A", dash="dash", width=1)


def draw_rr_zones(fig, pts, strategy):
    if len(pts) < 2: return
    if strategy == "Зигзаг тенденции":
        t_c, p_c = _ts(pts[-2][0]), pts[-2][1]
        t_d, p_d = _ts(pts[-1][0]), pts[-1][1]
    else:
        t_c, p_c = _ts(pts[0][0]), pts[0][1]
        t_d, p_d = _ts(pts[-1][0]), pts[-1][1]

    low, high = min(p_c, p_d), max(p_c, p_d)
    diff = high - low
    if diff <= 0: return
    is_up = p_d > p_c
    color_bottom = "rgba(0, 128, 0, 0.1)" if is_up else "rgba(255, 0, 0, 0.1)"
    color_top = "rgba(255, 0, 0, 0.1)" if is_up else "rgba(0, 128, 0, 0.1)"

    fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=low, y1=low + diff/3,
                  fillcolor=color_bottom, line=dict(width=0), layer="below", row=1, col=1)
    fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=low + 2*diff/3, y1=high,
                  fillcolor=color_top, line=dict(width=0), layer="below", row=1, col=1)


def draw_clusters(fig, clusters, x_left, x_right):
    for cl in clusters:
        fig.add_shape(type="rect", x0=x_left, x1=x_right,
                      y0=cl["low"], y1=cl["high"],
                      fillcolor="rgba(255, 140, 0, 0.15)",
                      line=dict(width=0), layer="below", row=1, col=1)


def draw_breakouts(fig, breakouts, decimals):
    drawn_coords = set()
    for brk in breakouts:
        line_color_breakout = "#0d6efd" if brk["trend"] == "up" else "#dc3545"
        line_color_pullback = "#fd7e14"
        breakout_bg = "rgba(13, 110, 253, 0.9)" if brk["trend"] == "up" else "rgba(220, 53, 69, 0.9)"
        pullback_bg = "rgba(253, 126, 20, 0.9)"

        b_text = f"Δ: {brk['delta']:.{decimals}f}<br>Бар: {brk['bars']}<br>Vol: {brk['volume']:,.0f}"
        p_text = f"Δ: {brk['retr_delta']:.{decimals}f}<br>Бар: {brk['retr_bars']}<br>Vol: {brk['retr_volume']:,.0f}"

        if (brk['peak_time'], brk['peak_price']) not in drawn_coords:
            fig.add_annotation(x=brk['peak_time'], y=brk['peak_price'], text=b_text,
                               showarrow=True, arrowhead=2, ax=40, ay=-40,
                               bgcolor=breakout_bg, font=dict(color="white", size=10),
                               bordercolor="black", row=1, col=1)
            drawn_coords.add((brk['peak_time'], brk['peak_price']))

        fig.add_shape(type="line", x0=brk['resistance_time'], y0=brk['resistance_price'],
                      x1=brk['breakout_time'], y1=brk['resistance_price'],
                      line=dict(color=line_color_breakout, width=2), row=1, col=1)
        fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['resistance_price'],
                      x1=brk['breakout_time'], y1=brk['peak_price'],
                      line=dict(color=line_color_breakout, width=2, dash="dot"), row=1, col=1)
        fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['peak_price'],
                      x1=brk['peak_time'], y1=brk['peak_price'],
                      line=dict(color=line_color_breakout, width=2, dash="dot"), row=1, col=1)

        mid_y = brk['resistance_price'] + (brk['peak_price'] - brk['resistance_price']) / 2
        fig.add_annotation(x=brk['breakout_time'], y=mid_y,
                           text=f"Δ: {brk['delta']:.{decimals}f}",
                           showarrow=False, xanchor="right", xshift=-5,
                           font=dict(color=line_color_breakout, size=11, weight="bold"), row=1, col=1)

        if brk.get('pullback_time') is not None:
            if (brk['pullback_time'], brk['pullback_price']) not in drawn_coords:
                fig.add_annotation(x=brk['pullback_time'], y=brk['pullback_price'], text=p_text,
                                   showarrow=True, arrowhead=2, ax=0, ay=40,
                                   bgcolor=pullback_bg, font=dict(color="white", size=10),
                                   bordercolor="black", row=1, col=1)
                drawn_coords.add((brk['pullback_time'], brk['pullback_price']))
            fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['resistance_price'],
                          x1=brk['breakout_time'], y1=brk['pullback_price'],
                          line=dict(color=line_color_pullback, width=2, dash="dot"), row=1, col=1)
            fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['pullback_price'],
                          x1=brk['pullback_time'], y1=brk['pullback_price'],
                          line=dict(color=line_color_pullback, width=2), row=1, col=1)


def draw_deal(fig, plan, x_left, x_right):
    entry, sl, tp = plan.get("entry"), plan.get("sl"), plan.get("tp")
    if not entry: return
    _line(fig, x_left, entry, x_right, entry, "#37474F", dash="dash", width=1.5)
    if sl: _line(fig, x_left, sl, x_right, sl, RED, dash="dash")
    if tp: _line(fig, x_left, tp, x_right, tp, GREEN, dash="dash")


def _volume_colors(df, tf_name):
    is_d1, is_h1, is_m10 = (tf_name == "D1", tf_name == "H1", tf_name == "M10")
    volumes = df["Volume"].values
    times = df.index
    colors = ["gray"] * len(df)

    for i in range(2, len(df)):
        if volumes[i] > volumes[i-1] and volumes[i] > volumes[i-2]:
            colors[i] = "black"

    if is_h1:
        for i in range(len(df)):
            if times[i].hour == 10 and times[i].minute == 0:
                prev = [volumes[j] for j in range(i-1, -1, -1) if times[j].hour == 10 and times[j].minute == 0][:2]
                if len(prev) == 2 and volumes[i] > prev[0] and volumes[i] > prev[1]:
                    colors[i] = "black"

    anomaly = None
    if is_m10: anomaly = "red"
    elif is_h1: anomaly = "green"
    elif is_d1: anomaly = "blue"

    if anomaly:
        avg = pd.Series(volumes).rolling(20, min_periods=5).mean().shift(1)
        for i in range(len(volumes)):
            if pd.notna(avg.iloc[i]) and avg.iloc[i] > 0 and volumes[i] > avg.iloc[i] * 3.0:
                colors[i] = anomaly

    return colors


def build_figure(df, *, tf_name, title, decimals, mobile):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.8, 0.2])

    fig.add_trace(go.Ohlc(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=BAR_LINE_COLOR, decreasing_line_color=BAR_LINE_COLOR,
        increasing_line_width=1.5, decreasing_line_width=1.5,
        name="Рынок"
    ), row=1, col=1)

    if "Volume" in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"],
            marker_color=_volume_colors(df, tf_name),
            name="Объем"
        ), row=2, col=1)

    breaks = [dict(bounds=["sat", "mon"])]
    if tf_name != "D1":
        breaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    fig.update_xaxes(rangeslider_visible=False, rangebreaks=breaks, showgrid=True,
                     gridcolor="lightgray", row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, rangebreaks=breaks, showgrid=True,
                     gridcolor="lightgray", row=2, col=1)
    fig.update_yaxes(side="right", tickformat=f".{decimals}f", showgrid=True,
                     gridcolor="lightgray", row=1, col=1)
    fig.update_yaxes(side="right", showgrid=True, gridcolor="lightgray", row=2, col=1)

    fig.update_layout(
        title=title, height=450 if mobile else 700,
        margin=dict(l=10, r=10, t=50, b=50),
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False, hovermode="closest", uirevision="keep"
    )
    return fig


PLOT_CONFIG = {
    "scrollZoom": True, "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
    "doubleClick": "reset"
}


def capture_click(chart_key: str) -> tuple[str, float] | None:
    """Перехватывает клик по графику (защита от дублей)."""
    ev = st.session_state.get(chart_key)
    if not isinstance(ev, dict): return None
    pts = (ev.get("selection") or {}).get("points") or []
    if not pts: return None
    p = pts[-1]
    x, y = p.get("x"), p.get("y")
    if x is None or y is None: return None
    sig = f"{x}|{y}"
    store = st.session_state.setdefault("_click_sig", {})
    if store.get(chart_key) == sig: return None
    store[chart_key] = sig
    return str(x), float(y)
