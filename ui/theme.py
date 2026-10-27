from __future__ import annotations
import pandas as pd
import streamlit as st

CSS = """
<style>
  .block-container{padding-top:1rem;padding-bottom:3.5rem;}
  div[data-testid="stToolbar"]{visibility:hidden;height:0;}
  div[data-baseweb="tab-list"]{overflow-x:auto;scrollbar-width:none;}
  div[data-baseweb="tab-list"]::-webkit-scrollbar{display:none;}

  .fc-cards{display:grid;gap:.5rem;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));}
  .fc-card{
    background:#FFFFFF;
    border:1px solid #E3E7ED;
    border-radius:12px;
    padding:.6rem .75rem;
    box-shadow:0 1px 2px rgba(0,0,0,0.03);
  }
  .fc-card .lbl{font-size:.72rem;color:#6B7280;line-height:1.1;}
  .fc-card .val{font-size:1.05rem;font-weight:600;margin-top:.15rem;color:#0E1117;}
  .fc-ok{color:#1B7A6D !important;}
  .fc-bad{color:#D32F2F !important;}
  .fc-warn{color:#C77800 !important;}

  div[data-testid="stPlotlyChart"]{background:#FFFFFF;border-radius:10px;}

  @media (max-width: 640px){
    .block-container{padding-left:.6rem;padding-right:.6rem;padding-top:.6rem;}
    h1{font-size:1.3rem!important;} h2{font-size:1.1rem!important;} h3{font-size:1rem!important;}
    .stButton button, .stDownloadButton button{min-height:44px;width:100%;}
    div[data-testid="stMetricValue"]{font-size:1.05rem;}
    div[data-baseweb="tab"]{padding:.35rem .6rem;font-size:.82rem;}
    .fc-cards{grid-template-columns:repeat(2,1fr);}
    .js-plotly-plot{touch-action:pan-y;}
  }
</style>
"""

def inject_css() -> None:
    if not st.session_state.get("_css_done"):
        st.markdown(CSS, unsafe_allow_html=True)
        st.session_state["_css_done"] = True

def format_date(val) -> str:
    try:
        return pd.to_datetime(val).strftime('%d.%m.%Y')
    except Exception:
        return str(val)

def kv_data(items: list[tuple[str, str, str]], mobile: bool = False):
    """Рисует таблицу параметров. Статусы: ok / bad / warn / fail (красная заливка) / '' """
    if mobile:
        html = "<div style='display:flex; flex-direction:column; gap:6px;'>"
        for label, value, status in items:
            if status == "fail":
                row_style = "background:#ef5350; border:1px solid #c62828;"
                lbl_color = "color:#000000;"
                val_color = "color:#000000;"
            elif status == "ok":
                row_style = "background:#fff; border:1px solid #e2e8f0;"
                lbl_color = "color:#64748b;"
                val_color = "color:#16a34a;"
            elif status == "bad":
                row_style = "background:#fff; border:1px solid #e2e8f0;"
                lbl_color = "color:#64748b;"
                val_color = "color:#dc2626;"
            elif status == "warn":
                row_style = "background:#fff; border:1px solid #e2e8f0;"
                lbl_color = "color:#64748b;"
                val_color = "color:#d97706;"
            else:
                row_style = "background:#fff; border:1px solid #e2e8f0;"
                lbl_color = "color:#64748b;"
                val_color = "color:#0f172a;"

            html += f"""
            <div style="{row_style} border-radius:6px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center;">
                <span style="{lbl_color} font-size:13px;">{label}</span>
                <span style="font-weight:600; font-size:15px; {val_color}">{value}</span>
            </div>"""
        html += "</div>"
    else:
        html = "<table style='width:100%; border-collapse:collapse; font-size:14px; margin-bottom: 1rem;'>"
        html += "<thead><tr><th style='text-align:left; padding:10px; border-bottom:2px solid #cbd5e1; color:#475569; font-weight: 600;'>Параметр</th><th style='text-align:right; padding:10px; border-bottom:2px solid #cbd5e1; color:#475569; font-weight: 600;'>Значение</th></tr></thead><tbody>"
        for label, value, status in items:
            if status == "fail":
                color = "background:#ef5350; color:#000000;"
            elif status == "ok":
                color = "color: #16a34a;"
            elif status == "bad":
                color = "color: #dc2626;"
            elif status == "warn":
                color = "color: #d97706;"
            else:
                color = "color: #0f172a;"
            html += f"<tr><td style='padding:10px; border-bottom:1px solid #e2e8f0; color:#334155;'>{label}</td><td style='text-align:right; padding:10px; border-bottom:1px solid #e2e8f0; font-weight:600; {color}'>{value}</td></tr>"
        html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

def fragment(fn):
    f = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    return f(fn) if f else fn

def seg(label, options, *, key, default=None, fmt=None, help=None):
    if hasattr(st, "segmented_control"):
        if key not in st.session_state:
            st.session_state[key] = default if default is not None else options[0]
        return st.segmented_control(label, options, key=key, format_func=fmt or str,
                                    help=help, selection_mode="single")
    idx = options.index(default) if default in options else 0
    return st.radio(label, options, index=idx, key=key, horizontal=True,
                    format_func=fmt or str, help=help)

def money(v) -> str:
    try:
        return f"{float(v):,.2f} ₽".replace(",", " ").replace(".", ",")
    except Exception:
        return str(v)

def num(v, d=2) -> str:
    try:
        return f"{float(v):,.{d}f}".replace(",", " ").replace(".", ",")
    except Exception:
        return str(v)
