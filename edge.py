"""Qualité des signaux (après les stratégies, avant l'envoi) : objectifs sur la structure, bougie de rejet, niveaux
psychologiques, score de confluence, taille de position. Fonctions pures : bougies = dicts {epoch, open, high, low, close},
`provide(tf)` renvoie les bougies d'un timeframe (la dernière est en formation). Aucune règle de stratégie ici.

Rien de ce module n'a été validé par un backtest sur marché réel : les seuils sont des points de départ. Chaque mécanisme se
désactive par une variable (STRUCT_TP, PSYCH_LEVELS, MIN_SCORE=0, REJECTION_REQUIRED) et le score, la note et les objectifs
structurels sont enregistrés dans chaque trade pour être évalués par le backtest (rapport par note, par session)."""
import math
from datetime import timedelta

import strategies as S

NY = S.NY

STRUCT_TP = S._flag("STRUCT_TP", True)          # objectifs sur la structure (liquidité, obstacles H4/H1, extensions Fibonacci)
STRUCT_TP_STRATS = ("S1", "S9")                 # S2 vise déjà la liquidité ; S3 projette la hauteur de la figure ; S4 le range de C1
FIB_EXTENSIONS = (1.272, 1.618)                 # extensions de la jambe H1 retenues comme objectifs
PSYCH_LEVELS = S._flag("PSYCH_LEVELS", True)    # chiffres ronds, ouverture hebdomadaire, ouverture de minuit (New York)
PSYCH_TOL_ATR = 0.35                            # l'entrée est « sur » un niveau à moins de 0,35 unité M15
MIN_SCORE = S._num("MIN_SCORE", 4.0)            # score minimal sur 10 (0 = aucun filtre ; la note reste affichée)
REJECTION_REQUIRED = S._flag("REJECTION_REQUIRED", False)   # exiger une bougie de rejet sur la zone (désactivé par défaut)
REJECTION_LOOKBACK = 6                          # bougies d'entrée clôturées examinées
GRADE_A, GRADE_B = 7.0, 5.0                     # notes A (>= 7), B (>= 5), sinon C


# ---------------------------------------------------------------- niveaux psychologiques
def round_step(sym, price):
    """Pas du « chiffre rond » de l'actif : or 50 $, paires en yen 1,00, autres paires 0,0100, BTC 1000, ETH 100. None pour les
    indices synthétiques (aucun niveau rond pertinent sur un prix généré)."""
    if sym == "frxXAUUSD":
        return 50.0 if price >= 1000 else 10.0
    if sym.startswith("cryBTC"):
        return 1000.0
    if sym.startswith("cryETH"):
        return 100.0
    if sym.startswith("frx"):
        return 1.0 if "JPY" in sym else 0.01
    return None


def _sunday_open_ts(now):
    """Dimanche 17h New York le plus récent (ouverture de la semaine de trading)."""
    dt = S.datetime.fromtimestamp(now, NY)
    back = (dt.weekday() + 1) % 7                     # lundi = 0 ... dimanche = 6 : jours depuis dimanche
    sun = (dt - timedelta(days=back)).replace(hour=17, minute=0, second=0, microsecond=0)
    if dt < sun:
        sun -= timedelta(days=7)
    return int(sun.timestamp())


def _first_open(h1, t0, max_gap=7200):
    """Ouverture de la première bougie H1 à partir de t0, si elle ouvre dans les `max_gap` secondes ; sinon None."""
    for c in h1:
        if c["epoch"] >= t0:
            return c["open"] if c["epoch"] - t0 <= max_gap else None
    return None


def psych_levels(sym, price, now, provide):
    """[(nom, prix)] : chiffres ronds autour du prix, ouverture hebdomadaire, ouverture de minuit (New York)."""
    out = []
    step = round_step(sym, price)
    if step:
        base = math.floor(price / step) * step
        out += [("chiffre rond", base + k * step) for k in (-1, 0, 1, 2)]
    h1 = provide("H1") or []
    if h1:
        wk = _first_open(h1, _sunday_open_ts(now))
        if wk is not None:
            out.append(("ouverture hebdo", wk))
        mid = S.datetime.fromtimestamp(now, NY).replace(hour=0, minute=0, second=0, microsecond=0)
        mo = _first_open(h1, int(mid.timestamp()), 3600)
        if mo is not None:
            out.append(("ouverture de minuit", mo))
    return out


def psych_hit(levels, px, tol):
    """Nom du premier niveau à moins de `tol` de `px`, sinon None."""
    return next((nm for nm, v in levels if abs(v - px) <= tol), None)


# ---------------------------------------------------------------- bougie de rejet
def is_rejection(c, prev, d):
    """Bougie de rejet dans le sens d : pin bar (longue mèche du côté testé, clôture à l'opposé) ou englobante."""
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body = abs(c["close"] - c["open"])
    if d == "BUY":
        wick = min(c["open"], c["close"]) - c["low"]
        pin = wick >= 2 * max(body, 0.05 * rng) and wick >= 0.6 * rng and c["close"] >= c["low"] + 0.6 * rng
        eng = (prev is not None and prev["close"] < prev["open"] and c["close"] > c["open"]
               and c["close"] >= prev["open"] and c["open"] <= prev["close"])
    else:
        wick = c["high"] - max(c["open"], c["close"])
        pin = wick >= 2 * max(body, 0.05 * rng) and wick >= 0.6 * rng and c["close"] <= c["high"] - 0.6 * rng
        eng = (prev is not None and prev["close"] > prev["open"] and c["close"] < c["open"]
               and c["close"] <= prev["open"] and c["open"] >= prev["close"])
    return pin or eng


def rejection_near(ltf, d, entry, a, look=REJECTION_LOOKBACK):
    """Vrai si l'une des `look` dernières bougies clôturées de l'unité d'entrée est un rejet dont la mèche a testé l'entrée (à
    moins de 0,75 unité). `ltf` : bougies de l'unité d'entrée, la dernière en formation."""
    cs = ltf[:-1][-(look + 1):]
    for i in range(1, len(cs)):
        c = cs[i]
        extreme = c["low"] if d == "BUY" else c["high"]
        if abs(extreme - entry) <= 0.75 * a and is_rejection(c, cs[i - 1], d):
            return True
    return False


# ---------------------------------------------------------------- objectifs sur la structure
def structural_targets(sig, provide, now):
    """[(nom, prix, distance en R)] du plus proche au plus lointain, dans le sens du trade, entre S2_TP_MIN_R et S2_TP_MAX_R :
    liquidité opposée intacte (PDH/PDL, plage asiatique, equal highs/lows), obstacles H4/H1 (sommets, creux, zones) et
    extensions Fibonacci de la jambe H1. Deux niveaux à moins de 0,25 R l'un de l'autre sont fusionnés."""
    d, e = sig["dir"], sig["entry"]
    risk = abs(e - sig["sl"])
    m15, h1 = provide("M15") or [], provide("H1") or []
    if risk <= 0 or len(m15) < 50 or len(h1) < 40:
        return []
    sgn = 1 if d == "BUY" else -1
    m15c, h1c = m15[:-1], h1[:-1]
    a_m15, a_h1 = S.unit(m15c), S.unit(h1c)
    if a_m15 <= 0 or a_h1 <= 0:
        return []
    levels = S.liquidity_levels(h1c, provide("D1"), m15c, now, a_h1)
    cands = list(S.liquidity_targets(levels, m15c, d, e, risk, a_m15))
    obs = S.htf_obstacles(provide, now)
    if obs:
        for lo, hi, nm in (obs["res"] if d == "BUY" else obs["sup"]):
            px = lo if d == "BUY" else hi
            r = (px - e) * sgn / risk
            if S.S2_TP_MIN_R <= r <= S.S2_TP_MAX_R:
                cands.append((nm, px - sgn * S.S2_TP_BUF_ATR * a_m15, r))
    rng = S.fib_dealing_range(h1c, 3, 120)
    if rng:
        lo, hi = rng
        for k in FIB_EXTENSIONS:
            px = hi + (k - 1) * (hi - lo) if d == "BUY" else lo - (k - 1) * (hi - lo)
            r = (px - e) * sgn / risk
            if S.S2_TP_MIN_R <= r <= S.S2_TP_MAX_R:
                cands.append((f"extension Fibonacci {k:g}".replace(".", ","), px - sgn * S.S2_TP_BUF_ATR * a_m15, r))
    cands.sort(key=lambda x: x[2])
    out = []
    for c in cands:
        if not out or c[2] - out[-1][2] >= 0.25:
            out.append(c)
    return out


def apply_structure_tps(sig, provide, now):
    """Remplace les objectifs en multiples du risque par des niveaux de structure (stratégies de STRUCT_TP_STRATS). Un objectif
    n'est jamais plus proche que le TP1 d'origine (le ratio minimal de la stratégie reste respecté). Sans niveau exploitable,
    les objectifs d'origine sont conservés. Retourne True si les objectifs ont changé."""
    if not STRUCT_TP or sig.get("strat") not in STRUCT_TP_STRATS:
        return False
    risk = abs(sig["entry"] - sig["sl"])
    if risk <= 0 or sig.get("tp1") is None:
        return False
    r1 = abs(sig["tp1"] - sig["entry"]) / risk
    cands = [c for c in structural_targets(sig, provide, now) if c[2] >= max(S.S2_TP_MIN_R, r1 - 1e-9)]
    if not cands:
        return False
    tps, tg = S.s2_tps(sig["dir"], sig["entry"], risk, cands)
    dec = sig.get("dec", 2)
    sig["tp1"], sig["tp2"], sig["tp3"] = tps
    named = [f"TP{i + 1} {t[0]} {tps[i]:.{dec}f}" for i, t in enumerate(tg) if t]
    sig["details"] = list(sig["details"]) + ["🎯 Objectifs sur la structure : " + " · ".join(named)]
    sig["extra"] = dict(sig.get("extra") or {}, tp_struct="oui")
    return True


# ---------------------------------------------------------------- score de confluence
def score_signal(sig, provide, now, infos=None, ltf=None, psych=None):
    """(score sur 10, [(points, libellé)]). Fibonacci (2), niveau H4/H1 (2), tendance D1 et H4 (1 + 1), session Londres ou New York
    (1), bougie de rejet (1), niveau psychologique (1), ratio de TP2 d'au moins 3 (1)."""
    d, e = sig["dir"], sig["entry"]
    parts = []
    h1 = provide("H1") or []
    h1c = h1[:-1]
    rng = S.fib_dealing_range(h1c, 3, 120) if len(h1c) >= 20 else None
    if rng:
        z = S.fib_zone_name(S.fib_retrace(d, e, rng[0], rng[1]))
        if z in ("Golden Zone", "OTE"):
            parts.append((2, f"Fibonacci {z}"))
    obs = S.htf_obstacles(provide, now)
    if obs:
        mine = obs["sup"] if d == "BUY" else obs["res"]
        tol = S.OBST_TOL_ATR * obs["atr"]
        hit = next((nm for lo, hi, nm in mine if lo - tol <= e <= hi + tol), None)
        if hit:
            parts.append((2, f"sur {hit}"))
    for tf in ("D1", "H4"):
        info = (infos or {}).get(tf)
        if info and info.get("dir") == d:
            parts.append((1, f"tendance {tf}"))
    if sig.get("session") in ("Londres", "New York"):
        parts.append((1, f"session {sig['session']}"))
    m15 = provide("M15") or []
    a = S.unit(m15[:-1]) if len(m15) > 30 else 0
    if ltf and a > 0 and rejection_near(ltf, d, e, a):
        parts.append((1, "bougie de rejet"))
    if psych and a > 0:
        hit = psych_hit(psych, e, PSYCH_TOL_ATR * a)
        if hit:
            parts.append((1, hit))
    if S.s5_rr(sig, "tp2") >= 3.0:
        parts.append((1, "ratio TP2 ≥ 3"))
    return sum(p for p, _ in parts), parts


def grade_of(score):
    return "A" if score >= GRADE_A else "B" if score >= GRADE_B else "C"


# ---------------------------------------------------------------- taille de position
def position_size(sym, entry, sl, balance, risk_pct):
    """{'risk_amt', 'units', 'lot'} pour risquer `risk_pct` % de `balance` (devise du compte = USD), ou None si inconnu.
    Or : 1 lot = 100 oz. Paires USD (EURUSD...) et USD/xxx (USDJPY, USDCAD, USDCHF) : 1 lot = 100 000 unités. Cryptos : unités.
    Les croisements (EURGBP, EURJPY...) et les synthétiques demandent un taux de change que le bot n'a pas : None."""
    dist = abs(entry - sl)
    risk_amt = balance * risk_pct / 100.0
    if dist <= 0 or risk_amt <= 0:
        return None
    if sym == "frxXAUUSD":
        units, lot = risk_amt / dist, risk_amt / dist / 100.0
    elif sym.startswith("cry"):
        units, lot = risk_amt / dist, None
    elif sym.startswith("frx") and sym.endswith("USD"):
        units = risk_amt / dist
        lot = units / 100000.0
    elif sym.startswith("frxUSD"):
        units = risk_amt * entry / dist
        lot = units / 100000.0
    else:
        return None
    return {"risk_amt": risk_amt, "units": units, "lot": lot}


def size_text(sym, entry, sl, balance, risk_pct):
    z = position_size(sym, entry, sl, balance, risk_pct) if balance and balance > 0 else None
    if not z:
        return None
    fr = lambda x, n: f"{x:,.{n}f}".replace(",", " ").replace(".", ",")
    size = f"{fr(z['lot'], 2)} lot" if z["lot"] is not None else f"{fr(z['units'], 4 if z['units'] < 10 else 2)} unités"
    return f"💰 Risque {fr(risk_pct, 1 if risk_pct % 1 else 0)} % ({fr(z['risk_amt'], 0)} $) : {size} si le stop est touché"


# ---------------------------------------------------------------- point d'entrée
def enrich(sig, provide, now, infos, funnel, ltf=None, balance=0.0, risk_pct=1.0):
    """Appliqué à chaque signal juste avant les contrôles d'envoi. Modifie `sig` (objectifs, détails, score, taille) et retourne
    False si le signal est écarté (score sous MIN_SCORE, ou rejet exigé et absent)."""
    apply_structure_tps(sig, provide, now)
    psych = psych_levels(sig["sym"], sig["entry"], now, provide) if PSYCH_LEVELS else []
    sc, parts = score_signal(sig, provide, now, infos, ltf, psych)
    sig["score"], sig["grade"] = sc, grade_of(sc)
    sig["details"] = list(sig["details"]) + [f"🏅 Note {sig['grade']} · score {sc:g}/10 : " + (", ".join(p[1] for p in parts) or "aucune confluence")]
    rej = any(p[1] == "bougie de rejet" for p in parts)
    sig["extra"] = dict(sig.get("extra") or {}, score=sc, grade=sig["grade"], rejet="oui" if rej else "non")
    if MIN_SCORE and sc < MIN_SCORE:
        funnel["score"] += 1
        return False
    if REJECTION_REQUIRED and not rej:
        funnel["rejet"] += 1
        return False
    sig["size_txt"] = size_text(sig["sym"], sig["entry"], sig["sl"], balance, risk_pct)
    return True
