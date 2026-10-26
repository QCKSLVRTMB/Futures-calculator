import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data import vlookup, to_float, get_margin, fetch_moex_candles
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
    """Определяет тренд только на основе переданного окна данных."""
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

def get_zigzag_pivots_tw(df, depth=4, deviation_pct=0.07):
    """
    Точная реализация индикатора ZigZag из TradingView.
    depth: количество баров для поиска локального экстремума (по умолчанию 4)
    deviation_pct: процент отката для подтверждения (по умолчанию 7%)
    """
    pivots = []
    if len(df) < depth * 2:
        return pivots

    # 1. Поиск локальных экстремумов (High и Low) с учетом параметра Depth
    potential_pivots = []
    for i in range(depth, len(df) - depth):
        # Проверяем, является ли бар локальным максимумом
        is_high = all(df['High'].iloc[i] >= df['High'].iloc[i-j] for j in range(1, depth+1)) and \
                  all(df['High'].iloc[i] >= df['High'].iloc[i+j] for j in range(1, depth+1))
        if is_high:
            potential_pivots.append((df.index[i], 'high', df['High'].iloc[i]))

        # Проверяем, является ли бар локальным минимумом
        is_low = all(df['Low'].iloc[i] <= df['Low'].iloc[i-j] for j in range(1, depth+1)) and \
                 all(df['Low'].iloc[i] <= df['Low'].iloc[i+j] for j in range(1, depth+1))
        if is_low:
            potential_pivots.append((df.index[i], 'low', df['Low'].iloc[i]))

    # Сортируем потенциальные точки по времени
    potential_pivots.sort(key=lambda x: x[0])

    if not potential_pivots:
        return []

    # 2. Фильтрация по Deviation (процент отклонения)
    pivots = [potential_pivots[0]]
    for current in potential_pivots[1:]:
        last = pivots[-1]
        
        # Если тип тот же самый (например, два high подряд), оставляем самый экстремальный
        if current[1] == last[1]:
            if (current[1] == 'high' and current[2] > last[2]) or \
               (current[1] == 'low' and current[2] < last[2]):
                pivots[-1] = current
        else:
            # Если тип разный, проверяем, было ли отклонение достаточным (Deviation)
            if last[1] == 'high':
                drop_pct = (last[2] - current[2]) / last[2] # Падение
                if drop_pct >= deviation_pct:
                    pivots.append(current)
            else:
                rise_pct = (current[2] - last[2]) / last[2] # Рост
                if rise_pct >= deviation_pct:
                    pivots.append(current)

    return pivots

def get_sperandeo_geometry(df, trend_direction):
    """
    Строит канал, используя ZigZag (TW style).
    """
    # Используем настройки как на вашем скриншоте: Depth=4, Deviation=7%
    pivots = get_zigzag_pivots_tw(df, depth=4, deviation_pct=0.07)
    
    if len(pivots) < 3:
        return None, []

    channel_data = None
    annotations = []

    if trend_direction == "Тренд вверх":
        # 1. Ищем глобальный минимум (L1)
        l1_idx = None
        min_low = float('inf')
        for i, p in enumerate(pivots):
            if p[1] == 'low' and p[2] < min_low:
                min_low = p[2]
                l1_idx = i
        
        if l1_idx is not None:
            # 2. Ищем следующий валидный минимум (L2), который выше L1
            l2_idx = None
            for i in range(l1_idx + 1, len(pivots)):
                if pivots[i][1] == 'low' and pivots[i][2] > pivots[l1_idx][2]:
                    l2_idx = i
                    break # Берем первый же валидный откат
            
            if l2_idx is not None:
                # 3. Ищем максимум (H1) между L1 и L2
                highs = [p for p in pivots[l1_idx+1:l2_idx] if p[1] == 'high']
                if highs:
                    h1 = max(highs, key=lambda x: x[2])
                    channel_data = {
                        'p1': (pivots[l1_idx][0], pivots[l1_idx][2]),
                        'p2': (pivots[l2_idx][0], pivots[l2_idx][2]),
                        'p3': (h1[0], h1[2])
                    }
                    annotations = [pivots[l1_idx], h1, pivots[l2_idx]]

    elif trend_direction == "Тренд вниз":
        # 1. Ищем глобальный максимум (H1)
        h1_idx = None
        max_high = -float('inf')
        for i, p in enumerate(pivots):
            if p[1] == 'high' and p[2] > max_high:
                max_high = p[2]
                h1_idx = i
        
        if h1_idx is not None:
            # 2. Ищем следующий валидный максимум (H2), который ниже H1
            h2_idx = None
            for i in range(h1_idx + 1, len(pivots)):
                if pivots[i][1] == 'high' and pivots[i][2] < pivots[h1_idx][2]:
                    h2_idx = i
                    break
            
            if h2_idx is not None:
                # 3. Ищем минимум (L1) между H1 и H2
                lows = [p for p in pivots[h1_idx+1:h2_idx] if p[1] == 'low']
                if lows:
                    l1 = min(lows, key=lambda x: x[2])
                    channel_data = {
                        'p1': (pivots[h1_idx][0], pivots[h1_idx][2]),
                        'p2': (pivots[h2_idx][0], pivots[h2_idx][2]),
                        'p3': (l1[0], l1[2])
                    }
                    annotations = [pivots[h1_idx], l1, pivots[h2_idx]]

    annotations.sort(key=lambda x: x[0])
    return channel_data, annotations

def draw_chart(df_chart, p_a, p_b, p_c, p_d, title="", is_intraday=False, decimals=0, trend_text="", channel_data=None, annotations_data=None):
    if df_chart.empty:
        return None

    df_chart = df_chart.tail(150).copy()
    tick_fmt = f",.{decimals}f"

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
            name='Зигзаг'
        ), row=1, col=1)

    if 'Volume' in df_chart.columns:
        colors = ['black' if c >= o else 'gray' for o, c in zip(df_chart['Open'], df_chart['Close'])]
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
        fmt = f",.{decimals}f"
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
                time_buffer = pd.Timedelta(hours=12) if title.endswith("H1") else pd.Timedelta(hours=2)
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
        xaxis_rangeslider_visible=False, showlegend=False,
        hovermode='closest', spikedistance=-1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday:
        rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    if len(df_chart) > 1:
        if is_intraday:
            time_buffer = pd.Timedelta(hours=12) if title.endswith("H1") else pd.Timedelta(hours=2)
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
    
    return fig

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

    # --- АНАЛИЗ ТОЛЬКО ВИДИМОГО УЧАСТКА D1 (150 баров) ---
    df_d1_full = fetch_moex_candles(ticker, interval=24, days_back=250)
    
    if not df_d1_full.empty:
        df_d1_view = df_d1_full.tail(150).copy()
        trend_d1 = detect_trend(df_d1_view)
        channel_data, annotations_data = get_sperandeo_geometry(df_d1_view, trend_d1)
    else:
        trend_d1 = "Боковик"
        channel_data, annotations_data = None, []

    st.markdown("#### 🧩 Торгуемый зигзаг (A-B-C-D)")
    c1, c2, c3, c4 = st.columns(4)
    p_a = c1.number_input("Точка A", value=None, step=100.0, format="%.2f", key=key("p_a"))
    p_b = c2.number_input("Точка B", value=None, step=100.0, format="%.2f", key=key("p_b"))
    p_c = c3.number_input("Точка C", value=None, step=100.0, format="%.2f", key=key("p_c"))
    p_d = c4.number_input("Точка D", value=None, step=100.0, format="%.2f", key=key("p_d"))

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
                
                fig = draw_chart(
                    df_candles, p_a, p_b, p_c, p_d,
                    title=f"{ticker} — {tf_name}",
                    is_intraday=cfg["is_intraday"],
                    decimals=decimals,
                    trend_text=trend_d1 if is_d1 else "",
                    channel_data=channel_data if is_d1 else None,
                    annotations_data=annotations_data if is_d1 else None
                )
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"Не удалось отрисовать график {tf_name}: {e}")

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
