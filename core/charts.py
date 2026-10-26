from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core.config import FIB_LEVELS

# Цвета разметки (подобраны так, чтобы одинаково хорошо читались на белом фоне)
GREEN  = "#26a69a"   # TP / рост
RED    = "#ef5350"   # SL / падение
BLUE   = "#1976D2"   # канал
ORANGE = "#FB8C00"   # зигзаг / тенденция
PURPLE = "#7B1FA2"   # фибо

# Цвета для OHLC-баров — все чёрные (как было в старом проекте)
BAR_LINE_COLOR = "#000000"

def _ts(x) -> pd.Timestamp: return pd.to_datetime(x)
def sort_points(points: list) -> list: return sorted((p for p in points if p), key=lambda p: _ts(p[0]))

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

def _line(fig, x0, y0, x1, y1, color, dash=None, width=2, name=None, show=False):
    fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                             line=dict(color=color, width=width, dash=dash),
                             name=name or "", showlegend=show, hoverinfo="skip"))

def draw_channel(fig, pts, x_right):
    pts = sort_points(pts)
    if len(pts) < 2: return
    (t0, y0), (t1, y1) = pts[0][:2], pts[1][:2]
    x0, x1 = _ts(t0), _ts(t1)
    dt = (x1 - x0).total_seconds() or 1
    k = (y1 - y0) / dt
    y_end = y0 + k * (_ts(x_right) - x0).total_seconds()
    _line(fig, x0, y0, x_right, y_end, BLUE, name="Канал")
    if len(pts) >= 3:
        t2, y2 = pts[2][:2]
        off = y2 - (y0 + k * (_ts(t2) - x0).total_seconds())
        _line(fig, x0, y0 + off, x_right, y_end + off, BLUE, dash="dot")
        fig.add_trace(go.Scatter(x=[x0, x_right, x_right, x0],
                                 y=[y0, y_end, y_end + off, y0 + off],
                                 fill="toself", fillcolor="rgba(25,118,210,0.08)",
                                 line=dict(width=0), hoverinfo="skip", showlegend=False))

def draw_fib(fig, pts, x_left, x_right):
    pts = sort_points(pts)
    if len(pts) < 2: return
    y0, y1 = float(pts[0][1]), float(pts[1][1])
    span = y1 - y0
    for lv in FIB_LEVELS:
        y = y0 + span * lv
        _line(fig, x_left, y, x_right, y, PURPLE,
              dash="dot" if lv not in (0.0, 1.0) else None, width=1)
        fig.add_annotation(x=x_right, y=y,
                           text=f"{lv:.3f} · {y:,.2f}".replace(",", " "),
                           showarrow=False, xanchor="left",
                           font=dict(size=9, color=PURPLE))

def draw_zigzag(fig, pts):
    pts = sort_points(pts)
    if len(pts) < 2: return
    xs = [_ts(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers+text",
                             line=dict(color=ORANGE, width=2),
                             marker=dict(size=8, color=ORANGE),
                             text=[""] + [f"{(ys[i] - ys[i-1]):+,.2f}".replace(",", " ") for i in range(1, len(ys))],
                             textposition="top center",
                             textfont=dict(size=9, color=ORANGE),
                             name="Зигзаг", hoverinfo="y"))

def draw_levels(fig, levels, x_left, x_right):
    for y in levels or []:
        _line(fig, x_left, y, x_right, y, "#546E7A", dash="dash", width=1)
        fig.add_annotation(x=x_left, y=y,
                           text=f"{y:,.2f}".replace(",", " "),
                           showarrow=False, xanchor="right",
                           font=dict(size=9, color="#546E7A"))

def draw_deal(fig, plan, x_left, x_right):
    entry, sl, tp = plan.get("entry"), plan.get("sl"), plan.get("tp")
    if not entry: return
    _line(fig, x_left, entry, x_right, entry, "#37474F", dash="dash", width=1.5)
    if sl:
        fig.add_shape(type="rect", x0=x_left, x1=x_right,
                      y0=min(entry, sl), y1=max(entry, sl),
                      fillcolor="rgba(239,83,80,0.13)", line_width=0, layer="below")
        _line(fig, x_left, sl, x_right, sl, RED, dash="dash")
    if tp:
        fig.add_shape(type="rect", x0=x_left, x1=x_right,
                      y0=min(entry, tp), y1=max(entry, tp),
                      fillcolor="rgba(38,166,154,0.13)", line_width=0, layer="below")
        _line(fig, x_left, tp, x_right, tp, GREEN, dash="dash")

def build_figure(df: pd.DataFrame, *, tf: str, title: str = "",
                 mobile: bool = False, hit_layer: bool = True) -> go.Figure:
    fig = go.Figure()

    # ===== ЧЁРНЫЕ OHLC-БАРЫ (вместо свечей) =====
    fig.add_trace(go.Ohlc(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=BAR_LINE_COLOR, decreasing_line_color=BAR_LINE_COLOR,
        increasing_line_width=1.5, decreasing_line_width=1.5,
        name="OHLC", showlegend=False,
    ))

    if hit_layer:
        x = list(df.index) * 3
        y = list(df["High"]) + list(df["Low"]) + list(df["Close"])
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="markers", name="hit",
            marker=dict(size=22 if mobile else 12, color="rgba(0,0,0,0.001)"),
            hovertemplate="%{x|%d.%m %H:%M}<br><b>%{y:,.2f}</b><extra></extra>",
            showlegend=False,
        ))

    breaks = [dict(bounds=["sat", "mon"])]
    if tf != "D1":
        breaks.append(dict(bounds=[23.9, 6.9], pattern="hour"))

    # Цвета сетки и осей подобраны под белый фон
    fig.update_xaxes(rangeslider_visible=False, rangebreaks=breaks,
                     showgrid=True, gridcolor="rgba(0,0,0,0.08)",
                     zeroline=False, linecolor="rgba(0,0,0,0.15)")
    fig.update_yaxes(side="right", showgrid=True, gridcolor="rgba(0,0,0,0.08)",
                     zeroline=False, linecolor="rgba(0,0,0,0.15)")

    fig.update_layout(
        title=dict(text=title, font=dict(size=13)) if title else None,
        height=380 if mobile else 560,
        margin=dict(l=4, r=56, t=28 if title else 8, b=4),
        dragmode="pan", hovermode="x unified",
        uirevision="keep",
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        showlegend=False,
        font=dict(size=10 if mobile else 12, color="#0E1117"),
    )
    return fig

PLOT_CONFIG = {"scrollZoom": True, "displaylogo": False,
               "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
               "doubleClick": "reset"}

def capture_click(chart_key: str) -> tuple[str, float] | None:
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
