import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data import vlookup, to_float, get_margin, fetch_moex_candles
from rules import lookup

INTERVALS = {
    "D1":  {"interval": 24, "days_back": 250, "is_intraday": False, "show_trend": True},
    "H1":  {"interval": 60, "days_back": 30,  "is_intraday": True,  "show_trend": False},
    "M10": {"interval": 10, "days_back": 5,   "is_intraday": True,  "show_trend": False},
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

    if df.index.get_loc(min_idx) < len(df) * 0.5 and current_price > df['Low'].min() * 1.05:
        if current_price > df['High'].iloc[-5:].mean():
            return "Тренд вверх"

    if df.index.get_loc(max_idx) < len(df) * 0.5 and current_price < df['High'].max() * 0.95:
        if current_price < df['Low'].iloc[-5:].mean():
            return "Тренд вниз"

    sma20 = df['Close'].rolling(20).mean().iloc[-1]
    sma50 = df['Close'].rolling(50).mean().iloc[-1]
    if pd.notna(sma20) and pd.notna(sma50):
        if sma20 > sma50:
            return "Тренд вверх"
        elif sma20 < sma50:
            return "Тренд вниз"
    return "Боковик"

def add_extreme_annotations(fig, df, decimals=0):
    """Находит локальные экстремумы и накладывает на них черные плашки с белым шрифтом."""
    if len(df) < 5:
        return

    # Окно 5 баров: проверяем максимум/минимум бара по сравнению с 2 соседями слева и справа
    window = 5
    df_copy = df.copy()
    df_copy['local_high'] = df_copy['High'].rolling(window=window, center=True).max() == df_copy['High']
    df_copy['local_low'] = df_copy['Low'].rolling(window=window, center=True).min() == df_copy['Low']

    # Берем 10 последних экстремумов, чтобы не засорять график
    highs = df_copy[df_copy['local_high']].tail(10)
    lows = df_copy[df_copy['local_low']].tail(10)

    fmt = f",.{decimals}f"

    # 1. Выноски для максимумов (High)
    for idx, row in highs.iterrows():
        price_str = f"{row['High']:{fmt}}"
        fig.add_annotation(
            x=idx, y=row['High'],
            text=price_str,
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="black",
            ax=0, ay=-40, # Смещение плашки вверх
            bgcolor="black",
            font=dict(color="white", size=10),
            bordercolor="black",
            borderwidth=1,
            borderpad=3,
            opacity=0.85,
            row=1, col=1
        )

    # 2. Выноски для минимумов (Low)
    for idx, row in lows.iterrows():
        price_str = f"{row['Low']:{fmt}}"
        fig.add_annotation(
            x=idx, y=row['Low'],
            text=price_str,
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="black",
            ax=0, ay=40, # Смещение плашки вниз
            bgcolor="black",
            font=dict(color="white", size=10),
            bordercolor="black",
            borderwidth=1,
            borderpad=3,
            opacity=0.85,
            row=1, col=1
        )

def draw_chart(df_chart, p_a, p_b, p_c, p_d, title="", is_intraday=False, decimals=0, show_trend=False, channel_data=None):
    if df_chart.empty:
        return None

    tick_fmt = f",.{decimals}f"

    # Увеличиваем отступы сверху и снизу, чтобы плашки не обрезались
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.8, 0.2])

    # Бары OHLC (черные)
    fig.add_trace(go.Ohlc(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
        low=df_chart['Low'], close=df_chart['Close'],
        increasing_line_color='black', decreasing_line_color='black', name='Рынок'
    ), row=1, col=1)

    # Зигзаг
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
            mode='lines+markers+text',
            text=['A', 'B', 'C', 'D'],
            textposition='top center',
            textfont=dict(size=14, color='blue'),
            line=dict(color='blue', width=3),
            marker=dict(size=8, color='blue'),
            name='Зигзаг'
        ), row=1, col=1)

    # Объем
    if 'Volume' in df_chart.columns:
        colors = ['black' if c >= o else 'gray' for o, c in zip(df_chart['Open'], df_chart['Close'])]
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'],
                             marker_color=colors, name='Объем'), row=2, col=1)

    # --- ПЛАШКА ТРЕНДА ---
    if show_trend:
        trend_text = detect_trend(df_chart)
        
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

    # --- РУЧНОЙ КАНАЛ СПЕРАНДЕО (ЛУЧИ) ---
    if channel_data and not df_chart.empty:
        x1, y1, x2, y2, x3, y3 = channel_data
        
        try:
            idx1 = df_chart.index.get_loc(x1)
            idx2 = df_chart.index.get_loc(x2)
            idx3 = df_chart.index.get_loc(x3)
            
            slope = (y2 - y1) / (idx2 - idx1) if idx2 != idx1 else 0
            intercept = y1 - slope * idx1
            intercept_par = y3 - slope * idx3
            
            if len(df_chart) > 1:
                delta = df_chart.index[-1] - df_chart.index[-2]
                dt_end = df_chart.index[-1] + delta * 10
            else:
                dt_end = df_chart.index[-1]

            y_ray1_end = slope * (len(df_chart) + 10) + intercept
            y_ray2_end = slope * (len(df_chart) + 10) + intercept_par
            y_ray2_start = slope * idx1 + intercept_par

            fig.add_trace(go.Scatter(
                x=[x1, dt_end], y=[y1, y_ray1_end], 
                mode='lines', name='Линия тренда', 
                line=dict(color='blue', width=2)
            ), row=1, col=1)
            
            fig.add_trace(go.Scatter(
                x=[x1, dt_end], y=[y_ray2_start, y_ray2_end], 
                mode='lines', name='Граница канала', 
                line=dict(color='blue', width=2)
            ), row=1, col=1)
            
        except Exception:
            pass

    # --- ПОДСКАЗКИ ДЛЯ ЭКСТРЕМУМОВ (Только для дневного графика) ---
    if not is_intraday:
        add_extreme_annotations(fig, df_chart, decimals=decimals)

    fig.update_layout(
        title=title, height=700,
        margin=dict(l=10, r=10, t=50, b=50), # Увеличены отступы для плашек
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis_rangeslider_visible=False, showlegend=False,
        hovermode='closest',
        spikedistance=-1,
    )

    rangebreaks = [dict(bounds=["sat", "mon"])]
    if is_intraday:
        rangebreaks.append(dict(bounds=[23.833, 7], pattern="hour"))

    if len(df_chart) > 1:
        delta = df_chart.index[-1] - df_chart.index[-2]
        x_range = [df_chart.index[0] - delta, df_chart.index[-1] + 4 * delta]
    else:
        x_range = None

    fig.update_xaxes(
        showgrid=True, gridcolor='lightgray',
        rangebreaks=rangebreaks,
        range=x_range,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
    )
    
    fig.update_yaxes(
        showgrid=True, gridcolor='lightgray', side='right',
        tickformat=tick_fmt,
        showspikes=True, spikemode='across', spikesnap='cursor',
        spikecolor='gray', spikethickness=1, spikedash='dash',
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

    # --- Загрузка D1 для тренда и канала ---
    df_d1 = fetch_moex_candles(ticker, interval=24, days_back=250)
    trend_d1 = detect_trend(df_d1) if not df_d1.empty else "Боковик"

    channel_data = None
    with st.expander("📐 Трендовый канал (Сперандео)"):
        st.markdown(f"**Определенный тренд (D1):** {trend_d1}")
        
        if trend_d1 == "Тренд вверх":
            c1, c2, c3 = st.columns(3)
            y1 = c1.number_input("Минимум 1", value=None, step=100.0, format="%.2f", key=key("min1"))
            y2 = c2.number_input("Минимум 2", value=None, step=100.0, format="%.2f", key=key("min2"))
            y3 = c3.number_input("Максимум", value=None, step=100.0, format="%.2f", key=key("max"))
            
            if y1 is not None and y2 is not None and y3 is not None:
                if y1 < y2:
                    x1 = (df_d1['Low'] - y1).abs().idxmin()
                    x2 = (df_d1['Low'] - y2).abs().idxmin()
                    if x1 > x2: x1, x2 = x2, x1
                    mask = (df_d1.index >= x1) & (df_d1.index <= x2)
                    if mask.sum() > 0:
                        sub_df = df_d1.loc[mask]
                        x3 = (sub_df['High'] - y3).abs().idxmin()
                        channel_data = (x1, y1, x2, y2, x3, y3)
                else:
                    st.error("Минимум 1 должен быть меньше Минимума 2")
                
        elif trend_d1 == "Тренд вниз":
            c1, c2, c3 = st.columns(3)
            y1 = c1.number_input("Максимум 1", value=None, step=100.0, format="%.2f", key=key("max1"))
            y2 = c2.number_input("Максимум 2", value=None, step=100.0, format="%.2f", key=key("max2"))
            y3 = c3.number_input("Минимум", value=None, step=100.0, format="%.2f", key=key("min"))
            
            if y1 is not None and y2 is not None and y3 is not None:
                if y1 > y2:
                    x1 = (df_d1['High'] - y1).abs().idxmin()
                    x2 = (df_d1['High'] - y2).abs().idxmin()
                    if x1 > x2: x1, x2 = x2, x1
                    mask = (df_d1.index >= x1) & (df_d1.index <= x2)
                    if mask.sum() > 0:
                        sub_df = df_d1.loc[mask]
                        x3 = (sub_df['Low'] - y3).abs().idxmin()
                        channel_data = (x1, y1, x2, y2, x3, y3)
                else:
                    st.error("Максимум 1 должен быть больше Максимума 2")
        else:
            st.info("Для боковика канал не строится.")

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
                fig = draw_chart(
                    df_candles, p_a, p_b, p_c, p_d,
                    title=f"{ticker} — {tf_name}",
                    is_intraday=cfg["is_intraday"],
                    decimals=decimals,
                    show_trend=cfg["show_trend"],
                    channel_data=channel_data if tf_name == "D1" else None
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
