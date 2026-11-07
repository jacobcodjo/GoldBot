"""Setups de la tendance, du retournement, de S3 (Figures & Retournement) et de S4 (CRT). Toutes les règles sont décrites dans le README (section Stratégies).

Ce module regroupe quatre anciens modules, dans cet ordre : tendance (récapitulatif journalier et alerte), alerte / ordre de retournement,
figures chartistes (S3) et CRT (S4). Il importe `strategies` (primitives SMC, réglages, constantes) ; `strategies` ne l'importe qu'à l'appel.

== TENDANCE ==
Tendance et âge de la tendance, pour le récapitulatif journalier (aucune alerte de trade n'en dépend).

Règles (bougies clôturées ; fractales de 2 bougies de chaque côté, 1 seule en D1 pour une lecture plus précoce),
tendance HAUSSIÈRE :
  1. le dernier sommet ET le dernier creux sont plus hauts que les précédents (2 swings suffisent) ;
  2. structure intacte : aucune clôture sous le dernier creux depuis sa formation ;
  3. cassure par une clôture (pas une simple mèche) du sommet précédent (BOS_BY_CLOSE) ;
  4. âge = nombre de jambes consécutives (sommet + creux plus hauts) : 1 -> naissante, 2-3 -> établie,
     4 et plus -> mûre (proche de sa fin).
Tendance BAISSIÈRE : l'inverse. Sinon : pas de tendance claire.
Informations ajoutées : durée depuis le début de la série de jambes, niveau d'invalidation (dernier creux
pour une hausse, dernier sommet pour une baisse), et cassure « impulsive » (corps >= 1,2 x le corps moyen).
Inspiré de la lecture de tendance de l'ancien bot (jambes consécutives), sans reprendre ses stratégies.


== RETOURNEMENT ==
Alerte de retournement possible (information seulement : aucun ordre, aucun suivi, aucun filtre sur les stratégies).

Une tendance H4 mûre peut se retourner. On n'alerte que lorsque plusieurs éléments se cumulent :

  1. tendance H4 mûre (4 jambes consécutives ou plus) encore intacte : on prévient avant que le H4 ne casse ;
  2. sweep : une bougie H1 prend un sommet (creux) récent puis referme de l'autre côté ;
  3. ce sommet (creux) se trouve sur un niveau majeur : sommet / creux H4, zone H4, plus haut / bas de la veille ;
  4. cassure de structure H1 contre la tendance : clôture sous le dernier creux (au-dessus du dernier sommet) formé avant le sweep ;
  5. signes d'essoufflement (au moins REVERSAL_MIN_SIGNS sur 3) : divergence RSI H1, bougies qui rétrécissent, mèche de rejet.

Le raisonnement est écrit pour une tendance haussière ; une tendance baissière est traitée en miroir (prix inversés).


== FIGURES (S3) ==
S3 Chart Patterns : figures chartistes de retournement et de continuation (voir le README).

Cadre intraday du bot : la figure est détectée sur les bougies clôturées H1 ou H4 (obstacles majeurs), la cassure de sa
ligne clé est CONFIRMÉE en M15 (clôture M15 au-delà de la ligne, la bougie précédente encore en deçà).
Module autonome (aucune entrée/sortie réseau), même interface que les autres stratégies : scan_s3(provide, now, funnel, ...).

Toutes les figures sont écrites pour une cassure BAISSIÈRE ; les figures haussières s'obtiennent en retournant les prix
(miroir) : même code pour les deux sens.


== CRT (S4) ==
S4 CRT (Candle Range Theory) pur : le range d'une bougie de référence (C1) est balayé par la bougie suivante (C2), qui clôture à
l'intérieur de ce range ; on entre en M15 (ou M5, S4_CONFIRM_TF) sur la cassure de structure qui suit la clôture de C2, vers le milieu puis le bord opposé de C1.

  C1  bougie de référence D1 (range daily) ou H4 (la dernière clôturée avant C2) : son range est la jambe de livraison.
  C2  bougie clôturée qui dépasse le plus haut (vente) ou le plus bas (achat) de C1 et clôture DANS le range de C1.
      Une bougie qui dépasse les deux côtés (englobante) ou qui clôture hors du range n'est pas un CRT.
  C3  la bougie en formation : la livraison se fait pendant C3, donc la confirmation (M15 ou M5) doit arriver avant sa clôture.
  Entrée : première clôture M15 (ou M5) au-delà du dernier swing de ce timeframe, après la clôture de C2 (CHoCH avec déplacement), ordre limite sur le
          bloc d'ordre ou le FVG de ce timeframe s'il y en a un. Stop : au-delà de l'extrême de C2. Objectifs : milieu de C1, bord opposé de C1,
          bord opposé + 50 % du range ; ratio minimal 1 pour 3 calculé sur TP1 (milieu de C1), comme les autres stratégies.

Les réglages (CRT_*) sont dans strategies.py. strategies importe ce module en fin de fichier : on n'importe donc strategies qu'à
l'appel, pas au chargement.

"""
import os

import strategies as S
from strategies import is_displacement, close_beyond


# ==========================================================================
# TENDANCE
# ==========================================================================

SWING_N = 2
SWING_N_BY_TF = {"D1": 1}   # D1 : un swing est confirmé 1 jour après (et non 2) ; réglable, à comparer au backtest
AGE_ESTABLISHED = 2       # jambes consécutives : 1 = naissante
AGE_MATURE = 4            # 4 jambes ou plus = mûre
BOS_BY_CLOSE = True
MIN_CANDLES = 12
TIMEFRAMES = ("D1", "H4", "H1")


def _run(vals):
    """Nombre de hausses successives à la fin de la liste (ex : 1,2,3 -> 2)."""
    n = 0
    for a, b in zip(vals[-2::-1], vals[:0:-1]):
        if b > a:
            n += 1
        else:
            break
    return n


def flip(cs):
    return [{"epoch": c["epoch"], "open": -c["open"], "high": -c["low"], "low": -c["high"], "close": -c["close"]}
            for c in cs]


def _up(h, n=SWING_N):
    """Tendance haussière sur des bougies clôturées (fractales de n bougies), ou None."""
    if len(h) < MIN_CANDLES:
        return None
    sh, sl = S.swings(h, "high", n), S.swings(h, "low", n)
    if len(sh) < 2 or len(sl) < 2:
        return None
    highs, lows = [h[i]["high"] for i in sh], [h[i]["low"] for i in sl]
    if not (highs[-1] > highs[-2] and lows[-1] > lows[-2]):
        return None
    if any(c["close"] < lows[-1] for c in h[sl[-1] + 1:]):
        return None                                   # structure cassée
    brk = next((i for i in range(sh[-2] + 1, len(h)) if h[i]["close"] > highs[-2]), None)
    if BOS_BY_CLOSE and brk is None:
        return None                                   # sommet dépassé seulement par une mèche
    legs = max(1, min(_run(highs), _run(lows)))
    age = "naissante" if legs < AGE_ESTABLISHED else "établie" if legs < AGE_MATURE else "mûre"
    start = min(sh[-(legs + 1)], sl[-(legs + 1)])
    impulsive = False
    if brk is not None and brk >= 1:
        avg = S.body_avg(h[max(0, brk - 20):brk])
        impulsive = avg > 0 and S.body(h[brk]) >= S.DISP_MULT * avg
    return {"legs": legs, "age": age, "start_epoch": h[start]["epoch"], "invalid": lows[-1],
            "impulsive": impulsive}


def trend_info(candles, tf=None):
    """candles : bougies du timeframe, la dernière est en formation (ignorée).
    Retourne {"dir": "BUY"|"SELL", "age", "legs", "start_epoch", "invalid", "impulsive"} ou None."""
    h = candles[:-1]
    n = SWING_N_BY_TF.get(tf, SWING_N)
    up = _up(h, n)
    if up:
        return dict(up, dir="BUY")
    dn = _up(flip(h), n)
    if dn:
        return dict(dn, dir="SELL", invalid=-dn["invalid"])
    return None


def fmt_duration(sec):
    sec = max(0, sec)
    return f"{sec / 86400:.0f} j" if sec >= 2 * 86400 else f"{max(1, round(sec / 3600))} h"


def tf_line(tf, info, now, dec):
    if info is None:
        return f"  {tf}  ⚪ Pas de tendance claire"
    buy = info["dir"] == "BUY"
    legs = f"{info['legs']} jambe" + ("s" if info["legs"] > 1 else "")
    return (f"  {tf}  {'🟢 Haussière' if buy else '🔴 Baissière'} · {info['age']} ({legs}, "
            f"{fmt_duration(now - info['start_epoch'])}){' ⚡' if info['impulsive'] else ''} · "
            f"invalidation {info['invalid']:.{dec}f}")


def summary(infos):
    """Phrase de synthèse sur l'alignement D1 / H4 / H1. infos : {tf: info ou None}."""
    dirs = {tf: (infos.get(tf) or {}).get("dir") for tf in TIMEFRAMES}
    word = {"BUY": "haussiers", "SELL": "baissiers"}
    if dirs["D1"] and dirs["D1"] == dirs["H4"] == dirs["H1"]:
        return f"→ D1, H4 et H1 alignés ({word[dirs['D1']]})"
    if dirs["D1"] and dirs["D1"] == dirs["H4"]:
        rest = "sans tendance claire" if not dirs["H1"] else f"à contre-sens ({word[dirs['H1']]})"
        return f"→ D1 et H4 alignés ({word[dirs['D1']]}), H1 {rest}"
    if dirs["H4"] and dirs["H4"] == dirs["H1"]:
        rest = "sans tendance claire" if not dirs["D1"] else f"à contre-sens ({word[dirs['D1']]})"
        return f"→ H4 et H1 alignés ({word[dirs['H4']]}), D1 {rest}"
    return "→ timeframes non alignés"


ALERT_TFS = ("D1", "H4")


def alert_lines(d, infos, now):
    """Lignes de tendance (D1 et H4) ajoutées à une alerte de trade de sens d ('BUY'/'SELL'), et champs
    d'enregistrement pour le backtest. ✅ = tendance dans le sens du trade, ⚠️ = à contre-sens.
    C'est une information : aucune alerte n'est filtrée sur la tendance ou son âge."""
    lines, extra = [], {}
    for tf in ALERT_TFS:
        info = infos.get(tf)
        if info is None:
            lines.append(f"⚪ Tendance {tf} : pas de tendance claire")
            extra[f"tend_{tf.lower()}"] = "aucune"
            continue
        ok = info["dir"] == d
        legs = f"{info['legs']} jambe" + ("s" if info["legs"] > 1 else "")
        lines.append(f"{'✅' if ok else '⚠️'} Tendance {tf} {'haussière' if info['dir'] == 'BUY' else 'baissière'}"
                     f" · {info['age']} ({legs}, {fmt_duration(now - info['start_epoch'])})"
                     f"{'' if ok else ' : contre le trade'}")
        extra[f"tend_{tf.lower()}"] = f"{info['age']} {'avec' if ok else 'contre'}"
    return lines, extra


def alert_short(d, infos, now):
    """Tendance D1/H4 en une ligne, ex. « ✅ D1 haussière établie (9 j) · ⚠️ H4 baissière mûre (6 j) »."""
    parts = []
    for tf in ALERT_TFS:
        info = infos.get(tf)
        if info is None:
            parts.append(f"⚪ {tf} sans tendance")
            continue
        parts.append(f"{'✅' if info['dir'] == d else '⚠️'} {tf} {'haussière' if info['dir'] == 'BUY' else 'baissière'} "
                     f"{info['age']} ({fmt_duration(now - info['start_epoch'])})")
    return " · ".join(parts)


def symbol_line(name, infos, now, dec):
    """Récapitulatif compact : une ligne par actif, ex. « XAUUSD  🟢 D1 établie ⚡ · 🟢 H4 mûre · ⚪ H1 ». La couleur donne le sens,
    donc l'alignement des timeframes se lit d'un coup d'œil ; l'invalidation et la durée sont dans le format complet."""
    parts = []
    for tf in TIMEFRAMES:
        info = infos.get(tf)
        if info is None:
            parts.append(f"⚪ {tf}")
        else:
            parts.append(f"{'🟢' if info['dir'] == 'BUY' else '🔴'} {tf} {info['age']}{' ⚡' if info['impulsive'] else ''}")
    return f"{name}  " + " · ".join(parts)


def symbol_block(name, infos, now, dec):
    return "\n".join([name] + [tf_line(tf, infos.get(tf), now, dec) for tf in TIMEFRAMES] + [f"  {summary(infos)}"])

# ==========================================================================
# RETOURNEMENT
# ==========================================================================

ENABLED = (os.getenv("REVERSAL_ALERTS") or "1").strip() != "0"      # REVERSAL_ALERTS=0 : désactive l'alerte
AGES = ("mûre",)                  # âges de tendance H4 qui peuvent s'essouffler
REQUIRE_LEVEL = True              # le sommet (creux) pris doit être sur un niveau majeur H4 / veille
SWEEP_BARS = 6                    # le sweep date de moins de 6 bougies H1
FRESH_BARS = 2                    # la cassure de structure date de 2 bougies H1 au plus
PIVOT_BARS = 12                   # le creux (sommet) cassé a été formé dans les 12 bougies avant le sweep
LEVEL_BARS = 80                   # sommets (creux) candidats : les 80 dernières bougies H1
REV_SWING_N = 2
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
    highs = [i for i in S.swings(h, "high", REV_SWING_N) if i >= n - LEVEL_BARS]
    lows = S.swings(h, "low", REV_SWING_N)
    for i in range(n - 1, max(n - 1 - SWEEP_BARS, REV_SWING_N), -1):          # du sweep le plus récent au plus ancien
        c = h[i]
        for p in sorted((x for x in highs if x <= i - REV_SWING_N - 1), reverse=True):
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
    t4 = trend_info(h4, "H4")
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
        return None                                   # pas assez de signes d'essoufflement
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
             *(["✅ Essoufflement : " + " · ".join(rev["signs"])] if rev["signs"] else []),
             f"Invalidation : retour {side} de {rev['ext']:.{dec}f}",
             "ℹ️ Information : aucun ordre, aucun suivi. Attendre la cassure du H4 pour confirmer." + (f" {clock}" if clock else "")]
    return "\n".join(lines)


# ----------------------------- Retournement : l'alerte devient un ordre (partie « retournement » de S3) -----------------------------
def _f(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


try:
    MIN_SIGNS = int(os.getenv("REVERSAL_MIN_SIGNS") or 2)             # signes d'essoufflement exigés (sur 3)
except ValueError:
    MIN_SIGNS = 2


def _num(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


S7_RISK_CAP_ATR = _num("S7_RISK_CAP_ATR", 3.0)       # risque maximal : 3 x ATR H1
S7_ENTRY_MAX_ATR = _num("S7_ENTRY_MAX_ATR", 1.0)     # retest du niveau cassé à plus de 1 ATR H1 du prix : signal écarté
S3_REV_MIN_RR = _num("S3_REV_MIN_RR", S.S5_MIN_RR)   # ratio minimal sur TP1 : le même que S1 et S2 par défaut (0 = désactivé)
S7_SL_BUF_ATR = 0.2                                 # marge du stop au-delà de l'extrême du sweep (en ATR H1)
S7_LIMIT_TTL = 7200                                 # validité de l'ordre limite, en secondes
STRAT, LABEL = "S3", "Figures & Retournement"       # l'ancienne S7 Reversal est fusionnée dans S3 (STRAT_ALIAS : S7 -> S3)


def reversal_signal(provide, now, funnel, dec=2, mode="market", rev=None):
    """Retournement possible (detect) en ordre : mêmes conditions que l'alerte d'information. Entrée au retest du dernier creux
    (sommet) H1 cassé, stop au-delà de l'extrême du sweep, objectifs 1R / 2R / 3R. Contre une tendance H4 mûre : taille réduite
    conseillée. `rev` : résultat de detect() déjà calculé (sinon calculé ici). Retourne un signal, ou None."""
    rev = rev or detect(provide, now)
    if not rev:
        return None
    funnel["S3_retournement"] += 1
    cf_n = S.confirm_tf("S3")                      # timeframe d'entrée : M15 (défaut) ou M5 (m15 / m15c / a_m15 : bougies et ATR de ce timeframe)
    m15, h1 = provide(cf_n), provide("H1")
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
            funnel["S3_stale"] += 1
            return None                               # retest trop loin du prix
    elif S.is_late(d, price, rev["pivot"], a_m15, S.S3_CHASE_ATR):
        funnel["S3_stale"] += 1
        return None                                   # le prix a déjà fui après la cassure
    lv = S.build_levels(d, entry, sl, a_m15)
    if lv is None:
        return None
    if S7_RISK_CAP_ATR and lv["risk"] > S7_RISK_CAP_ATR * a_h1:
        funnel["S3_risque"] += 1
        return None                                   # stop trop large pour la volatilité H1
    # Objectifs sur la liquidité opposée intacte (comme S2) : TP1 = première liquidité entre 1 R et 6 R, TP2 / TP3 = les suivantes
    # (sinon +1 R) ; sans liquidité, TP1 au ratio minimal (3 R) puis +1 R / +2 R. Un retournement vise la structure, pas des multiples génériques.
    levels = S.liquidity_levels(h1[:-1], provide("D1"), m15c, now, a_h1) or []
    targets = S.liquidity_targets(levels, m15c, d, entry, lv["risk"], a_m15)
    lv["tp"], srcs = S.s2_tps(d, entry, lv["risk"], targets, S3_REV_MIN_RR)
    tp_lines = [f"🎯 {lab} sur la liquidité {t[0]} ({px_tp:.{dec}f}, {abs(px_tp - entry) / lv['risk']:.1f} R)"
                for lab, t, px_tp in zip(("TP1", "TP2", "TP3"), srcs, lv["tp"]) if t]
    if not tp_lines:
        tp_lines = [f"🎯 Pas de liquidité opposée intacte à 1-6 R : TP1 au ratio minimal ({S3_REV_MIN_RR or S.S2_FALLBACK_R:g} R), TP2 / TP3 à +1 R / +2 R"]
    if S3_REV_MIN_RR and abs(lv["tp"][0] - entry) / lv["risk"] < S3_REV_MIN_RR:
        funnel["S3_rr"] += 1
        return None                                   # ratio gain/risque sur TP1 (première liquidité) sous le minimum
    funnel["S3_signal"] += 1
    word = {"BUY": "haussière", "SELL": "baissière"}[rev["trend_dir"]]
    taken = "sommet" if d == "SELL" else "creux"
    broke = "sous le dernier creux" if d == "SELL" else "au-dessus du dernier sommet"
    return S._signal(
        STRAT, LABEL, d, entry, lv, m15, cf_n, f"{rev['epoch']}",
        [f"✅ Tendance H4 {word} mûre ({rev['legs']} jambes), encore intacte",
         f"✅ Sweep : {taken} H1 {rev['level'][0]:.{dec}f} ({rev['level'][1]}) pris puis rejeté",
         f"✅ Cassure de structure H1 : clôture {broke} ({rev['pivot']:.{dec}f})",
         *(["✅ Essoufflement : " + " · ".join(rev["signs"])] if rev["signs"] else []),
         "⚠️ Contre la tendance H4 : taille réduite conseillée"] + tp_lines,
        lines=[{"y": rev["level"][0], "label": f"Sweep · {rev['level'][1]}", "kind": "sweep"},
               {"y": rev["pivot"], "label": "Cassure de structure H1", "kind": "info"}],
        inval=sl, short=f"Retournement · {rev['level'][1]}", trig=m15c[-1]["epoch"], otype=otype, price_now=price,
        ttl=S7_LIMIT_TTL if otype != d else None,
        entry_note=f"Ordre limite au retest du niveau cassé ({entry:.{dec}f})" if otype != d else "",
        extra={"origine": "retournement", "contre_tendance": True, "niveau": rev["level"][1], "signes": len(rev["signs"]),
               "tp": "liquidité" if any(srcs) else "fixe"})

# ==========================================================================
# FIGURES CHARTISTES (S3)
# ==========================================================================

PIVOT_K = int(_f("S6_PIVOT_K", 4))               # bougies de chaque côté d'un pivot
MIN_SWING_ATR = _f("S6_MIN_SWING_ATR", 0.8)      # swing minimal entre deux pivots (en ATR du timeframe de la figure)
TOL_ATR = _f("S6_TOL_ATR", 0.5)                  # tolérance de touche des lignes (en ATR)
MIN_H_ATR = _f("S6_MIN_H_ATR", 1.5)              # hauteur minimale d'une figure (en ATR)
BUF_ATR = _f("S6_BUF_ATR", 0.1)                  # marge de cassure (en ATR du timeframe de la figure)
MAX_AGE = int(_f("S6_MAX_AGE", 40))              # âge max du dernier pivot (en bougies du timeframe de la figure)
TREND_LB = int(_f("S6_TREND_LB", 30))
TREND_ATR = _f("S6_TREND_ATR", 1.5)
POLE_LB = int(_f("S6_POLE_LB", 20))
POLE_ATR = _f("S6_POLE_ATR", 3.5)
SL_BUF_ATR = 0.2                                 # marge du stop au-delà de la figure (en ATR du timeframe de la figure)
TP_FRACTIONS = (0.5, 1.0, 1.5)                   # TP1/TP2/TP3 = ligne - fraction x hauteur de la figure (mât pour drapeau/fanion)
S3_RISK_CAP_ATR = _f("S6_RISK_CAP_ATR", 5.0)       # risque maximal : 5 x ATR du timeframe de la figure (H1 ou H4)
S3_MIN_RR = _f("S6_MIN_RR", 1.0)                 # ratio minimal vers TP3 (les objectifs sont des fractions de la hauteur : 1:3 sur TP2 serait inatteignable)
S3_NOCONF_MIN_RR = _f("S6_NOCONF_MIN_RR", 1.5)   # figure de retournement SANS confluence avec l'alerte de retournement : ratio minimal vers TP3
S3_CONF_RISK_FACTOR = _f("S6_CONF_RISK_FACTOR", 1.4)   # figure de retournement AVEC confluence : risque maximal multiplié par ce facteur
S3_TFS = ("H1", "H4")                            # timeframes de détection des figures
S3_LIMIT_TTL = 10800                              # validité de l'ordre limite (retest de la ligne cassée), en secondes
FLAT = 0.025                                      # pente "plate" (ATR par bougie)
PAR = 0.02                                        # écart de pente max pour un canal

# ----------------------------- Outils géométriques -----------------------------
def at(line, i):
    (i1, v1), (i2, v2) = line
    return v1 if i2 == i1 else v1 + (v2 - v1) * (i - i1) / (i2 - i1)


def slope(line):
    (i1, v1), (i2, v2) = line
    return 0.0 if i2 == i1 else (v2 - v1) / (i2 - i1)


def atr_last(h, l, c, n=14):
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    seg = trs[-n:]
    return sum(seg) / len(seg)


def zigzag(h, l, k, minswing):
    """Pivots confirmés (k bougies de chaque côté), alternés H/L, swings filtrés."""
    raw = []
    for i in range(k, len(h) - k):
        is_h = h[i] >= max(h[i - k:i + k + 1]) and h[i] > max(h[i - k:i])
        is_l = l[i] <= min(l[i - k:i + k + 1]) and l[i] < min(l[i - k:i])
        if is_h and is_l:
            continue
        if is_h:
            raw.append((i, h[i], "H"))
        elif is_l:
            raw.append((i, l[i], "L"))
    z = []
    for p in raw:
        if not z:
            z.append(p)
            continue
        last = z[-1]
        if p[2] == last[2]:
            if (p[2] == "H" and p[1] > last[1]) or (p[2] == "L" and p[1] < last[1]):
                z[-1] = p
        elif abs(p[1] - last[1]) >= minswing:
            z.append(p)
    return z


def pretrend(c, start, atr):
    d = c[start] - c[max(0, start - TREND_LB)]
    if d > TREND_ATR * atr:
        return "up"
    if d < -TREND_ATR * atr:
        return "down"
    return "flat"


# ----------------------------- Détecteurs (cassure baissière) -----------------------------
def d_double_top(z, c, atr):
    if len(z) < 3:
        return []
    a, b, d = z[-3:]
    if (a[2], b[2], d[2]) != ("H", "L", "H"):
        return []
    height = min(a[1], d[1]) - b[1]
    if height < 2 * atr or abs(a[1] - d[1]) > 0.2 * height or d[0] - a[0] < 8:
        return []
    return [dict(name="Double sommet", kind="retournement", need="up", start=a[0], end=d[0],
                 level=((b[0], b[1]), (d[0], b[1])), slref=max(a[1], d[1]), height=height)]


def d_triple_top(z, c, atr):
    if len(z) < 5:
        return []
    p = z[-5:]
    if [x[2] for x in p] != ["H", "L", "H", "L", "H"]:
        return []
    highs = [p[0][1], p[2][1], p[4][1]]
    neck = min(p[1][1], p[3][1])
    height = sum(highs) / 3 - neck
    if height < 2 * atr or max(highs) - min(highs) > 0.2 * height \
            or abs(p[1][1] - p[3][1]) > 0.35 * height:
        return []
    return [dict(name="Triple sommet", kind="retournement", need="up", start=p[0][0], end=p[4][0],
                 level=((p[1][0], neck), (p[4][0], neck)), slref=max(highs), height=height)]


def d_head_shoulders(z, c, atr):
    if len(z) < 5:
        return []
    p = z[-5:]
    if [x[2] for x in p] != ["H", "L", "H", "L", "H"]:
        return []
    ls, head, rs = p[0][1], p[2][1], p[4][1]
    neck = ((p[1][0], p[1][1]), (p[3][0], p[3][1]))
    height = head - at(neck, p[2][0])
    if height < 2 * atr or head - max(ls, rs) < 0.2 * height or abs(ls - rs) > 0.4 * height \
            or abs(p[1][1] - p[3][1]) > 0.5 * height:
        return []
    return [dict(name="Tête et épaules", kind="retournement", need="up", start=p[0][0], end=p[4][0],
                 level=neck, slref=rs, height=height)]


def d_cup_handle(z, c, atr):
    """Version miroir (tasse inversée) ; en flip = tasse avec anse haussière."""
    if len(z) < 4:
        return []
    l1, top, l2, hh = z[-4:]
    if (l1[2], top[2], l2[2], hh[2]) != ("L", "H", "L", "H"):
        return []
    depth = top[1] - (l1[1] + l2[1]) / 2
    span = l2[0] - l1[0]
    if depth < 3 * atr or abs(l1[1] - l2[1]) > 0.2 * depth or span < 20:
        return []
    if hh[1] > top[1] - 0.5 * depth or hh[1] < min(l1[1], l2[1]) + 0.1 * depth \
            or hh[0] - l2[0] > span / 2:
        return []
    seg = c[l1[0]:l2[0] + 1]
    t = len(seg) // 3
    if t < 3:
        return []
    mid = sum(seg[t:2 * t]) / t
    side = (sum(seg[:t]) / t + sum(seg[-t:]) / t) / 2
    if mid - side < 0.3 * depth:
        return []
    rim = min(l1[1], l2[1])
    return [dict(name="Tasse inversée avec anse", kind="continuation", need="down", start=l1[0],
                 end=hh[0], level=((l2[0], rim), (hh[0], rim)), slref=hh[1], height=depth)]


def fit(z, size, atr, c, n):
    pts = z[-size:]
    if len(pts) < size:
        return None
    H = [(i, p) for i, p, t in pts if t == "H"]
    L = [(i, p) for i, p, t in pts if t == "L"]
    if len(H) < 2 or len(L) < 2:
        return None
    lh, ll = (H[0], H[-1]), (L[0], L[-1])
    tol = TOL_ATR * atr
    for i, p in H[1:-1]:
        if abs(p - at(lh, i)) > tol:
            return None
    for i, p in L[1:-1]:
        if abs(p - at(ll, i)) > tol:
            return None
    for i in range(pts[0][0], n - 1):          # le prix doit être resté dans la figure
        if c[i] > at(lh, i) + tol or c[i] < at(ll, i) - tol:
            return None
    return lh, ll, pts


def classify(lh, ll, atr, i0, i1):
    sh, sl = slope(lh) / atr, slope(ll) / atr
    w0, w1 = at(lh, i0) - at(ll, i0), at(lh, i1) - at(ll, i1)
    if w0 <= 0 or w1 <= 0:
        return None, 0
    fh, fl = abs(sh) < FLAT, abs(sl) < FLAT
    if fh and fl:
        return ("Rectangle", w0) if 0.75 <= w1 / w0 <= 1.3 else (None, 0)
    if sh * sl > 0 and abs(sh - sl) < PAR and not (fh or fl):
        return ("Canal haussier" if sh > 0 else "Canal baissier"), w0
    if sh < -FLAT and sl > FLAT and w1 < 0.8 * w0:
        return "Triangle symétrique", w0
    if fl and sh < -FLAT and w1 < 0.8 * w0:
        return "Triangle descendant", w0
    if sh > FLAT and sl > FLAT and sl > sh and w1 < 0.8 * w0:
        return "Biseau montant", w0
    if sh > FLAT and sl < -FLAT and w1 > 1.2 * w0:
        return "Élargissement", w0
    return None, 0


def d_two_lines(z, c, atr, n):
    out, seen = [], set()
    for size in (5, 6, 7, 8):
        f = fit(z, size, atr, c, n)
        if not f:
            continue
        lh, ll, pts = f
        name, w0 = classify(lh, ll, atr, pts[0][0], pts[-1][0])
        if not name or name in seen or w0 < MIN_H_ATR * atr:
            continue
        seen.add(name)
        out.append(dict(name=name, kind=None, need=None, start=pts[0][0], end=pts[-1][0],
                        level=ll, slref=at(lh, n - 1), height=w0, two=True))
    return out


FLIP_NAMES = {
    "Double sommet": "Double creux", "Triple sommet": "Triple creux",
    "Tête et épaules": "Tête et épaules inversée", "Biseau montant": "Biseau descendant",
    "Triangle descendant": "Triangle ascendant", "Drapeau baissier": "Drapeau haussier",
    "Fanion baissier": "Fanion haussier", "Canal haussier": "Canal baissier",
    "Canal baissier": "Canal haussier", "Tasse inversée avec anse": "Tasse avec anse",
}




# ----------------------------- Candidats (figures sans test de cassure) -----------------------------
def candidates(h, l, c, flip):
    """Figures présentes sur les bougies clôturées (h, l, c), dont le dernier pivot est récent. Chaque candidat : nom, famille
    (retournement / continuation), s (+1 / -1 : signe du miroir), atr, ligne de cassure `level` (indices de bougies, espace miroir),
    slref (extrême du stop), height (hauteur de la mesure). La cassure se teste ensuite en M15 (voir scan_s3)."""
    n = len(c)
    if n < 80:
        return []
    if flip:
        h, l, c = [-x for x in l], [-x for x in h], [-x for x in c]
    s = -1 if flip else 1
    atr = atr_last(h, l, c)
    if atr <= 0:
        return []
    z = zigzag(h, l, PIVOT_K, MIN_SWING_ATR * atr)
    cands = (d_double_top(z, c, atr) + d_triple_top(z, c, atr) + d_head_shoulders(z, c, atr)
             + d_cup_handle(z, c, atr) + d_two_lines(z, c, atr, n))
    out = []
    for d in cands:
        if n - 1 - d["end"] > MAX_AGE:
            continue
        pt = pretrend(c, d["start"], atr)
        name, kind, height = d["name"], d["kind"], d["height"]
        if d["need"]:
            if pt != d["need"]:
                continue
        else:
            if pt == "flat":
                continue
            kind = "retournement" if pt == "up" else "continuation"
            if pt == "down" and d["end"] - d["start"] <= 40 and name in (
                    "Canal haussier", "Rectangle", "Triangle symétrique", "Biseau montant"):
                seg = c[max(0, d["start"] - POLE_LB):d["start"] + 1]
                pole = max(seg) - c[d["start"]]
                if pole >= POLE_ATR * atr and d["height"] <= 0.6 * pole:
                    name = "Drapeau baissier" if name in ("Canal haussier", "Rectangle") else "Fanion baissier"
                    height = pole
        out.append(dict(name=FLIP_NAMES.get(name, name) if flip else name, kind=kind, s=s, atr=atr,
                        dir="BUY" if flip else "SELL", start=d["start"], end=d["end"], level=d["level"],
                        slref=d["slref"], height=height))
    return out


def prior_leg(S, d, csc):
    """Jambe qui précède la figure d, en espace miroir « baissier » (la figure casse vers le bas ; s = -1 retourne les prix).
    Continuation : le prix baissait avant la figure ; retourne (origine = plus haut avant la figure, fin = plus bas jusqu'à la fin de la figure).
    Retournement : le prix montait ; retourne (origine = plus bas avant la figure, None). None si la fenêtre est vide.
    Fenêtre de recherche : S.S3_FIB_LB bougies avant le début de la figure."""
    s, a, b = d["s"], max(0, d["start"] - S.S3_FIB_LB), d["start"]
    if b >= len(csc) or a > b:
        return None
    hm = [x["high"] if s == 1 else -x["low"] for x in csc]
    lm = [x["low"] if s == 1 else -x["high"] for x in csc]
    if d["kind"] == "continuation":
        io = max(range(a, b + 1), key=lambda i: hm[i])
        return hm[io], min(lm[io:d["end"] + 1])
    io = min(range(a, b + 1), key=lambda i: lm[i])
    return lm[io], None


def _trigger(S, d, tf, csc, m15c, m15, a_m15, funnel, dec, mode, rev_fn=lambda: None, cf_n="M15"):
    """Confirmation (M15 ou M5, `cf_n` ; m15c / m15 / a_m15 sont les bougies et l'ATR de ce timeframe) de la cassure de la figure d (détectée sur csc, bougies clôturées de `tf`) : une des 2 dernières bougies
    clôturées finit au-delà de la ligne, la précédente non. Retourne le signal ou None."""
    s, dr = d["s"], d["dir"]
    (i1, v1), (i2, v2) = d["level"]
    t1, t2 = csc[i1]["epoch"], csc[i2]["epoch"]

    def lvl(t):                                   # ligne de cassure à l'instant t (espace miroir)
        return v1 + (v2 - v1) * (t - t1) / (t2 - t1) if t2 != t1 else v1

    buf = BUF_ATR * d["atr"]
    k = len(m15c) - 1
    cur = None
    for i in range(k, max(k - S.FRESH, 0), -1):
        c0, c1 = m15c[i], m15c[i - 1]
        if s * c0["close"] < lvl(c0["epoch"] + S.GRAN[cf_n]) - buf and s * c1["close"] >= lvl(c1["epoch"] + S.GRAN[cf_n]) - buf:
            cur = c0
            break
    if cur is None:
        return None
    funnel["S3_cassure"] += 1
    # Fibonacci, figure de continuation : le repli (la figure) ne doit pas reprendre plus de 61,8 % de la jambe qui la précède.
    # Plus profond, ce n'est plus une pause dans la tendance mais un début de retournement : la figure est écartée.
    fib_note, leg = None, prior_leg(S, d, csc) if (S.S3_FIB_FILTER or S.S3_FIB_CAP_TP3) else None
    if S.S3_FIB_FILTER and d["kind"] == "continuation" and leg and leg[0] - leg[1] >= 2 * d["atr"]:
        depth = S.fib_pullback_depth(leg[0], leg[1], d["slref"])
        if depth is not None and depth > S.S3_FIB_CONT_MAX:
            funnel["S3_fib"] += 1
            return None
        if depth is not None:
            fib_note = f"✅ Repli de {max(depth, 0) * 100:.0f} % de la jambe précédente (Fibonacci, maximum {S.S3_FIB_CONT_MAX * 100:.1f} %)"
    t_now = m15[-1]["epoch"] + S.GRAN[cf_n]
    price = m15[-1]["close"]
    sl = s * (d["slref"] + SL_BUF_ATR * d["atr"])
    ref = lvl(cur["epoch"] + S.GRAN[cf_n])
    tps = [s * (ref - m * d["height"]) for m in TP_FRACTIONS]
    # Fibonacci, figure de retournement : la mesure de la figure ne doit pas dépasser l'origine de la jambe précédente (100 %) ; un
    # retournement reprend rarement plus que la jambe entière lors du premier mouvement. TP3 est plafonné à cette origine tant qu'elle reste
    # au-delà de TP2 ; sinon on n'y touche (le ratio minimal écarte alors les cas où l'objectif est trop proche).
    if S.S3_FIB_CAP_TP3 and d["kind"] == "retournement" and leg and leg[0] is not None:
        tp2_m, tp3_m = ref - TP_FRACTIONS[1] * d["height"], ref - TP_FRACTIONS[2] * d["height"]
        if tp3_m < leg[0] < tp2_m:
            tps[2] = s * leg[0]
            fib_note = "ℹ️ TP3 plafonné à l'origine de la jambe précédente (100 % Fibonacci)"
    zone = s * lvl(t_now)                          # retest de la ligne cassée
    otype, entry = S.pick_entry(dr, price, zone, sl, mode)
    if otype != dr:
        if abs(price - entry) > S.S3_LIMIT_MAX_ATR * a_m15:
            funnel["S3_stale"] += 1
            return None                            # zone du retest trop loin du prix
    elif S.is_late(dr, price, cur["close"], a_m15, S.S3_CHASE_ATR):
        funnel["S3_stale"] += 1
        return None                                # le prix a déjà fui après la cassure
    # Confluence avec l'alerte de retournement (sweep sur niveau majeur + cassure de structure H1 contre une tendance H4 mûre) :
    # une figure de retournement qui la rejoint a un risque admis plus large ; sans elle, un ratio plus exigeant.
    conf, min_rr, cap = None, S3_MIN_RR, S3_RISK_CAP_ATR
    if d["kind"] == "retournement":
        rev = rev_fn()
        conf = bool(rev and rev["dir"] == dr)
        if conf:
            cap = S3_RISK_CAP_ATR * S3_CONF_RISK_FACTOR
        else:
            min_rr = S3_NOCONF_MIN_RR
    lv = S.build_levels(dr, entry, sl, a_m15, tps=tps)
    if lv is None:
        return None
    if cap and lv["risk"] > cap * d["atr"]:
        funnel["S3_risque"] += 1
        return None                                # stop trop large pour la volatilité de la figure
    gain = lambda t: ((t - entry) if dr == "BUY" else (entry - t)) / lv["risk"]
    if gain(tps[0]) <= 0:
        return None                                # TP1 déjà dépassé : le mouvement a eu lieu
    if min_rr and gain(tps[2]) < min_rr:
        funnel["S3_rr"] += 1
        return None                                # ratio gain/risque vers TP3 sous le minimum
    funnel["S3_signal"] += 1
    fam = d["kind"]
    return S._signal(
        "S3", "Figures & Retournement", dr, entry, lv, m15, cf_n, f"{d['name']}|{tf}|{cur['epoch']}",
        [f"✅ Figure {tf} : {d['name']} ({fam})",
         f"✅ Cassure confirmée en {cf_n} ({'sous' if dr == 'SELL' else 'au-dessus de'} la ligne)",
         f"✅ Objectif = hauteur de la figure ({d['height']:.{dec}f})"]
        + (["✅ Confluence : retournement possible (sweep sur niveau majeur + cassure de structure H1)"] if conf else [])
        + ([f"ℹ️ Pas de confluence de retournement : ratio minimal {S3_NOCONF_MIN_RR:g} exigé"] if conf is False else [])
        + ([fib_note] if fib_note else []),
        lines=[{"y": s * ref, "label": f"{d['name']} · cassure", "kind": "info"}],
        inval=sl, short=f"{d['name']} {tf} · {fam}", trig=cur["epoch"], otype=otype, price_now=price,
        ttl=S3_LIMIT_TTL if otype != dr else None,
        entry_note=f"Ordre limite au retest de la ligne cassée ({entry:.{dec}f})" if otype != dr else "",
        extra=dict({"origine": "figure", "figure": d["name"], "famille": fam, "tf_figure": tf},
                   **({"confluence_retournement": conf} if conf is not None else {}), **{"min_rr": min_rr}))


def _s3_gate(S, sig, provide, now, funnel, kz):
    """Garde-fous communs aux figures et au retournement, appliqués au signal construit : session, âge du déclencheur, contexte H4/D1
    (continuation), obstacles H4/H1 (intraday). Retourne False (et compte le refus) si le signal est écarté."""
    if kz and S.S3_SESSIONS and sig.get("trig_close") and S.session_name(sig["trig_close"] - 1) not in S.S3_SESSIONS:
        funnel["S3_session"] += 1                   # déclencheur hors des sessions de Londres / New York (marchés à séance seulement)
        return False
    if S.S3_MAX_AGE_MIN and sig.get("trig_close") and (now - sig["trig_close"]) / 60 > S.S3_MAX_AGE_MIN:
        funnel["S3_age"] += 1                       # déclencheur trop ancien (retard du cron ou du workflow)
        return False
    extra = sig.get("extra") or {}
    if S.S3_CONTEXT_ALIGN and extra.get("famille") == "continuation":
        for tf in ("H4", "D1"):                     # une continuation ne va pas contre une tendance H4 ou D1 claire
            cs = provide(tf)
            info = trend_info(cs, tf) if cs and len(cs) >= 10 else None
            if info is not None and info["dir"] != sig["dir"]:
                funnel["S3_contexte"] += 1
                return False
    if S.INTRADAY:
        if extra.get("origine") == "figure":
            min_rr, on = extra.get("min_rr", S3_MIN_RR), "tp3"      # objectifs = fractions de la hauteur : ratio vers TP3
        else:
            min_rr, on = S3_REV_MIN_RR, "tp1"              # TP1 = première liquidité : même ratio que S1 et S2
        why = S.obstacle_filter(sig, provide, now, "S3", False, min_rr, on)
        if why:
            funnel[why] += 1                        # obstacle H4/H1 trop proche devant l'objectif
            return False
    return True


def scan_s3(provide, now, funnel, dec=2, kz=True, mode="market"):
    """S3 Figures & Retournement : figures H1 / H4 (cassure confirmée en M15) et retournement possible (ex-S7). Retourne une liste de signaux (au plus un par sens), ou None.
    `kz` : les sessions ne s'appliquent qu'aux marchés à séance (False pour les marchés 24h/24)."""
    import strategies as S
    cf_n = S.confirm_tf("S3")                       # confirmation de la cassure : M15 (défaut) ou M5
    m15 = provide(cf_n)
    if not m15:
        return None
    m15c = m15[:-1]
    if len(m15c) < 20:
        return None
    a_m15 = S.atr(m15c)
    if a_m15 <= 0:
        return None
    h1v = provide("H1")
    if S.S3_VOL_MIN_RATIO and h1v and S.vol_ratio(h1v[:-1]) < S.S3_VOL_MIN_RATIO:
        funnel["S3_vol"] += 1
        return None                                 # marché trop calme : le spread domine
    memo = {}

    def rev_fn():                                   # alerte de retournement, calculée une seule fois par scan, et seulement si utile
        if "rev" not in memo:
            memo["rev"] = detect(provide, now)
        return memo["rev"]

    best = {}
    for tf in S3_TFS:
        cs = provide(tf)
        csc = (cs[:-1] if cs else [])[-300:]
        if len(csc) < 80:
            continue
        h = [x["high"] for x in csc]
        l = [x["low"] for x in csc]
        c = [x["close"] for x in csc]
        for flip in (False, True):
            for d in candidates(h, l, c, flip):
                funnel["S3_figure"] += 1
                sig = _trigger(S, d, tf, csc, m15c, m15, a_m15, funnel, dec, mode, rev_fn, cf_n)
                if not sig or not _s3_gate(S, sig, provide, now, funnel, kz):
                    continue
                risk = abs(sig["entry"] - sig["sl"])
                sig["rr_tp3"] = abs(sig["tp3"] - sig["entry"]) / risk if risk else 0
                if sig["dir"] not in best or sig["rr_tp3"] > best[sig["dir"]]["rr_tp3"]:
                    best[sig["dir"]] = sig
    for sig in best.values():
        sig.pop("rr_tp3", None)
    out = list(best.values())
    # Partie « retournement » (ex-S7) : le même événement (sweep d'un niveau majeur + cassure de structure H1) en ordre. Si une figure de
    # retournement a déjà donné un signal dans ce sens, c'est elle qui le porte (avec sa confluence) : un seul signal par sens.
    rev = rev_fn()
    if rev and rev["dir"] not in best:
        sig = reversal_signal(provide, now, funnel, dec, mode, rev=rev)
        if sig and _s3_gate(S, sig, provide, now, funnel, kz):
            out.append(sig)
    return out or None

# ==========================================================================
# CRT (S4)
# ==========================================================================

def crt_pair(S, rc, funnel=None):
    """(sens, C1, C2, ATR) si les deux dernières bougies clôturées `rc` forment un CRT : C2 balaie UN côté de C1 (d'au moins
    CRT_SWEEP_MIN_ATR x ATR) et clôture dans son range, et le range de C1 a une taille raisonnable (entre CRT_MIN_RANGE_ATR et
    CRT_MAX_RANGE_ATR x ATR) : assez grand pour qu'un stop serré donne 1:3 jusqu'au milieu du range, pas démesuré. Sinon None."""
    if len(rc) < S.ATR_N + 3:
        return None
    c1, c2 = rc[-2], rc[-1]
    a = S.atr(rc)
    if a <= 0:
        return None
    up, dn = c2["high"] > c1["high"], c2["low"] < c1["low"]
    if up == dn:                                         # aucun sweep, ou bougie englobante (les deux côtés)
        return None
    if not (c1["low"] < c2["close"] < c1["high"]):       # C2 doit clôturer dans le range de C1
        return None
    pen = (c2["high"] - c1["high"]) if up else (c1["low"] - c2["low"])
    if S.CRT_SWEEP_MIN_ATR and pen < S.CRT_SWEEP_MIN_ATR * a:
        if funnel is not None:
            funnel["CRT_sweep"] += 1                     # mèche à peine au-delà du bord de C1 : pas un vrai balayage
        return None
    if not (S.CRT_MIN_RANGE_ATR * a <= c1["high"] - c1["low"] <= S.CRT_MAX_RANGE_ATR * a):
        if funnel is not None:
            funnel["CRT_taille"] += 1                    # range de C1 trop petit ou démesuré
        return None
    return ("SELL" if up else "BUY"), c1, c2, a


def crt_confirm(S, d, c2, tf, cfc, cf_n="M15"):
    """Cassure de structure (M15 ou M5, `cf_n`) après la clôture de C2, pendant C3. Retourne {'ext_i', 'ext_px', 'trig', 'pivot'} ou None.
    L'extrême de C2 ne doit pas avoir été repris depuis sa clôture (sinon le sweep a échoué). Le pivot est le dernier swing M15
    (fractale de 2 bougies) confirmé avant la bougie testée, à moins de CRT_PIVOT_BARS bougies de l'extrême de C2 ; la cassure est la
    première clôture au-delà de ce pivot, et doit être l'une des FRESH dernières bougies clôturées."""
    c2_end = c2["epoch"] + S.GRAN[tf]
    ext_px = c2["high"] if d == "SELL" else c2["low"]
    inside = [i for i, c in enumerate(cfc) if c2["epoch"] <= c["epoch"] < c2_end]
    after = [i for i, c in enumerate(cfc) if c["epoch"] >= c2_end]
    if not inside or not after:
        return None
    ext_i = (max(inside, key=lambda i: (cfc[i]["high"], i)) if d == "SELL"
             else min(inside, key=lambda i: (cfc[i]["low"], -i)))
    if any((cfc[i]["high"] > ext_px) if d == "SELL" else (cfc[i]["low"] < ext_px) for i in after):
        return None                                      # l'extrême de C2 a été repris : pas de retournement
    pk = "low" if d == "SELL" else "high"
    sw = S.swings(cfc, pk, 2)
    for j in after:
        if cfc[j]["epoch"] >= c2_end + S.GRAN[tf]:       # on est sorti de C3
            break
        piv = [i for i in sw if i >= ext_i - S.bars(S.CRT_PIVOT_BARS, cf_n) and i + 2 < j]
        if piv and close_beyond(cfc[j], cfc[piv[-1]][pk], d == "BUY"):
            if j < len(cfc) - S.FRESH:
                return None                              # cassure trop ancienne
            return {"ext_i": ext_i, "ext_px": ext_px, "trig": j, "pivot": cfc[piv[-1]][pk]}
    return None


def _crt_one(S, tf, ref, m15, m15c, a_m15, a_h1, funnel, dec, kz, mode, cf_n="M15"):
    pair = crt_pair(S, ref[:-1], funnel)
    if pair is None:
        return None
    d, c1, c2, a_ref = pair
    funnel["CRT_c2"] += 1
    cfm = crt_confirm(S, d, c2, tf, m15c, cf_n)
    if cfm is None:
        return None
    funnel["CRT_choch"] += 1
    ext_i, ext_px, trig, pivot = cfm["ext_i"], cfm["ext_px"], cfm["trig"], cfm["pivot"]
    tc = m15c[trig]
    if not is_displacement(tc, S.body_avg(m15c[-21:-1]), S.DISP_MULT):
        return None
    sess = S.session_name(tc["epoch"])
    if kz and S.CRT_SESSIONS and sess not in S.CRT_SESSIONS:
        funnel["CRT_session"] += 1                       # cassure hors des sessions de Londres / New York (marchés à séance seulement)
        return None
    lo1, hi1 = c1["low"], c1["high"]
    rng = hi1 - lo1
    mid = (hi1 + lo1) / 2
    sgn = 1 if d == "BUY" else -1
    price = m15[-1]["close"]
    sl = ext_px + S.CRT_SL_BUF_ATR * a_m15 if d == "SELL" else ext_px - S.CRT_SL_BUF_ATR * a_m15
    poi = S.entry_zone(m15c, ext_i, trig - 1, d)
    otype, entry = S.pick_entry(d, price, poi[0] if poi else None, sl, mode)
    if otype != d:
        if abs(price - entry) > S.CRT_LIMIT_MAX_ATR * a_m15:
            funnel["CRT_stale"] += 1
            return None                                  # zone d'entrée trop loin du prix
    elif S.is_late(d, price, tc["close"], a_m15, S.CRT_CHASE_ATR):
        funnel["CRT_stale"] += 1
        return None                                      # le prix a déjà fui après la cassure
    tp1 = mid
    tp2 = hi1 if d == "BUY" else lo1
    tp3 = tp2 + sgn * S.CRT_TP3_EXT * rng
    if sgn * (tp1 - entry) <= 0:                         # le milieu de C1 est déjà atteint : la livraison a eu lieu
        funnel["stale"] += 1
        return None
    lv = S.build_levels(d, entry, sl, a_m15, tps=[tp1, tp2, tp3])
    if lv is None:
        return None
    if S.CRT_MIN_RR and abs(tp1 - entry) / lv["risk"] < S.CRT_MIN_RR:
        funnel["CRT_rr"] += 1
        return None                                      # ratio gain/risque jusqu'au milieu de C1 (TP1) sous le minimum
    funnel["CRT_signal"] += 1
    side_hi = d == "SELL"
    details = [f"✅ CRT {tf} : C2 a balayé le {'plus haut' if side_hi else 'plus bas'} de C1 ({hi1 if side_hi else lo1:.{dec}f}, "
               f"mèche {ext_px:.{dec}f}) et clôturé dans son range",
               f"✅ Range C1 {lo1:.{dec}f} - {hi1:.{dec}f} ({rng / a_ref:.1f} ATR {tf})",
               f"✅ CHoCH {cf_n} {'sous' if side_hi else 'au-dessus de'} {pivot:.{dec}f} après la clôture de C2"]
    details.append(f"🎯 Objectifs sur C1 : milieu {tp1:.{dec}f}, bord opposé {tp2:.{dec}f}, bord opposé + {S.CRT_TP3_EXT * 100:.0f} % du range {tp3:.{dec}f}")
    return S._signal(
        "S4", "CRT", d, entry, lv, m15, cf_n, f"{tf}|{c2['epoch']}", details,
        lines=[{"y": hi1, "label": f"C1 haut {tf}", "kind": "range"}, {"y": lo1, "label": f"C1 bas {tf}", "kind": "range"},
               {"y": mid, "label": "Milieu C1", "kind": "info"}, {"y": ext_px, "label": "Sweep C2", "kind": "sweep"},
               {"y": pivot, "label": "CHoCH", "kind": "info"}],
        zones=[{"lo": lo1, "hi": hi1, "label": f"Range C1 {tf}", "kind": "fib"}],
        inval=ext_px, session=sess,
        extra={"ref": tf, "c1": f"{lo1:.{dec}f}-{hi1:.{dec}f}", "poi": poi[1] if otype != d else "marché", "tp": "range C1"},
        short=f"CRT {tf} · C2 clôturée dans C1 · CHoCH {cf_n}", trig=tc["epoch"], otype=otype, price_now=price,
        ttl=S.LIMIT_TTL["S4"] if otype != d else None,
        entry_note=S.poi_note(poi, cf_n, dec) if otype != d else "")


def scan_crt(provide, now, funnel, dec=2, kz=True, mode="market"):
    """S4 CRT : une liste de signaux (au plus un par bougie de référence : H4 et H1), vide s'il n'y a rien."""
    import strategies as S
    cf_n = S.confirm_tf("S4")                         # confirmation : M15 (défaut) ou M5 (m15 / m15c / a_m15 : bougies et ATR de ce timeframe)
    m15, h1 = provide(cf_n), provide("H1")
    if not (m15 and h1):
        return []
    m15c, h1c = m15[:-1], h1[:-1]
    if len(m15c) < 40 or len(h1c) < 40:
        return []
    a_m15, a_h1 = S.atr(m15c), S.atr(h1c)
    if min(a_m15, a_h1) <= 0:
        return []
    if S.CRT_VOL_MIN_RATIO and S.vol_ratio(h1c) < S.CRT_VOL_MIN_RATIO:
        funnel["CRT_vol"] += 1
        return []                                         # marché trop calme : le spread domine
    out = []
    for tf in S.CRT_REFS:
        ref = provide(tf)
        if not ref:
            continue
        sig = _crt_one(S, tf, ref, m15, m15c, a_m15, a_h1, funnel, dec, kz, mode, cf_n)
        if sig and _crt_gate(S, sig, provide, now, funnel):
            out.append(sig)
    return out


def _crt_gate(S, sig, provide, now, funnel):
    """Garde-fous appliqués au signal construit : âge du déclencheur, contexte H4/D1, obstacles H4/H1 (intraday)."""
    if S.CRT_MAX_AGE_MIN and sig.get("trig_close") and (now - sig["trig_close"]) / 60 > S.CRT_MAX_AGE_MIN:
        funnel["CRT_age"] += 1                           # déclencheur trop ancien (retard du cron ou du workflow)
        return False
    if S.CRT_CONTEXT_ALIGN:
        for tf in ("H4", "D1"):                          # pas contre une tendance H4 ou D1 claire
            cs = provide(tf)
            info = trend_info(cs, tf) if cs and len(cs) >= 10 else None
            if info is not None and info["dir"] != sig["dir"]:
                funnel["CRT_contexte"] += 1
                return False
    if S.INTRADAY:
        why = S.obstacle_filter(sig, provide, now, "CRT", False, S.CRT_MIN_RR, "tp1")
        if why:
            funnel[why] += 1                             # obstacle H4/H1 trop proche devant l'objectif
            return False
    return True
