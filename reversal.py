"""Alerte de retournement possible (information seulement : aucun ordre, aucun suivi, aucun filtre sur les stratégies).

Une tendance H4 mûre peut se retourner. On n'alerte que lorsque plusieurs éléments se cumulent :

  1. tendance H4 mûre (4 jambes consécutives ou plus) encore intacte : on prévient avant que le H4 ne casse ;
  2. sweep : une bougie H1 prend un sommet (creux) récent puis referme de l'autre côté ;
  3. ce sommet (creux) se trouve sur un niveau majeur : sommet / creux H4, zone H4, plus haut / bas de la veille ;
  4. cassure de structure H1 contre la tendance : clôture sous le dernier creux (au-dessus du dernier sommet) formé avant le sweep ;
  5. signes d'essoufflement (au moins REVERSAL_MIN_SIGNS sur 3) : divergence RSI H1, bougies qui rétrécissent, mèche de rejet.

Le raisonnement est écrit pour une tendance haussière ; une tendance baissière est traitée en miroir (prix inversés).
"""
import os

import strategies as S
import trend as TR

ENABLED = (os.getenv("REVERSAL_ALERTS") or "1").strip() != "0"      # REVERSAL_ALERTS=0 : désactive l'alerte
try:
    MIN_SIGNS = int(os.getenv("REVERSAL_MIN_SIGNS") or 2)             # signes d'essoufflement exigés (sur 3)
except ValueError:
    MIN_SIGNS = 2
AGES = ("mûre",)                  # âges de tendance H4 qui peuvent s'essouffler
REQUIRE_LEVEL = True              # le sommet (creux) pris doit être sur un niveau majeur H4 / veille
SWEEP_BARS = 6                    # le sweep date de moins de 6 bougies H1
FRESH_BARS = 2                    # la cassure de structure date de 2 bougies H1 au plus
PIVOT_BARS = 12                   # le creux (sommet) cassé a été formé dans les 12 bougies avant le sweep
LEVEL_BARS = 80                   # sommets (creux) candidats : les 80 dernières bougies H1
SWING_N = 2
STALE = 3 * 3600                  # données H1 plus vieilles : marché fermé, pas d'alerte
RSI_N, RSI_MARGIN = 14, 1.0       # divergence : RSI au nouveau sommet inférieur d'au moins 1 point à celui du sommet précédent
FADE_RATIO = 0.6                  # 3 dernières bougies < 60 % du corps moyen des 10 précédentes
WICK_RATIO = 2.0                  # mèche haute >= 2 fois le corps et >= la moitié de la bougie
MAJOR_WORDS = ("H4", "veille")    # niveaux « majeurs » parmi les obstacles de strategies.htf_obstacles


def _body(c):
    return abs(c["close"] - c["open"])


def rsi_divergence(h, p, e, rsi=None):
    """Divergence baissière (sens haussier, voir le module) : le plus haut de la bougie e dépasse celui de la bougie p, mais le RSI
    de e est inférieur à celui de p. h : bougies clôturées, p < e. Retourne False si le RSI n'est pas calculable."""
    if rsi is None:
        rsi = S.rsi_series([c["close"] for c in h], RSI_N)
    if p >= e or rsi[p] is None or rsi[e] is None:
        return False
    return h[e]["high"] > h[p]["high"] and rsi[e] < rsi[p] - RSI_MARGIN


def shrinking_candles(h, e):
    """Élan qui s'éteint : corps moyen des 3 bougies jusqu'à e (comprise) < FADE_RATIO fois celui des 10 bougies précédentes."""
    if e < 12:
        return False
    last = [_body(c) for c in h[e - 2:e + 1]]
    prior = [_body(c) for c in h[e - 12:e - 2]]
    mean_prior = sum(prior) / len(prior)
    return mean_prior > 0 and sum(last) / len(last) < FADE_RATIO * mean_prior


def rejection_wick(c):
    """Longue mèche haute : >= WICK_RATIO fois le corps et >= la moitié de l'amplitude de la bougie."""
    rng = c["high"] - c["low"]
    upper = c["high"] - max(c["open"], c["close"])
    return rng > 0 and upper >= WICK_RATIO * max(_body(c), 1e-12) and upper >= 0.5 * rng


def find_reversal(h):
    """Sweep + cassure de structure sur des bougies H1 clôturées, écrits pour une tendance haussière.
    Retourne {'level_i', 'sweep_i', 'ext_i', 'pivot_i', 'trig_i'} ou None."""
    n = len(h)
    if n < 40:
        return None
    highs = [i for i in S.swings(h, "high", SWING_N) if i >= n - LEVEL_BARS]
    lows = S.swings(h, "low", SWING_N)
    for i in range(n - 1, max(n - 1 - SWEEP_BARS, SWING_N), -1):          # du sweep le plus récent au plus ancien
        c = h[i]
        for p in sorted((x for x in highs if x <= i - SWING_N - 1), reverse=True):
            lv = h[p]["high"]
            if not (c["high"] > lv > c["close"]):
                continue
            if any(h[j]["high"] > lv for j in range(p + 1, i)):            # sommet déjà pris : plus de liquidité
                continue
            e = max(range(i, n), key=lambda j: (h[j]["high"], -j))          # extrême après le sweep
            cand = [q for q in lows if e - PIVOT_BARS <= q < e]
            if not cand:
                continue
            q = max(cand)
            pivot = h[q]["low"]
            trig = next((k for k in range(e + 1, n) if h[k]["close"] < pivot), None)
            if trig is None or trig < n - FRESH_BARS:
                continue
            return {"level_i": p, "sweep_i": i, "ext_i": e, "pivot_i": q, "trig_i": trig}
    return None


def detect(provide, now):
    """Retournement possible sur un actif, ou None. provide(tf) -> bougies (la dernière est en formation).
    Retourne un dict : dir (sens du retournement), trend_dir, age, legs, level (px, nom), ext, pivot, signs, key, epoch."""
    h4, h1 = provide("H4"), provide("H1")
    if not h4 or not h1 or len(h1) < 41 or now - h1[-2]["epoch"] > STALE:
        return None
    t4 = TR.trend_info(h4, "H4")
    if not t4 or t4["age"] not in AGES:
        return None
    up = t4["dir"] == "BUY"
    h = h1[:-1] if up else S._s5_flip(h1[:-1])              # miroir pour une tendance baissière
    found = find_reversal(h)
    if not found:
        return None
    mir = (lambda x: x) if up else (lambda x: -x)             # prix du miroir -> prix réels
    lv_px, ext_px, pivot_px = mir(h[found["level_i"]]["high"]), mir(h[found["ext_i"]]["high"]), mir(h[found["pivot_i"]]["low"])
    obs = S.htf_obstacles(provide, now)
    level_name = None
    if obs:
        tol = S.OBST_TOL_ATR * obs["atr"]
        pool = obs["res"] if up else obs["sup"]
        for lo, hi, nm in pool:
            if any(w in nm for w in MAJOR_WORDS) and lo - tol <= lv_px <= hi + tol:
                level_name = nm
                break
    if REQUIRE_LEVEL and level_name is None:
        return None
    rsi = S.rsi_series([c["close"] for c in h], RSI_N)
    signs = []
    if rsi_divergence(h, found["level_i"], found["ext_i"], rsi):
        signs.append("divergence RSI H1")
    if shrinking_candles(h, found["ext_i"]):
        signs.append("bougies qui rétrécissent")
    if rejection_wick(h[found["ext_i"]]) or rejection_wick(h[found["sweep_i"]]):
        signs.append("mèche de rejet")
    if len(signs) < MIN_SIGNS:
        return None
    ext_epoch = h[found["ext_i"]]["epoch"]
    d = "SELL" if up else "BUY"
    return {"dir": d, "trend_dir": t4["dir"], "age": t4["age"], "legs": t4["legs"], "level": (lv_px, level_name or "niveau"),
            "ext": ext_px, "pivot": pivot_px, "signs": signs, "epoch": ext_epoch}


def message(rev, name, dec, clock=""):
    """Texte de l'alerte (information)."""
    word = {"BUY": "haussier", "SELL": "baissier"}
    side = "au-dessus" if rev["dir"] == "SELL" else "en dessous"
    taken = "sommet" if rev["dir"] == "SELL" else "creux"
    broke = "sous le dernier creux" if rev["dir"] == "SELL" else "au-dessus du dernier sommet"
    lines = [f"🔄 Retournement possible · {name} · {word[rev['dir']]}",
             f"Contre une tendance H4 {word[rev['trend_dir']]} mûre ({rev['legs']} jambes), encore intacte",
             f"✅ Sweep : {taken} H1 {rev['level'][0]:.{dec}f} ({rev['level'][1]}) pris puis rejeté (extrême {rev['ext']:.{dec}f})",
             f"✅ Cassure de structure H1 : clôture {broke} ({rev['pivot']:.{dec}f})",
             "✅ Essoufflement : " + " · ".join(rev["signs"]),
             f"Invalidation : retour {side} de {rev['ext']:.{dec}f}",
             "ℹ️ Information : aucun ordre, aucun suivi. Attendre la cassure du H4 pour confirmer." + (f" {clock}" if clock else "")]
    return "\n".join(lines)
