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

def generate_ohlc_from_zigzag(a, b, c, d):
    """
    Генерирует фейковые бары OHLC, чтобы визуализировать структуру зигзага.
    Создает по 10 свечей на каждый отрезок: A->B, B->C, C->D.
    """
    opens, highs, lows, closes, dates = [], [], [], [], []
    
    segments = [(a, b), (b, c), (c, d)]
    current_date = datetime.today() - timedelta(days=30)
    
    prev_close = a
    
    for start, end in segments:
        # Генерируем плавное движение от start к end
        prices = np.linspace(start, end, 10)
        
        for i, p in enumerate(prices):
            open_p = prev_close
            close_p = p
            # Добавляем шум для High/Low, чтобы было похоже на реальные свечи
            high_p = max(open_p, close_p) + abs(np.random.normal(0, abs(end-start)*0.05))
            low_p = min(open_p, close_p) - abs(np.random.normal(0, abs(end-start)*0.05))
            
            opens.append(open_p)
            closes.append(close_p)
            highs.append(high_p)
            lows.append(low_p)
            dates.append(current_date)
            
            prev_close = close_p
            current_date += timedelta(days=1)
            
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes}, index=dates)

def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- 1. Состояние рынка и Справка ----------
    state = st.session_state["market_state"].get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
    trend, wave, tendency = state["trend"], state["wave"], state["tendency"]

    st.markdown(f"#### 📡 Состояние рынка: Тренд **{trend.capitalize()}** | Волна **{wave.capitalize()}** | Тенденция **{tendency.capitalize()}**")

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

    selected_label = st.selectbox("🎯 Выберите сценарий для расчета:", list(options_labels.keys()), key=key("scenario"))
    tt, direction, rule = options_labels[selected_label]
    
    risk_level = rule["risk_level"]
    st.markdown(f"**🛡️ Уровень ГО:** {RISK_LEVEL_ICONS.get(risk_level,'')} **{risk_level}**")

    # ---------- 2. Данные контракта ----------
    iss_df = fetch_moex_forts()
    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty else pd.DataFrame()
    
    market = to_float(iss_row.iloc[0]["LAST"]) or to_float(iss_row.iloc[0]["PREVSETTLEPRICE"]) if not iss_row.empty else 100000.0
    go = get_margin(go_df, ticker, risk_level, direction) or (to_float(iss_row.iloc[0]["INITIALMARGIN"]) if not iss_row.empty else 25000.0)
    
    step_price = to_float(vlookup(api_df, ticker, 6)) or 10.0
    step_cost = to_float(vlookup(api_df, ticker, 17)) or 16.2
    pv = _div(step_cost, step_price)

    # ---------- 3. Ввод точек зигзага (A, B, C, D) ----------
    st.markdown("---")
    st.markdown("#### 🧩 Торгуемый зигзаг (A-B-C-D)")
    st.caption("Введите ценовые уровни экстремумов. По умолчанию поля пустые.")
    
    c1, c2, c3, c4 = st.columns(4)
    # Используем value=None для пустых полей по умолчанию
    p_a = c1.number_input("Точка A", value=None, step=100.0, format="%.2f", key=key("p_a"))
    p_b = c2.number_input("Точка B", value=None, step=100.0, format="%.2f", key=key("p_b"))
    p_c = c3.number_input("Точка C", value=None, step=100.0, format="%.2f", key=key("p_c"))
    p_d = c4.number_input("Точка D", value=None, step=100.0, format="%.2f", key=key("p_d"))

    # Проверяем, что все поля заполнены
    all_filled = all(x is not None for x in [p_a, p_b, p_c, p_d])
    
    if all_filled:
        zigzag_ok, zigzag_msg = check_zigzag_pattern(p_a, p_b, p_c, p_d, direction)
        if zigzag_ok:
            st.success(zigzag_msg)
        else:
            st.warning(zigzag_msg)
            
        # Проверка логики расчета SL/TP
        avg_entry = p_c
        sl_price = p_a if direction == "LONG" else p_b
        sl_points = abs(avg_entry - sl_price)
        
        if sl_points <= 0:
            st.error("Стоп (SL) находится на уровне входа или неверно задан. Проверьте точки A, B, C.")
            return
            
        # Логика проверки, что TP в правильную сторону
        if direction == "LONG" and p_d <= p_c:
            st.error("Для LONG точка D должна быть выше C (движение вверх).")
            return
        if direction == "SHORT" and p_d >= p_c:
            st.error("Для SHORT точка D должна быть ниже C (движение вниз).")
            return
    else:
        st.info("👆 Заполните все 4 точки (A, B, C, D), чтобы увидеть структуру и рассчитать сделку.")

    # ---------- 4. Параметры сделки ----------
    st.markdown("#### ⚙️ Параметры сделки")
    
    p1, p2 = st.columns(2)
    risk_pct = p1.number_input("Риск (в % от депозита)", min_value=0.1, max_value=100.0, value=1.0, step=0.1, key=key("risk_pct"))
    rr_ratio = p2.number_input("Risk Reward (1 к ...)", min_value=1.0, value=3.0, step=0.5, key=key("rr_ratio"))
    
    if all_filled:
        risk_budget = deposit * (risk_pct / 100)
        # TP рассчитываем от точки входа (C) на основе RR
        tp_price = avg_entry + (sl_points * rr_ratio) if direction == "LONG" else avg_entry - (sl_points * rr_ratio)
        
        st.info(f"Вход (C): **{avg_entry:,.2f}** | SL (A/B): **{sl_price:,.2f}** | TP: **{tp_price:,.2f}** (RR 1:{rr_ratio})")
        
        max_contracts_by_risk = int(risk_budget / (sl_points * pv)) if pv > 0 else 0
        
        if max_contracts_by_risk < 1:
            st.error("Бюджет риска слишком мал для данной структуры (размер SL слишком большой).")
            return

        contracts = st.number_input("Количество контрактов", min_value=1, max_value=max_contracts_by_risk, value=max_contracts_by_risk, key=key("contracts"))
        margin_used = contracts * go
    else:
        contracts = 0
        margin_used = 0
        tp_price = 0
        sl_points = 0
        risk_budget = 0

    # ---------- 5. График (OHLC + Volume + Zigzag) ----------
    st.markdown("---")
    st.markdown("#### 📊 График структуры")
    
    if all_filled:
        # Генерируем бары на основе введенных точек
        df_chart = generate_ohlc_from_zigzag(p_a, p_b, p_c, p_d)
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.75, 0.25])

        # 1. Бары OHLC (Черные)
        fig.add_trace(go.Ohlc(
            x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], 
            low=df_chart['Low'], close=df_chart['Close'],
            increasing_line_color='black', decreasing_line_color='black',
            name='OHLC'
        ), row=1, col=1)

        # 2. Зигзаг (A-B-C-D)
        # Привязываем точки к индексам сгенерированных свечей: 0 (A), 10 (B), 20 (C), 29 (D)
        zigzag_x = [df_chart.index[0], df_chart.index[9], df_chart.index[19], df_chart.index[29]]
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

        # 3. Гистограмма объема (Снизу)
        # Объем генерируем случайно для визуализации
        np.random.seed(42)
        volumes = np.random.randint(1000, 10000, size=len(df_chart))
        colors = ['black' if close >= open_p else 'gray' for open_p, close in zip(df_chart['Open'], df_chart['Close'])]
        
        fig.add_trace(go.Bar(
            x=df_chart.index, y=volumes,
            marker_color=colors, name='Volume'
        ), row=2, col=1)

        fig.update_layout(
            height=600,
            margin=dict(l=10, r=10, t=30, b=10),
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis_rangeslider_visible=False,
            showlegend=False
        )
        fig.update_xaxes(showgrid=True, gridcolor='lightgray')
        fig.update_yaxes(showgrid=True, gridcolor='lightgray', side='right')

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("График появится после заполнения всех точек A, B, C, D.")

    # ---------- 6. Результаты ----------
    if all_filled and contracts > 0:
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
