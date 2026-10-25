import streamlit as st
import pandas as pd
from data import vlookup, to_float, get_margin, fetch_moex_forts
from rules import (
    RISK_LEVELS, RISK_LEVEL_DESCRIPTIONS, RISK_LEVEL_ICONS, 
    lookup
)

def _div(a, b, default=0.0):
    return a / b if b else default

def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- 1. Состояние рынка и Справка ----------
    state = st.session_state["market_state"].get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
    trend, wave, tendency = state["trend"], state["wave"], state["tendency"]

    st.markdown(f"#### 📡 Состояние рынка: Тренд **{trend.capitalize()}** | Волна **{wave.capitalize()}** | Тенденция **{tendency.capitalize()}**")

    scenarios = []
    options_labels = {}
    
    for tt in ["трендовая", "контртренд"]:
        for d in ["LONG", "SHORT"]:
            rule = lookup(trend, wave, tendency, tt, d)
            if rule is not None:
                is_forbidden = rule["is_forbidden"]
                if is_forbidden:
                    label = f"⚪️ {tt.capitalize()} {d}"
                    color = "#e2e3e5"
                    status = "⛔ Не торгуется"
                elif tt == "трендовая":
                    label = f"🟢 {tt.capitalize()} {d}"
                    color = "#d4edda"
                    status = "✅ Разрешено"
                else:
                    label = f"🔴 {tt.capitalize()} {d}"
                    color = "#f8d7da"
                    status = "⚠️ Рискованно"
                
                options_labels[label] = (tt, d, rule, not is_forbidden)
                scenarios.append({
                    "Сценарий": f"{tt.capitalize()} {d}",
                    "Статус": status,
                    "Рекомендация": rule["description"] if rule["description"] else "-",
                    "_color": color
                })

    with st.expander("📖 Справка по торговле", expanded=False):
        df_help = pd.DataFrame(scenarios)
        def _row_color(row):
            return [f"background-color: {row['_color']}; color: black;" for _ in row]
        st.dataframe(df_help.style.apply(_row_color, axis=1).hide(axis="columns", subset=["_color"]), use_container_width=True, hide_index=True)

    valid_options = {k: v for k, v in options_labels.items() if v[3]}
    if not valid_options:
        st.error("❌ Для данного состояния рынка нет разрешенных сценариев.")
        return

    selected_label = st.selectbox("🎯 Выберите сценарий для расчета:", list(valid_options.keys()), key=key("scenario"))
    tt, direction, rule, _ = valid_options[selected_label]

    risk_level = rule["risk_level"]
    st.markdown(f"**🛡️ Уровень ГО:** {RISK_LEVEL_ICONS.get(risk_level,'')} **{risk_level}**")

    # ---------- 2. Данные контракта ----------
    iss_df = fetch_moex_forts()
    iss_row = iss_df[iss_df["SECID"] == ticker] if not iss_df.empty else pd.DataFrame()
    
    code = vlookup(api_df, ticker, 9)
    step_price = to_float(vlookup(api_df, ticker, 6))
    step_cost = to_float(vlookup(api_df, ticker, 17))
    market = to_float(vlookup(md_df, ticker, 9))
    
    if not iss_row.empty:
        iss_price = to_float(iss_row.iloc[0]["LAST"])
        if iss_price == 0:
            iss_price = to_float(iss_row.iloc[0]["PREVSETTLEPRICE"])
        market = iss_price or market
        step_price = to_float(iss_row.iloc[0]["MINSTEP"]) or step_price
        step_cost = to_float(iss_row.iloc[0]["STEPPRICE"]) or step_cost
    
    go = get_margin(go_df, ticker, risk_level, direction)
    if go == 0 and not iss_row.empty:
        go = to_float(iss_row.iloc[0]["INITIALMARGIN"])
        
    pv = _div(step_cost, step_price)

    if step_price <= 0 or step_cost <= 0 or go <= 0 or market <= 0:
        st.error("Нет данных по контракту (ISS или Google Sheets).")
        return

    # ---------- 3. Ввод параметров сделки ----------
    st.markdown("#### ⚙️ Параметры сделки")
    
    # Адаптивная верстка: на мобильных колонки схлопнутся в столбик
    p1, p2 = st.columns(2)
    risk_pct = p1.number_input("Риск (в %)", min_value=0.1, max_value=100.0, value=2.0, step=0.1, key=key("risk_pct"))
    rr_safe = p2.number_input("Безопасный RR", min_value=0.1, value=3.0, step=0.5, key=key("rr"))
    
    p3, p4 = st.columns(2)
    tp_price = p3.number_input("TP (Выход)", value=float(market), key=key("tp"))
    sl_price = p4.number_input("SL (Стоп)", value=float(market), key=key("sl"))

    # ---------- 4. Точки входа (Усреднение) ----------
    st.markdown("#### 📍 Точки входа")
    entries = st.data_editor(
        pd.DataFrame({"Цена входа": [float(market)] + [0.0]*3, "Кол-во контрактов": [1] + [0]*3}),
        num_rows="dynamic", key=key("entries"),
        column_config={
            "Цена входа": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
            "Кол-во контрактов": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    
    entries = entries[(entries["Цена входа"] > 0) & (entries["Кол-во контрактов"] > 0)]
    if entries.empty:
        st.info("Добавьте хотя бы одну точку входа.")
        return

    # ---------- 5. РАСЧЕТЫ ----------
    total_contracts = int(entries["Кол-во контрактов"].sum())
    avg_entry = (entries["Цена входа"] * entries["Кол-во контрактов"]).sum() / total_contracts
    margin_used = total_contracts * go
    risk_budget = deposit * risk_pct / 100

    if direction == "LONG":
        profit_rub = (tp_price - avg_entry) * pv * total_contracts
        loss_rub = (avg_entry - sl_price) * pv * total_contracts
        delta_tp = tp_price - avg_entry
        delta_sl = avg_entry - sl_price
    else:
        profit_rub = (avg_entry - tp_price) * pv * total_contracts
        loss_rub = (sl_price - avg_entry) * pv * total_contracts
        delta_tp = avg_entry - tp_price
        delta_sl = sl_price - avg_entry

    mm_ok = risk_budget > loss_rub
    rr_actual = _div(profit_rub, loss_rub)
    max_by_risk = int(risk_budget / (abs(delta_sl) * pv)) if delta_sl > 0 and pv > 0 else 0

    if direction == "LONG":
        safe_rr_price = tp_price - (tp_price - sl_price) * 0.667
    else:
        safe_rr_price = tp_price - (tp_price - sl_price) * 0.333

    if total_contracts > 0:
        point_risk = (risk_budget / total_contracts) / pv
        allowed_entry = sl_price + point_risk if direction == "LONG" else sl_price - point_risk
        allowed_sl = avg_entry - point_risk if direction == "LONG" else avg_entry + point_risk
    else:
        allowed_entry = allowed_sl = 0.0

    required_capital = _div(loss_rub * 100, risk_pct)
    cur_pnl = (market - avg_entry) * pv * total_contracts if direction == "LONG" else (avg_entry - market) * pv * total_contracts
    
    move_for_margin_1pct = _div(margin_used * 0.01, pv * total_contracts)
    price_for_margin_1pct = avg_entry + move_for_margin_1pct if direction == "LONG" else avg_entry - move_for_margin_1pct
    
    move_for_deposit_1pct = _div(deposit * 0.01, pv * total_contracts)
    price_for_deposit_1pct = avg_entry + move_for_deposit_1pct if direction == "LONG" else avg_entry - move_for_deposit_1pct

    points_in_deal = delta_tp / step_price if step_price else 0
    profit_from_points = (points_in_deal * step_cost) * total_contracts

    # ---------- 6. ВЫВОД РЕЗУЛЬТАТОВ ----------
    st.markdown("---")
    
    # Переключатель вида
    view_mode = st.radio("Формат отображения:", ["📊 Таблица", "📱 Карточки"], horizontal=True, key=key("view"))

    # Собираем все данные в один словарь для отображения
    res_data = {
        "Показатель": [
            "Средняя ТВХ", "Всего контрактов", "Занятое ГО", "Доля депозита",
            "Убыток на SL", "Прибыль на TP", "Бюджет риска", "MM (Money Management)",
            "RR факт", "Безопасный RR", "Макс. контрактов", "Цена при Safe RR",
            "Допустимая ТВХ", "Допустимый SL",
            "Текущий P/L", "P/L к ГО", "Пунктов до TP",
            "Для +1% к ГО", "Для +1% к депозиту"
        ],
        "Значение": [
            f"{avg_entry:,.2f}", f"{total_contracts}", f"{margin_used:,.0f} ₽", f"{_div(margin_used, deposit)*100:.2f}%",
            f"−{loss_rub:,.0f} ₽", f"+{profit_rub:,.0f} ₽", f"{risk_budget:,.0f} ₽", "✅ OK" if mm_ok else "❌ ПРЕВЫШЕН",
            f"{rr_actual:.2f}", f"{rr_safe:.2f}", f"{max_by_risk}", f"{safe_rr_price:,.2f}",
            f"{allowed_entry:,.2f}", f"{allowed_sl:,.2f}",
            f"{cur_pnl:+,.0f} ₽", f"{_div(cur_pnl, margin_used)*100:+.2f}%", f"{points_in_deal:.1f}",
            f"{price_for_margin_1pct:,.2f}", f"{price_for_deposit_1pct:,.2f}"
        ]
    }

    if view_mode == "📊 Таблица":
        df_res = pd.DataFrame(res_data)
        # Разделяем таблицу на две колонки для компактности
        col1, col2 = st.columns(2)
        with col1:
            st.dataframe(df_res.iloc[:10], use_container_width=True, hide_index=True)
        with col2:
            st.dataframe(df_res.iloc[10:], use_container_width=True, hide_index=True)
            
    else:
        # Вид "Карточки" для мобильных
        st.markdown("##### 🏦 Контракт и позиция")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.write(f"**ТВХ:** {avg_entry:,.2f}")
            c1.write(f"**Кол-во:** {total_contracts} шт.")
            c2.write(f"**ГО:** {margin_used:,.0f} ₽ ({_div(margin_used, deposit)*100:.1f}%)")
            c2.write(f"**Рынок:** {market:,.2f}")

        st.markdown("##### ⚖️ Риски и Цели")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.write(f"**Убыток SL:** <span style='color:red'>−{loss_rub:,.0f} ₽</span>", unsafe_allow_html=True)
            c1.write(f"**Прибыль TP:** <span style='color:green'>+{profit_rub:,.0f} ₽</span>", unsafe_allow_html=True)
            c2.write(f"**Бюджет риска:** {risk_budget:,.0f} ₽")
            mm_color = "green" if mm_ok else "red"
            c2.write(f"**MM:** <span style='color:{mm_color}'>{'✅ OK' if mm_ok else '❌ ПРЕВЫШЕН'}</span>", unsafe_allow_html=True)
            
        st.markdown("##### 📊 Оценка RR")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.write(f"**RR факт:** {rr_actual:.2f} (Safe: {rr_safe:.2f})")
            c1.write(f"**Макс. контрактов:** {max_by_risk}")
            c2.write(f"**Цена при Safe RR:** {safe_rr_price:,.2f}")
            c2.write(f"**Пунктов до TP:** {points_in_deal:.1f}")

        st.markdown("##### 🛡️ Допустимые уровни")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            c1.write(f"**ТВХ:** {allowed_entry:,.2f}")
            c2.write(f"**SL:** {allowed_sl:,.2f}")

        st.markdown("##### 💰 Текущая позиция")
        with st.container(border=True):
            c1, c2 = st.columns(2)
            pnl_color = "green" if cur_pnl >= 0 else "red"
            c1.write(f"**Текущий P/L:** <span style='color:{pnl_color}'>{cur_pnl:+,.0f} ₽</span>", unsafe_allow_html=True)
            c1.write(f"**P/L к ГО:** {_div(cur_pnl, margin_used)*100:+.2f}%")
            c2.write(f"**Для +1% к ГО:** {price_for_margin_1pct:,.2f}")
            c2.write(f"**Для +1% к депозиту:** {price_for_deposit_1pct:,.2f}")

    # Предупреждения выводятся отдельно внизу
    if not mm_ok:
        st.error(f"Убыток по стопу ({loss_rub:,.0f} ₽) превышает допустимый риск ({risk_budget:,.0f} ₽). "
                 f"Для этой сделки нужно минимум **{required_capital:,.0f} ₽** капитала.")
