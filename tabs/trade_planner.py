import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from data import vlookup, to_float, get_margin, fetch_moex_forts
from rules import (
    RISK_LEVELS, RISK_LEVEL_DESCRIPTIONS, RISK_LEVEL_ICONS, 
    lookup
)
# Импортируем компонент для графиков
from lightweight_charts_v5 import lightweight_charts_v5_component

def _div(a, b, default=0.0):
    return a / b if b else default

# ==========================================
# НОВАЯ ЛОГИКА: ЗИГЗАГ ТЕНДЕНЦИИ
# ==========================================
def check_zigzag_pattern(prices, direction):
    """
    Проверяет паттерн зигзага.
    prices: список последних цен (как минимум 4 экстремума или ключевые точки)
    Для LONG: a < b > c < d, и b > d (торгуем результативное движение CD)
    Для SHORT: a > b < c > d, и b < d
    """
    if len(prices) < 4:
        return False, "Недостаточно данных для анализа зигзага"
    
    a, b, c, d = prices[-4], prices[-3], prices[-2], prices[-1]
    
    if direction == "LONG":
        # Условие: a < b > c < d и b > d
        if a < b and b > c and c < d and b > d:
            return True, "✅ Структура зигзага соответствует: a<b>c<d (b>d)"
        else:
            return False, "❌ Структура не соответствует: a<b>c<d (b>d)"
    else: # SHORT
        # Условие: a > b < c > d и b < d
        if a > b and b < c and c > d and b < d:
            return True, "✅ Структура зигзага соответствует: a>b<c>d (b<d)"
        else:
            return False, "❌ Структура не соответствует: a>b<c>d (b<d)"

# ==========================================
# ОСНОВНАЯ ФУНКЦИЯ РЕНДЕРА
# ==========================================
def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- 1. Данные и Справка ----------
    state = st.session_state["market_state"].get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
    trend, wave, tendency = state["trend"], state["wave"], state["tendency"]

    st.markdown(f"#### 📡 Состояние рынка: Тренд **{trend.capitalize()}** | Волна **{wave.capitalize()}** | Тенденция **{tendency.capitalize()}**")

    # ... (Код для формирования options_labels и scenarios как в предыдущей версии) ...
    # Для краткости я опускаю блок построения таблицы справки, он остается без изменений.
    # Предполагаем, что selected_label уже выбран и мы знаем direction, rule.
    # (Вставьте сюда ваш существующий код для options_labels и selected_label)
    
    # ЗАГЛУШКА для демонстрации (замените на ваш реальный код выбора сценария)
    # В реальном коде здесь должен быть selectbox и логика выбора rule
    # ...
    
    # Допустим, мы выбрали сценарий:
    # tt, direction, rule, _ = valid_options[selected_label]
    # Для примера возьмем direction = "LONG"
    direction = "LONG" # Замените на реальное значение из выбора

    # ---------- 2. Данные контракта ----------
    # ... (Загрузка данных из ISS / Google Sheets как в предыдущей версии) ...
    # iss_df = fetch_moex_forts()
    # ... получение market, step_price, step_cost, go ...
    
    # ЗАГЛУШКА для демонстрации
    market = 100000.0
    step_price = 10.0
    step_cost = 16.2251
    go = 24529.0
    pv = _div(step_cost, step_price)

    # ---------- 3. БЛОК ЗИГЗАГА ТЕНДЕНЦИИ ----------
    st.markdown("---")
    st.markdown("#### 🧩 Анализ структуры (Зигзаг тенденции)")
    
    # В реальном коде здесь нужно загрузить последние 4 экстремума с графика.
    # Для примера используем заглушку, которая всегда возвращает True для LONG.
    # В продакшене вы должны брать эти данные из API TradingView или MOEX.
    mock_prices = [99000, 101000, 99500, 100500] # Пример: a, b, c, d
    zigzag_ok, zigzag_msg = check_zigzag_pattern(mock_prices, direction)
    
    if zigzag_ok:
        st.success(zigzag_msg)
    else:
        st.warning(zigzag_msg)
        st.info("Рекомендуется дождаться формирования корректной структуры (результативного движения CD).")

    # ---------- 4. Ввод параметров (Новый RR) ----------
    st.markdown("#### ⚙️ Параметры сделки")
    
    p1, p2 = st.columns(2)
    risk_pct = p1.number_input("Риск (в %)", min_value=0.1, max_value=100.0, value=1.0, step=0.1, key=key("risk_pct"))
    
    # НОВЫЙ ФОРМАТ RR: 1 к 3
    st.markdown("**Risk Reward (RR)**")
    rr_mode = st.radio("Режим:", ["Автоматический (1 к 3)", "Ручной"], horizontal=True, key=key("rr_mode"))
    
    if rr_mode == "Автоматический (1 к 3)":
        # SL = 1% от депозита (риск), TP = 3 * SL (цель)
        risk_amount = deposit * (risk_pct / 100)
        # Логика расчета TP на основе SL
        # ...
        st.info(f"Риск: 1 часть = {risk_pct}% депозита. Цель: 3 части.")
        # Здесь вы можете автоматически рассчитывать TP и SL на основе этих пропорций
        # и подставлять их в поля ниже.
    else:
        # Ручной ввод, как раньше
        pass
    
    # Поля TP и SL (будут автоматически заполнены в зависимости от режима)
    p3, p4 = st.columns(2)
    tp_price = p3.number_input("TP (Выход)", value=float(market), key=key("tp"))
    sl_price = p4.number_input("SL (Стоп)", value=float(market), key=key("sl"))

    # ... (Остальной код расчетов и вывода результатов) ...

    # ---------- 5. ГРАФИКИ TRADINGVIEW ----------
    st.markdown("---")
    st.markdown("#### 📊 Графики (TradingView)")
    
    # Выбор таймфрейма
    tf = st.radio("Таймфрейм:", ["D1", "H1", "M10"], horizontal=True, key=key("tf"))
    
    # Формируем символ для TradingView (склейка)
    # Пример: для RIZ6 -> RI1! (или FOREXCOM:RI1!)
    # Вам нужно будет настроить маппинг тикеров на символы TradingView
    tv_symbol = f"MOEX:{ticker}1!" # Пример для MOEX
    
    # Заглушка для данных (в реальном коде здесь нужно загружать OHLC)
    # Для демонстрации создадим фейковые данные
    dates = pd.date_range(start="2026-01-01", periods=100, freq="D")
    chart_data = []
    price = 100000
    for d in dates:
        price += np.random.normal(0, 100)
        chart_data.append({
            "time": d.strftime("%Y-%m-%d"),
            "open": price,
            "high": price + 500,
            "low": price - 500,
            "close": price + 200,
        })
    
    # Рендер графика
    lightweight_charts_v5_component(
        name=f"{ticker} Chart",
        charts=[{
            "chart": {"layout": {"background": {"color": "#FFFFFF"}}},
            "series": [{
                "type": "Candlestick",
                "data": chart_data,
                "options": {
                    "upColor": "#26a69a",
                    "downColor": "#ef5350",
                }
            }],
            "height": 400
        }],
        height=400
    )

    # ... (Остальной код вывода результатов) ...
