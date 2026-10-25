import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

from data import vlookup, to_float, get_margin, fetch_moex_forts
from rules import (
    RISK_LEVELS, RISK_LEVEL_DESCRIPTIONS, RISK_LEVEL_ICONS, 
    lookup
)

def _div(a, b, default=0.0):
    return a / b if b else default

def check_zigzag_pattern(a, b, c, d, direction):
    """Проверяет паттерн зигзага."""
    if direction == "LONG":
        if a < b and b > c and c < d and b > d:
            return True, "✅ Структура LONG соответствует: a<b>c<d (b>d)"
        return False, "❌ Структура LONG НЕ соответствует: нужно a<b>c<d (b>d)"
    else: # SHORT
        if a > b and b < c and c > d and b < d:
            return True, "✅ Структура SHORT соответствует: a>b<c>d (b<d)"
        return False, "❌ Структура SHORT НЕ соответствует: нужно a>b<c>d (b<d)"

def generate_market_data(base_price, num_bars=60):
    """Генерирует реалистичный рыночный график (бары + объем) для визуального анализа."""
    np.random.seed(42) # Фиксируем seed, чтобы график не прыгал при каждом клике
    dates = pd.date_range(end=datetime.today(), periods=num_bars, freq="D")
    
    # Генерируем волнообразный тренд, чтобы было похоже на реальный рынок
    trend = np.linspace(0, 1, num_bars) * base_price * 0.05
    wave = np.sin(np.linspace(0, 3 * np.pi, num_bars)) * base_price * 0.03
    noise = np.random.normal(0, base_price * 0.005, num_bars)
    
    closes = base_price + trend + wave + noise
    opens = np.roll(closes, 1)
    opens[0] = base_price
    
    highs = np.maximum(opens, closes) + np.abs(np.random.normal(0, base_price * 0.002, num_bars))
    lows = np.minimum(opens, closes) - np.abs(np.random.normal(0, base_price * 0.002, num_bars))
    
    volumes = np.random.randint(1000, 15000, num_bars)
    
    return pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes
    }, index=dates)

def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- 1. Данные контракта ----------
    iss_df = fetch_moex_forts()
    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty else pd.DataFrame()
    
    market = to_float(iss_row.iloc[0]["LAST"]) or to_float(iss_row.iloc[0]["PREVSETTLEPRICE"]) if not iss_row.empty else 100000.0
    go = get_margin(go_df, ticker, "КСУР", "LONG") or (to_float(iss_row.iloc[0]["INITIALMARGIN"]) if not iss_row.empty else 25000.0)
    step_price = to_float(vlookup(api_df, ticker, 6)) or 10.0
    step_cost = to_float(vlookup(api_df, ticker, 17)) or 16.2
    pv = _div(step_cost, step_price)

    # ---------- 2. Состояние рынка ----------
    state = st.session_state["market_state"].get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
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

    # ---------- 3. РЫНОЧНЫЙ ГРАФИК (Всегда виден) ----------
    st.markdown("#### 📊 График рынка")
    
    # Генерируем базовые данные для графика на основе рыночной цены
    df_chart = generate_market_data(market)
    
    # Создаем фигуру Plotly (Цена + Объем)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])

    # Бары OHLC (Черные)
    fig.add_trace(go.Ohlc(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'],
        increasing_line_color='black', decreasing_line_color='black', name='Рынок'
    ), row=1, col=1)

    # Объем
    colors = ['black' if c >= o else 'gray' for o, c in zip(df_chart['Open'], df_chart['Close'])]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, name='Объем'), row=2, col=1)

    # ---------- 4. ВВОД A-B-C-D и НАЛОЖЕНИЕ ЗИГЗАГА ----------
    st.markdown("#### 🧩 Торгуемый зигзаг (A-B-C-D)")
    st.caption("Введите ценовые уровни. Линия зигзага появится на графике сверху.")
    
    c1, c2, c3, c4 = st.columns(4)
    p_a = c1.number_input("Точка A", value=None, step=100.0, format="%.2f", key=key("p_a"))
    p_b = c2.number_input("Точка B", value=None, step=100.0, format="%.2f", key=key("p_b"))
    p_c = c3.number_input("Точка C", value=None, step=100.0, format="%.2f", key=key("p_c"))
    p_d = c4.number_input("Точка D", value=None, step=100.0, format="%.2f", key=key("p_d"))

    all_filled = all(x is not None for x in [p_a, p_b, p_c, p_d])

    # Если все точки введены, добавляем зигзаг на график
    if all_filled:
        # Привязываем точки к последним 4-м значимым барам (для визуализации)
        # Берем индексы: -40, -25, -10, -1
        zigzag_x = [df_chart.index[-40], df_chart.index[-25], df_chart.index[-10], df_chart.index[-1]]
        zigzag_y = [p_a, p_b, p_c, p_d]
        
        fig.add_trace(go.Scatter(
            x=zigzag_x, y=zigzag_y,
            mode='lines+markers+text',
            text=['A', 'B', 'C', 'D'],
            textposition='top center',
            textfont=dict(size=14, color='blue'),
            line=dict(color='blue', width=3),
            marker=dict(size=8, color='blue'),
            name='Зигзаг'
        ), row=1, col=1)

        zigzag_ok, zigzag_msg = check_zigzag_pattern(p_a, p_b, p_c, p_d, direction)
        if zigzag_ok:
            st.success(zigzag_msg)
        else:
            st.warning(zigzag_msg)
    else:
        st.info("👆 Заполните все 4 точки, чтобы увидеть, как они ложатся на график.")

    # Настройка внешнего вида графика
    fig.update_layout(
        height=500, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor='white', paper_bgcolor='white',
        xaxis_rangeslider_visible=False, showlegend=False
    )
    fig.update_xaxes(showgrid=True, gridcolor='lightgray')
    fig.update_yaxes(showgrid=True, gridcolor='lightgray', side='right')

    st.plotly_chart(fig, use_container_width=True)

    # ---------- 5. Параметры сделки и расчеты ----------
    if not all_filled:
        return

    # Проверка логики расчета
    avg_entry = p_c
    sl_price = p_a if direction == "LONG" else p_b
    sl_points = abs(avg_entry - sl_price)
    
    if sl_points <= 0:
        st.error("Стоп (SL) находится на уровне входа или неверно задан.")
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
    margin_used = contracts * go

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
