import streamlit as st
import pandas as pd
from data import vlookup, to_float, get_margin
from rules import (
    TREND_VALUES, TRADE_TYPES, DIRECTION_VALUES,
    RISK_LEVELS, RISK_LEVEL_DESCRIPTIONS, RISK_LEVEL_ICONS,
    build_formula, lookup, find_alternatives,
)


def _div(a, b, default=0.0):
    return a / b if b else default


def render_trade_planner(*, ticker, api_df, go_df, md_df, deposit,
                         default_risk_pct, rules_map):
    """Калькулятор позиции по одному конкретному тикеру."""
    key = lambda n: f"deal_{ticker}_{n}"     # уникальные ключи для каждого тикера

    st.subheader(f"🎯 Позиция: {ticker}")

    # ---------- Состояние рынка ----------
    st.markdown("#### 📡 Состояние рынка")
    s1, s2, s3, s4 = st.columns(4)
    trend      = s1.selectbox("Тренд",     TREND_VALUES,  key=key("tr"))
    wave       = s2.selectbox("Волна",     TREND_VALUES,  key=key("wv"))
    tendency   = s3.selectbox("Тенденция", TREND_VALUES,  key=key("tn"))
    trade_type = s4.selectbox("Вид сделки", TRADE_TYPES,  key=key("tt"))

    direction = st.radio(
        "Направление сделки", DIRECTION_VALUES, horizontal=True, key=key("dir")
    )

    formula_key = build_formula(trend, wave, tendency, trade_type, direction)
    st.caption(f"Ключ правила: `{formula_key}`")

    with st.expander("📖 Все правила для этого состояния рынка", expanded=False):
        st.dataframe(
            pd.DataFrame(find_alternatives(rules_map, trend, wave, tendency)),
            use_container_width=True, hide_index=True,
        )

    # ---------- Проверка правила ----------
    rule = lookup(rules_map, trend, wave, tendency, trade_type, direction)

    if rule is None:
        st.error(f"❌ **НЕТ СДЕЛКИ** — нет правила для «{formula_key}».")
        st.info("Откройте блок «Все правила» выше — там видно допустимые варианты.")
        return

    if rule["is_forbidden"]:
        st.error("⛔ Комбинация помечена как **«Не торгуется»**. Сделка заблокирована.")
        return

    if rule["direction"] and rule["direction"] != direction:
        st.error(f"❌ Правило требует **{rule['direction']}**, а выбрано {direction}.")
        return

    st.success(f"✅ **Сделка разрешена** · {direction}")
    st.markdown(f"**📝 Правило торговли:** {rule['description']}")

    risk_level = rule["risk_level"]
    st.markdown(
        f"**🛡️ Уровень риска (из правила):** "
        f"{RISK_LEVEL_ICONS.get(risk_level,'')} **{risk_level}** — "
        f"{RISK_LEVEL_DESCRIPTIONS[risk_level]}"
    )

    override = st.checkbox(
        "Переопределить уровень ГО вручную",
        key=key("override"),
        help="По умолчанию используется уровень из правила",
    )
    if override:
        risk_level = st.selectbox(
            "Уровень ГО", RISK_LEVELS,
            index=RISK_LEVELS.index(risk_level),
            key=key("risk_override"),
        )
        st.warning(
            f"⚠️ Ручной override: **{risk_level}** "
            f"({RISK_LEVEL_DESCRIPTIONS[risk_level]}). "
            f"Правило требовало **{rule['risk_level']}**."
        )

    # ---------- Спецификация контракта ----------
    code       = vlookup(api_df, ticker, 9)
    step_price = to_float(vlookup(api_df, ticker, 6))
    step_cost  = to_float(vlookup(api_df, ticker, 17))
    market     = to_float(vlookup(md_df,  ticker, 9))
    go         = get_margin(go_df, ticker, risk_level, direction)
    pv         = _div(step_cost, step_price)

    missing = []
    if step_price <= 0: missing.append("шаг цены")
    if step_cost  <= 0: missing.append("стоимость шага")
    if go         <= 0: missing.append(f"ГО ({risk_level}/{direction})")
    if market     <= 0: missing.append("рыночная цена")

    h = st.columns(5)
    h[0].metric("Код",     code)
    h[1].metric("Шаг",     f"{step_price:g}" if step_price else "—")
    h[2].metric("Ст.шага", f"{step_cost:g} ₽" if step_cost else "—")
    h[3].metric(f"ГО {risk_level}", f"{go:,.0f} ₽" if go else "—")
    h[4].metric("Рынок",   f"{market:,.2f}" if market else "—")

    if missing:
        st.error(f"Нет данных: **{', '.join(missing)}**. Проверьте листы API/ГО/MARKETDATA.")
        return

    # ---------- Параметры расчёта ----------
    st.markdown("#### ⚙️ Параметры расчёта")
    p1, p2, p3 = st.columns(3)
    risk_pct = p1.number_input(
        "Риск, % от депозита",
        min_value=0.1, max_value=100.0,
        value=float(default_risk_pct), step=0.1,
        key=key("risk"),
        help="По умолчанию — из бокового меню. Можно изменить для этой позиции.",
    )
    rr_safe  = p2.number_input("Безопасный RR", value=3.0, step=0.5, key=key("rr"))
    tp_price = p3.number_input("TP", value=float(market), key=key("tp"))
    sl_price = st.number_input("SL",  value=float(market), key=key("sl"))

    # ---------- Точки входа ----------
    st.markdown("#### 📍 Точки входа")
    entries = st.data_editor(
        pd.DataFrame({"Цена": [0.0] * 4, "Контрактов": [0] * 4}),
        num_rows="dynamic", key=key("entries"),
        column_config={
            "Цена":       st.column_config.NumberColumn(format="%.2f", min_value=0.0),
            "Контрактов": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    entries = entries[(entries["Цена"] > 0) & (entries["Контрактов"] > 0)]
    if entries.empty:
        st.info("Добавьте хотя бы одну точку входа.")
        return

    contracts   = int(entries["Контрактов"].sum())
    avg_entry   = (entries["Цена"] * entries["Контрактов"]).sum() / contracts
    margin_used = contracts * go

    if margin_used > deposit * 0.75:
        st.warning(f"Загрузка ГО {margin_used/deposit*100:.1f}% > 75% депозита")

    # ---------- Расчёты ----------
    delta_tp = (tp_price - avg_entry) if direction == "LONG" else (avg_entry - tp_price)
    delta_sl = (avg_entry - sl_price) if direction == "LONG" else (sl_price - avg_entry)

    profit_rub  = delta_tp * pv * contracts
    loss_rub    = delta_sl * pv * contracts
    risk_budget = deposit * risk_pct / 100
    mm_ok       = risk_budget > loss_rub
    rr_actual   = _div(profit_rub, loss_rub)
    rr_ok       = rr_actual >= rr_safe
    max_by_risk = int(risk_budget / (abs(delta_sl) * pv)) if delta_sl and pv else 0
    rr_price    = avg_entry + delta_sl * rr_safe

    # ---------- Результаты ----------
    st.markdown("#### 📊 Результаты")
    a, b, c, d = st.columns(4)
    a.metric("Ср. вход",       f"{avg_entry:,.2f}")
    b.metric("Контрактов",     contracts)
    c.metric("Убыток на SL",   f"−{loss_rub:,.0f} ₽")
    d.metric("Прибыль на TP",  f"+{profit_rub:,.0f} ₽")

    a, b, c, d = st.columns(4)
    a.metric("Бюджет риска",   f"{risk_budget:,.0f} ₽")
    b.metric("MM",             "✅ OK" if mm_ok else "❌ превышен")
    c.metric("RR факт",        f"{rr_actual:.2f}")
    d.metric("Макс. контрактов", max_by_risk)

    if not mm_ok:
        st.error(f"Убыток SL ({loss_rub:,.0f} ₽) > бюджета риска ({risk_budget:,.0f} ₽)")
    if not rr_ok:
        st.warning(f"RR {rr_actual:.2f} < {rr_safe:.2f} — цена для RR-цели: {rr_price:,.2f}")

    # ---------- Текущий P/L ----------
    cur_delta = (market - avg_entry) if direction == "LONG" else (avg_entry - market)
    cur_pnl   = cur_delta * pv * contracts

    a, b, c, d = st.columns(4)
    a.metric("Текущий P/L",       f"{cur_pnl:+,.0f} ₽")
    b.metric("P/L к ГО",          f"{_div(cur_pnl, margin_used)*100:+.2f}%")
    c.metric("P/L к депозиту",    f"{_div(cur_pnl, deposit)*100:+.2f}%")
    d.metric(
        "Статус",
        "🛑 SL" if ((direction == "LONG"  and market < sl_price) or
                    (direction == "SHORT" and market > sl_price))
        else "🟢 в работе",
    )
