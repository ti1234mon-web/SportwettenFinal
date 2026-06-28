# wetten_dashboard.py
# ============================================================
# SPORTWETTEN-DASHBOARD – MIT KORREKTER NETTO-GEWINN-DARSTELLUNG
# ============================================================

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import math
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

# ============================================================
# 1. HILFSFUNKTIONEN
# ============================================================

def poisson_probability(actual_goals: int, expected_goals: float) -> float:
    if expected_goals <= 0:
        return 1.0 if actual_goals == 0 else 0.0
    return (pow(expected_goals, actual_goals) * math.exp(-expected_goals)) / math.factorial(actual_goals)

def poisson_cumulative_under(threshold: float, expected_goals: float, max_goals: int = 10) -> float:
    if threshold <= 0:
        return 0.0
    max_goal = int(math.ceil(threshold)) - 1
    if max_goal < 0:
        return 0.0
    prob = 0.0
    for g in range(max_goal + 1):
        prob += poisson_probability(g, expected_goals)
    return min(prob, 1.0)

def poisson_cumulative_over(threshold: float, expected_goals: float, max_goals: int = 10) -> float:
    return 1.0 - poisson_cumulative_under(threshold + 1, expected_goals, max_goals)

def no_vig_probabilities(odds: List[float]) -> List[float]:
    if not odds or any(o <= 0 for o in odds):
        return [0.0] * len(odds)
    inverse = [1.0 / o for o in odds]
    sum_inv = sum(inverse)
    return [inv / sum_inv for inv in inverse]

def expected_value(probability: float, odds: float, stake: float = 1.0) -> float:
    if odds <= 0:
        return -stake
    return (probability * odds - 1.0) * stake

# ============================================================
# 2. DATENKLASSEN
# ============================================================

@dataclass
class MatchOdds:
    home_win: float
    draw: float
    away_win: float

    @property
    def probabilities_no_vig(self) -> Tuple[float, float, float]:
        probs = no_vig_probabilities([self.home_win, self.draw, self.away_win])
        return probs[0], probs[1], probs[2]

@dataclass
class TeamExpectedGoals:
    home: float
    away: float

@dataclass
class OverUnderOdds:
    over: float
    under: float

    @property
    def probabilities_no_vig(self) -> Tuple[float, float]:
        probs = no_vig_probabilities([self.over, self.under])
        return probs[0], probs[1]

@dataclass
class MatchOverUnder:
    line_0_5: OverUnderOdds
    line_1_5: OverUnderOdds
    line_2_5: OverUnderOdds
    line_3_5: OverUnderOdds

@dataclass
class TeamOverUnder:
    line_0_5: OverUnderOdds
    line_1_5: OverUnderOdds
    line_2_5: OverUnderOdds
    line_3_5: OverUnderOdds

@dataclass
class FullOdds:
    match_odds: MatchOdds
    home_team_ou: TeamOverUnder
    away_team_ou: TeamOverUnder
    total_ou: MatchOverUnder

# ============================================================
# 3. BERECHNUNGSKLASSE
# ============================================================

class BettingCalculator:
    def __init__(self, expected_goals: TeamExpectedGoals, odds: FullOdds):
        self.expected_goals = expected_goals
        self.odds = odds

    def match_probabilities(self) -> Dict[str, float]:
        max_goals = 10
        p_home_win, p_draw, p_away_win = 0.0, 0.0, 0.0
        lam_h, lam_a = self.expected_goals.home, self.expected_goals.away
        for gh in range(max_goals + 1):
            for ga in range(max_goals + 1):
                prob = poisson_probability(gh, lam_h) * poisson_probability(ga, lam_a)
                if gh > ga:
                    p_home_win += prob
                elif gh == ga:
                    p_draw += prob
                else:
                    p_away_win += prob
        return {"Heim": p_home_win, "Unentschieden": p_draw, "Auswärts": p_away_win}

    def match_value(self) -> Dict[str, float]:
        own = self.match_probabilities()
        impl = self.odds.match_odds
        values = {}
        for label, prob in own.items():
            odds = getattr(impl, {"Heim": "home_win", "Unentschieden": "draw", "Auswärts": "away_win"}[label])
            values[label] = expected_value(prob, odds, stake=1.0)
        return values

    def team_ou_data(self, team: str) -> Dict[str, Dict[str, float]]:
        lam = self.expected_goals.home if team == "home" else self.expected_goals.away
        ou = self.odds.home_team_ou if team == "home" else self.odds.away_team_ou
        prefix = "Heim" if team == "home" else "Auswärts"
        lines = {0.5: ou.line_0_5, 1.5: ou.line_1_5, 2.5: ou.line_2_5, 3.5: ou.line_3_5}
        result = {}
        for line, odds in lines.items():
            if odds.over <= 0 or odds.under <= 0:
                continue
            prob_over = poisson_cumulative_over(line, lam)
            prob_under = 1.0 - prob_over
            result[f"{prefix} >{line}"] = {
                "typ": "Team_OU",
                "quote": odds.over,
                "eigene_wk": prob_over,
                "impl_wk": 1.0 / odds.over,
                "value": expected_value(prob_over, odds.over, stake=1.0),
                "label": f"{prefix} >{line}",
                "event_type": "over"
            }
            result[f"{prefix} <{line}"] = {
                "typ": "Team_OU",
                "quote": odds.under,
                "eigene_wk": prob_under,
                "impl_wk": 1.0 / odds.under,
                "value": expected_value(prob_under, odds.under, stake=1.0),
                "label": f"{prefix} <{line}",
                "event_type": "under"
            }
        return result

    def total_ou_data(self) -> Dict[str, Dict[str, float]]:
        lam_total = self.expected_goals.home + self.expected_goals.away
        ou = self.odds.total_ou
        lines = {1.5: ou.line_1_5, 2.5: ou.line_2_5, 3.5: ou.line_3_5}
        result = {}
        for line, odds in lines.items():
            if odds.over <= 0 or odds.under <= 0:
                continue
            prob_over = poisson_cumulative_over(line, lam_total)
            prob_under = 1.0 - prob_over
            result[f"Gesamt >{line}"] = {
                "typ": "Total_OU",
                "quote": odds.over,
                "eigene_wk": prob_over,
                "impl_wk": 1.0 / odds.over,
                "value": expected_value(prob_over, odds.over, stake=1.0),
                "label": f"Gesamt >{line}",
                "event_type": "over"
            }
            result[f"Gesamt <{line}"] = {
                "typ": "Total_OU",
                "quote": odds.under,
                "eigene_wk": prob_under,
                "impl_wk": 1.0 / odds.under,
                "value": expected_value(prob_under, odds.under, stake=1.0),
                "label": f"Gesamt <{line}",
                "event_type": "under"
            }
        return result

    def all_single_bets(self) -> List[Dict]:
        all_bets = []
        own = self.match_probabilities()
        impl = self.odds.match_odds
        for label, prob in own.items():
            odds = getattr(impl, {"Heim": "home_win", "Unentschieden": "draw", "Auswärts": "away_win"}[label])
            if odds > 0:
                all_bets.append({
                    "typ": "1X2",
                    "label": label,
                    "quote": odds,
                    "eigene_wk": prob,
                    "impl_wk": 1.0 / odds,
                    "value": expected_value(prob, odds, stake=1.0),
                    "event_type": label
                })
        for team in ["home", "away"]:
            for d in self.team_ou_data(team).values():
                all_bets.append(d)
        for d in self.total_ou_data().values():
            all_bets.append(d)
        return all_bets

    def spread_sigma(self) -> Dict[str, float]:
        avg = (self.expected_goals.home + self.expected_goals.away) / 2.0
        return {
            "1 Sigma": avg * 1.3413,
            "-1 Sigma": avg - 0.3413,
            "2 Sigma": avg * 1.4772,
            "-2 Sigma": avg - 0.4772
        }

    def spread_probabilities(self) -> Dict[str, float]:
        avg = (self.expected_goals.home + self.expected_goals.away) / 2.0
        return {
            "Unter 2,5": poisson_cumulative_under(2.5, avg),
            "Über 1,5": poisson_cumulative_over(1.5, avg)
        }

# ============================================================
# 4. STREAMLIT-UI (mit Tabs)
# ============================================================

st.set_page_config(page_title="Wetten Dashboard", layout="wide")

def render_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        * { font-family: 'Inter', sans-serif; box-sizing: border-box; }
        .stApp { background: linear-gradient(160deg, #0A0A0A 0%, #1A1A1A 35%, #222222 65%, #0A0A0A 100%); min-height: 100vh; }
        .stApp::before { content: ''; position: fixed; top: -20%; left: -20%; width: 140%; height: 140%; background: radial-gradient(ellipse at 40% 30%, rgba(212, 168, 83, 0.03) 0%, transparent 60%); pointer-events: none; z-index: 0; }
        .main > div { background: transparent; max-width: 1400px; margin: 0 auto; padding: 1rem 2rem 4rem 2rem; position: relative; z-index: 1; }
        .block-container { padding-top: 1rem; padding-bottom: 4rem; max-width: 1400px; margin: 0 auto; }
        .title-wrapper { display: flex; justify-content: center; width: 100%; margin: 0 auto 1rem auto; }
        .main-title { font-size: 2.4rem; font-weight: 800; letter-spacing: 0.04em; text-align: center; margin: 0; color: #FFFFFF; line-height: 1.2; text-shadow: 0 2px 40px rgba(212, 168, 83, 0.05); }
        .main-title span { background: linear-gradient(135deg, #D4A853 0%, #F5D98E 50%, #D4A853 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        .section-headline { font-size: 1.0rem !important; font-weight: 500; text-transform: uppercase; letter-spacing: 0.15em; color: rgba(255, 255, 255, 0.35) !important; text-align: center; margin: 0.5rem 0 1rem 0; }
        .stDataFrame { background: rgba(255, 255, 255, 0.02) !important; backdrop-filter: blur(8px); border-radius: 16px !important; border: 1px solid rgba(255, 255, 255, 0.04) !important; overflow: hidden; margin: 0 auto 1rem auto; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3); }
        .stDataFrame th { background: rgba(255, 255, 255, 0.03) !important; color: rgba(255, 255, 255, 0.2) !important; font-weight: 500 !important; font-size: 0.6rem !important; text-transform: uppercase !important; letter-spacing: 0.2em !important; text-align: center !important; padding: 0.6rem 1rem !important; border-bottom: 1px solid rgba(255, 255, 255, 0.03) !important; }
        .stDataFrame td { background: transparent !important; color: rgba(255, 255, 255, 0.8) !important; text-align: center !important; padding: 0.5rem 1rem !important; font-size: 0.85rem !important; border-bottom: 1px solid rgba(255, 255, 255, 0.02) !important; }
        .stDataFrame tr:hover td { background: rgba(255, 255, 255, 0.03) !important; }
        .stDataFrame tr:last-child td { border-bottom: none !important; }
        .stTab { background: rgba(255,255,255,0.02); border-radius: 12px; padding: 1rem; margin-top: 1rem; }
        .stTab > div { padding: 0.5rem 0; }
    </style>
    """, unsafe_allow_html=True)

def render_sidebar():
    st.sidebar.markdown("### 📖 Wett-Dashboard")
    st.sidebar.markdown("""
    **Tabs:**
    - **1X2 & OU** – alle klassischen Wetten
    - **Spread** – Sigma-Werte um die Tore
    - **Beste Wetten** – Value > 0 mit GuV
    """)
    st.sidebar.markdown("---")
    st.sidebar.caption("📅 v2.8 – Korrekte Netto-Darstellung")

# ---- EINGABE (optimiert) ----
def input_section() -> Tuple[TeamExpectedGoals, FullOdds]:
    st.markdown('<p class="section-headline">⚽ Eingabe – Erwartete Tore & Quoten</p>', unsafe_allow_html=True)

    col_a, col_b, col_c, col_d, col_e = st.columns([1, 1, 1.5, 1.5, 1.5])
    with col_a:
        st.caption("λ Heim")
        lam_h = st.number_input("Heim", min_value=0.0, value=1.75, step=0.05, format="%.2f", key="lam_h", label_visibility="collapsed")
    with col_b:
        st.caption("λ Auswärts")
        lam_a = st.number_input("Auswärts", min_value=0.0, value=1.5, step=0.05, format="%.2f", key="lam_a", label_visibility="collapsed")
    with col_c:
        st.caption("Heimsieg")
        home_win = st.number_input("Heimsieg", min_value=1.01, value=1.5, step=0.01, format="%.2f", key="hw", label_visibility="collapsed")
    with col_d:
        st.caption("Unentschieden")
        draw = st.number_input("Unentschieden", min_value=1.01, value=4.5, step=0.01, format="%.2f", key="dr", label_visibility="collapsed")
    with col_e:
        st.caption("Auswärtssieg")
        away_win = st.number_input("Auswärtssieg", min_value=1.01, value=5.5, step=0.01, format="%.2f", key="aw", label_visibility="collapsed")

    expected = TeamExpectedGoals(home=lam_h, away=lam_a)
    match_odds = MatchOdds(home_win, draw, away_win)

    # Über/Unter (Heim)
    st.markdown("**Über/Unter (Heim)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        h_1_5_o = st.number_input(">1.5", value=1.42, step=0.01, format="%.2f", key="h15o")
        h_1_5_u = st.number_input("<1.5", value=2.6, step=0.01, format="%.2f", key="h15u")
    with col2:
        h_2_5_o = st.number_input(">2.5", value=2.35, step=0.01, format="%.2f", key="h25o")
        h_2_5_u = st.number_input("<2.5", value=1.52, step=0.01, format="%.2f", key="h25u")
    with col3:
        h_3_5_o = st.number_input(">3.5", value=4.3, step=0.01, format="%.2f", key="h35o")
        h_3_5_u = st.number_input("<3.5", value=1.17, step=0.01, format="%.2f", key="h35u")

    home_ou = TeamOverUnder(
        line_0_5=OverUnderOdds(0.0, 0.0),
        line_1_5=OverUnderOdds(h_1_5_o, h_1_5_u),
        line_2_5=OverUnderOdds(h_2_5_o, h_2_5_u),
        line_3_5=OverUnderOdds(h_3_5_o, h_3_5_u)
    )

    # Über/Unter (Auswärts)
    st.markdown("**Über/Unter (Auswärts)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        a_1_5_o = st.number_input(">1.5", value=2.35, step=0.01, format="%.2f", key="a15o")
        a_1_5_u = st.number_input("<1.5", value=1.37, step=0.01, format="%.2f", key="a15u")
    with col2:
        a_2_5_o = st.number_input(">2.5", value=7.8, step=0.01, format="%.2f", key="a25o")
        a_2_5_u = st.number_input("<2.5", value=1.04, step=0.01, format="%.2f", key="a25u")
    with col3:
        a_3_5_o = st.number_input(">3.5", value=0.0, step=0.01, format="%.2f", key="a35o")
        a_3_5_u = st.number_input("<3.5", value=0.0, step=0.01, format="%.2f", key="a35u")

    away_ou = TeamOverUnder(
        line_0_5=OverUnderOdds(0.0, 0.0),
        line_1_5=OverUnderOdds(a_1_5_o, a_1_5_u),
        line_2_5=OverUnderOdds(a_2_5_o, a_2_5_u),
        line_3_5=OverUnderOdds(a_3_5_o, a_3_5_u)
    )

    # Über/Unter (Gesamt)
    st.markdown("**Über/Unter (Gesamt)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        t_1_5_o = st.number_input(">1.5", value=1.12, step=0.01, format="%.2f", key="t15o")
        t_1_5_u = st.number_input("<1.5", value=5.5, step=0.01, format="%.2f", key="t15u")
    with col2:
        t_2_5_o = st.number_input(">2.5", value=1.5, step=0.01, format="%.2f", key="t25o")
        t_2_5_u = st.number_input("<2.5", value=2.5, step=0.01, format="%.2f", key="t25u")
    with col3:
        t_3_5_o = st.number_input(">3.5", value=2.15, step=0.01, format="%.2f", key="t35o")
        t_3_5_u = st.number_input("<3.5", value=1.65, step=0.01, format="%.2f", key="t35u")

    total_ou = MatchOverUnder(
        line_0_5=OverUnderOdds(0.0, 0.0),
        line_1_5=OverUnderOdds(t_1_5_o, t_1_5_u),
        line_2_5=OverUnderOdds(t_2_5_o, t_2_5_u),
        line_3_5=OverUnderOdds(t_3_5_o, t_3_5_u)
    )

    odds = FullOdds(match_odds, home_ou, away_ou, total_ou)
    return expected, odds

# ---- TABS ----
def tab_1x2_ou(calc: BettingCalculator):
    st.markdown('<p class="section-headline">📊 1X2 Analyse</p>', unsafe_allow_html=True)
    own = calc.match_probabilities()
    impl = calc.odds.match_odds
    no_vig = calc.odds.match_odds.probabilities_no_vig
    values = calc.match_value()
    data = []
    for label, prob in own.items():
        odds = getattr(impl, {"Heim": "home_win", "Unentschieden": "draw", "Auswärts": "away_win"}[label])
        inv = 1.0 / odds if odds > 0 else 0.0
        idx = ["Heim", "Unentschieden", "Auswärts"].index(label)
        data.append({
            "Ergebnis": label,
            "Quote": f"{odds:.2f}",
            "impl. WK": f"{inv*100:.2f}%",
            "No-Vig WK": f"{no_vig[idx]*100:.2f}%",
            "eigene WK": f"{prob*100:.2f}%",
            "Value (1€)": f"{values[label]:+.2f}€"
        })
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    st.markdown('<p class="section-headline">📊 Über/Unter – Heim</p>', unsafe_allow_html=True)
    data = calc.team_ou_data("home")
    df = pd.DataFrame([{"Wette": d["label"], "Quote": d["quote"], "eigene WK": f"{d['eigene_wk']*100:.2f}%",
                        "impl. WK": f"{d['impl_wk']*100:.2f}%", "Value": f"{d['value']:+.2f}€"} for d in data.values()])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown('<p class="section-headline">📊 Über/Unter – Auswärts</p>', unsafe_allow_html=True)
    data = calc.team_ou_data("away")
    df = pd.DataFrame([{"Wette": d["label"], "Quote": d["quote"], "eigene WK": f"{d['eigene_wk']*100:.2f}%",
                        "impl. WK": f"{d['impl_wk']*100:.2f}%", "Value": f"{d['value']:+.2f}€"} for d in data.values()])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown('<p class="section-headline">📊 Über/Unter – Gesamt</p>', unsafe_allow_html=True)
    data = calc.total_ou_data()
    df = pd.DataFrame([{"Wette": d["label"], "Quote": d["quote"], "eigene WK": f"{d['eigene_wk']*100:.2f}%",
                        "impl. WK": f"{d['impl_wk']*100:.2f}%", "Value": f"{d['value']:+.2f}€"} for d in data.values()])
    st.dataframe(df, use_container_width=True, hide_index=True)

    fig = go.Figure()
    labels = ["Heim", "Unentschieden", "Auswärts"]
    own_vals = [own["Heim"], own["Unentschieden"], own["Auswärts"]]
    impl_vals = [1.0/impl.home_win, 1.0/impl.draw, 1.0/impl.away_win]
    fig.add_trace(go.Bar(x=labels, y=own_vals, name="eigene WK", marker_color="#D4A853"))
    fig.add_trace(go.Bar(x=labels, y=impl_vals, name="impl. WK", marker_color="#F5D98E"))
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="white"),
                      barmode="group", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
    st.plotly_chart(fig, use_container_width=True)

def tab_spread(calc: BettingCalculator):
    st.markdown('<p class="section-headline">📊 Spread-Wetten (Tore) – um die Durchschnittstore herum</p>', unsafe_allow_html=True)
    avg = (calc.expected_goals.home + calc.expected_goals.away) / 2.0
    st.metric("Kombinierte durchschnittliche Tore", f"{avg:.2f}")

    sigma = calc.spread_sigma()
    df_sigma = pd.DataFrame({
        "Bezeichnung": ["1 Sigma", "-1 Sigma", "2 Sigma", "-2 Sigma"],
        "Tore": [sigma["1 Sigma"], sigma["-1 Sigma"], sigma["2 Sigma"], sigma["-2 Sigma"]]
    })
    df_sigma["Tore"] = df_sigma["Tore"].apply(lambda x: f"{x:.3f}")
    st.dataframe(df_sigma, use_container_width=True, hide_index=True)

    probs = calc.spread_probabilities()
    st.markdown("**Wahrscheinlichkeiten für Spread-Linien (Poisson):**")
    df_probs = pd.DataFrame({
        "Linie": ["Unter 2,5", "Über 1,5"],
        "Wahrscheinlichkeit": [f"{probs['Unter 2,5']*100:.2f}%", f"{probs['Über 1,5']*100:.2f}%"]
    })
    st.dataframe(df_probs, use_container_width=True, hide_index=True)

    st.markdown("**Value-Check (Quote eingeben):**")
    col1, col2 = st.columns(2)
    with col1:
        q_u = st.number_input("Quote Unter 2,5", min_value=1.01, value=1.65, step=0.01, format="%.2f", key="sp_u")
        vu = expected_value(probs["Unter 2,5"], q_u, stake=1.0)
        st.metric("Value Unter 2,5", f"{vu:+.3f} €")
    with col2:
        q_o = st.number_input("Quote Über 1,5", min_value=1.01, value=1.12, step=0.01, format="%.2f", key="sp_o")
        vo = expected_value(probs["Über 1,5"], q_o, stake=1.0)
        st.metric("Value Über 1,5", f"{vo:+.3f} €")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=["-2σ", "-1σ", "μ", "+1σ", "+2σ"],
        y=[sigma["-2 Sigma"], sigma["-1 Sigma"], avg, sigma["1 Sigma"], sigma["2 Sigma"]],
        mode="lines+markers",
        name="Sigma-Band",
        line=dict(color="#D4A853", width=2),
        marker=dict(size=10, color="#D4A853")
    ))
    fig.add_hline(y=avg, line_dash="dash", line_color="gray", annotation_text="μ")
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        xaxis_title="Sigma",
        yaxis_title="Tore"
    )
    st.plotly_chart(fig, use_container_width=True)

# ---- KORRIGIERTE GuV-Darstellung ----
def tab_best_bets(calc: BettingCalculator):
    st.markdown('<p class="section-headline">📈 Beste Einzelwetten & GuV (wie in Excel)</p>', unsafe_allow_html=True)

    all_bets = calc.all_single_bets()
    best_bets = [b for b in all_bets if b["value"] > 0.001]
    best_bets.sort(key=lambda x: x["value"], reverse=True)

    if not best_bets:
        st.info("Keine Wetten mit positivem Value gefunden.")
        return

    bet_labels = [b["label"] + f" (Q {b['quote']:.2f}, Value {b['value']:+.3f})" for b in best_bets]
    bet_options = {label: i for i, label in enumerate(bet_labels)}

    st.subheader("GuV für zwei ausgewählte Wetten")
    col1, col2 = st.columns(2)
    with col1:
        w1 = st.selectbox("Wette 1", options=bet_labels, key="gw1")
        stake1 = st.number_input("Einsatz Wette 1 (€)", min_value=0.0, value=10.0, step=0.5, key="gs1")
    with col2:
        w2 = st.selectbox("Wette 2", options=bet_labels, key="gw2")
        stake2 = st.number_input("Einsatz Wette 2 (€)", min_value=0.0, value=10.0, step=0.5, key="gs2")

    if w1 == w2:
        st.warning("Bitte zwei verschiedene Wetten auswählen.")
        return

    idx1, idx2 = bet_options[w1], bet_options[w2]
    bet1, bet2 = best_bets[idx1], best_bets[idx2]

    # Gewinne bei Treffer (positive Zahlen)
    gain1 = stake1 * (bet1["quote"] - 1)
    gain2 = stake2 * (bet2["quote"] - 1)

    # Szenarien mit Verlust als negative Zahl (wie in Excel)
    scenarios = [
        {"Fall": "Beide Ergebnisse", "Gewinn": gain1 + gain2, "Verlust": 0.0},
        {"Fall": "Nur Ergebnis 1", "Gewinn": gain1, "Verlust": -stake2},
        {"Fall": "Nur Ergebnis 2", "Gewinn": gain2, "Verlust": -stake1},
        {"Fall": "Kein Ergebnis", "Gewinn": 0.0, "Verlust": -(stake1 + stake2)}
    ]

    # Tabelle mit Gewinn/Verlust (wie in Excel)
    df_pnl = pd.DataFrame(scenarios)
    # Für die Anzeige formatieren
    df_pnl["Gewinn"] = df_pnl["Gewinn"].apply(lambda x: f"{x:+.2f}€")
    df_pnl["Verlust"] = df_pnl["Verlust"].apply(lambda x: f"{x:+.2f}€")
    st.dataframe(df_pnl, use_container_width=True, hide_index=True)

    # Netto-Gewinn = Gewinn + Verlust (da Verlust negativ ist)
    df_plot = pd.DataFrame(scenarios)
    df_plot["Netto"] = df_plot["Gewinn"] + df_plot["Verlust"]

    st.markdown("**Netto-Gewinn pro Szenario (Gewinn + Verlust):**")
    st.dataframe(df_plot[["Fall", "Netto"]].style.format({"Netto": "{:+.2f}€"}), use_container_width=True, hide_index=True)

    # Balkendiagramm: Nur Netto-Gewinn, farbig je nach Vorzeichen
    fig = go.Figure()
    colors = ["#4CAF50" if val >= 0 else "#F44336" for val in df_plot["Netto"]]
    fig.add_trace(go.Bar(
        x=df_plot["Fall"],
        y=df_plot["Netto"],
        name="Netto-Gewinn",
        marker_color=colors,
        text=df_plot["Netto"].apply(lambda x: f"{x:+.2f}€"),
        textposition="outside"
    ))
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        showlegend=False,
        yaxis_title="Netto-Gewinn (€)",
        yaxis=dict(gridcolor="rgba(255,255,255,0.1)")
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("**Gewählte Wetten:**")
    st.write(f"1) {bet1['label']} – Quote {bet1['quote']:.2f}, WK {bet1['eigene_wk']*100:.1f}%, Value {bet1['value']:+.3f}")
    st.write(f"2) {bet2['label']} – Quote {bet2['quote']:.2f}, WK {bet2['eigene_wk']*100:.1f}%, Value {bet2['value']:+.3f}")

    with st.expander("Alle Wetten mit Value > 0 anzeigen"):
        df_all = pd.DataFrame(best_bets)
        df_all = df_all[["label", "quote", "eigene_wk", "value"]]
        df_all.columns = ["Wette", "Quote", "eigene WK", "Value (1€)"]
        df_all["eigene WK"] = df_all["eigene WK"].apply(lambda x: f"{x*100:.1f}%")
        df_all["Value (1€)"] = df_all["Value (1€)"].apply(lambda x: f"{x:+.3f}")
        st.dataframe(df_all, use_container_width=True, hide_index=True)

# ============================================================
# 5. HAUPTPROGRAMM
# ============================================================

def main():
    render_css()
    render_sidebar()

    st.markdown("""
        <div class="title-wrapper">
            <h1 class="main-title">⚽ WETTEN <span>DASHBOARD</span></h1>
        </div>
    """, unsafe_allow_html=True)

    expected, odds = input_section()
    calc = BettingCalculator(expected, odds)

    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📊 1X2 & Über/Unter", "📈 Spread-Wetten (Sigma)", "🏆 Beste Wetten & GuV"])

    with tab1:
        tab_1x2_ou(calc)
    with tab2:
        tab_spread(calc)
    with tab3:
        tab_best_bets(calc)

if __name__ == "__main__":
    main()