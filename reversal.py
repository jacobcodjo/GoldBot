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
    h = h1[:-1] if up else S.mirror(h1[:-1])              # miroir pour une tendance baissière
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


# ----------------------------- Retournement : l'alerte devient un ordre (partie « retournement » de S4) -----------------------------
def _f(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


S7_RISK_CAP_ATR = _f("S7_RISK_CAP_ATR", 3.0)       # risque maximal : 3 x ATR H1 (stop au-delà de l'extrême du sweep) ; nom hérité de l'ancienne S7
S7_SL_BUF_ATR = 0.2                                 # marge du stop au-delà de l'extrême du sweep (en ATR H1)
S7_ENTRY_MAX_ATR = _f("S7_ENTRY_MAX_ATR", 1.0)      # retest du creux (sommet) cassé à plus de 1 ATR H1 du prix : signal écarté
S7_LIMIT_TTL = 7200                                 # validité de l'ordre limite, en secondes
STRAT, LABEL = "S4", "Figures & Retournement"       # l'ancienne S7 Reversal est fusionnée dans S4 (STRAT_ALIAS : S7 -> S4)


def reversal_signal(provide, now, funnel, dec=2, mode="market", rev=None):
    """Retournement possible (detect) en ordre : mêmes conditions que l'alerte d'information. Entrée au retest du dernier creux
    (sommet) H1 cassé, stop au-delà de l'extrême du sweep, objectifs 1R / 2R / 3R. Contre une tendance H4 mûre : taille réduite
    conseillée. `rev` : résultat de detect() déjà calculé (sinon calculé ici). Retourne un signal, ou None."""
    rev = rev or detect(provide, now)
    if not rev:
        return None
    funnel["S4_retournement"] += 1
    m15, h1 = provide("M15"), provide("H1")
    if not m15 or not h1:
        return None
    m15c = m15[:-1]
    a_m15, a_h1 = S.atr(m15c), S.atr(h1[:-1])
    if a_m15 <= 0 or a_h1 <= 0:
        return None
    d, price = rev["dir"], m15[-1]["close"]
    sl = rev["ext"] + (S7_SL_BUF_ATR * a_h1 if d == "SELL" else -S7_SL_BUF_ATR * a_h1)
    otype, entry = S.pick_entry(d, price, rev["pivot"], sl, mode)
    if otype != d:
        if abs(price - entry) > S7_ENTRY_MAX_ATR * a_h1:
            funnel["stale"] += 1
            return None
    elif S.is_late(d, price, rev["pivot"], a_m15):
        funnel["stale"] += 1
        return None
    lv = S.build_levels(d, entry, sl, a_m15, a_h1, S7_RISK_CAP_ATR)
    if lv is None:
        return None
    # Objectifs sur la liquidité opposée intacte (comme S2) : TP1 = 1 R, TP2 = première liquidité entre 2 R et 6 R (sinon 2 R),
    # TP3 = liquidité suivante à 3 R ou plus (sinon 3 R). Un retournement vise la structure, pas des multiples génériques.
    levels = S.liquidity_levels(h1[:-1], provide("D1"), m15c, now, a_h1) or []
    targets = S.liquidity_targets(levels, m15c, d, entry, lv["risk"], a_m15)
    lv["tp"], t2, t3 = S.s2_tps(d, entry, lv["risk"], targets)
    tp_lines = [f"🎯 {lab} sur la liquidité {t[0]} ({px_tp:.{dec}f}, {abs(px_tp - entry) / lv['risk']:.1f} R)"
                for lab, t, px_tp in (("TP2", t2, lv["tp"][1]), ("TP3", t3, lv["tp"][2])) if t]
    if not tp_lines:
        tp_lines = ["🎯 Pas de liquidité opposée intacte à 2-6 R : TP2 / TP3 à 2 R / 3 R"]
    funnel["S4_signal"] += 1
    word = {"BUY": "haussière", "SELL": "baissière"}[rev["trend_dir"]]
    taken = "sommet" if d == "SELL" else "creux"
    broke = "sous le dernier creux" if d == "SELL" else "au-dessus du dernier sommet"
    return S._signal(
        STRAT, LABEL, d, entry, lv, m15, "M15", f"{rev['epoch']}",
        [f"✅ Tendance H4 {word} mûre ({rev['legs']} jambes), encore intacte",
         f"✅ Sweep : {taken} H1 {rev['level'][0]:.{dec}f} ({rev['level'][1]}) pris puis rejeté",
         f"✅ Cassure de structure H1 : clôture {broke} ({rev['pivot']:.{dec}f})",
         "✅ Essoufflement : " + " · ".join(rev["signs"]),
         "⚠️ Contre la tendance H4 : taille réduite conseillée"] + tp_lines,
        lines=[{"y": rev["level"][0], "label": f"Sweep · {rev['level'][1]}", "kind": "sweep"},
               {"y": rev["pivot"], "label": "Cassure de structure H1", "kind": "info"}],
        inval=sl, short=f"Retournement · {rev['level'][1]}", trig=m15c[-1]["epoch"], otype=otype, price_now=price,
        ttl=S7_LIMIT_TTL if otype != d else None,
        entry_note=f"Ordre limite au retest du niveau cassé ({entry:.{dec}f})" if otype != d else "",
        extra={"origine": "retournement", "contre_tendance": True, "niveau": rev["level"][1], "signes": len(rev["signs"]),
               "tp": "liquidité" if (t2 or t3) else "fixe"})
