import streamlit as st
import pandas as pd
from data import vlookup, to_float, get_margin, fetch_moex_forts
from rules import (
    RISK_LEVELS, RISK_LEVEL_DESCRIPTIONS, RISK_LEVEL_ICONS, lookup
)

def _div(a, b, default=0.0):
    return a / b if b else default

def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit, rules_map):
    key = lambda n: f"deal_{ticker}_{n}"
    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- 1. Получаем состояние рынка из глобального хранилища ----------
    state = st.session_state["market_state"].get(ticker, {"trend": "вверх", "wave": "вверх", "tendency": "вверх"})
    trend, wave, tendency = state["trend"], state["wave"], state["tendency"]

    st.markdown("#### 📡 Текущее состояние рынка (с вкладки Данные):")
    st.info(f"Тренд: **{trend.capitalize()}** | Волна: **{wave.capitalize()}** | Тенденция: **{tendency.capitalize()}**")

    # ---------- 2. Формируем доступные сценарии (Зеленые/Красные/Серые) ----------
    options = {}
    table_rows = []
    
    for tt in ["трендовая", "контртренд"]:
        for d in ["LONG", "SHORT"]:
            rule = lookup(rules_map, trend, wave, tendency, tt, d)
            
            # Если правило есть в таблице
            if rule is not None:
                is_forbidden = rule["is_forbidden"]
                status = "⛔ Не торгуется" if is_forbidden else "✅ Разрешено"
                
                if is_forbidden:
                    label = f"⚪️ {tt.capitalize()} {d}"
                    color = "#e2e3e5" # Серый
                elif tt == "трендовая":
                    label = f"🟢 {tt.capitalize()} {d}"
                    color = "#d4edda" # Зеленый
                else:
                    label = f"🔴 {tt.capitalize()} {d} (Рискованно)"
                    color = "#f8d7da" # Красный
                
                options[label] = (tt, d, rule, not is_forbidden)
                
                # Данные для красивого отображения справки
                table_rows.append({
                    "Сценарий": f"{tt.capitalize()} {d}",
                    "Статус": status,
                    "Описание правила": rule["description"] if rule["description"] else "-",
                    "_color": color
                })

    if not options:
        st.error("❌ Для данного состояния рынка нет настроенных правил.")
        return

    st.markdown("#### 📖 Справка по сценариям (из правил)")
    df_help = pd.DataFrame(table_rows)
    
    # Красим строки в зеленый/красный/серый (как на скриншоте)
    def _row_color(row):
        return [f"background-color: {row['_color']}"] * len(row)
    
    st.dataframe(
        df_help.style.apply(_row_color, axis=1).hide(axis="columns", subset=["_color"]),
        use_container_width=True,
        hide_index=True
    )

    # ---------- 3. Выбор сценария ----------
    st.markdown("#### 🎯 Выбор сценария для расчета")
    selected_label = st.radio("Выберите сценарий:", list(options.keys()), key=key("scenario"))
    tt, direction, rule, is_valid = options[selected_label]

    if not is_valid:
        st.error("⛔ Комбинация помечена как **«Не торгуется»**. Выберите другой сценарий.")
        return

    if tt == "трендовая":
        st.success(f"**📝 Рекомендация (Торговля по тренду):** {rule['description']}")
    else:
        st.error(f"**📝 Рекомендация (Контртренд — повышенный риск):** {rule['description']}")

    risk_level = rule["risk_level"]
    st.markdown(f"**🛡️ Уровень ГО:** {RISK_LEVEL_ICONS.get(risk_level,'')} **{risk_level}** — {RISK_LEVEL_DESCRIPTIONS[risk_level]}")

    override = st.checkbox("Переопределить ГО вручную", key=key("override"))
    if override:
        risk_level = st.selectbox("Уровень ГО", RISK_LEVELS, index=RISK_LEVELS.index(risk_level), key=key("risk_override"))
        st.warning(f"⚠️ Ручной override: **{risk_level}** ({RISK_LEVEL_DESCRIPTIONS[risk_level]}). Правило требовало **{rule['risk_level']}**.")

    # ---------- 4. Спецификация контракта ----------
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

    h = st.columns(5)
    h[0].metric("Код", code if code != "-" else ticker)
    h[1].metric("Шаг", f"{step_price:g}")
    h[2].metric("Ст.шага", f"{step_cost:g} ₽")
    h[3].metric(f"ГО {risk_level}", f"{go:,.0f} ₽")
    h[4].metric("Рынок", f"{market:,.2f}")

    # ---------- 5. Параметры расчета ----------
    st.markdown("#### ⚙️ Параметры расчета")
    p1, p2, p3 = st.columns(3)
    risk_pct = p1.number_input(
        "Риск, % от депозита", min_value=0.1, max_value=100.0, value=1.0, step=0.1, key=key("risk_pct"),
        help="Индивидуальный риск для этой позиции"
    )
    rr_safe  = p2.number_input("Безопасный RR", value=3.0, step=0.5, key=key("rr"))
    tp_price = p3.number_input("TP", value=float(market), key=key("tp"))
    sl_price = st.number_input("SL", value=float(market), key=key("sl"))

    # ---------- 6. Точки входа ----------
    st.markdown("#### 📍 Точки входа")
    entries = st.data_editor(
        pd.DataFrame({"Цена": [0.0] * 4, "Контрактов": [0] * 4}),
        num_rows="dynamic", key=key("entries"),
        column_config={
            "Цена": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
            "Контрактов": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    entries = entries[(entries["Цена"] > 0) & (entries["Контрактов"] > 0)]
    if entries.empty:
        st.info("Добавьте хотя бы одну точку входа.")
        return

    contracts = int(entries["Контрактов"].sum())
    avg_entry = (entries["Цена"] * entries["Контрактов"]).sum() / contracts
    margin_used = contracts * go

    if margin_used > deposit * 0.75:
        st.warning(f"Загрузка ГО {margin_used/deposit*100:.1f}% > 75% депозита")

    # ---------- 7. Расчёты ----------
    delta_tp = (tp_price - avg_entry) if direction == "LONG" else (avg_entry - tp_price)
    delta_sl = (avg_entry - sl_price) if direction == "LONG" else (sl_price - avg_entry)

    profit_rub = delta_tp * pv * contracts
    loss_rub = delta_sl * pv * contracts
    risk_budget = deposit * risk_pct / 100
    mm_ok = risk_budget > loss_rub
    rr_actual = _div(profit_rub, loss_rub)
    rr_ok = rr_actual >= rr_safe
    max_by_risk = int(risk_budget / (abs(delta_sl) * pv)) if delta_sl and pv else 0

    # ---------- 8. Результаты ----------
    st.markdown("#### 📊 Результаты")
    a, b, c, d = st.columns(4)
    a.metric("Ср. вход", f"{avg_entry:,.2f}")
    b.metric("Контрактов", contracts)
    c.metric("Убыток на SL", f"−{loss_rub:,.0f} ₽")
    d.metric("Прибыль на TP", f"+{profit_rub:,.0f} ₽")

    a, b, c, d = st.columns(4)
    a.metric("Бюджет риска", f"{risk_budget:,.0f} ₽")
    b.metric("MM", "✅ OK" if mm_ok else "❌ превышен")
    c.metric("RR факт", f"{rr_actual:.2f}")
    d.metric("Макс. контрактов", max_by_risk)

    cur_delta = (market - avg_entry) if direction == "LONG" else (avg_entry - market)
    cur_pnl = cur_delta * pv * contracts

    a, b, c, d = st.columns(4)
    a.metric("Текущий P/L", f"{cur_pnl:+,.0f} ₽")
    b.metric("P/L к ГО", f"{_div(cur_pnl, margin_used)*100:+.2f}%")
    c.metric("P/L к депозиту", f"{_div(cur_pnl, deposit)*100:+.2f}%")
