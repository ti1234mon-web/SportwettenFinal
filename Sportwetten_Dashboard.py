# wetten_dashboard.py
# ============================================================
# SPORTWETTEN-DASHBOARD – NUR EINZELWETTEN
# MIT GUV-RECHNUNG (GENAU WIE IN DER EXCEL-TABELLE)
# FÜR ZWEI AUSGEWÄHLTE WETTEN
# BASIEREND AUF DEM GOOGLE SHEETS SPREADSHEET
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
    """Poisson-Wahrscheinlichkeit für eine bestimmte Toranzahl."""
    if expected_goals <= 0:
        return 1.0 if actual_goals == 0 else 0.0
    return (pow(expected_goals, actual_goals) * math.exp(-expected_goals)) / math.factorial(actual_goals)

def poisson_cumulative_under(threshold: float, expected_goals: float, max_goals: int = 10) -> float:
    """P(Tore < threshold) = kumulierte Wahrscheinlichkeit für 0 bis floor(threshold-1)."""
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
    """P(Tore > threshold) = 1 - P(Tore <= threshold)."""
    return 1.0 - poisson_cumulative_under(threshold + 1, expected_goals, max_goals)

def no_vig_probabilities(odds: List[float]) -> List[float]:
    """Berechnet No-Vig-Wahrscheinlichkeiten aus Quoten."""
    if not odds or any(o <= 0 for o in odds):
        return [0.0] * len(odds)
    inverse = [1.0 / o for o in odds]
    sum_inv = sum(inverse)
    return [inv / sum_inv for inv in inverse]

def expected_value(probability: float, odds: float, stake: float = 1.0) -> float:
    """Erwartungswert einer Wette: (prob * odds - 1) * stake."""
    if odds <= 0:
        return -stake
    return (probability * odds - 1.0) * stake

# ============================================================
# 2. WETTEN-MODELLE
# ============================================================

@dataclass
class MatchOdds:
    """Quoten für 1-X-2."""
    home_win: float
    draw: float
    away_win: float

    @property
    def probabilities_no_vig(self) -> Tuple[float, float, float]:
        probs = no_vig_probabilities([self.home_win, self.draw, self.away_win])
        return probs[0], probs[1], probs[2]

@dataclass
class TeamExpectedGoals:
    """Erwartete Tore für Heim und Auswärts."""
    home: float
    away: float

@dataclass
class OverUnderOdds:
    """Quoten für Über/Unter bei einer bestimmten Linie."""
    over: float
    under: float

    @property
    def probabilities_no_vig(self) -> Tuple[float, float]:
        probs = no_vig_probabilities([self.over, self.under])
        return probs[0], probs[1]

@dataclass
class MatchOverUnder:
    """Über/Unter-Quoten für mehrere Linien."""
    line_0_5: OverUnderOdds
    line_1_5: OverUnderOdds
    line_2_5: OverUnderOdds
    line_3_5: OverUnderOdds

@dataclass
class TeamOverUnder:
    """Über/Unter-Quoten für ein einzelnes Team (Tore des Teams)."""
    line_0_5: OverUnderOdds
    line_1_5: OverUnderOdds
    line_2_5: OverUnderOdds
    line_3_5: OverUnderOdds

@dataclass
class FullOdds:
    """Alle Quoten für ein Spiel."""
    match_odds: MatchOdds          # 1X2
    home_team_ou: TeamOverUnder    # Tore Team 1
    away_team_ou: TeamOverUnder    # Tore Team 2
    total_ou: MatchOverUnder       # Gesamttore

# ============================================================
# 3. BERECHNUNGSLOGIK
# ============================================================

class BettingCalculator:
    """Kapselt alle Berechnungen für Wetten."""

    def __init__(self, expected_goals: TeamExpectedGoals, odds: FullOdds):
        self.expected_goals = expected_goals
        self.odds = odds

    # ---- 1X2 ----
    def match_probabilities(self) -> Dict[str, float]:
        """Eigene Wahrscheinlichkeiten für 1X2 (Poisson)."""
        max_goals = 10
        p_home_win = 0.0
        p_draw = 0.0
        p_away_win = 0.0
        lam_h = self.expected_goals.home
        lam_a = self.expected_goals.away
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
        """Value (Erwartungswert) für 1X2 basierend auf eigenen Wahrscheinlichkeiten vs. impliziten Quoten."""
        own = self.match_probabilities()
        impl = self.odds.match_odds
        values = {}
        for label, prob in own.items():
            if label == "Heim":
                odds = impl.home_win
            elif label == "Unentschieden":
                odds = impl.draw
            else:
                odds = impl.away_win
            values[label] = expected_value(prob, odds, stake=1.0)
        return values

    # ---- Über/Unter für ein Team ----
    def team_ou_data(self, team: str) -> Dict[str, Dict[str, float]]:
        """Eigene Wahrscheinlichkeiten für Über/Unter bei verschiedenen Linien für ein Team."""
        if team == "home":
            lam = self.expected_goals.home
            ou = self.odds.home_team_ou
            prefix = "Heim"
        else:
            lam = self.expected_goals.away
            ou = self.odds.away_team_ou
            prefix = "Auswärts"

        lines = {
            0.5: ou.line_0_5,
            1.5: ou.line_1_5,
            2.5: ou.line_2_5,
            3.5: ou.line_3_5
        }
        result = {}
        for line, odds in lines.items():
            if odds.over <= 0 or odds.under <= 0:
                continue  # ungültige Quoten überspringen
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

    # ---- Gesamt-Über/Unter ----
    def total_ou_data(self) -> Dict[str, Dict[str, float]]:
        """Eigene Wahrscheinlichkeiten für Gesamt-Über/Unter."""
        lam_total = self.expected_goals.home + self.expected_goals.away
        ou = self.odds.total_ou
        lines = {
            1.5: ou.line_1_5,
            2.5: ou.line_2_5,
            3.5: ou.line_3_5
        }
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

    # ---- Alle Einzelwetten sammeln ----
    def all_single_bets(self) -> List[Dict]:
        """Sammelt alle Einzelwetten (1X2, Team-OU, Total-OU) in einer Liste."""
        all_bets = []

        # 1X2
        own = self.match_probabilities()
        impl = self.odds.match_odds
        for label, prob in own.items():
            if label == "Heim":
                odds = impl.home_win
            elif label == "Unentschieden":
                odds = impl.draw
            else:
                odds = impl.away_win
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

        # Team-OU
        for team in ["home", "away"]:
            data = self.team_ou_data(team)
            for key, d in data.items():
                all_bets.append(d)

        # Total-OU
        data = self.total_ou_data()
        for key, d in data.items():
            all_bets.append(d)

        return all_bets

# ============================================================
# 4. STREAMLIT-UI
# ============================================================

def render_css():
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        * { font-family: 'Inter', sans-serif; box-sizing: border-box; margin: 0; padding: 0; }
        .stApp { background: linear-gradient(160deg, #0A0A0A 0%, #1A1A1A 35%, #222222 65%, #0A0A0A 100%); min-height: 100vh; }
        .stApp::before { content: ''; position: fixed; top: -20%; left: -20%; width: 140%; height: 140%; background: radial-gradient(ellipse at 40% 30%, rgba(212, 168, 83, 0.03) 0%, transparent 60%); pointer-events: none; z-index: 0; }
        .main > div { background: transparent; max-width: 1300px; margin: 0 auto; padding: 2rem 2rem 4rem 2rem; position: relative; z-index: 1; }
        .block-container { padding-top: 1.5rem; padding-bottom: 4rem; max-width: 1300px; margin: 0 auto; }
        
        .title-wrapper { display: flex; justify-content: center; width: 100%; margin: 0 auto 1.2rem auto; max-width: 700px; white-space: nowrap; }
        .main-title { font-size: 2.6rem; font-weight: 800; letter-spacing: 0.04em; text-align: center; margin: 0; color: #FFFFFF; line-height: 1.2; width: 100%; text-shadow: 0 2px 40px rgba(212, 168, 83, 0.05); white-space: nowrap; }
        .main-title span { background: linear-gradient(135deg, #D4A853 0%, #F5D98E 50%, #D4A853 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        
        .section-headline { font-size: 1.1rem !important; font-weight: 500; text-transform: uppercase; letter-spacing: 0.15em; color: rgba(255, 255, 255, 0.35) !important; text-align: center; margin: 0; }
        
        .stDataFrame { background: rgba(255, 255, 255, 0.02) !important; backdrop-filter: blur(8px); border-radius: 16px !important; border: 1px solid rgba(255, 255, 255, 0.04) !important; overflow: hidden; margin: 0 auto 1rem auto; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3); }
        .stDataFrame th { background: rgba(255, 255, 255, 0.03) !important; color: rgba(255, 255, 255, 0.2) !important; font-weight: 500 !important; font-size: 0.6rem !important; text-transform: uppercase !important; letter-spacing: 0.2em !important; text-align: center !important; padding: 0.8rem 1rem !important; border-bottom: 1px solid rgba(255, 255, 255, 0.03) !important; }
        .stDataFrame td { background: transparent !important; color: rgba(255, 255, 255, 0.8) !important; text-align: center !important; padding: 0.7rem 1rem !important; font-size: 0.9rem !important; border-bottom: 1px solid rgba(255, 255, 255, 0.02) !important; }
        .stDataFrame tr:hover td { background: rgba(255, 255, 255, 0.03) !important; }
        .stDataFrame tr:last-child td { border-bottom: none !important; }
    </style>
    """, unsafe_allow_html=True)

def render_sidebar():
    st.sidebar.markdown("### 📖 Wett-Dashboard")
    st.sidebar.markdown("""
    **Funktionen:**
    - 1X2: No-Vig & Value
    - Über/Unter (Team & Gesamt)
    - **Beste Einzelwetten** (Value > 0)
    - **GuV für zwei Wetten** – wie in der Excel-Tabelle
    """)
    st.sidebar.markdown("---")
    st.sidebar.caption("📅 Wetten Dashboard v2.2")

def input_odds_section() -> FullOdds:
    st.markdown("""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">⚽ Quoten & Erwartete Tore</p>
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Heim")
        home_win = st.number_input("1 (Heimsieg)", min_value=1.01, value=1.5, step=0.01, format="%.2f")
        home_team_ou = TeamOverUnder(
            line_0_5=OverUnderOdds(over=0.0, under=0.0),
            line_1_5=OverUnderOdds(over=1.42, under=2.6),
            line_2_5=OverUnderOdds(over=2.35, under=1.52),
            line_3_5=OverUnderOdds(over=4.3, under=1.17)
        )
        st.caption("Über/Unter (Heim)")
        home_1_5_over = st.number_input("Heim >1.5", value=1.42, step=0.01, format="%.2f", key="h_1_5_o")
        home_1_5_under = st.number_input("Heim <1.5", value=2.6, step=0.01, format="%.2f", key="h_1_5_u")
        home_2_5_over = st.number_input("Heim >2.5", value=2.35, step=0.01, format="%.2f", key="h_2_5_o")
        home_2_5_under = st.number_input("Heim <2.5", value=1.52, step=0.01, format="%.2f", key="h_2_5_u")
        home_3_5_over = st.number_input("Heim >3.5", value=4.3, step=0.01, format="%.2f", key="h_3_5_o")
        home_3_5_under = st.number_input("Heim <3.5", value=1.17, step=0.01, format="%.2f", key="h_3_5_u")
        home_team_ou.line_1_5 = OverUnderOdds(home_1_5_over, home_1_5_under)
        home_team_ou.line_2_5 = OverUnderOdds(home_2_5_over, home_2_5_under)
        home_team_ou.line_3_5 = OverUnderOdds(home_3_5_over, home_3_5_under)

        # Gesamttore
        st.subheader("Gesamttore")
        total_1_5_over = st.number_input("Gesamt >1.5", value=1.12, step=0.01, format="%.2f", key="t_1_5_o")
        total_1_5_under = st.number_input("Gesamt <1.5", value=5.5, step=0.01, format="%.2f", key="t_1_5_u")
        total_2_5_over = st.number_input("Gesamt >2.5", value=1.5, step=0.01, format="%.2f", key="t_2_5_o")
        total_2_5_under = st.number_input("Gesamt <2.5", value=2.5, step=0.01, format="%.2f", key="t_2_5_u")
        total_3_5_over = st.number_input("Gesamt >3.5", value=2.15, step=0.01, format="%.2f", key="t_3_5_o")
        total_3_5_under = st.number_input("Gesamt <3.5", value=1.65, step=0.01, format="%.2f", key="t_3_5_u")

    with col2:
        st.subheader("Auswärts")
        draw = st.number_input("X (Unentschieden)", min_value=1.01, value=4.5, step=0.01, format="%.2f")
        away_win = st.number_input("2 (Auswärtssieg)", min_value=1.01, value=5.5, step=0.01, format="%.2f")

        away_team_ou = TeamOverUnder(
            line_0_5=OverUnderOdds(over=0.0, under=0.0),
            line_1_5=OverUnderOdds(over=2.35, under=1.37),
            line_2_5=OverUnderOdds(over=7.8, under=1.04),
            line_3_5=OverUnderOdds(over=0.0, under=0.0)
        )
        st.caption("Über/Unter (Auswärts)")
        away_1_5_over = st.number_input("Auswärts >1.5", value=2.35, step=0.01, format="%.2f", key="a_1_5_o")
        away_1_5_under = st.number_input("Auswärts <1.5", value=1.37, step=0.01, format="%.2f", key="a_1_5_u")
        away_2_5_over = st.number_input("Auswärts >2.5", value=7.8, step=0.01, format="%.2f", key="a_2_5_o")
        away_2_5_under = st.number_input("Auswärts <2.5", value=1.04, step=0.01, format="%.2f", key="a_2_5_u")
        away_3_5_over = st.number_input("Auswärts >3.5", value=0.0, step=0.01, format="%.2f", key="a_3_5_o")
        away_3_5_under = st.number_input("Auswärts <3.5", value=0.0, step=0.01, format="%.2f", key="a_3_5_u")
        away_team_ou.line_1_5 = OverUnderOdds(away_1_5_over, away_1_5_under)
        away_team_ou.line_2_5 = OverUnderOdds(away_2_5_over, away_2_5_under)
        away_team_ou.line_3_5 = OverUnderOdds(away_3_5_over, away_3_5_under)

    match_odds = MatchOdds(home_win, draw, away_win)
    total_ou = MatchOverUnder(
        line_0_5=OverUnderOdds(0.0, 0.0),
        line_1_5=OverUnderOdds(total_1_5_over, total_1_5_under),
        line_2_5=OverUnderOdds(total_2_5_over, total_2_5_under),
        line_3_5=OverUnderOdds(total_3_5_over, total_3_5_under)
    )

    return FullOdds(
        match_odds=match_odds,
        home_team_ou=home_team_ou,
        away_team_ou=away_team_ou,
        total_ou=total_ou
    )

def input_expected_goals() -> TeamExpectedGoals:
    st.markdown("""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">📊 Erwartete Tore (Poisson λ)</p>
        </div>
    """, unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        lam_h = st.number_input("Heim λ", min_value=0.0, value=1.75, step=0.05, format="%.2f")
    with col2:
        lam_a = st.number_input("Auswärts λ", min_value=0.0, value=1.5, step=0.05, format="%.2f")
    return TeamExpectedGoals(home=lam_h, away=lam_a)

def render_match_analysis(calc: BettingCalculator):
    st.markdown("""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">📊 1X2 Analyse</p>
        </div>
    """, unsafe_allow_html=True)
    own = calc.match_probabilities()
    impl = calc.odds.match_odds
    no_vig_probs = calc.odds.match_odds.probabilities_no_vig
    values = calc.match_value()

    data = []
    for label, prob in own.items():
        if label == "Heim":
            odds = impl.home_win
        elif label == "Unentschieden":
            odds = impl.draw
        else:
            odds = impl.away_win
        inv = 1.0 / odds if odds > 0 else 0.0
        data.append({
            "Ergebnis": label,
            "Quote": odds,
            "impl. WK (1/Quote)": f"{inv*100:.2f}%",
            "No-Vig WK": f"{no_vig_probs[['Heim','Unentschieden','Auswärts'].index(label)]*100:.2f}%",
            "eigene WK (Poisson)": f"{prob*100:.2f}%",
            "Value (bei 1€)": f"{values[label]:+.2f}€"
        })
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, hide_index=True)

def render_team_ou(calc: BettingCalculator, team: str):
    st.markdown(f"""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">📊 Über/Unter – {team}</p>
        </div>
    """, unsafe_allow_html=True)
    data = calc.team_ou_data("home" if team == "Heim" else "away")
    table = []
    for key, d in data.items():
        table.append({
            "Wette": d["label"],
            "Quote": d["quote"],
            "eigene WK": f"{d['eigene_wk']*100:.2f}%",
            "impl. WK": f"{d['impl_wk']*100:.2f}%",
            "Value": f"{d['value']:+.2f}€"
        })
    if table:
        df = pd.DataFrame(table)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Keine gültigen Quoten für diese Linien.")

def render_total_ou(calc: BettingCalculator):
    st.markdown("""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">📊 Über/Unter – Gesamt</p>
        </div>
    """, unsafe_allow_html=True)
    data = calc.total_ou_data()
    table = []
    for key, d in data.items():
        table.append({
            "Wette": d["label"],
            "Quote": d["quote"],
            "eigene WK": f"{d['eigene_wk']*100:.2f}%",
            "impl. WK": f"{d['impl_wk']*100:.2f}%",
            "Value": f"{d['value']:+.2f}€"
        })
    if table:
        df = pd.DataFrame(table)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Keine gültigen Quoten für diese Linien.")

def render_best_bets_and_pnl(calc: BettingCalculator):
    st.markdown("""
        <div style="display: flex; justify-content: center; width: 100%; margin: 0.1rem 0 1.5rem 0;">
            <p class="section-headline">📈 Beste Einzelwetten & GuV (wie in Excel)</p>
        </div>
    """, unsafe_allow_html=True)

    all_bets = calc.all_single_bets()
    # Filtern nach Value > 0
    best_bets = [b for b in all_bets if b["value"] > 0.001]
    best_bets.sort(key=lambda x: x["value"], reverse=True)

    if not best_bets:
        st.info("Keine Wetten mit positivem Value gefunden.")
        return

    # Liste der Wetten für die Auswahl
    bet_labels = [b["label"] + f" (Quote {b['quote']:.2f}, Value {b['value']:+.3f})" for b in best_bets]
    bet_options = {label: i for i, label in enumerate(bet_labels)}

    st.subheader("GuV für zwei ausgewählte Wetten")
    st.markdown("Wähle zwei Wetten und gib den Einsatz für jede ein.")

    col1, col2 = st.columns(2)
    with col1:
        wette1_idx = st.selectbox("Wette 1", options=bet_labels, key="w1")
        stake1 = st.number_input("Einsatz Wette 1 (€)", min_value=0.0, value=10.0, step=0.5, key="stake1")
    with col2:
        wette2_idx = st.selectbox("Wette 2", options=bet_labels, key="w2")
        stake2 = st.number_input("Einsatz Wette 2 (€)", min_value=0.0, value=10.0, step=0.5, key="stake2")

    if wette1_idx == wette2_idx:
        st.warning("Bitte zwei verschiedene Wetten auswählen.")
        return

    idx1 = bet_options[wette1_idx]
    idx2 = bet_options[wette2_idx]
    bet1 = best_bets[idx1]
    bet2 = best_bets[idx2]

    # Gewinn bei Treffer = stake * (quote - 1)
    gain1 = stake1 * (bet1["quote"] - 1)
    loss1 = -stake1
    gain2 = stake2 * (bet2["quote"] - 1)
    loss2 = -stake2

    # Szenarien wie in Excel
    scenarios = [
        {"Fall": "Beide Ergebnisse", "Gewinn": gain1 + gain2, "Verlust": 0.0},
        {"Fall": "Nur Ergebnis 1", "Gewinn": gain1, "Verlust": loss2},  # Verlust der Wette 2
        {"Fall": "Nur Ergebnis 2", "Gewinn": gain2, "Verlust": loss1},  # Verlust der Wette 1
        {"Fall": "Kein Ergebnis", "Gewinn": 0.0, "Verlust": loss1 + loss2}
    ]

    df_pnl = pd.DataFrame(scenarios)
    # Formatierung der Zahlen
    df_pnl["Gewinn"] = df_pnl["Gewinn"].apply(lambda x: f"{x:+.2f}€")
    df_pnl["Verlust"] = df_pnl["Verlust"].apply(lambda x: f"{x:+.2f}€")

    st.markdown("#### GuV-Übersicht")
    st.dataframe(df_pnl, use_container_width=True, hide_index=True)

    # Zusätzliche Information: Die beiden Wetten
    st.markdown("#### Gewählte Wetten")
    st.write(f"**Wette 1:** {bet1['label']} – Quote {bet1['quote']:.2f}, eigene WK {bet1['eigene_wk']*100:.1f}%, Value {bet1['value']:+.3f}")
    st.write(f"**Wette 2:** {bet2['label']} – Quote {bet2['quote']:.2f}, eigene WK {bet2['eigene_wk']*100:.1f}%, Value {bet2['value']:+.3f}")

    # Optional: Balkendiagramm der Szenarien (nur die Gewinne/Verluste)
    # Wir erstellen eine separate Tabelle für die Grafik (Gewinn und Verlust als separate Spalten)
    df_plot = pd.DataFrame(scenarios)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_plot["Fall"],
        y=df_plot["Gewinn"],
        name="Gewinn",
        marker_color="#4CAF50"
    ))
    fig.add_trace(go.Bar(
        x=df_plot["Fall"],
        y=df_plot["Verlust"],
        name="Verlust",
        marker_color="#F44336"
    ))
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
    )
    st.plotly_chart(fig, use_container_width=True)

    # Zusätzlich: Liste aller Value-Wetten (Info)
    with st.expander("Alle Wetten mit Value > 0 anzeigen"):
        df_all = pd.DataFrame(best_bets)
        df_all = df_all[["label", "quote", "eigene_wk", "value"]]
        df_all.columns = ["Wette", "Quote", "eigene WK", "Value (1€)"]
        df_all["eigene WK"] = df_all["eigene WK"].apply(lambda x: f"{x*100:.1f}%")
        df_all["Value (1€)"] = df_all["Value (1€)"].apply(lambda x: f"{x:+.3f}")
        st.dataframe(df_all, use_container_width=True, hide_index=True)

# ============================================================
# 5. APP
# ============================================================

def main():
    render_css()
    render_sidebar()

    st.markdown("""
        <div class="title-wrapper">
            <h1 class="main-title">⚽ WETTEN <span>DASHBOARD</span></h1>
        </div>
    """, unsafe_allow_html=True)

    expected_goals = input_expected_goals()
    odds = input_odds_section()

    calc = BettingCalculator(expected_goals, odds)

    st.markdown("---")
    render_match_analysis(calc)
    render_team_ou(calc, "Heim")
    render_team_ou(calc, "Auswärts")
    render_total_ou(calc)

    st.markdown("---")
    render_best_bets_and_pnl(calc)

if __name__ == "__main__":
    main()