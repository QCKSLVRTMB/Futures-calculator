from __future__ import annotations
import streamlit as st

CSS = """
<style>
  .block-container{padding-top:1.2rem;padding-bottom:3.5rem;}
  div[data-testid="stToolbar"]{visibility:hidden;height:0;}
  div[data-baseweb="tab-list"]{overflow-x:auto;scrollbar-width:none;}
  div[data-baseweb="tab-list"]::-webkit-scrollbar{display:none;}

  /* ===== Карточки (светлая тема) ===== */
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

  /* Плотные таблицы/графики — чёрные бары как раньше, светлый фон */
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

def cards(items: list[tuple[str, str, str]]) -> None:
    html = "".join(
        f'<div class="fc-card"><div class="lbl">{l}</div>'
        f'<div class="val fc-{c}">{v}</div></div>'
        for l, v, c in items
    )
    st.markdown(f'<div class="fc-cards">{html}</div>', unsafe_allow_html=True)

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
