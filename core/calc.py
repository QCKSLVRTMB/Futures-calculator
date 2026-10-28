from __future__ import annotations

from dataclasses import dataclass, field, replace
import numpy as np
import pandas as pd
import streamlit as st

from core.config import IMS_MARGIN_MAP, MARGIN_COL_MAP, TARIFF_CONFIGS
from core.market import to_float

# ======================================================================
#  INSTRUMENT
# ======================================================================
@dataclass(slots=True)
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
    def point_value(self) -> float:
        return (self.step_price / self.min_step) if self.min_step else 1.0

    @property
    def notional(self) -> float:
        return self.price * self.point_value

    def margin(self, direction: str) -> float:
        return self.margin_long if direction == "LONG" else self.margin_short

    def round_price(self, p: float) -> float:
        if not self.min_step:
            return round(p, self.decimals)
        return round(round(p / self.min_step) * self.min_step, self.decimals)

# ----------------------------------------------------------------------
#  Векторные хелперы
# ----------------------------------------------------------------------
def _num_col(df: pd.DataFrame | None, col, default: float = 0.0, n: int = 0) -> np.ndarray:
    if df is None or col not in df.columns:
        return np.full(n, default, dtype="float64")
    s = df[col]
    if not pd.api.types.is_numeric_dtype(s):
        s = (s.astype(str)
               .str.replace("\u00a0", "", regex=False)
               .str.replace(" ", "", regex=False)
               .str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce").fillna(default).to_numpy(dtype="float64")

def _str_col(df: pd.DataFrame, col, n: int, default: str = "-") -> np.ndarray:
    if col not in df.columns:
        return np.full(n, default, dtype=object)
    s = df[col].astype(str).str.strip()
    return s.where(s.ne("") & s.ne("nan") & s.ne("None"), default).to_numpy(dtype=object)

def _col_map(df: pd.DataFrame | None, col_idx: int) -> dict[str, float]:
    if df is None or df.empty or df.shape[1] <= col_idx:
        return {}
    keys = df.iloc[:, 0].astype(str).str.strip().str.upper().to_numpy()
    vals = _num_col(df, df.columns[col_idx], 0.0, len(df))
    out: dict[str, float] = {}
    for k, v in zip(keys, vals):
        if k not in out:
            out[k] = float(v)
    return out

# ----------------------------------------------------------------------
#  Таблица инструментов
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False, max_entries=4)
def build_instruments(iss_df, ims_df, go_df, api_df, md_df, margin_type: str = "КСУР") -> dict[str, Instrument]:
    if iss_df is None or iss_df.empty or "SECID" not in iss_df.columns:
        return {}

    n = len(iss_df)
    sec = iss_df["SECID"].astype(str).str.strip().str.upper().to_numpy(dtype=object)

    name   = _str_col(iss_df, "SHORTNAME", n)
    code   = _str_col(iss_df, "ASSETCODE", n)
    expiry = _str_col(iss_df, "LASTTRADEDATE", n)

    last  = _num_col(iss_df, "LAST", 0.0, n)
    prevs = _num_col(iss_df, "PREVSETTLEPRICE", 0.0, n)
    price = np.where(last > 0, last, prevs)

    min_step = _num_col(iss_df, "MINSTEP", 1.0, n)
    min_step = np.where(min_step > 0, min_step, 1.0)
    step_price = _num_col(iss_df, "STEPPRICE", 1.0, n)
    step_price = np.where(step_price > 0, step_price, 1.0)

    decimals = _num_col(iss_df, "DECIMALS", 2.0, n).astype(np.int64)
    exch_fee = _num_col(iss_df, "BUYSELLFEE", 0.0, n)
    oi       = _num_col(iss_df, "OPENPOSITION", 0.0, n)
    chg      = _num_col(iss_df, "LASTCHANGEPRCNT", 0.0, n)

    im = _num_col(iss_df, "INITIALMARGIN", 0.0, n)
    m_long, m_short = im.copy(), im.copy()

    if ims_df is not None and not ims_df.empty and margin_type in IMS_MARGIN_MAP:
        col_b, col_s = IMS_MARGIN_MAP[margin_type]
        key_col = next((c for c in ("SECID", "SEC_ID", "SECURITYID") if c in ims_df.columns), None)
        if key_col:
            pos = pd.Series(np.arange(len(ims_df)), index=ims_df[key_col].astype(str).str.upper())
            pos = pos[~pos.index.duplicated()]
            ridx = pos.reindex(pd.Index(sec)).to_numpy(dtype="float64")
            ok = np.flatnonzero(~np.isnan(ridx))
            if ok.size:
                ri = ridx[ok].astype(np.int64)
                vb = _num_col(ims_df, col_b, 0.0, len(ims_df))[ri]
                vs = _num_col(ims_df, col_s, 0.0, len(ims_df))[ri]
                m_long[ok]  = np.where(vb > 0, vb, m_long[ok])
                m_short[ok] = np.where(vs > 0, vs, m_short[ok])

    need_margin = np.flatnonzero(m_long <= 0)
    if need_margin.size and go_df is not None and not go_df.empty:
        cl, cs = MARGIN_COL_MAP.get(margin_type, (4, 5))
        gl, gs = _col_map(go_df, cl), _col_map(go_df, cs)
        for i in need_margin:
            t = sec[i]
            m_long[i]  = gl.get(t, 0.0)
            m_short[i] = gs.get(t, 0.0)

    need_step = np.flatnonzero((min_step <= 0) | (min_step == 1.0))
    if need_step.size and api_df is not None and not api_df.empty:
        a_step, a_price = _col_map(api_df, 6), _col_map(api_df, 17)
        for i in need_step:
            t = sec[i]
            v = a_step.get(t, 0.0)
            if v: min_step[i] = v
            v = a_price.get(t, 0.0)
            if v: step_price[i] = v

    need_price = np.flatnonzero(price <= 0)
    if need_price.size and md_df is not None and not md_df.empty:
        m_price = _col_map(md_df, 9)
        for i in need_price:
            price[i] = m_price.get(sec[i], 0.0)

    return {
        sec[i]: Instrument(
            ticker=str(sec[i]), name=name[i], asset_code=code[i], expiry=expiry[i],
            price=float(price[i]), min_step=float(min_step[i]), step_price=float(step_price[i]),
            decimals=int(decimals[i]), exch_fee=float(exch_fee[i]),
            margin_long=float(m_long[i]), margin_short=float(m_short[i]),
            open_interest=float(oi[i]), change_pct=float(chg[i]),
        )
        for i in range(n)
    }

def get_instrument(ticker, *, iss_df=None, ims_df=None, go_df=None, api_df=None, md_df=None, margin_type="КСУР") -> Instrument:
    table = build_instruments(iss_df, ims_df, go_df, api_df, md_df, margin_type)
    inst = table.get(str(ticker).strip().upper())
    if inst is None:
        return Instrument(ticker=str(ticker))
    return replace(inst, extra=dict(inst.extra))

def get_instruments(tickers, **kw) -> list[Instrument]:
    table = build_instruments(kw.get("iss_df"), kw.get("ims_df"), kw.get("go_df"), kw.get("api_df"), kw.get("md_df"), kw.get("margin_type", "КСУР"))
    res = []
    for t in tickers:
        inst = table.get(str(t).strip().upper())
        res.append(replace(inst, extra=dict(inst.extra)) if inst else Instrument(ticker=str(t)))
    return res

# ======================================================================
#  РАСЧЁТ СДЕЛКИ
# ======================================================================
def commission_per_side(inst: Instrument, price: float, tariff_name: str) -> float:
    cfg = TARIFF_CONFIGS.get(tariff_name) or TARIFF_CONFIGS["Т-Инвестиции"]
    fee = (price * inst.point_value * cfg["broker_percent"]) if cfg["type"] == "percent" else cfg["broker_fee"]
    return max(fee, cfg.get("min_fee", 0.0)) + inst.exch_fee + cfg.get("clearing_fee", 0.0)

def calc_avg_entry(entries: list[dict], default_price: float) -> tuple[float, int]:
    s_pq = s_q = s_p = 0.0
    cnt = 0
    for e in entries or []:
        p = float(e.get("price") or 0)
        if p <= 0: continue
        q = int(e.get("qty") or 0)
        s_pq += p * q
        s_q += q
        s_p += p
        cnt += 1
    if not cnt: return default_price, 0
    if s_q == 0: return s_p / cnt, 0
    return s_pq / s_q, int(s_q)

def plan_trade(inst: Instrument, *, direction: str, entries: list[dict], sl: float | None, tp: float | None, deposit: float, risk_pct: float, rr_ratio: float, tariff: str, max_margin_util: float = 50.0) -> dict:
    pv = inst.point_value
    entry, user_qty = calc_avg_entry(entries, inst.price)
    warnings: list[str] = []

    if sl is None or sl <= 0:
        warnings.append("Не задан стоп-лосс — сайзинг невозможен.")
        sl = 0.0

    sign = 1 if direction == "LONG" else -1
    if sl > 0 and entry > 0:
        if direction == "LONG" and sl >= entry: warnings.append("LONG: стоп должен быть **ниже** входа.")
        if direction == "SHORT" and sl <= entry: warnings.append("SHORT: стоп должен быть **выше** входа.")

    risk_pts = abs(entry - sl) if sl > 0 else 0.0
    fee_entry = commission_per_side(inst, entry, tariff)
    fee_sl = commission_per_side(inst, sl, tariff) if sl > 0 else 0.0
    risk_per_ct = (risk_pts * pv) + fee_entry + fee_sl
    target_profit_rub = risk_per_ct * rr_ratio

    if pv > 0:
        approx_tp = inst.round_price(entry + ((target_profit_rub + fee_entry) / pv) * sign)
        fee_tp_min = commission_per_side(inst, approx_tp, tariff) if approx_tp > 0 else 0.0
        min_tp = inst.round_price(entry + ((target_profit_rub + fee_entry + fee_tp_min) / pv) * sign)
    else:
        min_tp = inst.round_price(entry)

    if (tp is None or tp <= 0) and sl > 0 and entry > 0:
        tp = min_tp
    elif tp and tp > 0 and entry > 0:
        if direction == "LONG" and tp <= entry: warnings.append("LONG: тейк должен быть **выше** входа.")
        if direction == "SHORT" and tp >= entry: warnings.append("SHORT: тейк должен быть **ниже** входа.")

    has_tp = bool(tp and tp > 0)
    rew_pts = abs(tp - entry) if has_tp else 0.0
    fee_tp = commission_per_side(inst, tp, tariff) if has_tp else 0.0
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

    if qty > 0 and actual_rr < rr_ratio: warnings.append(f"R:R в сделке ({actual_rr:.2f}) ниже заданного ({rr_ratio}).")
    if total_risk > risk_budget: warnings.append(f"Риск в сделке ({total_risk:,.2f} ₽) превышает допустимый лимит ({risk_budget:,.2f} ₽).")

    return {
        "entry": entry, "sl": sl, "tp": tp, "direction": direction, "point_value": pv,
        "risk_pts": risk_pts, "reward_pts": rew_pts,
        "fee_entry": fee_entry, "fee_sl": fee_sl, "fee_tp": fee_tp,
        "fee_per_contract": fee_entry + (fee_tp if has_tp else fee_sl),
        "risk_per_contract": risk_per_ct,
        "qty_by_risk": qty_by_risk, "qty_by_margin": qty_by_margin,
        "qty_recommended": qty_rec, "qty": qty,
        "risk_budget": risk_budget, "risk_rub": total_risk,
        "risk_pct_fact": (total_risk / deposit * 100) if deposit else 0.0,
        "reward_rub": total_reward, "rr": actual_rr,
        "margin_total": margin * qty,
        "margin_pct": (margin * qty / deposit * 100) if deposit else 0.0,
        "breakeven": inst.round_price(entry + sign * (fee_entry + fee_sl) / pv) if pv and entry > 0 else entry,
        "notional": entry * pv * qty,
        "leverage": (entry * pv) / margin if margin > 0 else 0.0,
        "min_tp": min_tp, "target_profit_rub": target_profit_rub,
        "warnings": warnings,
    }

# ======================================================================
#  АНАЛИТИКА ГРАФИКОВ
# ======================================================================
class _Bars:
    __slots__ = ("idx", "high", "low", "vol", "cvol")
    def __init__(self, df: pd.DataFrame):
        self.idx = df.index
        self.high = df["High"].to_numpy(dtype="float64", copy=False)
        self.low = df["Low"].to_numpy(dtype="float64", copy=False)
        self.vol = df["Volume"].to_numpy(dtype="float64", copy=False)
        self.cvol = np.concatenate(([0.0], np.cumsum(self.vol)))

    def span(self, t0, t1) -> tuple[int, int]:
        i0 = int(self.idx.searchsorted(t0, side="left"))
        i1 = int(self.idx.searchsorted(t1, side="right"))
        return i0, max(i0, i1)

    def vsum(self, i0: int, i1: int) -> float:
        return float(self.cvol[i1] - self.cvol[i0])

def calculate_breakout_metrics(df, resistance_price, start_time, end_time, is_up=True):
    b = df if isinstance(df, _Bars) else _Bars(df)
    i0, i1 = b.span(start_time, end_time)
    if i1 <= i0: return 0, 0, start_time
    mask = (b.high[i0:i1] > resistance_price) if is_up else (b.low[i0:i1] < resistance_price)
    k = int(mask.argmax()) if mask.any() else None
    if k is None: brk_i, brk_time = i0, start_time
    else: brk_i = i0 + k; brk_time = b.idx[brk_i]
    j0, j1 = b.span(brk_time, end_time) if k is not None else (i0, i1)
    return j1 - j0, b.vsum(j0, j1), brk_time

def analyze_manual_zigzag(pts, df):
    if not pts or len(pts) < 4 or df is None or df.empty: return []
    b = _Bars(df)
    nodes = sorted(((pd.to_datetime(p[0]), float(p[1])) for p in pts), key=lambda x: x[0])
    breakouts = []
    
    for i in range(3, len(nodes)):
        (a_t, a_p), (b_t, b_p), (c_t, c_p), (d_t, d_p) = nodes[i - 3:i + 1]

        if a_p < b_p and a_p < c_p < b_p and d_p > b_p: s, trend = 1, "up"
        elif a_p > b_p and b_p < c_p < a_p and d_p < b_p: s, trend = -1, "down"
        else: continue

        bars, vol, brk_time = calculate_breakout_metrics(b, b_p, c_t, d_t, is_up=(s > 0))
        curr_height = s * (d_p - c_p)
        prev_height = s * (b_p - a_p)
        setup_delta = s * (b_p - c_p)

        p0, p1 = b.span(a_t, b_t)
        c0, c1 = b.span(c_t, d_t)
        s0, s1 = b.span(b_t, c_t)
        prev_bars, curr_bars = p1 - p0, c1 - c0
        prev_vol = b.vsum(p0, p1)

        height_ratio = curr_height / prev_height if prev_height > 0 else 0
        bars_ratio = curr_bars / prev_bars if prev_bars > 0 else 0
        vol_ratio = b.vsum(c0, c1) / prev_vol if prev_vol > 0 else 0
        breakout_pct = (curr_height / setup_delta * 100) if setup_delta > 0 else 0

        has_pullback = False
        e_t = e_p = e_delta = retracement_pct = pullback_verdict = None
        e_vs_05, retr_bars, retr_vol = "-", 0, 0

        if i + 1 < len(nodes):
            e_t, e_p = nodes[i + 1]
            if s * (d_p - e_p) > 0:
                has_pullback = True
                e_delta = s * (d_p - e_p)
                fib_05 = d_p - s * curr_height * 0.5
                retracement_pct = (e_delta / curr_height * 100) if curr_height > 0 else 0
                
                # Слабый откат (не дошел до 0.5) = сильный тренд. Сильный откат (глубже 0.5) = слабый тренд.
                if s * (e_p - fib_05) > 0:
                    pullback_verdict = "Слабый"
                    e_vs_05 = "выше 0.5" if s > 0 else "ниже 0.5"
                elif s * (e_p - fib_05) < 0:
                    pullback_verdict = "Сильный"
                    e_vs_05 = "ниже 0.5" if s > 0 else "выше 0.5"
                else:
                    pullback_verdict = "Нормальный"
                    e_vs_05 = "на уровне 0.5"
                    
                r0, r1 = b.span(d_t, e_t)
                retr_bars, retr_vol = r1 - r0, b.vsum(r0, r1)
            else: e_t = e_p = None

        if height_ratio >= 1.1 and bars_ratio <= 1.0: verdict = "strong"
        elif height_ratio <= 0.9 or bars_ratio >= 1.5 or vol_ratio >= 1.5: verdict = "weak"
        else: verdict = "normal"

        breakouts.append({
            "trend": trend, "resistance_time": b_t, "resistance_price": b_p,
            "pullback_setup_time": c_t, "pullback_setup_price": c_p,
            "peak_time": d_t, "peak_price": d_p, "breakout_time": brk_time,
            "delta": curr_height, "breakout_pct": breakout_pct, "bars": bars, "volume": vol,
            "setup_delta": setup_delta, "setup_bars": s1 - s0, "setup_vol": b.vsum(s0, s1),
            "has_pullback": has_pullback, "e_time": e_t, "e_price": e_p, "e_delta": e_delta,
            "retr_bars": retr_bars, "retr_vol": retr_vol,
            "retracement_pct": retracement_pct, "pullback_verdict": pullback_verdict,
            "e_vs_b": e_vs_05, "height_ratio": height_ratio, "bars_ratio": bars_ratio,
            "vol_ratio": vol_ratio, "breakout_verdict": verdict,
        })
    return breakouts

def _anomaly_color(tf_name: str) -> str | None:
    return {"M10": "red", "M1": "red", "H1": "green", "D1": "blue"}.get(tf_name)

def get_volume_colors(df, tf_name, sensitivity=3.0):
    if df is None or df.empty or "Volume" not in df.columns: return []
    v = df["Volume"].to_numpy(dtype="float64", copy=False)
    n = v.size
    colors = np.full(n, "gray", dtype=object)

    if n > 2:
        m = np.zeros(n, dtype=bool)
        m[2:] = (v[2:] > v[1:-1]) & (v[2:] > v[:-2])
        colors[m] = "black"

    if tf_name == "H1" and isinstance(df.index, pd.DatetimeIndex):
        pos = np.flatnonzero((df.index.hour == 10) & (df.index.minute == 0))
        if pos.size >= 3:
            vv = v[pos]
            cmp_ = (vv[2:] > vv[1:-1]) & (vv[2:] > vv[:-2])
            colors[pos[2:][cmp_]] = "black"

    anomaly = _anomaly_color(tf_name)
    if anomaly and n:
        avg = (pd.Series(v).rolling(20, min_periods=5).mean().shift(1).to_numpy(dtype="float64"))
        with np.errstate(invalid="ignore"):
            mask = np.isfinite(avg) & (avg > 0) & (v > avg * sensitivity)
        colors[mask] = anomaly
    return colors.tolist()

def calculate_volume_profile(df, tf_name="M10", threshold_pct=50, sensitivity=3.0, colors=None):
    """Профиль значимых объёмов. Строится по стандартным правилам (от Low до Close / от Close до High)."""
    if df is None or df.empty or "Volume" not in df.columns: return []
    colors = np.asarray(colors if colors is not None else get_volume_colors(df, tf_name, sensitivity), dtype=object)
    if colors.size != len(df): return []

    anomaly = _anomaly_color(tf_name)
    mask = (colors == "black") | ((colors == anomaly) if anomaly else False)
    if not mask.any(): return []

    o = df["Open"].to_numpy(dtype="float64", copy=False)[mask]
    c = df["Close"].to_numpy(dtype="float64", copy=False)[mask]
    h = df["High"].to_numpy(dtype="float64", copy=False)[mask]
    l = df["Low"].to_numpy(dtype="float64", copy=False)[mask]
    vol = df["Volume"].to_numpy(dtype="float64", copy=False)[mask]

    is_buy = c > o
    low = np.where(is_buy, l, c)
    high = np.where(is_buy, c, h)
        
    ok = (high > low) & (vol > 0)
    low, high, vol = low[ok], high[ok], vol[ok]
    if low.size == 0: return []

    edges = np.unique(np.concatenate((low, high)))
    if edges.size < 2: return []

    diff = np.zeros(edges.size, dtype="float64")
    np.add.at(diff, np.searchsorted(edges, low), vol)
    np.add.at(diff, np.searchsorted(edges, high), -vol)
    band_vol = np.cumsum(diff)[:-1]

    keep = band_vol > 0
    if not keep.any(): return []

    max_vol, min_vol = float(band_vol[keep].max()), float(band_vol[keep].min())
    if max_vol > min_vol: threshold = min_vol + (max_vol - min_vol) * (int(threshold_pct) - 10) / 90.0
    else: threshold = min_vol

    sel = keep & (band_vol >= threshold)
    if not sel.any(): return []

    if max_vol > threshold: opacity = 0.15 + 0.45 * (band_vol - threshold) / (max_vol - threshold)
    else: opacity = np.full(band_vol.size, 0.60)

    out, i, idx = [], 0, np.flatnonzero(sel)
    while i < idx.size:
        j = i
        while (j + 1 < idx.size and idx[j + 1] == idx[j] + 1 and band_vol[idx[j + 1]] == band_vol[idx[j]]): j += 1
        out.append({"low": float(edges[idx[i]]), "high": float(edges[idx[j] + 1]), "opacity": float(opacity[idx[i]])})
        i = j + 1
    return out
