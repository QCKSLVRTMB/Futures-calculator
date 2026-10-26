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
    "M10": {"interval": 10, "days_back": 30,  "is_intraday": True}, # Увеличили days_back
}

def _div(a, b, default=0.0):
    return a / b if b else default

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
            retr_delta = b_price - c_price
            df_pullback = df.loc[b_time:c_time]
            retr_bars = len(df_pullback)
            retr_vol = df_pullback['Volume'].sum()
            
            breakouts.append({
                "trend": "up",
                "resistance_time": b_time,
                "resistance_price": b_price,
                "pullback_time": c_time,
                "pullback_price": c_price,
                "peak_time": d_time,
                "peak_price": d_price,
                "breakout_time": brk_time,
                "delta": d_price - b_price,
                "bars": bars,
                "volume": vol,
                "retr_delta": retr_delta,
                "retr_bars": retr_bars,
                "retr_volume": retr_vol
            })
        elif a_price > b_price and b_price < c_price < a_price and d_price < b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=False)
            retr_delta = c_price - b_price
            df_pullback = df.loc[b_time:c_time]
            retr_bars = len(df_pullback)
            retr_vol = df_pullback['Volume'].sum()
            
            breakouts.append({
                "trend": "down",
                "resistance_time": b_time,
                "resistance_price": b_price,
                "pullback_time": c_time,
                "pullback_price": c_price,
                "peak_time": d_time,
                "peak_price": d_price,
                "breakout_time": brk_time,
                "delta": b_price - d_price,
                "bars": bars,
                "volume": vol,
                "retr_delta": retr_delta,
                "retr_bars": retr_bars,
                "retr_volume": retr_vol
            })
            
    return breakouts

def draw_chart(df_chart, title="", is_intraday=False, decimals=0, is_h1=False, is_m10=False, is_d1=False, ticker="", d1_pts=None, d1_fib_pts=None, h1_tend_pts=None, h1_fib_pts=None, m10_zig_pts=None, strategy="Зигзаг тенденции", zoom_start_time=None):
    if df_chart.empty:
        return None, []

    # --- УМНЫЙ ЗУМ ---
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

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.8, 0.2])

    fig.add_trace(go.Ohlc(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
        low=df_chart['Low'], close=df_chart['Close'],
        increasing_line_color='black', decreasing_line_color='black',
        increasing_line_width=1.5, decreasing_line_width=1.5,
        name='Рынок'
    ), row=1, col=1)

    # 1. Канал D1 (по 3 точкам)
    if d1_pts and len(d1_pts) == 3:
        t1, p1 = d1_pts[0]
        t2, p2 = d1_pts[1]
        t3, p3 = d1_pts[2]
        
        x1_ts = pd.to_datetime(t1)
        x2_ts = pd.to_datetime(t2)
        x3_ts = pd.to_datetime(t3)
        
        time1 = x1_ts.timestamp()
        time2 = x2_ts.timestamp()
        time3 = x3_ts.timestamp()
        
        dt_12 = time2 - time1 if time2 != time1 else 1
        slope_time = (p2 - p1) / dt_12
        
        if is_intraday:
            time_buffer = pd.Timedelta(hours=12) if is_h1 else pd.Timedelta(hours=2)
        else:
            time_buffer = pd.Timedelta(days=10)
            
        dt_end = df_chart.index[-1] + time_buffer
        time_end = dt_end.timestamp()
        
        y_ray1_end = slope_time * (time_end - time1) + p1
        y_ray2_end = slope_time * (time_end - time3) + p3

        fig.add_shape(
            type="line", x0=x1_ts, y0=p1, x1=dt_end, y1=y_ray1_end,
            line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1
        )
        fig.add_shape(
            type="line", x0=x3_ts, y0=p3, x1=dt_end, y1=y_ray2_end,
            line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1
        )
        
        fig.add_trace(go.Scatter(
            x=[t1, t2, t3], y=[p1, p2, p3],
            mode='markers', marker=dict(color='blue', size=10),
            name='Точки канала D1', showlegend=False
        ), row=1, col=1)

    # 2. Fib 0.5 D1
    if d1_fib_pts and len(d1_fib_pts) == 2:
        t1, p1 = d1_fib_pts[0]
        t2, p2 = d1_fib_pts[1]
        mid_price = (p1 + p2) / 2
        
        x1_ts = pd.to_datetime(t1)
        dt_end = df_chart.index[-1] + (pd.Timedelta(hours=12) if is_intraday else pd.Timedelta(days=10))
        
        fig.add_shape(
            type="line", x0=x1_ts, y0=mid_price, x1=dt_end, y1=mid_price,
            line=dict(color="blue", width=2, dash="dash"), xref="x", yref="y", row=1, col=1
        )
        fig.add_annotation(
            x=dt_end, y=mid_price, text="0.5 D1",
            showarrow=False, xanchor="left", font=dict(color="blue", size=10),
            row=1, col=1
        )

    # 3. Fib 0.5 H1
    if h1_fib_pts and len(h1_fib_pts) == 2:
        t1, p1 = h1_fib_pts[0]
        t2, p2 = h1_fib_pts[1]
        mid_price = (p1 + p2) / 2
        
        x1_ts = pd.to_datetime(t1)
        dt_end = df_chart.index[-1] + (pd.Timedelta(hours=12) if is_intraday else pd.Timedelta(days=10))
        
        fig.add_shape(
            type="line", x0=x1_ts, y0=mid_price, x1=dt_end, y1=mid_price,
            line=dict(color="green", width=2, dash="dash"), xref="x", yref="y", row=1, col=1
        )
        fig.add_annotation(
            x=dt_end, y=mid_price, text="0.5 H1",
            showarrow=False, xanchor="left", font=dict(color="green", size=10),
            row=1, col=1
        )

    # 4. H1 Тенденция (Зеленая)
    if h1_tend_pts:
        mx = [p[0] for p in h1_tend_pts]
        my = [p[1] for p in h1_tend_pts]
        fig.add_trace(go.Scatter(
            x=mx, y=my,
            mode='lines+markers',
            marker=dict(size=8, color='green', symbol='circle'),
            line=dict(color='green', width=3),
            name='Тенденция (H1)'
        ), row=1, col=1)

    # 5. M10 Зигзаг (Красный)
    if (is_h1 or is_m10) and m10_zig_pts:
        mx = [p[0] for p in m10_zig_pts]
        my = [p[1] for p in m10_zig_pts]
        fig.add_trace(go.Scatter(
            x=mx, y=my,
            mode='lines+markers',
            marker=dict(size=8, color='red', symbol='circle'),
            line=dict(color='red', width=3),
            name='Зигзаг (M10)'
        ), row=1, col=1)

        # Отрисовка зон RR по M10 Зигзагу
        if len(m10_zig_pts) >= 2:
            if strategy == "Зигзаг тенденции":
                t_c, p_c = m10_zig_pts[-2]
                t_d, p_d = m10_zig_pts[-1]
            else:
                t_c, p_c = m10_zig_pts[0]
                t_d, p_d = m10_zig_pts[-1]

            low = min(p_c, p_d)
            high = max(p_c, p_d)
            diff = high - low
            
            if diff > 0:
                y1_start, y1_end = low, low + diff/3
                y3_start, y3_end = low + 2*diff/3, high
                
                if p_d > p_c:
                    color_bottom = "rgba(0, 128, 0, 0.1)"
                    color_top = "rgba(255, 0, 0, 0.1)"
                else:
                    color_bottom = "rgba(255, 0, 0, 0.1)"
                    color_top = "rgba(0, 128, 0, 0.1)"

                fig.add_shape(
                    type="rect", x0=t_c, x1=t_d, y0=y1_start, y1=y1_end,
                    fillcolor=color_bottom, line=dict(width=0),
                    layer="below", xref="x", yref="y", row=1, col=1
                )
                
                fig.add_shape(
                    type="rect", x0=t_c, x1=t_d, y0=y3_start, y1=y3_end,
                    fillcolor=color_top, line=dict(width=0),
                    layer="below", xref="x", yref="y", row=1, col=1
                )

    # 6. Пробои и откаты по H1 Тенденции
    breakouts = []
    if is_h1 and h1_tend_pts:
        breakouts = analyze_manual_zigzag(h1_tend_pts, df_chart)
        
        drawn_coords = set()
        
        for brk in breakouts:
            breakout_bg = "rgba(13, 110, 253, 0.9)"
            pullback_bg = "rgba(253, 126, 20, 0.9)"
            line_color_breakout = "#0d6efd"
            line_color_pullback = "#fd7e14"
            
            breakout_text = (
                f"Δ: {brk['delta']:.{decimals}f}<br>"
                f"Бар: {brk['bars']}<br>"
                f"Vol: {brk['volume']:,.0f}"
            )
            
            peak_key = (brk['peak_time'], brk['peak_price'])
            if peak_key not in drawn_coords:
                fig.add_annotation(
                    x=brk['peak_time'], y=brk['peak_price'],
                    text=breakout_text,
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_breakout,
                    ax=40, ay=-40,
                    bgcolor=breakout_bg, 
                    font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3,
                    row=1, col=1
                )
                drawn_coords.add(peak_key)
            
            res_key = (brk['resistance_time'], brk['resistance_price'])
            if res_key not in drawn_coords:
                fig.add_annotation(
                    x=brk['resistance_time'], y=brk['resistance_price'],
                    text=breakout_text,
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_breakout,
                    ax=-40, ay=40,
                    bgcolor=breakout_bg, 
                    font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3,
                    row=1, col=1
                )
                drawn_coords.add(res_key)

            fig.add_shape(
                type="line", x0=brk['resistance_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['resistance_price'],
                line=dict(color=line_color_breakout, width=2), 
                xref="x", yref="y", row=1, col=1
            )
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['peak_price'], 
                x1=brk['peak_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )

            mid_y_breakout = brk['resistance_price'] + (brk['peak_price'] - brk['resistance_price']) / 2
            fig.add_annotation(
                x=brk['breakout_time'], y=mid_y_breakout,
                text=f"Δ: {brk['delta']:.{decimals}f}",
                showarrow=False, xanchor="right", xshift=-5,
                font=dict(color=line_color_breakout, size=11, weight="bold"),
                row=1, col=1
            )

            pullback_text = (
                f"Δ: {brk['retr_delta']:.{decimals}f}<br>"
                f"Бар: {brk['retr_bars']}<br>"
                f"Vol: {brk['retr_volume']:,.0f}"
            )
            
            pull_key = (brk['pullback_time'], brk['pullback_price'])
            if pull_key not in drawn_coords:
                fig.add_annotation(
                    x=brk['pullback_time'], y=brk['pullback_price'],
                    text=pullback_text,
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor=line_color_pullback,
                    ax=0, ay=40,
                    bgcolor=pullback_bg, 
                    font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3,
                    row=1, col=1
                )
                drawn_coords.add(pull_key)

            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['pullback_price'],
                line=dict(color=line_color_pullback, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['pullback_price'], 
                x1=brk['pullback_time'], y1=brk['pullback_price'],
                line=dict(color=line_color_pullback, width=2), 
                xref="x", yref="y", row=1, col=1
            )

            mid_y_pullback = brk['pullback_price'] + (brk['resistance_price'] - brk['pullback_price']) / 2
            fig.add_annotation(
                x=brk['breakout_time'], y=mid_y_pullback,
                text=f"Δ: {brk['retr_delta']:.{decimals}f}",
                showarrow=False, xanchor="right", xshift=-5,
                font=dict(color=line_color_pullback, size=11, weight="bold"),
                row=1, col=1
            )

    # Объемы
    if 'Volume' in df_chart.columns:
        colors = ['gray'] * len(df_chart)
        volumes = df_chart['Volume'].values
        times = df_chart.index

        for i in range(2, len(df_chart)):
            if volumes[i] > volumes[i-1] and volumes[i] > volumes[i-2]:
                colors[i] = 'black'

        if is_h1:
            for i in range(len(df_chart)):
                if times[i].hour == 10 and times[i].minute == 0:
                    prev_10s = []
                    for j in range(i-1, -1, -1):
                        if times[j].hour == 10 and times[j].minute == 0:
                            prev_10s.append(volumes[j])
                            if len(prev_10s) == 2:
                                break
                    if len(prev_10s) == 2:
                        if volumes[i] > prev_10s[0] and volumes[i] > prev_10s[1]:
                            colors[i] = 'black'

        if is_m10 or is_h1 or is_d1:
            vol_series = pd.Series(volumes)
            rolling_avg = vol_series.rolling(window=20, min_periods=5).mean().shift(1)
            
            anomaly_color = None
            if is_m10: anomaly_color = 'red'
            elif is_h1: anomaly_color = 'green'
            elif is_d1: anomaly_color = 'blue'

            if anomaly_color:
                for i in range(len(volumes)):
                    if pd.notna(rolling_avg.iloc[i]) and rolling_avg.iloc[i] > 0:
                        if volumes[i] > rolling_avg.iloc[i] * 3.0:
                            colors[i] = anomaly_color

        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
                             marker_color=colors, name='Объем'), row=2, col=1)

    fig.update_layout(
        title=title, height=700,
        margin=dict(l=10, r=10, t=50, b=50),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis_rangeslider_visible=False, showlegend=False,
        hovermode='closest', spikedistance=-1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday:
        rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    if len(df_chart) > 1:
        if is_intraday:
            time_buffer = pd.Timedelta(hours=12) if is_h1 else pd.Timedelta(hours=2)
            
            first_day = df_chart.index[0].normalize()
            snap_start = first_day + pd.Timedelta(hours=7)
            if snap_start > df_chart.index[0]:
                snap_start -= pd.Timedelta(days=1)
                
            x_range = [snap_start, df_chart.index[-1] + time_buffer]
        else:
            time_buffer = pd.Timedelta(days=10)
            x_range = [df_chart.index[0] - pd.Timedelta(days=1), df_chart.index[-1] + time_buffer]
    else:
        x_range = None

    y_min = df_chart['Low'].min()
    y_max = df_chart['High'].max()

    y_padding = (y_max - y_min) * 0.10
    y_range = [y_min - y_padding, y_max + y_padding]

    fig.update_xaxes(
        showgrid=True, gridcolor='lightgray', rangebreaks=rangebreaks, range=x_range,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
    )
    
    fig.update_yaxes(
        showgrid=True, gridcolor='lightgray', side='right', tickformat=tick_fmt,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
        range=y_range, row=1, col=1
    )

    fig.update_yaxes(
        showgrid=True, gridcolor='lightgray', side='right',
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
        row=2, col=1
    )
    
    return fig, breakouts

def render_trade_planner(*, ticker, api_df, go_df, md_df, iss_df, deposit, rr_ratio, commission, strategy):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"Позиция: {ticker}")

    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty and "SECID" in iss_df.columns else pd.DataFrame()

    if not iss_row.empty:
        market = to_float(iss_row.iloc[0].get("LAST", 0)) or to_float(iss_row.iloc[0].get("PREVSETTLEPRICE", 0))
        decimals = int(to_float(iss_row.iloc[0].get("DECIMALS", 0)))
    else:
        market = 100000.0
        decimals = 0

    margin_type = st.session_state.get("margin_type", "КСУР")

    margin_per_contract = get_margin(go_df, ticker, margin_type, "LONG")
    if margin_per_contract == 0 and not iss_row.empty:
        margin_per_contract = to_float(iss_row.iloc[0].get("INITIALMARGIN", 0))
    if margin_per_contract == 0:
        margin_per_contract = 25000.0

    step_price = to_float(vlookup(api_df, ticker, 6)) or 10.0
    step_cost = to_float(vlookup(api_df, ticker, 17)) or 16.2
    pv = _div(step_cost, step_price)

    direction = st.radio("Направление торговли", ["LONG", "SHORT"], horizontal=True, key=key("dir"))

    cache = load_trend_cache()
    ticker_cache = cache.get(ticker, {})

    pts_keys = {
        "d1_chan": f"manual_channel_{ticker}_D1",
        "d1_fib": f"manual_fib_{ticker}_D1",
        "h1_tend": f"manual_tend_{ticker}_H1",
        "h1_fib": f"manual_fib_{ticker}_H1",
        "m10_zig": f"manual_zig_{ticker}_M10",
    }
    
    cache_keys = {
        "d1_chan": "d1_manual_pts",
        "d1_fib": "d1_fib_pts",
        "h1_tend": "h1_tend_pts",
        "h1_fib": "h1_fib_pts",
        "m10_zig": "m10_zig_pts",
    }

    for k, skey in pts_keys.items():
        if skey not in st.session_state:
            cached_pts = ticker_cache.get(cache_keys[k], [])
            st.session_state[skey] = [(pd.to_datetime(t), float(p)) for t, p in cached_pts]

    for k in pts_keys.keys():
        undo_k = f"undo_{k}_{ticker}"
        redo_k = f"redo_{k}_{ticker}"
        deb_k = f"debounce_{k}_{ticker}"
        if undo_k not in st.session_state: st.session_state[undo_k] = []
        if redo_k not in st.session_state: st.session_state[redo_k] = []
        if deb_k not in st.session_state: st.session_state[deb_k] = 0.0

    h1_pts = st.session_state.get(pts_keys["h1_tend"], [])
    d1_pts = st.session_state.get(pts_keys["d1_chan"], [])

    p_a, p_b, p_c, p_d = None, None, None, None
    if len(h1_pts) >= 4:
        p_a = h1_pts[-4][1]
        p_b = h1_pts[-3][1]
        p_c = h1_pts[-2][1]
        p_d = h1_pts[-1][1]

    with st.expander("Техническая аналитика графика", expanded=False):
        st.markdown("**Последние 4 точки Тенденции (H1):**")
        c1, c2, c3, c4 = st.columns(4)
        
        val_a = f"{p_a:.{decimals}f}" if p_a is not None else "-"
        val_b = f"{p_b:.{decimals}f}" if p_b is not None else "-"
        val_c = f"{p_c:.{decimals}f}" if p_c is not None else "-"
        val_d = f"{p_d:.{decimals}f}" if p_d is not None else "-"
        
        c1.metric("Точка 1", val_a)
        c2.metric("Точка 2", val_b)
        c3.metric("Точка 3", val_c)
        c4.metric("Точка 4", val_d)

    all_filled = all(x is not None for x in [p_a, p_b, p_c, p_d])

    active_tool = st.radio(
        "Выберите инструмент для рисования", 
        ["Нет", "D1: Канал", "D1: Уровень 1/2", "H1: Тенденция", "H1: Уровень 1/2", "M10: Зигзаг"],
        horizontal=True, key=key("active_tool")
    )

    tool_map = {
        "D1: Канал": ("d1_chan", 3),
        "D1: Уровень 1/2": ("d1_fib", 2),
        "H1: Тенденция": ("h1_tend", None),
        "H1: Уровень 1/2": ("h1_fib", 2),
        "M10: Зигзаг": ("m10_zig", None)
    }
    
    if active_tool != "Нет":
        active_k, max_pts = tool_map[active_tool]
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

    st.markdown("#### Графики рынка (MOEX ISS)")
    chart_tabs = st.tabs(["D1 (Дни)", "H1 (Часы)", "M10 (10 минут)"])

    for tab, (tf_name, cfg) in zip(chart_tabs, INTERVALS.items()):
        with tab:
            df_candles = fetch_moex_candles(
                ticker,
                interval=cfg["interval"],
                days_back=cfg["days_back"],
            )
            if df_candles.empty:
                st.info(f"Нет данных для {tf_name}. Возможно, торги по контракту не проводились.")
                continue

            zoom_start = None
            if tf_name == "H1" and len(d1_pts) == 3:
                zoom_start = d1_pts[1][0]
            elif tf_name == "M10" and len(h1_pts) >= 4:
                zoom_start = h1_pts[-4][0]

            last_ts = df_candles.index[-1]
            st.caption(f"Последняя свеча: **{last_ts.strftime('%d.%m.%Y %H:%M')}**  ·  Свечей: {len(df_candles)}")

            try:
                is_d1 = (tf_name == "D1")
                is_h1 = (tf_name == "H1")
                is_m10 = (tf_name == "M10")
                
                d1_fib = st.session_state.get(pts_keys["d1_fib"], [])
                h1_fib = st.session_state.get(pts_keys["h1_fib"], [])
                m10_zig = st.session_state.get(pts_keys["m10_zig"], [])
                
                fig, breakouts = draw_chart(
                    df_candles,
                    title=f"{ticker} — {tf_name}",
                    is_intraday=cfg["is_intraday"],
                    decimals=decimals,
                    is_h1=is_h1,
                    is_m10=is_m10,
                    is_d1=is_d1,
                    ticker=ticker,
                    d1_pts=d1_pts,
                    d1_fib_pts=d1_fib,
                    h1_tend_pts=h1_pts,
                    h1_fib_pts=h1_fib,
                    m10_zig_pts=m10_zig,
                    strategy=strategy,
                    zoom_start_time=zoom_start
                )
                
                if fig:
                    if active_tool != "Нет":
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
                            new_pts = pts.copy()
                            
                            if max_pts is None or len(new_pts) < max_pts:
                                if active_k in ["h1_tend", "m10_zig"]:
                                    if new_pts and new_pts[-1][0] == bar.name:
                                        last_y = new_pts[-1][1]
                                        snapped_y = float(bar['Low']) if np.isclose(last_y, bar['High']) else float(bar['High'])
                                        new_pts[-1] = (bar.name, snapped_y)
                                    elif not new_pts:
                                        current_price = df_view.iloc[-1]['Close']
                                        clicked_mid = (bar['High'] + bar['Low']) / 2
                                        snapped_y = float(bar['Low']) if clicked_mid < current_price else float(bar['High'])
                                        new_pts.append((bar.name, snapped_y))
                                    elif len(new_pts) == 1:
                                        snapped_y = float(bar['High']) if clicked_y > new_pts[0][1] else float(bar['Low'])
                                        new_pts.append((bar.name, snapped_y))
                                    else:
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
                            
                    if is_h1 and breakouts:
                        st.markdown("---")
                        st.markdown("#### Анализ пробоев и откатов H1")
                        
                        df_metrics = pd.DataFrame([
                            {
                                "Направление": "Вверх" if b["trend"] == "up" else "Вниз",
                                "Уровень сопр.": b["resistance_price"],
                                "Откат": b["pullback_price"],
                                "Пик (D)": b["peak_price"],
                                "Δ Пробоя": b["delta"],
                                "Δ Отката": b["retr_delta"],
                                "Бар. (пробой/откат)": f"{b['bars']} / {b['retr_bars']}",
                                "Объем (пробой/откат)": f"{b['volume']:,.0f} / {b['retr_volume']:,.0f}"
                            }
                            for b in breakouts
                        ])
                        
                        st.dataframe(
                            df_metrics, 
                            use_container_width=True, 
                            hide_index=True,
                            column_config={
                                "Уровень сопр.": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Откат": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Пик (D)": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Δ Пробоя": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                                "Δ Отката": st.column_config.NumberColumn(format=f"%.{decimals}f"),
                            }
                        )
            except Exception as e:
                st.error(f"Не удалось отрисовать график {tf_name}: {e}")

    final_state = {
        "d1_manual_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["d1_chan"], [])],
        "d1_fib_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["d1_fib"], [])],
        "h1_tend_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["h1_tend"], [])],
        "h1_fib_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["h1_fib"], [])],
        "m10_zig_pts": [(str(t), float(p)) for t, p in st.session_state.get(pts_keys["m10_zig"], [])]
    }
    clean_state = {k: v for k, v in final_state.items() if v is not None}
    
    if clean_state != ticker_cache:
        save_trend_cache(ticker, clean_state)

    if not all_filled:
        return

    avg_entry = p_c
    sl_price = p_a if direction == "LONG" else p_b
    sl_points = abs(avg_entry - sl_price)

    st.markdown("#### Параметры сделки")
    p1, p2 = st.columns(2)
    risk_pct = p1.number_input("Риск (в % от депозита)", min_value=0.1, max_value=100.0, value=1.0, step=0.1, key=key("risk_pct"))
    
    st.info(f"Risk Reward установлен в боковом меню: 1 к {rr_ratio}")

    risk_budget = deposit * (risk_pct / 100)
    tp_price = avg_entry + (sl_points * rr_ratio) if direction == "LONG" else avg_entry - (sl_points * rr_ratio)

    st.info(f"Вход (C): **{avg_entry:,.2f}** | SL (A/B): **{sl_price:,.2f}** | TP: **{tp_price:,.2f}**")

    max_contracts_by_risk = int(risk_budget / (sl_points * pv)) if pv > 0 else 0
    if max_contracts_by_risk < 1:
        st.error("Бюджет риска слишком мал для данной структуры.")
        return

    contracts = st.number_input("Количество контрактов", min_value=1, max_value=max_contracts_by_risk, value=max_contracts_by_risk, key=key("contracts"))
    margin_used = contracts * margin_per_contract

    st.markdown("---")
    st.markdown("#### Итоги расчета")
    profit_rub = abs(tp_price - avg_entry) * pv * contracts
    loss_rub = abs(avg_entry - sl_price) * pv * contracts
    cur_pnl = (market - avg_entry) * pv * contracts if direction == "LONG" else (avg_entry - market) * pv * contracts

    c1, c2, c3 = st.columns(3)
    c1.metric("Занятое ГО", f"{margin_used:,.0f} ₽")
    c2.metric("Убыток (SL)", f"−{loss_rub:,.0f} ₽")
    c3.metric("Прибыль (TP)", f"+{profit_rub:,.0f} ₽")

    c1, c2 = st.columns(2)
    c1.metric("Текущий P/L (от рынка)", f"{cur_pnl:+,.0f} ₽")
    c2.metric("Доля депозита", f"{_div(margin_used, deposit)*100:.2f}%")
