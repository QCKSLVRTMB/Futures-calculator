"""Единая точка правды по константам приложения."""
from __future__ import annotations

SCHEMA_VERSION = 2
APP_TITLE = "Калькулятор фьючерсов"

TREND_VALUES = ["вверх", "вниз", "рейндж"]
TRADE_TYPES = ["трендовая", "контртренд"]
DIRECTIONS = ["LONG", "SHORT"]

MARGIN_LEVELS = ["НАЧ. ГО", "КНУР", "КСУР", "КПУР", "КОУР"]
MARGIN_HINTS = {
    "НАЧ. ГО": "НАЧ. ГО — базовое гарантийное обеспечение",
    "КНУР": "КНУР — начальный (новичкам с 01.04.2025)",
    "КСУР": "КСУР — стандартный",
    "КПУР": "КПУР — повышенный (квал. инвестор)",
    "КОУР": "КОУР — особый уровень риска",
}
# Google Sheets: (колонка LONG, колонка SHORT)
MARGIN_COL_MAP = {
    "НАЧ. ГО": (4, 5), "КНУР": (6, 7), "КСУР": (8, 9),
    "КПУР": (10, 11), "КОУР": (12, 13),
}
# MOEX ISS /forts/ims
IMS_MARGIN_MAP = {
    "НАЧ. ГО": ("IM_BUY", "IM_SELL"),
    "КНУР": ("IM_BUY_LRC", "IM_SELL_LRC"),
    "КСУР": ("IM_BUY_MRC", "IM_SELL_MRC"),
    "КПУР": ("IM_BUY_HRC", "IM_SELL_HRC"),
    "КОУР": ("IM_BUY_ERC", "IM_SELL_ERC"),
}

TARIFF_CONFIGS = {
    "Т-Инвестиции": {"type": "percent", "broker_percent": 0.001,
                     "clearing_fee": 0.0, "min_fee": 0.01},
    "Финам СТАНДАРТНЫЙ ФОРТС": {"type": "fixed", "broker_fee": 0.45,
                                "clearing_fee": 4.65, "min_fee": 0.01},
    "Без комиссии": {"type": "fixed", "broker_fee": 0.0,
                     "clearing_fee": 0.0, "min_fee": 0.0},
}

TF_SPEC = {
    "M10": {"interval": 10, "days": 14,  "label": "10 мин", "bars": 160},
    "H1":  {"interval": 60, "days": 90,  "label": "1 час",  "bars": 200},
    "D1":  {"interval": 24, "days": 500, "label": "1 день", "bars": 220},
}
TIMEFRAMES = list(TF_SPEC)

TOOLS = {
    "channel": "Канал",
    "fib":     "Фибо",
    "zigzag":  "Зигзаг / тенденция",
    "levels":  "Уровни",
}
DEFAULT_TOOLS = {"D1": "channel", "H1": "zigzag", "M10": "zigzag"}

FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618]

DEFAULT_GLOBAL = {
    "strategy": "Зигзаг тенденции",
    "deposit": 75000,
    "risk_pct": 1.0,
    "commission": "Т-Инвестиции",
    "margin_type": "КСУР",
    "rr_ratio": 3.0,
    "mobile_view": False,
    "max_margin_util": 50.0,
    "active_tickers": [],
}
