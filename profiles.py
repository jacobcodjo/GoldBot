"""profiles.py - Market Profiles + Key Levels (range -> manipulation -> expansion).

Price action pur : pivots, sweeps, clotures. Aucun indicateur (pas d'ATR).
Bougie = dict avec les cles : open, high, low, close
Setups codes : A (range + sweep), B (break & retest), C (reversal niveau cle),
D (manipulation sur support), E (retracement + deep sweep).
"""
from dataclasses import dataclass, field


@dataclass
class Setup:
    name: str
    side: str      # "BUY" ou "SELL"
    entry: float   # ordre limite sur le retest
    sl: float
    tp1: float
    rr_tp1: float
    note: str = ""
    trig: int = -1                          # index (dans c) de la bougie dont la cloture confirme le setup (CHoCH, cassure, retest)
    meta: dict = field(default_factory=dict)  # niveaux utiles a l'affichage : range, extreme, level


# ---------------------------------------------------------------- pivots
def pivots(c, left=3, right=3):
    """Swing highs/lows confirmes. Retourne [(index, "H"|"L", prix)]."""
    out = []
    for i in range(left, len(c) - right):
        hi, lo = c[i]["high"], c[i]["low"]
        if (all(hi > c[j]["high"] for j in range(i - left, i))
                and all(hi >= c[j]["high"] for j in range(i + 1, i + right + 1))):
            out.append((i, "H", hi))
        if (all(lo < c[j]["low"] for j in range(i - left, i))
                and all(lo <= c[j]["low"] for j in range(i + 1, i + right + 1))):
            out.append((i, "L", lo))
    return sorted(out, key=lambda x: x[0])


# ----------------------------------------------------------------- range
def detect_range(c, piv, n_piv=6, tol=0.25, max_height_pct=None):
    """Range = au moins 2 hauts et 2 bas proches des bornes, aucune cloture
    hors bornes. tol = fraction de la hauteur du range (pas d'ATR)."""
    p = piv[-n_piv:]
    highs = [x for x in p if x[1] == "H"]
    lows = [x for x in p if x[1] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    top = max(x[2] for x in highs)
    bot = min(x[2] for x in lows)
    h = top - bot
    if h <= 0:
        return None
    if max_height_pct and h / bot > max_height_pct:
        return None
    if sum(1 for x in highs if x[2] >= top - tol * h) < 2:
        return None
    if sum(1 for x in lows if x[2] <= bot + tol * h) < 2:
        return None
    start, end = p[0][0], p[-1][0]
    if any(not (bot <= c[i]["close"] <= top) for i in range(start, end + 1)):
        return None
    return {"top": top, "bot": bot, "start": start, "end": end}


# ----------------------------------------------------------------- sweep
def find_sweep(c, lookback=10, max_gap=8, **kw):
    """Sweep : la meche depasse une borne du range, la cloture revient dedans.
    Le range est calcule uniquement sur les bougies AVANT le sweep."""
    for s in range(len(c) - 1, max(len(c) - 1 - lookback, 10), -1):
        past = c[:s]
        rng = detect_range(past, pivots(past), **kw)
        if not rng or s - rng["end"] > max_gap:
            continue
        # pas de cassure entre la fin du range et le sweep
        if any(not (rng["bot"] <= k["close"] <= rng["top"])
               for k in c[rng["end"] + 1:s]):
            continue
        k = c[s]
        if k["low"] < rng["bot"] < k["close"]:
            return {"side": "BUY", "idx": s, "extreme": k["low"], "range": rng}
        if k["high"] > rng["top"] > k["close"]:
            return {"side": "SELL", "idx": s, "extreme": k["high"], "range": rng}
    return None


# --------------------------------------------------------- construction
def first_close_beyond(c, s, level, buy):
    """Index de la premiere bougie (a partir de s) dont la cloture depasse `level` (au-dessus si buy), sinon None."""
    for i in range(s, len(c)):
        if (c[i]["close"] > level) if buy else (c[i]["close"] < level):
            return i
    return None


def build(c, name, side, entry, sl, min_rr=3.0, note="", trig=-1, meta=None):
    """TP1 = premiere liquidite opposee (pivot). Sans liquidite : TP1 au ratio
    minimal. Rejet si ratio TP1 < min_rr ou si le retest est deja depasse."""
    buy = side == "BUY"
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    last = c[-1]["close"]
    if (buy and last < entry) or (not buy and last > entry):
        return None
    typ = "H" if buy else "L"
    liq = [p for _, t, p in pivots(c) if t == typ and (p > entry if buy else p < entry)]
    if liq:
        tp1 = min(liq) if buy else max(liq)
    else:
        tp1 = entry + min_rr * risk if buy else entry - min_rr * risk
    rr = abs(tp1 - entry) / risk
    if rr < min_rr - 1e-9:
        return None
    return Setup(name, side, entry, sl, tp1, round(rr, 2), note, trig, dict(meta or {}))


# ----------------------------------------------------- setup A : range + sweep
def scan_range_sweep(c, min_rr=3.0, **kw):
    sw = find_sweep(c, **kw)
    if not sw:
        return None
    buy = sw["side"] == "BUY"
    typ = "H" if buy else "L"
    past = [x for x in pivots(c[:sw["idx"]]) if x[1] == typ]
    if not past:
        return None
    lvl = past[-1][2]  # niveau de CHoCH = dernier pivot oppose avant le sweep
    trig = first_close_beyond(c, sw["idx"], lvl, buy)
    if trig is None:
        return None
    rg = sw["range"]
    return build(c, "A Range+Sweep", sw["side"], lvl, sw["extreme"], min_rr,
                 "sweep range + CHoCH, entree sur retest", trig,
                 {"range": (rg["bot"], rg["top"]), "extreme": sw["extreme"], "level": lvl})


# ------------------------------------------- setup C : reversal sur niveau cle
def scan_key_level_reversal(c, key_levels, min_rr=3.0, lookback=6):
    """Structure baissiere (hauts et bas descendants) -> sweep d'un niveau cle
    par le bas -> CHoCH haussier. Inverse pour la vente. Contre-tendance."""
    for s in range(len(c) - 1, max(len(c) - 1 - lookback, 10), -1):
        past = c[:s]
        pv = pivots(past)
        H = [x for x in pv if x[1] == "H"]
        L = [x for x in pv if x[1] == "L"]
        if len(H) < 2 or len(L) < 2:
            continue
        down = H[-1][2] < H[-2][2] and L[-1][2] < L[-2][2]
        up = H[-1][2] > H[-2][2] and L[-1][2] > L[-2][2]
        k = c[s]
        for lvl in key_levels:
            if down and k["low"] < lvl < k["close"]:
                choch = H[-1][2]
                t = first_close_beyond(c, s, choch, True)
                if t is not None:
                    r = build(c, "C Reversal niveau cle", "BUY", choch, k["low"],
                              min_rr, "contre-tendance", t,
                              {"key": lvl, "extreme": k["low"], "level": choch})
                    if r:
                        return r
            if up and k["high"] > lvl > k["close"]:
                choch = L[-1][2]
                t = first_close_beyond(c, s, choch, False)
                if t is not None:
                    r = build(c, "C Reversal niveau cle", "SELL", choch, k["high"],
                              min_rr, "contre-tendance", t,
                              {"key": lvl, "extreme": k["high"], "level": choch})
                    if r:
                        return r
    return None


# ------------------------------------------------------------- utilitaires
def confirm(c, s, side, choch, extreme, name, note, min_rr, meta=None):
    """CHoCH = une cloture au-dela de `choch` a partir de la bougie s."""
    buy = side == "BUY"
    t = first_close_beyond(c, s, choch, buy)
    if t is None:
        return None
    return build(c, name, side, choch, extreme, min_rr, note, t,
                 dict(meta or {}, extreme=extreme, level=choch))


def last_pattern(pv, pattern):
    """Dernier enchainement de pivots dont les types suivent `pattern`
    (ex. "HLH"), parmi les 8 derniers pivots. Retourne la liste ou None."""
    n = len(pattern)
    for i in range(len(pv) - n, max(len(pv) - n - 8, -1), -1):
        w = pv[i:i + n]
        if "".join(x[1] for x in w) == pattern:
            return w
    return None


# ------------------------------------------------- setup B : break & retest
def scan_break_retest(c, key_levels=(), min_rr=3.0, lookback=12, n_below=8):
    """Consolidation sous un niveau (cle ou borne de range), cloture au-dela,
    puis retour sur le niveau sans le reperdre. Si le retest n'a pas encore eu
    lieu : ordre limite sur le niveau. S'il a eu lieu : entree a la derniere
    cloture. SL sous le plus bas (au-dessus du plus haut) depuis la cassure."""
    for b in range(len(c) - 1, max(len(c) - 1 - lookback, n_below + 3), -1):
        past = c[:b]
        levels = list(key_levels)
        rng = detect_range(past, pivots(past))
        if rng:
            levels += [rng["top"], rng["bot"]]
        k, after, win = c[b], c[b + 1:], c[b - n_below:b]
        for lvl in levels:
            if k["close"] > lvl and all(x["close"] <= lvl for x in win):
                if any(x["close"] <= lvl for x in after):
                    continue  # niveau reperdu
                touched = any(x["low"] <= lvl for x in after)
                entry = c[-1]["close"] if touched else lvl
                sl = min(x["low"] for x in c[b:])
                tr = b + 1 + next(i for i, x in enumerate(after) if x["low"] <= lvl) if touched else b
                r = build(c, "B Break&Retest", "BUY", entry, sl, min_rr,
                          "retest effectue" if touched else "retest en attente", tr,
                          {"level": lvl, "extreme": sl})
                if r:
                    return r
            if k["close"] < lvl and all(x["close"] >= lvl for x in win):
                if any(x["close"] >= lvl for x in after):
                    continue
                touched = any(x["high"] >= lvl for x in after)
                entry = c[-1]["close"] if touched else lvl
                sl = max(x["high"] for x in c[b:])
                tr = b + 1 + next(i for i, x in enumerate(after) if x["high"] >= lvl) if touched else b
                r = build(c, "B Break&Retest", "SELL", entry, sl, min_rr,
                          "retest effectue" if touched else "retest en attente", tr,
                          {"level": lvl, "extreme": sl})
                if r:
                    return r
    return None


# --------------------------------------- setup D : manipulation sur support
def scan_manipulation_support(c, key_levels, min_rr=3.0, lookback=8,
                              exp_mult=1.5, **kw):
    """Expansion, puis range AU-DESSUS du niveau cle, faux breakdown (sweep du
    niveau), puis CHoCH. L'expansion precedente doit mesurer au moins
    exp_mult x la hauteur du range (pas d'ATR). Miroir pour la vente."""
    for s in range(len(c) - 1, max(len(c) - 1 - lookback, 15), -1):
        past = c[:s]
        pv = pivots(past)
        rng = detect_range(past, pv, **kw)
        if not rng or s - rng["end"] > 8:
            continue
        h = rng["top"] - rng["bot"]
        k = c[s]
        mid = c[rng["end"] + 1:s]
        hs = [x for x in pv if x[1] == "H"]
        ls = [x for x in pv if x[1] == "L"]
        for lvl in key_levels:
            if rng["bot"] > lvl and k["low"] < lvl < k["close"] \
                    and all(x["close"] > lvl for x in mid):
                before = [x for x in hs if x[0] < rng["start"]]
                if before and before[-1][2] - rng["bot"] >= exp_mult * h and hs:
                    r = confirm(c, s, "BUY", hs[-1][2], k["low"],
                                "D Manipulation support",
                                "expansion, range, faux breakdown", min_rr,
                                {"range": (rng["bot"], rng["top"]), "key": lvl})
                    if r:
                        return r
            if rng["top"] < lvl and k["high"] > lvl > k["close"] \
                    and all(x["close"] < lvl for x in mid):
                before = [x for x in ls if x[0] < rng["start"]]
                if before and rng["top"] - before[-1][2] >= exp_mult * h and ls:
                    r = confirm(c, s, "SELL", ls[-1][2], k["high"],
                                "D Manipulation support",
                                "expansion, range, faux breakout", min_rr,
                                {"range": (rng["bot"], rng["top"]), "key": lvl})
                    if r:
                        return r
    return None


# ------------------------------------- setup E : retracement + deep sweep
def scan_retrace_deep_sweep(c, key_levels, min_rr=3.0, lookback=6,
                            ret_min=0.25, ret_max=0.8, depth_frac=0.15):
    """Expansion (jambe H0->L0), retracement partiel (H1), puis un sweep
    PROFOND du niveau cle : la meche depasse le niveau d'au moins
    depth_frac x hauteur de l'expansion. Puis CHoCH. Contre-tendance."""
    for s in range(len(c) - 1, max(len(c) - 1 - lookback, 15), -1):
        past = c[:s]
        pv = pivots(past)
        k = c[s]
        hs = [x for x in pv if x[1] == "H"]
        ls = [x for x in pv if x[1] == "L"]
        for lvl in key_levels:
            if k["low"] < lvl < k["close"] and hs:
                t = last_pattern(pv, "HLH")
                if t:
                    h0, l0, h1 = t[0][2], t[1][2], t[2][2]
                    leg = h0 - l0
                    if (leg > 0 and h0 > h1 > l0
                            and ret_min <= (h1 - l0) / leg <= ret_max
                            and lvl - k["low"] >= depth_frac * leg):
                        r = confirm(c, s, "BUY", hs[-1][2], k["low"],
                                    "E Retrace+DeepSweep", "contre-tendance",
                                    min_rr, {"key": lvl})
                        if r:
                            return r
            if k["high"] > lvl > k["close"] and ls:
                t = last_pattern(pv, "LHL")
                if t:
                    l0, h0, l1 = t[0][2], t[1][2], t[2][2]
                    leg = h0 - l0
                    if (leg > 0 and l0 < l1 < h0
                            and ret_min <= (h0 - l1) / leg <= ret_max
                            and k["high"] - lvl >= depth_frac * leg):
                        r = confirm(c, s, "SELL", ls[-1][2], k["high"],
                                    "E Retrace+DeepSweep", "contre-tendance",
                                    min_rr, {"key": lvl})
                        if r:
                            return r
    return None


def scan_all(c, key_levels=(), min_rr=3.0):
    """Retourne la liste des setups (A, B, C, D, E) detectes sur c."""
    kl = list(key_levels)
    res = [scan_range_sweep(c, min_rr=min_rr),
           scan_break_retest(c, kl, min_rr=min_rr),
           scan_key_level_reversal(c, kl, min_rr=min_rr),
           scan_manipulation_support(c, kl, min_rr=min_rr),
           scan_retrace_deep_sweep(c, kl, min_rr=min_rr)]
    return [r for r in res if r]
