from __future__ import annotations
import pandas as pd
from dataclasses import dataclass, field
from core.config import IMS_MARGIN_MAP, MARGIN_COL_MAP, TARIFF_CONFIGS
from core.market import to_float, vlookup

@dataclass
class Instrument:
    ticker: str
    name: str = "-"
    asset_code: str = "-"
    expiry: str = "-"
    price: float = 0.0
    min_step: float = 1.0
    step_price: float = 1.0
    decimals: int = 2
    exch_fee: float = 0.0
    margin_long: float = 0.0
    margin_short: float = 0.0
    open_interest: float = 0.0
    change_pct: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def point_value(self) -> float: return (self.step_price / self.min_step) if self.min_step else 1.0
    @property
    def notional(self) -> float: return self.price * self.point_value
    def margin(self, direction: str) -> float: return self.margin_long if direction == "LONG" else self.margin_short
    def round_price(self, p: float) -> float:
        if not self.min_step: return round(p, self.decimals)
        return round(round(p / self.min_step) * self.min_step, self.decimals)

def get_instrument(ticker, *, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, margin_type="КСУР") -> Instrument:
    inst = Instrument(ticker=ticker)
    row = pd.Series(dtype=object)
    if iss_df is not None and not iss_df.empty and "SECID" in iss_df:
        sel = iss_df.loc[iss_df["SECID"] == ticker]
        if not sel.empty: row = sel.iloc[0]

    if not row.empty:
        inst.name = row.get("SHORTNAME") or "-"
        inst.asset_code = row.get("ASSETCODE") or "-"
        inst.expiry = str(row.get("LASTTRADEDATE") or "-")
        inst.price = to_float(row.get("LAST")) or to_float(row.get("PREVSETTLEPRICE"))
        inst.min_step = to_float(row.get("MINSTEP"), 1.0) or 1.0
        inst.step_price = to_float(row.get("STEPPRICE"), 1.0) or 1.0
        inst.decimals = int(to_float(row.get("DECIMALS"), 2))
        inst.exch_fee = to_float(row.get("BUYSELLFEE"))
        inst.open_interest = to_float(row.get("OPENPOSITION"))
        inst.change_pct = to_float(row.get("LASTCHANGEPRCNT"))
        inst.margin_long = inst.margin_short = to_float(row.get("INITIALMARGIN"))

    if ims_df is not None and not ims_df.empty and margin_type in IMS_MARGIN_MAP:
        col_b, col_s = IMS_MARGIN_MAP[margin_type]
        key_col = next((c for c in ("SECID", "SEC_ID", "SECURITYID") if c in ims_df), None)
        if key_col:
            sel = ims_df.loc[ims_df[key_col].astype(str) == str(ticker)]
            if not sel.empty:
                inst.margin_long = to_float(sel.iloc[0].get(col_b)) or inst.margin_long
                inst.margin_short = to_float(sel.iloc[0].get(col_s)) or inst.margin_short

    if go_df is not None and not go_df.empty and inst.margin_long == 0:
        cl, cs = MARGIN_COL_MAP.get(margin_type, (4, 5))
        inst.margin_long = to_float(vlookup(go_df, ticker, cl))
        inst.margin_short = to_float(vlookup(go_df, ticker, cs))
    if api_df is not None and not api_df.empty:
        if inst.min_step in (0, 1.0):
            inst.min_step = to_float(vlookup(api_df, ticker, 6), inst.min_step) or inst.min_step
            inst.step_price = to_float(vlookup(api_df, ticker, 17), inst.step_price) or inst.step_price
        if inst.name == "-": inst.name = vlookup(api_df, ticker, 3)
        if inst.expiry == "-": inst.expiry = str(vlookup(api_df, ticker, 7))
    if md_df is not None and not md_df.empty and inst.price == 0:
        inst.price = to_float(vlookup(md_df, ticker, 9))
    return inst

def commission_per_side(inst: Instrument, price: float, tariff_name: str) -> float:
    cfg = TARIFF_CONFIGS.get(tariff_name, TARIFF_CONFIGS["Т-Инвестиции"])
    fee = (price * inst.point_value * cfg["broker_percent"]) if cfg["type"] == "percent" else cfg["broker_fee"]
    return max(fee, cfg.get("min_fee", 0.0)) + inst.exch_fee + cfg.get("clearing_fee", 0.0)

def avg_entry(entries: list[dict]) -> tuple[float, int]:
    rows = [(float(e.get("price") or 0), int(e.get("qty") or 0)) for e in entries or []]
    rows = [(p, q) for p, q in rows if p > 0 and q > 0]
    if not rows: return 0.0, 0
    total = sum(q for _, q in rows)
    return sum(p * q for p, q in rows) / total, total

def plan_trade(inst: Instrument, *, direction: str, entries: list[dict], sl: float | None, tp: float | None, deposit: float, risk_pct: float, rr_ratio: float, tariff: str, max_margin_util: float = 50.0) -> dict:
    pv = inst.point_value
    entry, planned_qty = avg_entry(entries)
    if entry <= 0: entry = inst.price
    sign = 1 if direction == "LONG" else -1

    if tp is None and sl is not None and entry > 0:
        tp = inst.round_price(entry + sign * abs(entry - sl) * rr_ratio)

    risk_pts = abs(entry - sl) if (sl and entry) else 0.0
    rew_pts = abs(tp - entry) if (tp and entry) else 0.0
    fee = commission_per_side(inst, entry, tariff)
    fee_rt = fee * 2

    risk_per_ct = risk_pts * pv + fee_rt
    risk_budget = deposit * risk_pct / 100.0
    margin = inst.margin(direction)

    qty_by_risk = int(risk_budget // risk_per_ct) if risk_per_ct > 0 else 0
    qty_by_margin = int((deposit * max_margin_util / 100.0) // margin) if margin > 0 else 0
    qty_rec = max(0, min(qty_by_risk, qty_by_margin) if qty_by_margin else qty_by_risk)
    qty = planned_qty or qty_rec

    total_risk = risk_per_ct * qty
    total_reward = rew_pts * pv * qty - fee_rt * qty
    return {
        "entry": entry, "sl": sl, "tp": tp, "direction": direction, "point_value": pv,
        "risk_pts": risk_pts, "reward_pts": rew_pts, "fee_per_contract": fee_rt, "risk_per_contract": risk_per_ct,
        "qty_by_risk": qty_by_risk, "qty_by_margin": qty_by_margin, "qty_recommended": qty_rec, "qty": qty,
        "risk_budget": risk_budget, "risk_rub": total_risk, "risk_pct_fact": (total_risk / deposit * 100) if deposit else 0.0,
        "reward_rub": total_reward, "rr": (total_reward / total_risk) if total_risk > 0 else 0.0,
        "margin_total": margin * qty, "margin_pct": (margin * qty / deposit * 100) if deposit else 0.0,
        "breakeven": inst.round_price(entry + sign * (fee_rt / pv)) if pv else entry, "notional": entry * pv * qty,
        "warnings": _warnings(direction, entry, sl, tp, qty, qty_by_margin, qty_by_risk),
    }

def _warnings(direction, entry, sl, tp, qty, qty_m, qty_r) -> list[str]:
    w = []
    if not sl: w.append("Не задан стоп-лосс — сайзинг невозможен.")
    elif direction == "LONG" and sl >= entry: w.append("LONG: стоп должен быть **ниже** входа.")
    elif direction == "SHORT" and sl <= entry: w.append("SHORT: стоп должен быть **выше** входа.")
    if tp:
        if direction == "LONG" and tp <= entry: w.append("LONG: тейк должен быть **выше** входа.")
        if direction == "SHORT" and tp >= entry: w.append("SHORT: тейк должен быть **ниже** входа.")
    if qty == 0: w.append("Расчётный объём = 0: уменьшите стоп или увеличьте риск/депозит.")
    if qty_m and qty > qty_m: w.append(f"Объём превышает лимит по ГО ({qty_m} контр.).")
    if qty_r and qty > qty_r: w.append(f"Объём превышает риск-лимит ({qty_r} контр.).")
    return w
