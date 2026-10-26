import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

from data import vlookup, to_float, get_margin, fetch_moex_candles, load_trend_cache, save_trend_cache
from rules import lookup

INTERVALS = {
    "D1":  {"interval": 24, "days_back": 250, "is_intraday": False},
    "H1":  {"interval": 60, "days_back": 30,  "is_intraday": True},
    "M10": {"interval": 10, "days_back": 5,   "is_intraday": True},
}

def _div(a, b, default=0.0):
    return a / b if b else default

def check_zigzag_pattern(a, b, c, d, direction):
    if direction == "LONG":
        if a < b and b > c and c < d and b > d and a < c:
            return True, "✅ Структура LONG соответствует: a<b>c<d (b>d)"
        return False, "❌ Структура LONG НЕ соответствует: нужно a<b>c<d (b>d) и a<c"
    else:
        if a > b and b < c and c > d and b < d and a > c:
            return True, "✅ Структура SHORT соответствует: a>b<c>d (b<d)"
        return False, "❌ Структура SHORT НЕ соответствует: нужно a>b<c>d (b<d) и a>c"

def detect_trend(df):
    if len(df) < 20:
        return "Боковик"
    
    min_idx = df['Low'].idxmin()
    max_idx = df['High'].idxmax()
    current_price = df['Close'].iloc[-1]
    
    min_pos = df.index.get_loc(min_idx)
    max_pos = df.index.get_loc(max_idx)
    
    if min_pos < max_pos and current_price > df['Low'].iloc[-5:].mean():
        return "Тренд вверх"
    if max_pos < min_pos and current_price < df['High'].iloc[-5:].mean():
        return "Тренд вниз"
        
    sma20 = df['Close'].rolling(20).mean().iloc[-1]
    sma50 = df['Close'].rolling(50).mean().iloc[-1]
    if pd.notna(sma20) and pd.notna(sma50):
        if sma20 > sma50:
            return "Тренд вверх"
        elif sma20 < sma50:
            return "Тренд вниз"
    return "Боковик"

def get_sperandeo_geometry(df, trend_direction):
    if len(df) < 20: 
        return None, None, None, None, []
    
    if trend_direction == "Тренд вниз":
        p1_idx = df['High'].idxmax()
        p1_price = float(df.loc[p1_idx, 'High'])
        
        df_after_p1 = df.loc[p1_idx:]
        if len(df_after_p1) < 5: return p1_price, None, None, None, []
        
        p2_idx = df_after_p1['Low'].idxmin()
        p2_price = float(df.loc[p2_idx, 'Low'])
        
        df_after_p2 = df.loc[p2_idx:]
        if len(df_after_p2) < 5: return p1_price, p2_price, None, None, []
        
        p3_idx = df_after_p2['High'].idxmax()
        p3_price = float(df.loc[p3_idx, 'High'])
        
        df_after_p3 = df.loc[p3_idx:]
        is_breakout = len(df_after_p3) > 0 and df_after_p3['Low'].min() < p2_price
        
        if is_breakout:
            channel = {'p1': (p1_idx, p1_price), 'p2': (p2_idx, p2_price), 'p3': (p3_idx, p3_price)}
            ann = [(p1_idx, 'high', p1_price), (p2_idx, 'low', p2_price), (p3_idx, 'high', p3_price)]
            return p1_price, p2_price, p3_price, channel, ann
        
        return p1_price, p2_price, p3_price, None, []
        
    elif trend_direction == "Тренд вверх":
        p1_idx = df['Low'].idxmin()
        p1_price = float(df.loc[p1_idx, 'Low'])
        
        df_after_p1 = df.loc[p1_idx:]
        if len(df_after_p1) < 5: return p1_price, None, None, None, []
        
        p2_idx = df_after_p1['High'].idxmax()
        p2_price = float(df.loc[p2_idx, 'High'])
        
        df_after_p2 = df.loc[p2_idx:]
        if len(df_after_p2) < 5: return p1_price, p2_price, None, None, []
        
        p3_idx = df_after_p2['Low'].idxmin()
        p3_price = float(df.loc[p3_idx, 'Low'])
        
        df_after_p3 = df.loc[p3_idx:]
        is_breakout = len(df_after_p3) > 0 and df_after_p3['High'].max() > p2_price
        
        if is_breakout:
            channel = {'p1': (p1_idx, p1_price), 'p2': (p3_idx, p3_price), 'p3': (p2_idx, p2_price)}
            ann = [(p1_idx, 'low', p1_price), (p2_idx, 'high', p2_price), (p3_idx, 'low', p3_price)]
            return p1_price, p2_price, p3_price, channel, ann
            
        return p1_price, p2_price, p3_price, None, []
        
    return None, None, None, None, []

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
            
            # Расчет отката от B до C
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
            
            # Расчет отката от B до C
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

def draw_chart(df_chart, p_a, p_b, p_c, p_d, title="", is_intraday=False, decimals=0, trend_text="", channel_data=None, annotations_data=None, is_h1=False, is_m10=False, is_d1=False, ticker=""):
    if df_chart.empty:
        return None, []

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

    if all(x is not None for x in [p_a, p_b, p_c, p_d]):
        n = len(df_chart)
        step = max(1, n // 3)
        zigzag_x = [
            df_chart.index[0],
            df_chart.index[min(step, n - 1)],
            df_chart.index[min(step * 2, n - 1)],
            df_chart.index[-1],
        ]
        fig.add_trace(go.Scatter(
            x=zigzag_x, y=[p_a, p_b, p_c, p_d],
            mode='lines+markers+text', text=['A', 'B', 'C', 'D'],
            textposition='top center', textfont=dict(size=14, color='blue'),
            line=dict(color='blue', width=3), marker=dict(size=8, color='blue'),
            name='Зигзаг ABCD'
        ), row=1, col=1)

    manual_points_key = f"manual_zigzag_{ticker}_H1"
    manual_pts = []
    if is_h1 and manual_points_key in st.session_state and st.session_state[manual_points_key]:
        manual_pts = st.session_state[manual_points_key]
        mx = [p[0] for p in manual_pts]
        my = [p[1] for p in manual_pts]
        fig.add_trace(go.Scatter(
            x=mx, y=my,
            mode='lines+markers',
            marker=dict(size=8, color='red', symbol='circle'),
            line=dict(color='red', width=3),
            name='Ручной зигзаг (H1)'
        ), row=1, col=1)

    breakouts = []
    if is_h1 and manual_pts:
        breakouts = analyze_manual_zigzag(manual_pts, df_chart)
        
        for brk in breakouts:
            breakout_bg = "rgba(13, 110, 253, 0.9)"   # Синий для пробоев
            pullback_bg = "rgba(253, 126, 20, 0.9)"   # Оранжевый для откатов
            line_color_breakout = "#0d6efd"
            line_color_pullback = "#fd7e14"
            
            # === ПРОБОЙ (Синий) ===
            breakout_text = (
                f"Δ: {brk['delta']:.{decimals}f}<br>"
                f"Бар: {brk['bars']}<br>"
                f"Vol: {brk['volume']:,.0f}"
            )
            
            # Плашка у пика (D, F, H)
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
            
            # Плашка у сопротивления (B, D, F)
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

            # 1. Горизонталь от сопротивления до бара пробоя
            fig.add_shape(
                type="line", x0=brk['resistance_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['resistance_price'],
                line=dict(color=line_color_breakout, width=2), 
                xref="x", yref="y", row=1, col=1
            )

            # 2. Вертикаль от бара пробоя до пика
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )

            # 3. Горизонталь от вертикали к пику
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['peak_price'], 
                x1=brk['peak_time'], y1=brk['peak_price'],
                line=dict(color=line_color_breakout, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )

            # Текст пробоя
            mid_y_breakout = brk['resistance_price'] + (brk['peak_price'] - brk['resistance_price']) / 2
            fig.add_annotation(
                x=brk['breakout_time'], y=mid_y_breakout,
                text=f"Δ: {brk['delta']:.{decimals}f}",
                showarrow=False, xanchor="right", xshift=-5,
                font=dict(color=line_color_breakout, size=11, weight="bold"),
                row=1, col=1
            )

            # === ОТКАТ (Оранжевый) ===
            pullback_text = (
                f"Δ: {brk['retr_delta']:.{decimals}f}<br>"
                f"Бар: {brk['retr_bars']}<br>"
                f"Vol: {brk['retr_volume']:,.0f}"
            )
            
            # Плашка у отката (C, E, G)
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

            # 4. Вертикаль от бара пробоя вниз до уровня отката
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['resistance_price'], 
                x1=brk['breakout_time'], y1=brk['pullback_price'],
                line=dict(color=line_color_pullback, width=2, dash="dot"), 
                xref="x", yref="y", row=1, col=1
            )

            # 5. Горизонталь от вертикали до точки отката
            fig.add_shape(
                type="line", x0=brk['breakout_time'], y0=brk['pullback_price'], 
                x1=brk['pullback_time'], y1=brk['pullback_price'],
                line=dict(color=line_color_pullback, width=2), 
                xref="x", yref="y", row=1, col=1
            )

            # Текст отката
            mid_y_pullback = brk['pullback_price'] + (brk['resistance_price'] - brk['pullback_price']) / 2
            fig.add_annotation(
                x=brk['breakout_time'], y=mid_y_pullback,
                text=f"Δ: {brk['retr_delta']:.{decimals}f}",
                showarrow=False, xanchor="right", xshift=-5,
                font=dict(color=line_color_pullback, size=11, weight="bold"),
                row=1, col=1
            )

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

    if trend_text:
        if trend_text == "Тренд вверх":
            bg_color, font_color = "#198754", "white"
        elif trend_text == "Тренд вниз":
            bg_color, font_color = "#dc3545", "white"
        else:
            bg_color, font_color = "#e2e3e5", "black"

        fig.add_annotation(
            text=trend_text, xref="paper", yref="paper",
            x=0.99, y=0.99, xanchor="right", yanchor="top",
            showarrow=False,
            font=dict(size=14, color=font_color, weight="bold"),
            bgcolor=bg_color, bordercolor="black", borderwidth=1,
            borderpad=6, opacity=0.9
        )

    if annotations_data:
        fmt = f".{decimals}f"
        for idx, typ, val in annotations_data:
            price_str = f"{val:{fmt}}"
            if typ == 'high':
                fig.add_annotation(
                    x=idx, y=val, text=price_str, showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor="black",
                    ax=0, ay=-40, bgcolor="black", font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3, opacity=0.85, row=1, col=1
                )
            else:
                fig.add_annotation(
                    x=idx, y=val, text=price_str, showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1, arrowcolor="black",
                    ax=0, ay=40, bgcolor="black", font=dict(color="white", size=10),
                    bordercolor="black", borderwidth=1, borderpad=3, opacity=0.85, row=1, col=1
                )

    if channel_data:
        try:
            x1, y1 = channel_data['p1']
            x2, y2 = channel_data['p2']
            x3, y3 = channel_data['p3']
            
            x1_ts = pd.to_datetime(x1)
            x2_ts = pd.to_datetime(x2)
            x3_ts = pd.to_datetime(x3)
            
            time1 = x1_ts.timestamp()
            time2 = x2_ts.timestamp()
            time3 = x3_ts.timestamp()
            
            dt_12 = time2 - time1 if time2 != time1 else 1
            slope_time = (y2 - y1) / dt_12
            
            if is_intraday:
                time_buffer = pd.Timedelta(hours=12) if is_h1 else pd.Timedelta(hours=2)
            else:
                time_buffer = pd.Timedelta(days=10)
                
            dt_end = df_chart.index[-1] + time_buffer
            
            y_ray1_end = slope_time * (dt_end.timestamp() - time1) + y1
            y_ray2_end = slope_time * (dt_end.timestamp() - time3) + y3

            fig.add_shape(
                type="line", x0=x1_ts, y0=y1, x1=dt_end, y1=y_ray1_end,
                line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1
            )
            
            fig.add_shape(
                type="line", x0=x3_ts, y0=y3, x1=dt_end, y1=y_ray2_end,
                line=dict(color="blue", width=2), xref="x", yref="y", row=1, col=1
            )
            
        except Exception as e:
            st.error(f"Ошибка отрисовки канала: {e}")

    fig.update_layout(
        title=title, height=700,
        margin=dict(l=10, r=10, t=50, b=50),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode='closest', spikedistance=-1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday:
        rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    if len(df_chart) > 1:
        if is_intraday:
            time_buffer = pd.Timedelta(hours=12) if is_h1 else pd.Timedelta(hours=2)
        else:
            time_buffer = pd.Timedelta(days=10)
            
        x_range = [df_chart.index[0] - pd.Timedelta(hours=4), df_chart.index[-1] + time_buffer]
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

def render_trade_planner(*, ticker, api_df, go_df, md_df, iss_df, deposit):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty and "SECID" in iss_df.columns else pd.DataFrame()

    if not iss_row.empty:
        market = to_float(iss_row.iloc[0].get("LAST", 0)) or to_float(iss_row.iloc[0].get("PREVSETTLEPRICE", 0))
        decimals = int(to_float(iss_row.iloc[0].get("DECIMALS", 0)))
    else:
        market = 100000.0
        decimals = 0

    margin_per_contract = get_margin(go_df, ticker, "КСУР", "LONG")
    if margin_per_contract == 0 and not iss_row.empty:
        margin_per_contract = to_float(iss_row.iloc[0].get("INITIALMARGIN", 0))
    if margin_per_contract == 0:
        margin_per_contract = 25000.0

    step_price = to_float(vlookup(api_df, ticker, 6)) or 10.0
    step_cost = to_float(vlookup(api_df, ticker, 17)) or 16.2
    pv = _div(step_cost, step_price)

    market_state = st.session_state.setdefault("market_state", {})
    state = market_state.get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
    trend, wave, tendency = state["trend"], state["wave"], state["tendency"]

    options_labels = {}
    for tt in ["трендовая", "контртренд"]:
        for d in ["LONG", "SHORT"]:
            rule = lookup(trend, wave, tendency, tt, d)
            if rule is not None and not rule["is_forbidden"]:
                label = f"{'🟢' if tt == 'трендовая' else '🔴'} {tt.capitalize()} {d}"
                options_labels[label] = (tt, d, rule)

    if not options_labels:
        st.error("❌ Для данного состояния рынка нет разрешенных сценариев.")
        return

    selected_label = st.selectbox("🎯 Сценарий:", list(options_labels.keys()), key=key("scenario"))
    tt, direction, rule = options_labels[selected_label]

    # --- АНАЛИЗ D1 ---
    df_d1_full = fetch_moex_candles(ticker, interval=24, days_back=250)
    
    if not df_d1_full.empty:
        df_d1_view = df_d1_full.tail(150).copy()
        trend_d1 = detect_trend(df_d1_view)
        
        p1_auto, p2_auto, p3_auto, auto_channel, auto_ann = get_sperandeo_geometry(df_d1_view, trend_d1)
    else:
        trend_d1 = "Боковик"
        p1_auto, p2_auto, p3_auto = None, None, None
        auto_channel, auto_ann = None, []

    # --- ЗАГРУЗКА КЭША ИЗ JSON ---
    cache = load_trend_cache()
    ticker_cache = cache.get(ticker, {})

    init_p1 = ticker_cache.get("man_p1", p1_auto)
    init_p2 = ticker_cache.get("man_p2", p2_auto)
    init_p3 = ticker_cache.get("man_p3", p3_auto)

    init_a = ticker_cache.get("p_a")
    init_b = ticker_cache.get("p_b")
    init_c = ticker_cache.get("p_c")
    init_d = ticker_cache.get("p_d")

    # Инициализация точек H1 из кэша
    pts_key = f"manual_zigzag_{ticker}_H1"
    undo_key = f"undo_{ticker}_H1"
    redo_key = f"redo_{ticker}_H1"
    debounce_key = f"debounce_{ticker}_H1"
    
    if pts_key not in st.session_state:
        cached_h1_pts = ticker_cache.get("h1_manual_pts", [])
        st.session_state[pts_key] = [(pd.to_datetime(t), float(p)) for t, p in cached_h1_pts]
    if undo_key not in st.session_state:
        st.session_state[undo_key] = []
    if redo_key not in st.session_state:
        st.session_state[redo_key] = []
    if debounce_key not in st.session_state:
        st.session_state[debounce_key] = 0.0

    # --- СПОЙЛЕР: ТЕХНИЧЕСКАЯ АНАЛИТИКА ---
    with st.expander("📐 Техническая аналитика графика", expanded=False):
        st.markdown(f"**Тренд (D1):** {trend_d1}")
        
        c1, c2, c3 = st.columns(3)
        man_p1 = c1.number_input("Точка 1", value=float(init_p1) if init_p1 is not None else None, step=100.0, format="%.2f", key=key("man_p1"))
        man_p2 = c2.number_input("Точка 2", value=float(init_p2) if init_p2 is not None else None, step=100.0, format="%.2f", key=key("man_p2"))
        man_p3 = c3.number_input("Точка 3", value=float(init_p3) if init_p3 is not None else None, step=100.0, format="%.2f", key=key("man_p3"))
        
        st.markdown("---")
        
        st.markdown("**Зигзаг тенденции**")
        c1, c2, c3, c4 = st.columns(4)
        p_a = c1.number_input("Точка A", value=float(init_a) if init_a is not None else None, step=100.0, format="%.2f", key=key("p_a"))
        p_b = c2.number_input("Точка B", value=float(init_b) if init_b is not None else None, step=100.0, format="%.2f", key=key("p_b"))
        p_c = c3.number_input("Точка C", value=float(init_c) if init_c is not None else None, step=100.0, format="%.2f", key=key("p_c"))
        p_d = c4.number_input("Точка D", value=float(init_d) if init_d is not None else None, step=100.0, format="%.2f", key=key("p_d"))

    # Логика канала
    final_channel = auto_channel
    final_annotations = auto_ann
    
    if man_p1 is not None and man_p2 is not None and man_p3 is not None:
        def find_bar(price, start_time, is_high):
            sub = df_d1_view.loc[start_time:]
            if sub.empty: return None
            if is_high:
                idx = (sub['High'] - price).abs().idxmin()
                return (idx, float(sub.loc[idx, 'High']))
            else:
                idx = (sub['Low'] - price).abs().idxmin()
                return (idx, float(sub.loc[idx, 'Low']))
                
        if trend_d1 == "Тренд вниз":
            b1 = find_bar(man_p1, df_d1_view.index[0], True)
            b2 = find_bar(man_p2, b1[0], False) if b1 else None
            b3 = find_bar(man_p3, b2[0], True) if b2 else None
            
            if b1 and b2 and b3:
                if df_d1_view.loc[b3[0]:, 'Low'].min() < b2[1]:
                    final_channel = {'p1': b1, 'p2': b2, 'p3': b3}
                    final_annotations = [(b1[0], 'high', b1[1]), (b2[0], 'low', b2[1]), (b3[0], 'high', b3[1])]
                else:
                    st.warning("⚠️ Условие пробоя Точки 2 (поддержки) не выполнено. Канал не построен.")
                    final_channel = None
                    final_annotations = []
                    
        elif trend_d1 == "Тренд вверх":
            b1 = find_bar(man_p1, df_d1_view.index[0], False)
            b2 = find_bar(man_p2, b1[0], True) if b1 else None
            b3 = find_bar(man_p3, b2[0], False) if b2 else None
            
            if b1 and b2 and b3:
                if df_d1_view.loc[b3[0]:, 'High'].max() > b2[1]:
                    final_channel = {'p1': b1, 'p2': b3, 'p3': b2}
                    final_annotations = [(b1[0], 'low', b1[1]), (b2[0], 'high', b2[1]), (b3[0], 'low', b3[1])]
                else:
                    st.warning("⚠️ Условие пробоя Точки 2 (сопротивления) не выполнено. Канал не построен.")
                    final_channel = None
                    final_annotations = []

    all_filled = all(x is not None for x in [p_a, p_b, p_c, p_d])

    if all_filled:
        ok, msg = check_zigzag_pattern(p_a, p_b, p_c, p_d, direction)
        (st.success if ok else st.warning)(msg)

    st.markdown("#### 📊 Графики рынка (MOEX ISS)")
    chart_tabs = st.tabs(["📅 D1 (Дни)", "🕐 H1 (Часы)", "⏱️ M10 (10 минут)"])

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

            last_ts = df_candles.index[-1]
            st.caption(f"Последняя свеча: **{last_ts.strftime('%d.%m.%Y %H:%M')}**  ·  Свечей: {len(df_candles)}")

            try:
                is_d1 = (tf_name == "D1")
                is_h1 = (tf_name == "H1")
                is_m10 = (tf_name == "M10")
                
                fig, breakouts = draw_chart(
                    df_candles, p_a, p_b, p_c, p_d,
                    title=f"{ticker} — {tf_name}",
                    is_intraday=cfg["is_intraday"],
                    decimals=decimals,
                    trend_text=trend_d1 if is_d1 else "",
                    channel_data=final_channel,
                    annotations_data=final_annotations,
                    is_h1=is_h1,
                    is_m10=is_m10,
                    is_d1=is_d1,
                    ticker=ticker
                )
                
                if fig:
                    if is_h1:
                        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
                        with col1:
                            if st.button("⬅️ Отменить", key=f"undo_btn_{ticker}"):
                                if len(st.session_state[undo_key]) > 0:
                                    prev_state = st.session_state[undo_key].pop()
                                    st.session_state[redo_key].append(st.session_state[pts_key].copy())
                                    st.session_state[pts_key] = prev_state
                                    st.session_state[debounce_key] = 0.0
                                    st.rerun()
                        with col2:
                            if st.button("➡️ Повторить", key=f"redo_btn_{ticker}"):
                                if len(st.session_state[redo_key]) > 0:
                                    next_state = st.session_state[redo_key].pop()
                                    st.session_state[undo_key].append(st.session_state[pts_key].copy())
                                    st.session_state[pts_key] = next_state
                                    st.session_state[debounce_key] = 0.0
                                    st.rerun()
                        with col3:
                            if st.button("🗑️ Очистить", key=f"clear_{ticker}_H1"):
                                st.session_state[undo_key].append(st.session_state[pts_key].copy())
                                st.session_state[redo_key] = []
                                st.session_state[pts_key] = []
                                st.session_state[debounce_key] = 0.0
                                st.rerun()
                        with col4:
                            draw_mode = st.toggle("✏️ Режим рисования зигзага", value=True, key=f"draw_mode_{ticker}_H1")

                        if draw_mode:
                            event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key=f"plot_{ticker}_H1")
                            
                            now = time.time()
                            last_debounce = st.session_state.get(debounce_key, 0.0)
                            
                            if event and event["selection"]["points"] and (now - last_debounce > 0.5):
                                st.session_state[debounce_key] = now
                                
                                pt = event["selection"]["points"][0]
                                clicked_time = pd.to_datetime(pt["x"])
                                clicked_y = pt["y"]
                                
                                df_h1_view = df_candles.tail(150).copy()
                                idx = df_h1_view.index.get_indexer([clicked_time], method='nearest')[0]
                                bar = df_h1_view.iloc[idx]
                                
                                pts = st.session_state[pts_key]
                                new_pts = pts.copy()
                                
                                if new_pts and new_pts[-1][0] == bar.name:
                                    last_y = new_pts[-1][1]
                                    if np.isclose(last_y, bar['High']):
                                        snapped_y = float(bar['Low'])
                                    else:
                                        snapped_y = float(bar['High'])
                                    new_pts[-1] = (bar.name, snapped_y)
                                    
                                elif not new_pts:
                                    current_price = df_h1_view.iloc[-1]['Close']
                                    clicked_bar_mid = (bar['High'] + bar['Low']) / 2
                                    
                                    if clicked_bar_mid < current_price:
                                        snapped_y = float(bar['Low'])
                                    else:
                                        snapped_y = float(bar['High'])
                                        
                                    new_pts.append((bar.name, snapped_y))
                                    
                                elif len(new_pts) == 1:
                                    if clicked_y > new_pts[0][1]:
                                        snapped_y = float(bar['High'])
                                    else:
                                        snapped_y = float(bar['Low'])
                                    new_pts.append((bar.name, snapped_y))
                                    
                                else:
                                    last_time, last_y = new_pts[-1]
                                    last_bar = df_h1_view.loc[last_time]
                                    is_last_high = np.isclose(last_y, last_bar['High'])
                                    
                                    if is_last_high:
                                        snapped_y = float(bar['Low'])
                                    else:
                                        snapped_y = float(bar['High'])
                                        
                                    new_pts.append((bar.name, snapped_y))

                                if new_pts != pts:
                                    st.session_state[undo_key].append(pts.copy())
                                    st.session_state[redo_key] = []
                                    st.session_state[pts_key] = new_pts
                                    st.rerun()
                        else:
                            st.plotly_chart(fig, use_container_width=True)
                            
                        if breakouts:
                            st.markdown("---")
                            st.markdown("#### 📈 Анализ пробоев и откатов H1")
                            
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
                    else:
                        st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"Не удалось отрисовать график {tf_name}: {e}")

    current_pts = st.session_state.get(pts_key, [])
    serializable_pts = [(str(t), float(p)) for t, p in current_pts]
    
    final_state = {
        "man_p1": man_p1, "man_p2": man_p2, "man_p3": man_p3,
        "p_a": p_a, "p_b": p_b, "p_c": p_c, "p_d": p_d,
        "h1_manual_pts": serializable_pts
    }
    clean_state = {k: v for k, v in final_state.items() if v is not None}
    
    if clean_state != ticker_cache:
        save_trend_cache(ticker, clean_state)

    if not all_filled:
        return

    avg_entry = p_c
    sl_price = p_a if direction == "LONG" else p_b
    sl_points = abs(avg_entry - sl_price)

    if direction == "LONG" and sl_price >= avg_entry:
        st.error("Для LONG SL (A) должен быть ниже входа (C).")
        return
    if direction == "SHORT" and sl_price <= avg_entry:
        st.error("Для SHORT SL (B) должен быть выше входа (C).")
        return
    if direction == "LONG" and p_d <= p_c:
        st.error("Для LONG точка D должна быть выше C.")
        return
    if direction == "SHORT" and p_d >= p_c:
        st.error("Для SHORT точка D должна быть ниже C.")
        return

    st.markdown("#### ⚙️ Параметры сделки")
    p1, p2 = st.columns(2)
    risk_pct = p1.number_input("Риск (в % от депозита)", min_value=0.1, max_value=100.0, value=1.0, step=0.1, key=key("risk_pct"))
    rr_ratio = p2.number_input("Risk Reward (1 к ...)", min_value=1.0, value=3.0, step=0.5, key=key("rr_ratio"))

    risk_budget = deposit * (risk_pct / 100)
    tp_price = avg_entry + (sl_points * rr_ratio) if direction == "LONG" else avg_entry - (sl_points * rr_ratio)

    st.info(f"Вход (C): **{avg_entry:,.2f}** | SL (A/B): **{sl_price:,.2f}** | TP: **{tp_price:,.2f}** (RR 1:{rr_ratio})")

    max_contracts_by_risk = int(risk_budget / (sl_points * pv)) if pv > 0 else 0
    if max_contracts_by_risk < 1:
        st.error("Бюджет риска слишком мал для данной структуры.")
        return

    contracts = st.number_input("Количество контрактов", min_value=1, max_value=max_contracts_by_risk, value=max_contracts_by_risk, key=key("contracts"))
    margin_used = contracts * margin_per_contract

    st.markdown("---")
    st.markdown("#### 📈 Итоги расчета")
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
