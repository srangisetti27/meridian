"""Meridian Pipeline Intelligence — Streamlit chat UI.

This module only renders. Every number on screen comes from an AnswerPacket
built by analytics.py from the validated CSVs. The optional LLM layer may
route a question onto the approved intent menu and phrase a computed answer —
but a numeric validator vetoes any narration containing a number that the
deterministic engine did not produce.
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime
from typing import Optional

import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

import time

import config as C
import llm_layer
import observability
from analytics import AnswerPacket, ChartSpec, build_answer, pct, reconcile
from data_loader import DataValidationError, load_bundle
from question_router import (INTENT_LABELS, SUGGESTED_QUESTIONS, UNSUPPORTED,
                             route)

st.set_page_config(page_title="Meridian Pipeline Intelligence",
                   page_icon="◆", layout="wide",
                   initial_sidebar_state="collapsed")

# Neutral light palette with system semantic colors
_RISK_COLORS = {
    C.RISK_ON_TRACK: "#34C759", C.RISK_WATCH: "#FF9500",
    C.RISK_AT_RISK: "#FF3B30", C.RISK_INSUFFICIENT: "#8E8E93"}
_MEASURE_COLORS = {
    "Closed-Won (booked)": "#34C759", "Open pipeline": "#FF9500",
    "Q2 quota": "#D1D1D6"}

_GLOBAL_CSS = """
<style>
html, body, [data-testid="stAppViewContainer"] * {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text',
                 'Helvetica Neue', 'Inter', sans-serif;
    -webkit-font-smoothing: antialiased;
}
/* restore Streamlit's icon font (the universal rule above must not touch it,
   otherwise icons render as literal text like 'keyboard_arrow_right') */
[data-testid="stIconMaterial"], [class*="material-symbols"],
span[translate="no"] {
    font-family: 'Material Symbols Rounded' !important;
}
#MainMenu, footer, [data-testid="stDecoration"] { display: none; }

/* ---- FORCE LIGHT: these surfaces stay light even if the base theme or the
   browser's dark preference says otherwise ---- */
[data-testid="stAppViewContainer"] { background: #F5F5F7 !important; }
[data-testid="stHeader"] { background: #F5F5F7 !important; }
[data-testid="stSidebar"] { background: #FBFBFD !important; }
[data-testid="stSidebar"] * { color: #1D1D1F; }
[data-testid="stBottom"], [data-testid="stBottomBlockContainer"] {
    background: #F5F5F7 !important; }
[data-testid="stChatInput"] > div {
    background: #FFFFFF !important; border: 1px solid #E5E5EA !important; }
[data-testid="stChatInput"] textarea {
    background: #FFFFFF !important; color: #1D1D1F !important;
    caret-color: #1D1D1F !important; }
[data-testid="stChatInput"] textarea::placeholder { color: #86868B !important; }
body, p, li, span, label { color: #1D1D1F; }
.block-container { padding-top: 2.3rem; max-width: 1080px; }
:root { color-scheme: light; }

@keyframes rise { from { opacity: 0; transform: translateY(10px); }
                  to   { opacity: 1; transform: none; } }

/* ---- no ghost overlap: hide previous-run elements instantly during
   a rerun instead of Streamlit's slow crossfade ---- */
[data-stale="true"] { display: none !important; }

/* ---- kill Streamlit's hover element toolbar (the 'st.iframe' tag) ---- */
[data-testid="stElementToolbar"] { display: none !important; }

/* ---- slim workspace top bar ---- */
.wordmark { font-size: 1.05rem; font-weight: 700; letter-spacing: -.02em;
    color: #1D1D1F; padding-top: 4px; }
.wordmark span { color: #7C3AED; }
button[kind="tertiary"] {
    background: transparent !important; border: none !important;
    color: #86868B !important; font-size: .78rem !important;
    font-weight: 500 !important; box-shadow: none !important;
    min-height: 0 !important; padding: 6px 10px !important;
    justify-content: center !important; }
button[kind="tertiary"]:hover { color: #7C3AED !important;
    transform: none !important; }

/* ---- premium chat: user bubble right, assistant card airy ---- */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    display: flex; justify-content: flex-end; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"])
    [data-testid="stMarkdownContainer"] { text-align: right; }
.q-text { display: inline-block; background: #F5F3FF; color: #4C1D95;
    padding: 10px 18px; border-radius: 18px 18px 4px 18px;
    font-size: .92rem; font-weight: 500; text-align: left;
    box-shadow: 0 2px 10px rgba(124,58,237,.08); }

/* ---- premium chat input: floating violet-tinted pill ---- */
[data-testid="stBottom"] { background: transparent !important; }
[data-testid="stChatInput"] {
    border-radius: 999px; border: 1px solid #ECECF0; background: #FFFFFF;
    box-shadow: 0 12px 36px rgba(124,58,237,.10); }
[data-testid="stChatInput"]:focus-within {
    border-color: #C4B5FD; box-shadow: 0 12px 40px rgba(124,58,237,.16); }

/* ---------- landing orb: rotating gradient sphere ---------- */
.orb-wrap { display:flex; justify-content:center; margin:4px 0 20px; }
.orb { width:88px; height:88px; border-radius:50%; position:relative;
  background: radial-gradient(circle at 32% 28%,
      #fdf4ff 0%, #f0abfc 20%, #e879f9 40%, #d946ef 62%,
      #a21caf 86%, #86198f 100%);
  box-shadow: 0 18px 48px rgba(192,38,211,.35),
              0 0 80px rgba(232,121,249,.45);
  animation: orbFloat 5s ease-in-out infinite; }
.orb::before { content:''; position:absolute; inset:-5px; border-radius:50%;
  background: conic-gradient(from 0deg,
      rgba(255,255,255,0) 0deg,  rgba(255,255,255,.55) 70deg,
      rgba(255,255,255,0) 150deg, rgba(134,25,143,.30) 230deg,
      rgba(255,255,255,0) 360deg);
  filter: blur(7px); animation: orbSpin 6s linear infinite; }
.orb::after { content:''; position:absolute; left:20%; top:15%;
  width:26%; height:20%; border-radius:50%;
  background: rgba(255,255,255,.9); filter: blur(5px); }
@keyframes orbSpin  { to { transform: rotate(360deg); } }
@keyframes orbFloat { 0%,100% { transform: translateY(0) scale(1); }
                      50%     { transform: translateY(-7px) scale(1.03); } }

/* ---------- landing ---------- */
.land-kicker { font-size:.68rem; font-weight:700; letter-spacing:.14em;
    text-transform:uppercase; color:#7C3AED; margin-bottom:10px; }
.land-h1 { font-size:2.1rem; font-weight:700; letter-spacing:-.03em;
    color:#1D1D1F; line-height:1.15; margin-bottom:10px; }
.land-lead { font-size:1rem; color:#6E6E73; line-height:1.6;
    max-width:760px; margin-bottom:22px; }
.land-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px;
    margin:14px 0; }
.land-card { background:#FFFFFF; border:1px solid #E5E5EA;
    border-radius:16px; padding:16px 18px; animation: rise .5s ease-out both; }
.land-card:nth-child(2){animation-delay:.08s;}
.land-card:nth-child(3){animation-delay:.16s;}
.land-card h4 { font-size:.92rem; font-weight:650; color:#1D1D1F;
    margin-bottom:5px; }
.land-card p { font-size:.8rem; color:#6E6E73; line-height:1.5; margin:0; }
.land-card.ask { border-top:3px solid #7C3AED; }
.land-card .ok { color:#1E7E34; font-weight:600; font-size:.74rem; }
.land-flow { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
    margin:18px 0 6px; }
.land-step { border:1px solid #E5E5EA; background:#FFFFFF;
    border-radius:999px; padding:6px 14px; font-size:.78rem;
    font-weight:600; color:#3A3A3C; }
.land-step.g { border-color:#BFE3C6; background:#F2FBF4; color:#1E7E34; }
.land-step.b { border-color:#DDD6FE; background:#F5F3FF; color:#6D28D9; }
.land-arr { color:#B9B9BE; font-weight:700; }
.land-stats { display:flex; gap:10px; flex-wrap:wrap; margin:16px 0 20px; }
.land-stat { border:1px solid #E5E5EA; background:#FFFFFF;
    border-radius:12px; padding:8px 16px; text-align:center; }
.land-stat b { display:block; font-size:1.15rem; font-weight:700;
    color:#1D1D1F; font-variant-numeric:tabular-nums; }
.land-stat span { font-size:.68rem; color:#86868B; font-weight:600;
    letter-spacing:.04em; text-transform:uppercase; }
.land-try { font-size:.7rem; font-weight:700; letter-spacing:.1em;
    text-transform:uppercase; color:#86868B; margin:6px 0 8px; }

/* ---------- header ---------- */
.hero { padding: 0 2px 4px; margin-bottom: 2px; animation: rise .4s ease-out; }
.hero h1 { margin: 0 0 5px; font-size: 1.6rem; font-weight: 700;
           letter-spacing: -.02em; color: #1D1D1F; }
.hero p  { margin: 0 0 8px; color: #6E6E73; font-size: .92rem;
           max-width: 780px; line-height: 1.5; }
.meta-line { font-size: .78rem; color: #86868B; font-weight: 500; }
.meta-line b { color: #3A3A3C; font-weight: 600; }

/* ---------- answer header: intent + status ---------- */
.answer-head { display: flex; align-items: center; justify-content:
               space-between; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.intent-tag { font-size: .68rem; font-weight: 600; letter-spacing: .08em;
              text-transform: uppercase; color: #86868B; }
.status { display: inline-flex; align-items: center; gap: 7px;
          font-size: .76rem; font-weight: 600; padding: 4px 12px;
          border-radius: 999px; white-space: nowrap; }
.status .sdot { width: 7px; height: 7px; border-radius: 50%; flex: none; }
.status.green { background: #E9F7EC; color: #1E7E34; }
.status.green .sdot { background: #34C759; }
.status.amber { background: #FFF4E0; color: #955300; }
.status.amber .sdot { background: #FF9500; }
.status.red   { background: #FDECEB; color: #C2352B; }
.status.red .sdot   { background: #FF3B30; }

.answer-headline { font-size: 1.02rem; font-weight: 500; color: #1D1D1F;
                   line-height: 1.55; margin: 0 0 6px; max-width: 860px; }
.verify-line { font-size: .74rem; color: #86868B; margin: 0 0 14px; }
.verify-line b { color: #1E7E34; font-weight: 600; }
.verify-line.reject b { color: #C2352B; }

/* ---------- warnings & assumptions ---------- */
.sec-label { font-size: .66rem; font-weight: 700; letter-spacing: .09em;
             text-transform: uppercase; color: #955300; margin: 8px 0 6px; }
.warn { font-size: .8rem; color: #3A3A3C; padding: 8px 12px;
        border-left: 3px solid #FF9500; background: #FFFBF4;
        border-radius: 0 8px 8px 0; margin-bottom: 6px; line-height: 1.5;
        animation: rise .35s ease-out both; }
.assump { font-size: .77rem; color: #6E6E73; padding: 3px 0 3px 12px;
          border-left: 2px solid #E5E5EA; margin-bottom: 5px;
          line-height: 1.45; }
.calc { font-size: .76rem; color: #3A3A3C; font-family: 'SF Mono',
        ui-monospace, Menlo, monospace !important; padding: 5px 10px;
        background: #F5F5F7; border-radius: 8px; margin-bottom: 5px;
        line-height: 1.5; }

/* ---------- metric cards: hover lift ---------- */
[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 14px;
    padding: 13px 15px 9px; transition: transform .18s ease,
    box-shadow .18s ease; }
[data-testid="stMetric"]:hover { transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(0,0,0,.07); }
[data-testid="stMetricLabel"] p { font-size: .68rem !important;
    font-weight: 600 !important; text-transform: uppercase;
    letter-spacing: .06em; color: #86868B !important; }
[data-testid="stMetricValue"] { font-size: 1.3rem !important;
    font-weight: 700 !important; letter-spacing: -.02em;
    color: #1D1D1F !important; font-variant-numeric: tabular-nums; }

/* ---------- chips: uniform one-line capsules ---------- */
.try-label { font-size: .66rem; font-weight: 700; letter-spacing: .09em;
             text-transform: uppercase; color: #86868B; margin: 6px 0 2px; }
.stButton > button {
    border-radius: 999px; border: 1px solid #D8D8DC; background: #FFFFFF;
    color: #3A3A3C; font-weight: 500; font-size: .82rem;
    padding: 7px 16px; box-shadow: none; white-space: nowrap; width: 100%;
    transition: all .18s cubic-bezier(.4,0,.2,1); }
.stButton > button:hover {
    background: #F5F5F7; border-color: #B9B9BE; color: #7C3AED;
    transform: translateY(-1px); }
.stButton > button:active { transform: scale(.97); }

/* ---------- chat: animated entrance ---------- */
[data-testid^="stChatMessageAvatar"] { display: none; }
[data-testid="stChatMessage"] {
    background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 16px;
    padding: 18px 22px 14px; margin-bottom: 12px; gap: 0;
    animation: rise .4s ease-out both; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: transparent; border: none; box-shadow: none;
    padding: 2px 6px 0; margin-bottom: 2px; }

/* ---------- tabs ---------- */
[data-testid="stTabs"] button { font-size: .82rem; font-weight: 500; }

/* ---------- chat input ---------- */
[data-testid="stChatInput"] { border-radius: 999px; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { border-right: 1px solid #E5E5EA; }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    letter-spacing: .07em; text-transform: uppercase; font-size: .68rem;
    color: #86868B; font-weight: 600; margin-bottom: .4rem; }
.ok-line { display: flex; align-items: center; gap: 7px; font-size: .8rem;
           font-weight: 600; color: #1E7E34; margin-bottom: 8px; }
.ok-line::before { content: ''; width: 7px; height: 7px; border-radius: 50%;
           background: #34C759; display: inline-block; }
.dl { font-size: .78rem; color: #515154; line-height: 1.7;
      margin-bottom: 8px; }
.dl b { color: #1D1D1F; font-weight: 600; font-variant-numeric: tabular-nums; }
.flag { display: flex; gap: 8px; font-size: .73rem; color: #515154;
        line-height: 1.45; padding: 8px 0; border-bottom: 1px solid #ECECEE; }
.flag:last-child { border-bottom: none; }
.flag-code { flex: none; font-weight: 700; font-size: .64rem;
        color: #955300; background: #FFF3E0; border-radius: 6px;
        padding: 2px 7px; height: fit-content; margin-top: 1px; }

[data-testid="stCaptionContainer"] { color: #86868B; }
</style>
"""
st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def esc(text: str) -> str:
    """Escape $ for markdown contexts (prevents LaTeX garbling)."""
    return text.replace("$", r"\$")


def h(text: str) -> str:
    """Escape for raw-HTML contexts."""
    return _html.escape(text)


# ---------------------------------------------------------------------------
# Data loading (fail-closed)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Validating data…")
def _load() -> tuple:
    bundle = load_bundle()
    checks = reconcile(bundle)          # raises if totals do not agree
    return bundle, checks


try:
    BUNDLE, RECON_CHECKS = _load()
except DataValidationError as exc:
    st.error(f"**Data failed validation — no numbers will be shown.**\n\n{exc}")
    st.stop()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
_STATUS = {
    C.TRUST_VERIFIED: ("green", "Verified"),
    C.TRUST_WITH_ASSUMPTIONS: ("amber", "Verified with assumptions"),
    C.TRUST_INSUFFICIENT: ("red", "Insufficient data"),
}


def _status_html(trust: str) -> str:
    cls, label = _STATUS[trust]
    return (f'<span class="status {cls}"><span class="sdot"></span>'
            f'{label}</span>')


def _polish(fig) -> None:
    """Consistent, restrained chart styling with smooth hover."""
    fig.update_layout(
        template="plotly_white",
        font_family="-apple-system, BlinkMacSystemFont, Helvetica Neue, "
                    "Inter, sans-serif",
        font_size=12,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=44, b=8), height=320,
        title_font=dict(size=13, color="#6E6E73"),
        hoverlabel=dict(bgcolor="#1D1D1F", font_size=12,
                        font_color="#FFFFFF"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="right", x=1.0, font=dict(size=11)),
        transition=dict(duration=350, easing="cubic-in-out"))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#ECECF0")


def render_chart(spec: ChartSpec, key: str) -> None:
    if spec.kind == "grouped_money":
        fig = px.bar(spec.df, x="label", y="amount", color="measure",
                     barmode="group", title=spec.title,
                     color_discrete_map=_MEASURE_COLORS)
        fig.update_layout(yaxis_tickformat="$,.0f", xaxis_title="",
                          yaxis_title="", legend_title="")
    elif spec.kind == "coverage":
        fig = px.bar(spec.df, x="coverage", y="rep_name", orientation="h",
                     color="risk", title=spec.title,
                     color_discrete_map=_RISK_COLORS)
        fig.add_vline(x=C.RISK["cov_floor"], line_dash="dash",
                      line_color="#FF3B30",
                      annotation_text="1.0x — gap uncloseable below this")
        fig.add_vline(x=spec.meta["breakeven"], line_dash="dot",
                      line_color="#8E8E93",
                      annotation_text=f"{spec.meta['breakeven']:.2f}x break-even "
                                      "at Q1 win rate")
        fig.update_layout(xaxis_title="pipeline ÷ remaining quota",
                          yaxis_title="", legend_title="")
    elif spec.kind == "attainment_compare":
        fig = px.bar(spec.df, x="quarter", y="attainment_pct", title=spec.title,
                     text=spec.df["attainment_pct"].map(lambda v: f"{v:.1f}%"),
                     color="quarter",
                     color_discrete_sequence=["#D1D1D6", "#7C3AED"])
        fig.update_layout(yaxis_title="attainment (% of quota)",
                          xaxis_title="", showlegend=False)
    elif spec.kind == "stage_mix":
        fig = px.bar(spec.df, x="stage", y="value", title=spec.title,
                     text=spec.df["value"].map(lambda v: f"${v:,.0f}"),
                     color_discrete_sequence=["#7C3AED"])
        fig.update_layout(yaxis_tickformat="$,.0f", xaxis_title="",
                          yaxis_title="open pipeline value")
    elif spec.kind == "impact_bar":
        fig = px.bar(spec.df, x="label", y="value", title=spec.title,
                     text=spec.df["value"].map(lambda v: f"${v:,.0f}"),
                     color_discrete_sequence=["#FF3B30"])
        fig.update_layout(yaxis_tickformat="$,.0f", xaxis_title="",
                          yaxis_title="value touched")
    else:                                            # pragma: no cover
        return
    _polish(fig)
    st.plotly_chart(fig, key=key, config={"displayModeBar": False})


def render_answer(packet: AnswerPacket,
                  narration: Optional[llm_layer.Narration],
                  intent_label: str, matched_on: str,
                  turn_key: str) -> None:
    # Header row: what was answered + the trust status, on one line
    st.markdown(
        f'<div class="answer-head">'
        f'<span class="intent-tag">{h(intent_label)} &nbsp;·&nbsp; '
        f'{h(matched_on)}</span>'
        f'{_status_html(packet.trust)}</div>',
        unsafe_allow_html=True)

    # The answer itself — validated narration, or deterministic headline
    if narration is not None and narration.ok:
        st.markdown(f'<div class="answer-headline">{h(narration.text)}</div>',
                    unsafe_allow_html=True)
        st.markdown(
            f'<div class="verify-line">AI summary · '
            f'<b>{narration.numbers_checked} numbers verified</b> against '
            'computed results · deterministic wording under Calculation'
            '</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="answer-headline">{h(packet.headline)}</div>',
                    unsafe_allow_html=True)
        if narration is not None and not narration.ok:
            rejected = ", ".join(str(n) for n in narration.rejected_numbers)
            st.markdown(
                f'<div class="verify-line reject">AI summary '
                f'<b>rejected by the numeric validator</b> — it contained '
                f'{h(rejected)}, not present in the computed results. '
                'Deterministic answer shown instead.</div>',
                unsafe_allow_html=True)

    n = len(packet.metrics)
    for start in range(0, n, 5):
        cols = st.columns(min(5, n - start))
        for col, card in zip(cols, packet.metrics[start:start + 5]):
            col.metric(card.label, card.value)
            if card.caption:
                col.caption(esc(card.caption))

    if packet.chart is not None:
        render_chart(packet.chart, key=f"chart_{turn_key}")

    # Data-quality warnings stay always-visible — that is the product's point
    if packet.warnings:
        st.markdown('<div class="sec-label">Data-quality warnings</div>',
                    unsafe_allow_html=True)
        for warning in packet.warnings:
            st.markdown(f'<div class="warn">{h(warning)}</div>',
                        unsafe_allow_html=True)

    tab_src, tab_calc, tab_assump = st.tabs(
        ["Source data", "Calculation", "Assumptions"])
    with tab_src:
        for i, table in enumerate(packet.evidence):
            st.markdown(f"**{esc(table.title)}**")
            st.dataframe(table.df, width="stretch", hide_index=True,
                         key=f"ev_{turn_key}_{i}")
    with tab_calc:
        if narration is not None and narration.ok:
            st.markdown(
                f'<div class="answer-headline">{h(packet.headline)}</div>',
                unsafe_allow_html=True)
        for line in packet.calculation:
            st.markdown(f'<div class="calc">{h(line)}</div>',
                        unsafe_allow_html=True)
        st.caption("All figures are computed with deterministic pandas "
                   "operations on the validated CSV files. No language model "
                   "produces or transforms any number.")
    with tab_assump:
        for assumption in packet.assumptions:
            st.markdown(f'<div class="assump">{h(assumption)}</div>',
                        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Question processing
# ---------------------------------------------------------------------------
def process_question(question: str, llm_on: bool) -> dict:
    """Route, compute, and (optionally) narrate one question. Returns a turn
    dict for the conversation history. All numbers come from build_answer."""
    result = route(question, BUNDLE)
    if result.intent == UNSUPPORTED and llm_on:
        llm_result = llm_layer.classify_intent_llm(question, BUNDLE)
        if llm_result is not None:
            result = llm_result

    if result.intent == UNSUPPORTED:
        return {"question": question, "refusal": C.UNSUPPORTED_MESSAGE,
                "matched_on": result.matched_on}

    packet = build_answer(result.intent, result.entity, BUNDLE)
    narration = llm_layer.narrate_answer(packet, question) if llm_on else None
    return {"question": question, "packet": packet, "narration": narration,
            "intent": result.intent, "matched_on": result.matched_on}


# ---------------------------------------------------------------------------
# Landing page — the engagement story; shown until the user enters the app
# ---------------------------------------------------------------------------
def render_landing() -> None:
    """Assistant-home landing: orb, greeting, one big input, example cards."""
    hour = datetime.now().hour
    greeting = ("Good morning" if hour < 12
                else "Good afternoon" if hour < 18 else "Good evening")

    # Landing-only styling: example-card buttons + the big ask box.
    st.markdown("""
<style>
  .greet { text-align:center; font-size:2.3rem; font-weight:700;
           letter-spacing:-.03em; color:#1D1D1F; line-height:1.2; }
  .greet .grad { background:linear-gradient(92deg,#A855F7,#D946EF 55%,#EC4899);
           -webkit-background-clip:text; background-clip:text;
           color:transparent; }
  .greet-sub { text-align:center; color:#86868B; font-size:.85rem;
           margin:10px 0 26px; }
  .eg-label { font-size:.68rem; font-weight:700; letter-spacing:.12em;
           text-transform:uppercase; color:#86868B;
           max-width:900px; margin:26px auto 10px; }
  .stButton > button {
      border-radius:16px; background:#F7F7F9; border:1px solid #ECECF0;
      color:#3A3A3C; font-weight:500; font-size:.85rem; text-align:left;
      justify-content:flex-start; align-items:flex-start;
      min-height:112px; padding:16px; white-space:normal;
      line-height:1.45; box-shadow:none; }
  .stButton > button:hover {
      background:#F5F3FF; border-color:#C4B5FD; color:#5B21B6;
      transform:translateY(-2px);
      box-shadow:0 10px 26px rgba(124,58,237,.10); }
  .stButton > button[kind="tertiary"] {
      background:transparent; border:none; min-height:0; padding:6px;
      color:#86868B; font-size:.78rem; justify-content:center;
      text-align:center; }
  .stButton > button[kind="tertiary"]:hover { color:#7C3AED;
      background:transparent; transform:none; box-shadow:none; }
  [data-testid="stForm"] {
      border:1px solid #ECECF0; border-radius:22px; background:#FFFFFF;
      padding:14px 16px 8px; max-width:840px; margin:0 auto;
      box-shadow:0 14px 44px rgba(124,58,237,.09); }
  [data-testid="stForm"] div[data-baseweb="input"] {
      border:none !important; background:transparent !important;
      box-shadow:none !important; }
  [data-testid="stForm"] input { font-size:1.02rem !important;
      color:#1D1D1F !important; }
  [data-testid="stForm"] button {
      border-radius:14px; min-height:0; padding:8px 18px;
      background:#7C3AED; border-color:#7C3AED; color:#fff;
      font-weight:600; text-align:center; justify-content:center; }
  [data-testid="stForm"] button:hover { background:#6D28D9;
      border-color:#6D28D9; color:#fff; transform:none; box-shadow:none; }
</style>""", unsafe_allow_html=True)

    st.markdown(f"""
<div style="max-width:900px; margin:36px auto 0;">
  <div class="orb-wrap"><div class="orb"></div></div>
  <div class="greet">{greeting}.</div>
  <div class="greet">What's on <span class="grad">your pipeline?</span></div>
  <div class="greet-sub">Every answer shows its source records, its formula,
  and its assumptions — numbers are computed, never generated.</div>
</div>""", unsafe_allow_html=True)

    with st.form("landing_ask", clear_on_submit=False):
        col_in, col_btn = st.columns([8, 1])
        typed = col_in.text_input(
            "Ask", label_visibility="collapsed",
            placeholder="Ask about quota, reps, segments, regions, or "
                        "data quality…")
        submitted = col_btn.form_submit_button("Ask ↑")
    if submitted and typed.strip():
        st.session_state.entered = True
        st.session_state.landing_question = typed.strip()
        st.rerun()

    st.markdown('<div class="eg-label">Get started with an example '
                'below</div>', unsafe_allow_html=True)
    examples = [SUGGESTED_QUESTIONS[0][0], SUGGESTED_QUESTIONS[1][0],
                SUGGESTED_QUESTIONS[2][0], "What's wrong with my data?"]
    cols = st.columns(4)
    for col, question in zip(cols, examples):
        if col.button(question, key=f"eg_{question[:24]}", width="stretch"):
            st.session_state.entered = True
            st.session_state.landing_question = question
            st.rerun()

    center = st.columns([2, 1, 2])[1]
    if center.button("Open workspace without a question", type="tertiary",
                     width="stretch"):
        st.session_state.entered = True
        st.rerun()

    with st.expander("About this engagement"):
        st.markdown(
            "**Meridian Systems — sales-intelligence scenario.** Leaders "
            "piece together pipeline health from dashboards and analyst "
            "reports that don't talk to each other; a prior AI tool "
            "hallucinated numbers in front of the CCO. The task: an "
            "artifact where a sales leader asks a plain-English question "
            "and gets a **direct answer**, the **actual source data**, and "
            "a **flag** for incomplete data, ambiguity, or assumptions.\n\n"
            "Under the hood: 8 audited analyses · 10 guardrails enforced "
            "in code · 42 automated tests · 5 data findings surfaced · "
            "Q1 2026 final, Q2 in progress as of May 2, 2026.")


if not st.session_state.get("entered", False):
    render_landing()
    st.stop()

# Entry from the landing with a question: repaint the workspace first (fast),
# and process the question on the immediately-following run — so the landing
# never lingers on screen while the engine and LLM are working.
if "landing_question" in st.session_state:
    st.session_state.queued_question = st.session_state.pop(
        "landing_question")
    st.rerun()

# ---------------------------------------------------------------------------
# Sidebar — data status, AI status, known issues, methodology
# ---------------------------------------------------------------------------
LLM_AVAILABLE = llm_layer.is_llm_available()

with st.sidebar:
    st.markdown(
        f'<div class="ok-line">Data validated</div>'
        f'<div class="dl">{C.AS_OF:%b %d, %Y} · day {C.ELAPSED_DAYS} of '
        f'{C.Q2_DAYS} · {len(BUNDLE.q1_deals)}+{len(BUNDLE.q2_deals)} deals '
        f'· {len(BUNDLE.reps)} reps</div>',
        unsafe_allow_html=True)
    st.progress(C.ELAPSED_FRAC, text=f"{pct(C.ELAPSED_FRAC, 0)} of Q2 elapsed")

    st.toggle("Overview cards", value=True, key="show_overview",
              help="Off = assistant only: just the conversation.")
    if LLM_AVAILABLE:
        llm_on = st.toggle("AI narration", value=True,
                           help="The model only selects from approved "
                                "analyses and rephrases computed results — "
                                "a validator blocks any number the engine "
                                "did not produce.")
        st.caption(llm_layer.provider_label())
    else:
        llm_on = False
        st.caption("AI assist off — deterministic answers only.")

    _SHORT_FLAGS = {
        "F1": f"Reused deal IDs · {len(BUNDLE.recycled_ids)} deals",
        "F2": f"Closed deals reopened · {len(BUNDLE.reverted_ids)} deals",
        "F3": f"Overdue open deals · {len(BUNDLE.overdue_ids)}",
        "F4": f"Re-dated revenue · {len(BUNDLE.redated_ids)} deals",
        "F5": f"Edited closed records · {len(BUNDLE.edited_ids)}",
    }
    st.subheader("Data issues")
    rows = []
    for flag in BUNDLE.global_flags:
        code = flag.split(" — ")[0]
        rows.append(f'<div class="flag"><span class="flag-code">{h(code)}'
                    f'</span><span>{h(_SHORT_FLAGS.get(code, code))}'
                    f'</span></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    with st.expander("Details"):
        for flag in BUNDLE.global_flags:
            st.markdown(f'<div class="assump">{h(flag)}</div>',
                        unsafe_allow_html=True)

    with st.expander("Activity"):
        _obs = observability.summary()
        if _obs is None:
            st.caption("Every question is logged to logs/queries.jsonl.")
        else:
            st.markdown(
                f'<div class="dl"><b>{_obs["total"]}</b> logged · '
                f'<b>{_obs["answered"]}</b> answered · '
                f'<b>{_obs["refused"]}</b> refused · '
                f'<b>{_obs["narrations_verified"]}</b> AI summaries '
                f'verified</div>', unsafe_allow_html=True)
            for r in observability.recent(5):
                st.markdown(
                    f'<div class="flag"><span class="flag-code">'
                    f'{h(str(r.get("duration_ms", "—")))}ms</span>'
                    f'<span>{h(r.get("question", "")[:48])}</span></div>',
                    unsafe_allow_html=True)

    if st.button("← Engagement brief", type="tertiary", width="stretch"):
        st.session_state.entered = False
        st.rerun()

    with st.expander("Methodology"):
        st.markdown(
            "**Metric definitions**\n"
            "- *Attainment* — Closed-Won revenue ÷ quota; open pipeline is "
            "never blended in.\n"
            "- *Open pipeline* — unweighted value of open deals expected to "
            "close inside Q2.\n"
            "- *Coverage* — open pipeline ÷ remaining quota; break-even "
            f"{BUNDLE.cov_breakeven:.2f}x is derived from Q1's realized value "
            f"win-rate ({pct(BUNDLE.q1_win_rate_value)}).\n"
            "- *Same point in quarter* — equal days elapsed "
            f"(day {C.ELAPSED_DAYS}: {C.AS_OF:%b %d} ↔ {C.Q1_CUTOFF:%b %d}).\n"
            "- *Risk categories* — fixed published thresholds on pace, "
            "coverage, and record reliability; not a predictive model.\n\n"
            "**Why answers can be trusted**\n"
            "Questions are routed to one of eight approved, hand-verified "
            "calculations — by transparent keyword rules, or by an LLM that "
            "may only choose from that menu. A language model never "
            "computes or filters a number; AI-written summaries pass a "
            "validator that rejects any number the engine did not produce. "
            "Unsupported questions are refused, not guessed.\n\n"
            "**Reconciliation checks passed at load**")
        for check in RECON_CHECKS:
            st.markdown(f"- {check}")
        st.markdown("\n**Standing assumptions**")
        for code, text in C.ASSUMPTIONS.items():
            st.markdown(f"- **{code}** — {esc(text)}")

# ---------------------------------------------------------------------------
# Main panel — header, animated KPI band, chat
# ---------------------------------------------------------------------------
@st.cache_resource
def _company_kpis() -> dict:
    """Deterministic company-level figures for the always-visible KPI band."""
    from analytics import open_rows, won_rows
    won = won_rows(BUNDLE.q2_deals, C.Q2_START, C.AS_OF)
    pipe = open_rows(BUNDLE)
    booked = int(won["deal_value"].sum())
    quota = int(BUNDLE.reps["quota_q2_2026"].sum())
    pipeline = int(pipe["deal_value"].sum())
    redated = int(won.loc[won["deal_id"].isin(BUNDLE.redated_ids),
                          "deal_value"].sum())
    return {"booked": booked, "quota": quota, "pipeline": pipeline,
            "uncovered": max(quota - booked - pipeline, 0),
            "strictly_new": booked - redated,
            "attainment": booked / quota}


KPI = _company_kpis()


def _flip_overview() -> None:
    st.session_state.show_overview = (
        not st.session_state.get("show_overview", True))


_tb_left, _tb_right = st.columns([6, 1.4])
_tb_left.markdown(
    '<div class="wordmark">Meridian <span>·</span> Pipeline Intelligence'
    '</div>', unsafe_allow_html=True)
_tb_right.button(
    "Hide overview" if st.session_state.get("show_overview", True)
    else "Show overview",
    key="ov_btn", type="tertiary", width="stretch",
    on_click=_flip_overview)

if st.session_state.get("show_overview", True):
    # Animated count-up KPI band (runs in its own frame so the JS executes)
    _KPI_CARDS = json.dumps([
        {"cls": "", "label": "Quota", "v": KPI["quota"],
         "sub": "10 reps"},
        {"cls": "", "label": "Booked", "v": KPI["booked"],
         "sub": f"{KPI['attainment']:.1%} · new ${KPI['strictly_new']:,}"},
        {"cls": "amber", "label": "Pipeline", "v": KPI["pipeline"],
         "sub": "not yet revenue"},
        {"cls": "red", "label": "Uncovered", "v": KPI["uncovered"],
         "sub": "even at 100% win rate"},
    ])

    components.html("""
    <style>
      * { font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue',
          sans-serif; -webkit-font-smoothing: antialiased; box-sizing: border-box; }
      body { margin: 0; background: transparent; }
      .band { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
      .kpi { background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 14px;
             padding: 14px 18px 12px; opacity: 0; animation: rise .5s ease-out
             forwards; transition: transform .18s ease, box-shadow .18s ease;
             cursor: default; }
      .kpi:hover { transform: translateY(-3px);
                   box-shadow: 0 8px 22px rgba(0,0,0,.08); }
      @keyframes rise { from { opacity: 0; transform: translateY(12px); }
                        to   { opacity: 1; transform: none; } }
      .k-label { font-size: .68rem; font-weight: 600; letter-spacing: .07em;
                 text-transform: uppercase; color: #86868B; display: flex;
                 align-items: center; gap: 6px; }
      .k-label::before { content: ''; width: 6px; height: 6px; border-radius: 50%;
                 background: #7C3AED; display: inline-block; }
      .amber .k-label::before { background: #FF9500; }
      .red   .k-label::before { background: #FF3B30; }
      .k-value { font-size: 1.22rem; font-weight: 700; color: #1D1D1F;
                 margin: 5px 0 3px; letter-spacing: -.02em;
                 font-variant-numeric: tabular-nums; }
      .k-sub { font-size: .72rem; color: #86868B; line-height: 1.4; }
    </style>
    <div class="band" id="band"></div>
    <script>
      const DATA = """ + _KPI_CARDS + """;
      const band = document.getElementById('band');
      DATA.forEach((c, i) => {
        const el = document.createElement('div');
        el.className = 'kpi ' + c.cls;
        el.style.animationDelay = (i * 110) + 'ms';
        el.innerHTML = '<div class="k-label">' + c.label + '</div>' +
                       '<div class="k-value" id="v' + i + '">$0</div>' +
                       '<div class="k-sub">' + c.sub + '</div>';
        band.appendChild(el);
      });
      const ease = t => 1 - Math.pow(1 - t, 3);
      const t0 = performance.now();
      DATA.forEach((c, i) => {
        const el = document.getElementById('v' + i), dur = 950, delay = i * 110;
        (function step(now) {
          const p = Math.min(Math.max((now - t0 - delay) / dur, 0), 1);
          el.textContent = '$' + Math.round(c.v * ease(p)).toLocaleString();
          if (p < 1) requestAnimationFrame(step);
        })(performance.now());
      });
    </script>
    """, height=112)

if "history" not in st.session_state:
    st.session_state.history = []

_CHIPS = [
    ("Enterprise vs quota", SUGGESTED_QUESTIONS[0][0]),
    ("Reps at risk", SUGGESTED_QUESTIONS[1][0]),
    ("Q2 vs Q1 pace", SUGGESTED_QUESTIONS[2][0]),
    ("Regional view", "How is each region performing this quarter?"),
    ("Data quality", "What's wrong with my data?"),
]
pending: Optional[str] = None
if st.session_state.get("show_overview", True):
    chip_cols = st.columns(len(_CHIPS))
    for col, (label, full_question) in zip(chip_cols, _CHIPS):
        if col.button(label, help=full_question, width="stretch"):
            pending = full_question

typed = st.chat_input(
    "Ask about quota, reps, segments, regions, or data quality…")
question = (typed.strip() if typed
            else pending or st.session_state.pop("queued_question", None))

if question:
    with st.spinner("Thinking…"):
        _t0 = time.perf_counter()
        turn = process_question(question, llm_on)
        turn["duration_ms"] = int((time.perf_counter() - _t0) * 1000)
        st.session_state.history.append(turn)
    observability.log_turn(turn)
    if "refusal" in turn:
        st.toast("Outside the approved analyses — refused, not guessed")
    else:
        narration = turn.get("narration")
        if narration is not None and narration.ok:
            st.toast(f"Answer verified — {narration.numbers_checked} numbers "
                     "checked against the engine")
        else:
            st.toast("Answer computed by the deterministic engine")

for turn_index, turn in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.markdown(f'<div class="q-text">{h(turn["question"])}</div>',
                    unsafe_allow_html=True)
    with st.chat_message("assistant"):
        if "refusal" in turn:
            st.markdown(
                f'<div class="answer-head">'
                f'<span class="intent-tag">Not supported &nbsp;·&nbsp; '
                f'{h(turn["matched_on"])}</span></div>'
                f'<div class="answer-headline">{h(turn["refusal"])}</div>'
                f'<div class="verify-line">Supported analyses: '
                f'{h(" · ".join(INTENT_LABELS.values()))}</div>',
                unsafe_allow_html=True)
        else:
            render_answer(turn["packet"], turn.get("narration"),
                          INTENT_LABELS[turn["intent"]], turn["matched_on"],
                          turn_key=str(turn_index))
