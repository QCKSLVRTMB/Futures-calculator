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

    st.markdown("#### 📖 Справка по торговле")
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
        
    pv = _div(step_cost, step_price) # Стоимость 1 пункта в рублях

    if step_price <= 0 or step_cost <= 0 or go <= 0 or market <= 0:
        st.error("Нет данных по контракту (ISS или Google Sheets).")
        return

    # ---------- 3. Ввод параметров сделки ----------
    st.markdown("#### ⚙️ Параметры сделки")
    p1, p2, p3, p4 = st.columns(4)
    
    # Риск (по умолчанию 2%, как в Excel)
    risk_pct = p1.number_input("Риск (в %)", min_value=0.1, max_value=100.0, value=2.0, step=0.1, key=key("risk_pct"))
    
    # Безопасный RR (по умолчанию 3)
    rr_safe = p2.number_input("Безопасный RR", min_value=0.1, value=3.0, step=0.5, key=key("rr"))
    
    # TP и SL (по умолчанию ставим рыночную цену)
    tp_price = p3.number_input("TP (Выход)", value=float(market), key=key("tp"))
    sl_price = p4.number_input("SL (Стоп)", value=float(market), key=key("sl"))

    # ---------- 4. Точки входа (Усреднение) ----------
    st.markdown("#### 📍 Точки входа (и планируемые позиции)")
    entries = st.data_editor(
        pd.DataFrame({"Цена входа": [float(market)] + [0.0]*3, "Кол-во контрактов": [1] + [0]*3}),
        num_rows="dynamic", key=key("entries"),
        column_config={
            "Цена входа": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
            "Кол-во контрактов": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    
    # Фильтруем только заполненные строки
    entries = entries[(entries["Цена входа"] > 0) & (entries["Кол-во контрактов"] > 0)]
    if entries.empty:
        st.info("Добавьте хотя бы одну точку входа.")
        return

    # ---------- 5. РАСЧЕТЫ (Аналог Excel-листа) ----------
    
    # Базовые данные (столбец B и F в Excel)
    total_contracts = int(entries["Кол-во контрактов"].sum())                         # B15
    avg_entry = (entries["Цена входа"] * entries["Кол-во контрактов"]).sum() / total_contracts # A15
    margin_used = total_contracts * go                                                # C15
    risk_budget = deposit * risk_pct / 100                                            # G5

    # Проверка направления
    if direction == "LONG":
        if tp_price <= avg_entry: st.warning("⚠️ TP для LONG должен быть выше входа.")
        if sl_price >= avg_entry: st.warning("⚠️ SL для LONG должен быть ниже входа.")
    else:
        if tp_price >= avg_entry: st.warning("⚠️ TP для SHORT должен быть ниже входа.")
        if sl_price <= avg_entry: st.warning("⚠️ SL для SHORT должен быть выше входа.")

    # 1. Прибыль и Убыток (B6, C5)
    if direction == "LONG":
        profit_rub = (tp_price - avg_entry) * pv * total_contracts   # B6
        loss_rub = (avg_entry - sl_price) * pv * total_contracts     # C5
        delta_tp = tp_price - avg_entry
        delta_sl = avg_entry - sl_price
    else:
        profit_rub = (avg_entry - tp_price) * pv * total_contracts   # B6
        loss_rub = (sl_price - avg_entry) * pv * total_contracts     # C5
        delta_tp = avg_entry - tp_price
        delta_sl = sl_price - avg_entry

    # 2. Проверка MM (G5 > C5)
    mm_ok = risk_budget > loss_rub
    
    # 3. Потенциал RR (F6 / F7)
    rr_actual = _div(profit_rub, loss_rub)
    
    # 4. Контрактов на вход по риску
    max_by_risk = int(risk_budget / (abs(delta_sl) * pv)) if delta_sl > 0 and pv > 0 else 0

    # 5. Безопасный RR цена (O7 из Excel)
    # Формула из листа: LONG: TP - (TP-SL)*0.667; SHORT: TP - (TP-SL)*0.333
    if direction == "LONG":
        safe_rr_price = tp_price - (tp_price - sl_price) * 0.667
    else:
        safe_rr_price = tp_price - (tp_price - sl_price) * 0.333

    # 6. Допустимая ТВХ и SL (K31, K32)
    if total_contracts > 0:
        point_risk = (risk_budget / total_contracts) / pv
        if direction == "LONG":
            allowed_entry = sl_price + point_risk
            allowed_sl = avg_entry - point_risk
        else:
            allowed_entry = sl_price - point_risk
            allowed_sl = avg_entry + point_risk
    else:
        allowed_entry = allowed_sl = 0.0

    # 7. Необходимый капитал (K33)
    required_capital = _div(loss_rub * 100, risk_pct)

    # 8. Текущая прибыль (K26, K27)
    if direction == "LONG":
        cur_pnl = (market - avg_entry) * pv * total_contracts
    else:
        cur_pnl = (avg_entry - market) * pv * total_contracts

    # 9. Цены для увеличения капитала на 1% (K9, K12)
    # Чтобы увеличить маржу на 1%: нужно пройти (Margin * 0.01) / (pv * Contracts) пунктов
    move_for_margin_1pct = _div(margin_used * 0.01, pv * total_contracts)
    price_for_margin_1pct = avg_entry + move_for_margin_1pct if direction == "LONG" else avg_entry - move_for_margin_1pct
    
    move_for_deposit_1pct = _div(deposit * 0.01, pv * total_contracts)
    price_for_deposit_1pct = avg_entry + move_for_deposit_1pct if direction == "LONG" else avg_entry - move_for_deposit_1pct

    # 10. Сделка из пунктов (K34)
    points_in_deal = delta_tp / step_price if step_price else 0
    profit_from_points = (points_in_deal * step_cost) * total_contracts


    # ---------- 6. ВЫВОД РЕЗУЛЬТАТОВ ----------
    st.markdown("---")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Код", code if code != "-" else ticker)
    c2.metric("Шаг цены", f"{step_price:g}")
    c3.metric("Ст. шага", f"{step_cost:g} ₽")
    c4.metric(f"ГО ({direction})", f"{go:,.0f} ₽")
    c5.metric("Рынок", f"{market:,.2f}")

    st.markdown("#### 📊 Результаты сделки")
    
    # Блок 1: Основные цифры
    a, b, c, d = st.columns(4)
    a.metric("Средняя ТВХ", f"{avg_entry:,.2f}")
    b.metric("Всего контрактов", total_contracts)
    c.metric("Занятое ГО", f"{margin_used:,.0f} ₽")
    d.metric("Доля депозита", f"{_div(margin_used, deposit)*100:.2f}%")

    # Блок 2: Риски и Цели
    a, b, c, d = st.columns(4)
    a.metric("Убыток на SL", f"−{loss_rub:,.0f} ₽")
    b.metric("Прибыль на TP", f"+{profit_rub:,.0f} ₽")
    c.metric("Бюджет риска", f"{risk_budget:,.0f} ₽")
    d.metric("MM", "✅ OK" if mm_ok else "❌ ПРЕВЫШЕН", delta_color="inverse")
    
    if not mm_ok:
        st.error(f"Убыток по стопу ({loss_rub:,.0f} ₽) превышает допустимый риск ({risk_budget:,.0f} ₽). "
                 f"Для этой сделки нужно минимум **{required_capital:,.0f} ₽** капитала.")

    st.markdown("#### ⚖️ Оценка RR (Risk Reward)")
    a, b, c, d = st.columns(4)
    a.metric("RR факт", f"{rr_actual:.2f}")
    b.metric("Безопасный RR", f"{rr_safe:.2f}")
    c.metric("Макс. контрактов", max_by_risk)
    d.metric("Цена при Safe RR", f"{safe_rr_price:,.2f}")

    # Допустимые уровни
    st.markdown("#### 🛡️ Допустимые уровни")
    a, b = st.columns(2)
    a.metric("Допустимая ТВХ", f"{allowed_entry:,.2f}")
    b.metric("Допустимый SL", f"{allowed_sl:,.2f}")

    st.markdown("#### 💰 Текущая позиция и цели")
    a, b, c, d = st.columns(4)
    a.metric("Текущий P/L", f"{cur_pnl:+,.0f} ₽")
    b.metric("P/L к ГО", f"{_div(cur_pnl, margin_used)*100:+.2f}%")
    c.metric("Статус", "🛑 SL" if ((direction == "LONG" and market < sl_price) or (direction == "SHORT" and market > sl_price)) else "🟢 В работе")
    
    # Расчет прибыли в пунктах
    d.metric("Пунктов до TP", f"{points_in_deal:.2f}")
    st.caption(f"Сделка из {points_in_deal:.1f} пунктов принесет прибыль в размере **{profit_from_points:,.2f} ₽**")

    st.markdown("#### 🎯 Цены закрытия для увеличения капитала на 1%")
    a, b = st.columns(2)
    a.metric("Для +1% к ГО", f"{price_for_margin_1pct:,.2f}", help="Достаточно закрыть позицию по этой цене")
    b.metric("Для +1% к депозиту", f"{price_for_deposit_1pct:,.2f}", help="Достаточно закрыть позицию по этой цене")
