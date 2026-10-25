import pandas as pd
import streamlit as st

TREND_VALUES   = ["вверх", "вниз", "рейндж"]
TRADE_TYPES    = ["трендовая", "контртренд"]
DIRECTION_VALUES = ["LONG", "SHORT"]
RISK_LEVELS = ["НАЧ. ГО", "КНУР", "КСУР", "КПУР", "КОУР"]

RISK_LEVEL_DESCRIPTIONS = {
    "НАЧ. ГО": "базовое гарантийное обеспечение",
    "КНУР":    "начальный уровень риска",
    "КСУР":    "стандартный уровень риска",
    "КПУР":    "повышенный уровень риска",
    "КОУР":    "особый уровень риска",
}

RISK_LEVEL_ICONS = {
    "НАЧ. ГО": "🟢", "КНУР": "🟢", "КСУР": "🟡", "КПУР": "🟠", "КОУР": "🔴",
}

def build_formula(trend, wave, tendency, trade_type, direction) -> str:
    return f"{trend}{wave}{tendency}{trade_type}{direction}"

@st.cache_data(ttl=60)
def build_rules_map(rules_df: pd.DataFrame) -> dict:
    if rules_df.empty:
        return {}
    result = {}
    for _, r in rules_df.iterrows():
        fkey = str(r.get("Формула", "")).strip()
        if not fkey or fkey == "nan":
            continue
        desc = str(r.get("Описание торговли", "")).strip()
        rlvl = str(r.get("Коээфициент риска", "")).strip() or "КСУР"
        result[fkey] = {
            "description":  desc,
            "risk_level":   rlvl if rlvl in RISK_LEVELS else "КСУР",
            "direction":    str(r.get("Направление сделки", "")).strip(),
            "trade_type":   str(r.get("Тренд/контртренд", "")).strip(),
            "is_forbidden": ("не тог" in desc.lower()) or ("не торг" in desc.lower()),
        }
    return result

def lookup(rules_map, trend, wave, tendency, trade_type, direction):
    return rules_map.get(build_formula(trend, wave, tendency, trade_type, direction))

def find_alternatives(rules_map, trend, wave, tendency) -> list:
    rows = []
    for tt in TRADE_TYPES:
        for d in DIRECTION_VALUES:
            r = lookup(rules_map, trend, wave, tendency, tt, d)
            if r is None:
                status = "❌ нет правила"
            elif r["is_forbidden"]:
                status = "⛔ не торгуется"
            else:
                status = f"✅ {RISK_LEVEL_ICONS.get(r['risk_level'],'')} {r['risk_level']}"
            rows.append({
                "Вид": tt,
                "Направление": d,
                "Статус": status,
                "Описание": (r["description"][:90] + "…") if r and len(r["description"]) > 90 else (r["description"] if r else "—"),
            })
    return rows
