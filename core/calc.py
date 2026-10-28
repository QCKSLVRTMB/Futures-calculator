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
        sel = iss_df.loc[iss_df["SECID"].astype(str).str.upper() == str(ticker).upper()]
        if not sel.empty: row = sel.iloc[0]

    if not row.empty:
        name_val = row.get("SHORTNAME")
        inst.name = str(name_val).strip() if pd.notna(name_val) and str(name_val).strip() else "-"

        code_val = row.get("ASSETCODE")
        inst.asset_code = str(code_val).strip() if pd.notna(code_val) and str(code_val).strip() else "-"

        expiry_val = row.get("LASTTRADEDATE")
        inst.expiry = str(expiry_val) if pd.notna(expiry_val) else "-"

        price_val = to_float(row.get("LAST")) or to_float(row.get("PREVSETTLEPRICE"))
        inst.price = price_val
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
            sel = ims_df.loc[ims_df[key_col].astype(str).str.upper() == str(ticker).upper()]
            if not sel.empty:
                inst.margin_long = to_float(sel.iloc[0].get(col_b)) or inst.margin_long
                inst.margin_short = to_float(sel.iloc[0].get(col_s)) or inst.margin_short

    if not row.empty:
        if inst.margin_long == 0 and go_df is not None and not go_df.empty:
            cl, cs = MARGIN_COL_MAP.get(margin_type, (4, 5))
            inst.margin_long = to_float(vlookup(go_df, ticker, cl))
            inst.margin_short = to_float(vlookup(go_df, ticker, cs))

        if inst.min_step in (0, 1.0) and api_df is not None and not api_df.empty:
            inst.min_step = to_float(vlookup(api_df, ticker, 6), inst.min_step) or inst.min_step
            inst.step_price = to_float(vlookup(api_df, ticker, 17), inst.step_price) or inst.step_price

        if inst.price == 0 and md_df is not None and not md_df.empty:
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
    pts = sorted(pts, key=lambda p: pd.to_datetime(p[0]))

    breakouts = []
    for i in range(3, len(pts)):
        p_a, p_b, p_c, p_d = pts[i-3], pts[i-2], pts[i-1], pts[i]
        a_time, a_price = pd.to_datetime(p_a[0]), p_a[1]
        b_time, b_price = pd.to_datetime(p_b[0]), p_b[1]
        c_time, c_price = pd.to_datetime(p_c[0]), p_c[1]
        d_time, d_price = pd.to_datetime(p_d[0]), p_d[1]

        if a_price < b_price and a_price < c_price < b_price and d_price > b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=True)
            curr_height = d_price - c_price
            prev_height = b_price - a_price
            height_ratio = curr_height / prev_height if prev_height > 0 else 0

            prev_leg = df.loc[a_time:b_time]
            curr_leg = df.loc[c_time:d_time]
            bars_ratio = len(curr_leg) / len(prev_leg) if len(prev_leg) > 0 else 0
            vol_ratio = curr_leg['Volume'].sum() / prev_leg['Volume'].sum() if prev_leg['Volume'].sum() > 0 else 0

            setup_delta = b_price - c_price
            breakout_pct = (curr_height / setup_delta * 100) if setup_delta > 0 else 0

            has_pullback = False
            e_time = e_price = None
            e_delta = None
            retracement_pct = None
            pullback_verdict = None
            e_vs_05 = "-"
            retr_bars = 0
            retr_vol = 0

            if i + 1 < len(pts):
                e_time, e_price = pd.to_datetime(pts[i+1][0]), pts[i+1][1]
                if e_price < d_price:
                    has_pullback = True
                    e_delta = d_price - e_price
                    fib_05 = d_price - (d_price - c_price) * 0.5
                    retracement_pct = (d_price - e_price) / curr_height * 100 if curr_height > 0 else 0

                    if e_price > fib_05:
                        pullback_verdict = "Сильный"; e_vs_05 = "выше 0.5"
                    elif e_price < fib_05:
                        pullback_verdict = "Слабый"; e_vs_05 = "ниже 0.5"
                    else:
                        pullback_verdict = "Нормальный"; e_vs_05 = "на уровне 0.5"

                    df_pullback = df.loc[d_time:e_time]
                    retr_bars = len(df_pullback)
                    retr_vol = df_pullback['Volume'].sum()

            breakouts.append({
                "trend": "up", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "delta": curr_height, "breakout_pct": breakout_pct, "bars": bars, "volume": vol,
                "setup_delta": setup_delta, "setup_bars": len(df.loc[b_time:c_time]), "setup_vol": df.loc[b_time:c_time]['Volume'].sum(),
                "has_pullback": has_pullback, "e_time": e_time, "e_price": e_price, "e_delta": e_delta,
                "retr_bars": retr_bars, "retr_vol": retr_vol,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict, "e_vs_b": e_vs_05,
                "height_ratio": height_ratio, "bars_ratio": bars_ratio, "vol_ratio": vol_ratio
            })
        elif a_price > b_price and b_price < c_price < a_price and d_price < b_price:
            bars, vol, brk_time = calculate_breakout_metrics(df, b_price, c_time, d_time, is_up=False)
            curr_height = c_price - d_price
            prev_height = a_price - b_price
            height_ratio = curr_height / prev_height if prev_height > 0 else 0

            prev_leg = df.loc[a_time:b_time]
            curr_leg = df.loc[c_time:d_time]
            bars_ratio = len(curr_leg) / len(prev_leg) if len(prev_leg) > 0 else 0
            vol_ratio = curr_leg['Volume'].sum() / prev_leg['Volume'].sum() if prev_leg['Volume'].sum() > 0 else 0

            setup_delta = c_price - b_price
            breakout_pct = (curr_height / setup_delta * 100) if setup_delta > 0 else 0

            has_pullback = False
            e_time = e_price = None
            e_delta = None
            retracement_pct = None
            pullback_verdict = None
            e_vs_05 = "-"
            retr_bars = 0
            retr_vol = 0

            if i + 1 < len(pts):
                e_time, e_price = pd.to_datetime(pts[i+1][0]), pts[i+1][1]
                if e_price > d_price:
                    has_pullback = True
                    e_delta = e_price - d_price
                    fib_05 = d_price + (c_price - d_price) * 0.5
                    retracement_pct = (e_price - d_price) / curr_height * 100 if curr_height > 0 else 0

                    if e_price < fib_05:
                        pullback_verdict = "Сильный"; e_vs_05 = "ниже 0.5"
                    elif e_price > fib_05:
                        pullback_verdict = "Слабый"; e_vs_05 = "выше 0.5"
                    else:
                        pullback_verdict = "Нормальный"; e_vs_05 = "на уровне 0.5"

                    df_pullback = df.loc[d_time:e_time]
                    retr_bars = len(df_pullback)
                    retr_vol = df_pullback['Volume'].sum()

            breakouts.append({
                "trend": "down", "resistance_time": b_time, "resistance_price": b_price,
                "pullback_setup_time": c_time, "pullback_setup_price": c_price,
                "peak_time": d_time, "peak_price": d_price, "breakout_time": brk_time,
                "delta": curr_height, "breakout_pct": breakout_pct, "bars": bars, "volume": vol,
                "setup_delta": setup_delta, "setup_bars": len(df.loc[b_time:c_time]), "setup_vol": df.loc[b_time:c_time]['Volume'].sum(),
                "has_pullback": has_pullback, "e_time": e_time, "e_price": e_price, "e_delta": e_delta,
                "retr_bars": retr_bars, "retr_vol": retr_vol,
                "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict, "e_vs_b": e_vs_05,
                "height_ratio": height_ratio, "bars_ratio": bars_ratio, "vol_ratio": vol_ratio
            })

    for brk in breakouts:
        h_ratio, b_ratio, v_ratio = brk["height_ratio"], brk["bars_ratio"], brk["vol_ratio"]
        if h_ratio >= 1.1 and b_ratio <= 1.0:
            brk["breakout_verdict"] = "strong"
        elif h_ratio <= 0.9 or b_ratio >= 1.5 or v_ratio >= 1.5:
            brk["breakout_verdict"] = "weak"
        else:
            brk["breakout_verdict"] = "normal"

    return breakouts


def get_volume_colors(df, tf_name, sensitivity=3.0):
    """Возвращает массив цветов для гистограммы объемов (gray, black, green, red, blue)."""
    if df.empty or "Volume" not in df.columns: return []
    volumes = df["Volume"].values
    times = df.index
    colors = ["gray"] * len(df)
    
    for i in range(2, len(df)):
        if volumes[i] > volumes[i-1] and volumes[i] > volumes[i-2]: 
            colors[i] = "black"
            
    if tf_name == "H1":
        for i in range(len(df)):
            if times[i].hour == 10 and times[i].minute == 0:
                prev = [volumes[j] for j in range(i-1, -1, -1) if times[j].hour == 10 and times[j].minute == 0][:2]
                if len(prev) == 2 and volumes[i] > prev[0] and volumes[i] > prev[1]: 
                    colors[i] = "black"
                    
    anomaly = "red" if tf_name in ("M10", "M1") else ("green" if tf_name == "H1" else ("blue" if tf_name == "D1" else None))
    if anomaly:
        avg = pd.Series(volumes).rolling(20, min_periods=5).mean().shift(1)
        for i in range(len(volumes)):
            if pd.notna(avg.iloc[i]) and avg.iloc[i] > 0 and volumes[i] > avg.iloc[i] * sensitivity: 
                colors[i] = anomaly
    return colors


def calculate_volume_profile(df, tf_name="M10", threshold_pct=50, sensitivity=3.0):
    """Профиль значимых объёмов: зона каждого бара -> на всю ширину графика.
    Объёмы накладывающихся зон складываются; яркость растёт с суммой.
    threshold_pct (10–100): порог отсечения слабых зон (10 = показать всё, 100 = только POC)."""
    if df.empty or 'Volume' not in df.columns: return []
    
    # 1. Тот же фильтр, что и для гистограммы (M10 -> black/red)
    colors = get_volume_colors(df, tf_name, sensitivity)
    anomaly_color = "red" if tf_name in ("M10", "M1") else ("green" if tf_name == "H1" else ("blue" if tf_name == "D1" else None))
    
    valid_indices = [i for i in range(len(df)) if colors[i] == "black" or colors[i] == anomaly_color]
    if not valid_indices: return []
    
    df_valid = df.iloc[valid_indices]
    
    # 2. Зона каждого значимого бара: buy -> [LOW, CLOSE], sell -> [CLOSE, HIGH]
    zones = []
    for _, row in df_valid.iterrows():
        is_buy = float(row['Close']) > float(row['Open'])
        y_low = float(row['Low']) if is_buy else float(row['Close'])
        y_high = float(row['Close']) if is_buy else float(row['High'])
        vol = float(row['Volume'])
        if y_high <= y_low or vol <= 0: continue
        zones.append({"low": y_low, "high": y_high, "vol": vol})
    
    if not zones: return []
    
    # 3. Все границы зон = точки разрыва; между соседними состав перекрытия постоянен
    breakpoints = sorted(set([z["low"] for z in zones] + [z["high"] for z in zones]))
    if len(breakpoints) < 2: return []
    
    bands = []
    for i in range(len(breakpoints) - 1):
        lo, hi = breakpoints[i], breakpoints[i + 1]
        if hi <= lo: continue
        total_vol = sum(z["vol"] for z in zones if z["low"] <= lo and z["high"] >= hi)
        if total_vol <= 0: continue
        bands.append({"low": lo, "high": hi, "vol": total_vol})
    
    if not bands: return []
    
    max_vol = max(b["vol"] for b in bands)
    min_vol = min(b["vol"] for b in bands)
    
    # 4. Порог: 10 -> min_vol (всё), 100 -> max_vol (только POC)
    if max_vol > min_vol:
        threshold = min_vol + (max_vol - min_vol) * (int(threshold_pct) - 10) / 90.0
    else:
        threshold = min_vol
    
    # 5. Слабые отсекаем; яркость линейно от порога до max
    zones_out = []
    for b in bands:
        if b["vol"] < threshold: continue
        if max_vol > threshold:
            opacity = 0.15 + 0.45 * (b["vol"] - threshold) / (max_vol - threshold)
        else:
            opacity = 0.60
        zones_out.append({
            "low": b["low"],
            "high": b["high"],
            "opacity": opacity,
        })
    return zones_out
