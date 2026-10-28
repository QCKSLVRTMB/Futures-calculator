from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from core.calc import get_volume_colors

GREEN  = "#26a69a"
RED    = "#ef5350"
BLUE   = "#1976D2"
ORANGE = "#FB8C00"
PURPLE = "#7B1FA2"
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
    fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color=color, width=width, dash=dash), name=name or "", showlegend=show, hoverinfo="skip"), row=1, col=1)

def _annot(fig, x, y, text, **kwargs):
    fig.add_annotation(x=x, y=y, text=text, row=1, col=1, **kwargs)

def _shape(fig, **kwargs):
    fig.add_shape(row=1, col=1, **kwargs)

def draw_channel(fig, pts, x_right):
    if len(pts) < 3: return
    t_a, y_a = pts[0][:2]; t_b, y_b = pts[1][:2]; t_c, y_c = pts[2][:2]
    x_a, x_c = _ts(t_a), _ts(t_c)
    dt = (x_c - x_a).total_seconds() or 1
    k = (y_c - y_a) / dt
    y_c_ext = y_a + k * (_ts(x_right) - x_a).total_seconds()
    fig.add_shape(type="line", x0=x_a, y0=y_a, x1=x_right, y1=y_c_ext, line=dict(color="blue", width=2), row=1, col=1)
    off = y_b - (y_a + k * (_ts(t_b) - x_a).total_seconds())
    fig.add_shape(type="line", x0=x_a, y0=y_a + off, x1=x_right, y1=y_c_ext + off, line=dict(color="blue", width=2), row=1, col=1)
    fig.add_trace(go.Scatter(x=[x_a, x_right, x_right, x_a], y=[y_a, y_c_ext, y_c_ext + off, y_a + off], fill="toself", fillcolor="rgba(25,118,210,0.08)", line=dict(width=0), hoverinfo="skip", showlegend=False), row=1, col=1)
    fig.add_trace(go.Scatter(x=[x_a, _ts(t_b), x_c], y=[y_a, y_b, y_c], mode='markers+text', marker=dict(color='blue', size=10), text=["A", "B", "C"], textposition="top center", showlegend=False), row=1, col=1)

def draw_fib(fig, pts, x_left, x_right, color, label):
    pts = sort_points(pts)
    if len(pts) < 2: return
    y0, y1 = float(pts[0][1]), float(pts[1][1])
    mid_price = (y0 + y1) / 2
    fig.add_shape(type="line", x0=x_left, y0=mid_price, x1=x_right, y1=mid_price, line=dict(color=color, width=2, dash="dash"), row=1, col=1)
    _annot(fig, x=x_right, y=mid_price, text=label, showarrow=False, xanchor="left", font=dict(color=color, size=10))

def draw_zigzag(fig, pts, color, name):
    pts = sort_points(pts)
    if len(pts) < 2: return
    xs = [_ts(p[0]) for p in pts]; ys = [float(p[1]) for p in pts]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", line=dict(color=color, width=3), marker=dict(size=8, color=color), name=name), row=1, col=1)

def draw_levels(fig, levels, x_left, x_right):
    for y in levels or []:
        _line(fig, x_left, y, x_right, y, "#546E7A", dash="dash", width=1)

def draw_rr_zones(fig, t_c, p_c, t_d, p_d, strategy):
    low, high = min(p_c, p_d), max(p_c, p_d)
    diff = high - low
    if diff <= 0: return
    is_up = p_d > p_c
    color_bottom = "rgba(0, 128, 0, 0.1)" if is_up else "rgba(255, 0, 0, 0.1)"
    color_top = "rgba(255, 0, 0, 0.1)" if is_up else "rgba(0, 128, 0, 0.1)"
    fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=low, y1=low + diff/3, fillcolor=color_bottom, line=dict(width=0), layer="below", row=1, col=1)
    fig.add_shape(type="rect", x0=t_c, x1=t_d, y0=low + 2*diff/3, y1=high, fillcolor=color_top, line=dict(width=0), layer="below", row=1, col=1)

def draw_clusters(fig, clusters, x_left, x_right):
    """Рисует зоны кластеров (профиль объема) — оранжевые, ярче при наложении."""
    for cl in clusters:
        fill_color = f"rgba(251, 140, 0, {cl['opacity']:.2f})"
        fig.add_shape(
            type="rect", x0=x_left, x1=x_right, y0=cl["low"], y1=cl["high"],
            fillcolor=fill_color, line=dict(width=0), layer="below", row=1, col=1
        )

def draw_breakouts(fig, breakouts, decimals):
    drawn_coords = set()
    for brk in breakouts:
        line_color_breakout = "#0d6efd" if brk["trend"] == "up" else "#dc3545"
        breakout_bg = "rgba(13, 110, 253, 0.9)" if brk["trend"] == "up" else "rgba(220, 53, 69, 0.9)"
        
        b_text = f"Пробой: {brk['delta']:.{decimals}f} ({brk['breakout_pct']:.1f}%)<br>Бар: {brk['bars']}<br>Vol: {brk['volume']:,.0f}"
        if (brk['peak_time'], brk['peak_price']) not in drawn_coords:
            fig.add_annotation(x=brk['peak_time'], y=brk['peak_price'], text=b_text, showarrow=True, arrowhead=2, ax=40, ay=-40, bgcolor=breakout_bg, font=dict(color="white", size=10), bordercolor="black", row=1, col=1)
            drawn_coords.add((brk['peak_time'], brk['peak_price']))
            
        fig.add_shape(type="line", x0=brk['resistance_time'], y0=brk['resistance_price'], x1=brk['breakout_time'], y1=brk['resistance_price'], line=dict(color=line_color_breakout, width=2), row=1, col=1)
        fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['resistance_price'], x1=brk['breakout_time'], y1=brk['peak_price'], line=dict(color=line_color_breakout, width=2, dash="dot"), row=1, col=1)
        fig.add_shape(type="line", x0=brk['breakout_time'], y0=brk['peak_price'], x1=brk['peak_time'], y1=brk['peak_price'], line=dict(color=line_color_breakout, width=2, dash="dot"), row=1, col=1)
        
        mid_y = brk['resistance_price'] + (brk['peak_price'] - brk['resistance_price']) / 2
        fig.add_annotation(x=brk['breakout_time'], y=mid_y, text=f"Δ: {brk['delta']:.{decimals}f}", showarrow=False, xanchor="right", xshift=-5, font=dict(color=line_color_breakout, size=11, weight="bold"), row=1, col=1)
        
        if brk.get('has_pullback') and brk.get('e_time') is not None:
            p_verdict = brk['pullback_verdict']
            pullback_bg = "rgba(
