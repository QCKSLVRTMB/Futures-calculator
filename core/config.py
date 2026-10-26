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
MARGIN_COL_MAP = {
    "НАЧ. ГО": (4, 5), "КНУР": (6, 7), "КСУР": (8, 9),
    "КПУР": (10, 11), "КОУР": (12, 13),
}
IMS_MARGIN_MAP = {
    "НАЧ. ГО": ("IM_BUY", "IM_SELL"),
    "КНУР": ("IM_BUY_LRC", "IM_SELL_LRC"),
    "КСУР": ("IM_BUY_MRC", "IM_SELL_MRC"),
    "КПУР": ("IM_BUY_HRC", "IM_SELL_HRC"),
    "КОУР": ("IM_BUY_ERC", "IM_SELL_ERC"),
}

TARIFF_CONFIGS = {
    "Т-Инвестиции": {"type": "percent", "broker_percent": 0.001, "clearing_fee": 0.0, "min_fee": 0.01},
    "Финам СТАНДАРТНЫЙ ФОРТС": {"type": "fixed", "broker_fee": 0.45, "clearing_fee": 4.65, "min_fee": 0.01},
    "Без комиссии": {"type": "fixed", "broker_fee": 0.0, "clearing_fee": 0.0, "min_fee": 0.0},
}

# Интервалы, взятые из вашего trade_planner.py
INTERVALS = {
    "D1":  {"interval": 24, "days_back": 250, "is_intraday": False, "label": "D1 (Дни)"},
    "H1":  {"interval": 60, "days_back": 30,  "is_intraday": True,  "label": "H1 (Часы)"},
    "M10": {"interval": 10, "days_back": 5,   "is_intraday": True,  "label": "M10 (10 минут)"},
}

# ВАЖНО: storage.py использует TIMEFRAMES для создания дефолтных словарей
TIMEFRAMES = list(INTERVALS.keys())

TOOLS = {
    "channel": "D1: Канал",
    "fib_d1":  "D1: Уровень 1/2",
    "zigzag":  "H1: Зигзаг",
    "fib_h1":  "H1: Уровень 1/2",
}

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
