from __future__ import annotations
import pandas as pd
import numpy as np
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

def calc_avg_entry(entries: list[dict], default_price: float) -> tuple[float, int]:
    rows = [(float(e.get("price") or 0), int(e.get("qty") or 0)) for e in entries or []]
    rows = [(p, q) for p, q in rows if p > 0]
    if not rows: return default_price, 0
    total_qty = sum(q for _, q in rows)
    if total_qty == 0:
        return sum(p for p, _ in rows) / len(rows), 0
    return sum(p * q for p, q in rows) / total_qty, total_qty

def plan_trade(inst: Instrument, *, direction: str, entries: list[dict], sl: float | None, tp: float | None, deposit: float, risk_pct: float, rr_ratio: float, tariff: str, max_margin_util: float = 50.0) -> dict:
    pv = inst.point_value
    entry, user_qty = calc_avg_entry(entries, inst.price)
    
    warnings = []
    if sl is None or sl <= 0:
        warnings.append("Не задан стоп-лосс — сайзинг невозможен.")
        sl = 0.0
        
    sign = 1 if direction == "LONG" else -1

    if sl > 0 and entry > 0:
        if direction == "LONG" and sl >= entry:
            warnings.append("LONG: стоп должен быть **ниже** входа.")
        if direction == "SHORT" and sl <= entry:
            warnings.append("SHORT: стоп должен быть **выше** входа.")

    # Автоматический расчет TP, если не задан
    if (tp is None or tp <= 0) and sl > 0 and entry > 0:
        tp = inst.round_price(entry + (abs(entry - sl) * rr_ratio * sign))
    elif tp is not None and tp > 0 and entry > 0:
        if direction == "LONG" and tp <= entry: warnings.append("LONG: тейк должен быть **выше** входа.")
        if direction == "SHORT" and tp >= entry: warnings.append("SHORT: тейк должен быть **ниже** входа.")

    risk_pts = abs(entry - sl) if sl > 0 else 0.0
    rew_pts = abs(tp - entry) if tp is not None and tp > 0 else 0.0
    
    fee_entry = commission_per_side(inst, entry, tariff)
    fee_sl = commission_per_side(inst, sl, tariff) if sl > 0 else 0.0
    fee_tp = commission_per_side(inst, tp, tariff) if tp is not None and tp > 0 else 0.0

    risk_per_ct = (risk_pts * pv) + fee_entry + fee_sl
    reward_per_ct = (rew_pts * pv) - fee_entry - fee_tp

    risk_budget = deposit * (risk_pct / 100.0)
    margin = inst.margin(direction)
    
    qty_by_risk = int(risk_budget // risk_per_ct) if risk_per_ct > 0 else 0
    qty_by_margin = int((deposit * max_margin_util / 100.0) // margin) if margin > 0 else 0
    qty_rec = max(0, min(qty_by_risk, qty_by_margin) if qty_by_margin else qty_by_risk)
    
    qty = user_qty if user_qty > 0 else qty_rec

    total_risk = risk_per_ct * qty
    total_reward = reward_per_ct * qty
    actual_rr = total_reward / total_risk if total_risk > 0 else 0.0

    if qty > 0 and actual_rr < rr_ratio:
        warnings.append(f"R:R в сделке ({actual_rr:.2f}) ниже заданного ({rr_ratio}).")
    
    if total_risk > risk_budget:
        warnings.append(f"Риск в сделке ({total_risk:,.2f} ₽) превышает допустимый лимит ({risk_budget:,.2f} ₽).")

    return {
        "entry": entry, "sl": sl, "tp": tp, "direction": direction, "point_value": pv,
        "risk_pts": risk_pts, "reward_pts": rew_pts,
        "fee_entry": fee_entry, "fee_sl": fee_sl, "fee_tp": fee_tp,
        "fee_per_contract": fee_entry + (fee_tp if tp is not None and tp > 0 else fee_sl),
        "risk_per_contract": risk_per_ct,
        "qty_by_risk": qty_by_risk, "qty_by_margin": qty_by_margin, "qty_recommended": qty_rec, "qty": qty,
        "risk_budget": risk_budget, "risk_rub": total_risk, "risk_pct_fact": (total_risk / deposit * 100) if deposit else 0.0,
        "reward_rub": total_reward, "rr": actual_rr,
        "margin_total": margin * qty, "margin_pct": (margin * qty / deposit * 100) if deposit else 0.0,
        "breakeven": inst.round_price(entry + sign * (fee_entry + fee_sl) / pv) if pv and entry > 0 else entry, 
        "notional": entry * pv * qty,
        "leverage": (entry * pv) / margin if margin > 0 else 0.0,
        "warnings": warnings,
    }

# ==========================================
# АНАЛИТИКА ГРАФИКОВ
# ==========================================
def calculate_breakout_metrics(df, resistance_price, start_time, end_time, is_up=True):
    df_period = df.loc[start_time:end_time]
    if df_period.empty: return 0, 0, start_time
    if is_up:
        breakout_bars = df_period[df_period['High'] > resistance_price]
    else:
        breakout_bars = df_period[df_period['Low'] < resistance_price]
    if not breakout_bars.empty:
        breakout_time = breakout_bars.index[0]
    else:
        breakout_time = start_time
    df_active = df.loc[breakout_time:end_time]
    return len(df_active), df_active['Volume'].sum(), breakout_time

def analyze_manual_zigzag(pts, df):
    if len(pts) < 4: return []
    breakouts = []
    for i in range(3, len(pts)):
        p_a, p_b, p_c, p_d = pts[i-3], pts[i-2], pts[i-1], pts[i]
        a_time, a_price = pd.to_datetime(p_a[0]), p_a[1]
        b_time, b_price = pd.to_datetime(p_b[0]), p_b[1]
        c_time, c_price = pd.to_datetime(p_c[0]), p_c[1]
        d_time, d_price = pd.to_datetime(p_d[0]), p_d[1]

        if a_price < b_price and a_price < c_price < b_price and d_price > b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=True)
            breakout_mag = d_price - b_price
            setup_delta = b_price - c_price
            df_setup = df.loc[b_time:c_time]
            has_pullback = False; e_time = e_price = None; retracement_pct = None; pullback_verdict = None; e_vs_b = "-"; e_delta = None
            if i + 1 < len(pts):
                e_time, e_price = pd.to_datetime(pts[i+1][0]), pts[i+1][1]
                if e_price < d_price:
                    has_pullback = True; e_delta = d_price - e_price
                    if breakout_mag > 0: retracement_pct = (d_price - e_price) / breakout_mag * 100
                    if e_price > b_price: pullback_verdict = "strong"; e_vs_b = "выше B"
                    elif e_price < b_price: pullback_verdict = "weak"; e_vs_b = "ниже B"
                    else: pullback_verdict = "normal"; e_vs_b = "на уровне B"
            breakouts.append({
                "trend": "up", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "delta": breakout_mag, "bars": bars, "volume": vol,
                "setup_delta": setup_delta, "setup_bars": len(df_setup), "setup_vol": df_setup['Volume'].sum(),
                "has_pullback": has_pullback, "e_time": e_time, "e_price": e_price, "e_delta": e_delta,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict, "e_vs_b": e_vs_b
            })
        elif a_price > b_price and b_price < c_price < a_price and d_price < b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=False)
            breakout_mag = b_price - d_price
            setup_delta = c_price - b_price
            df_setup = df.loc[b_time:c_time]
            has_pullback = False; e_time = e_price = None; retracement_pct = None; pullback_verdict = None; e_vs_b = "-"; e_delta = None
            if i + 1 < len(pts):
                e_time, e_price = pd.to_datetime(pts[i+1][0]), pts[i+1][1]
                if e_price > d_price:
                    has_pullback = True; e_delta = e_price - d_price
                    if breakout_mag > 0: retracement_pct = (e_price - d_price) / breakout_mag * 100
                    if e_price < b_price: pullback_verdict = "strong"; e_vs_b = "ниже B"
                    elif e_price > b_price: pullback_verdict = "weak"; e_vs_b = "выше B"
                    else: pullback_verdict = "normal"; e_vs_b = "на уровне B"
            breakouts.append({
                "trend": "down", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "delta": breakout_mag, "bars": bars, "volume": vol,
                "setup_delta": setup_delta, "setup_bars": len(df_setup), "setup_vol": df_setup['Volume'].sum(),
                "has_pullback": has_pullback, "e_time": e_time, "e_price": e_price, "e_delta": e_delta,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict, "e_vs_b": e_vs_b
            })

    for i, brk in enumerate(breakouts):
        if i == 0:
            brk['breakout_verdict'] = "base"; brk['breakout_ratio'] = None; brk['retracement_ratio'] = None
        else:
            prev = breakouts[i-1]
            if prev['delta'] > 0:
                ratio = brk['delta'] / prev['delta']
                brk['breakout_ratio'] = ratio
                if ratio >= 1.15: brk['breakout_verdict'] = "strong"
                elif ratio <= 0.85: brk['breakout_verdict'] = "weak"
                else: brk['breakout_verdict'] = "normal"
            else:
                brk['breakout_ratio'] = None; brk['breakout_verdict'] = "normal"
            if prev.get('retracement_pct') and brk.get('retracement_pct'):
                brk['retracement_ratio'] = brk['retracement_pct'] / prev['retracement_pct'] if prev['retracement_pct'] > 0 else None
            else:
                brk['retracement_ratio'] = None
    return breakouts

def find_volume_clusters(df: pd.DataFrame, threshold_mult=3.0, window=20) -> list[dict]:
    if df.empty or 'Volume' not in df.columns: return []
    volumes = df['Volume'].values
    rolling_avg = pd.Series(volumes).rolling(window=window, min_periods=5).mean().shift(1)
    zones = []
    for i in range(len(df)):
        avg = rolling_avg.iloc[i]
        if pd.isna(avg) or avg <= 0 or volumes[i] <= avg * threshold_mult: continue
        row = df.iloc[i]
        is_buy = float(row['Close']) > float(row['Open'])
        y_low = float(row['Low']) if is_buy else float(row['Close'])
        y_high = float(row['Close']) if is_buy else float(row['High'])
        if y_high > y_low: zones.append({"time": df.index[i], "low": y_low, "high": y_high, "is_buy": is_buy})
    return zones
