"""S6 Chart Patterns : figures chartistes de retournement et de continuation (voir STRATEGIES.md).

Cadre intraday du bot : la figure est détectée sur les bougies clôturées H1 ou H4 (obstacles majeurs), la cassure de sa
ligne clé est CONFIRMÉE en M15 (clôture M15 au-delà de la ligne, la bougie précédente encore en deçà).
Module autonome (aucune entrée/sortie réseau), même interface que les autres stratégies : scan_s6(provide, now, funnel, ...).

Toutes les figures sont écrites pour une cassure BAISSIÈRE ; les figures haussières s'obtiennent en retournant les prix
(miroir) : même code pour les deux sens.
"""
import os


def _f(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


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
S6_TFS = ("H1", "H4")                            # timeframes de détection des figures
S6_RISK_CAP_ATR = _f("S6_RISK_CAP_ATR", 5.0)       # risque maximal : 5 x ATR du timeframe de la figure (H1 ou H4)
S6_MIN_RR = _f("S6_MIN_RR", 1.0)                 # ratio minimal vers TP3
S6_NOCONF_MIN_RR = _f("S6_NOCONF_MIN_RR", 1.5)   # figure de retournement SANS confluence avec l'alerte de retournement : ratio minimal vers TP3
S6_CONF_RISK_FACTOR = _f("S6_CONF_RISK_FACTOR", 1.4)   # figure de retournement AVEC confluence : risque maximal multiplié par ce facteur
S6_LIMIT_TTL = 10800                              # validité de l'ordre limite (retest de la ligne cassée), en secondes
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
    slref (extrême du stop), height (hauteur de la mesure). La cassure se teste ensuite en M15 (voir scan_s6)."""
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


def _trigger(S, d, tf, csc, m15c, m15, a_m15, funnel, dec, mode, rev_fn=lambda: None):
    """Confirmation M15 de la cassure de la figure d (détectée sur csc, bougies clôturées de `tf`) : une des 2 dernières bougies M15
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
        if s * c0["close"] < lvl(c0["epoch"] + S.GRAN["M15"]) - buf and s * c1["close"] >= lvl(c1["epoch"] + S.GRAN["M15"]) - buf:
            cur = c0
            break
    if cur is None:
        return None
    funnel["S6_cassure"] += 1
    t_now = m15[-1]["epoch"] + S.GRAN["M15"]
    price = m15[-1]["close"]
    sl = s * (d["slref"] + SL_BUF_ATR * d["atr"])
    ref = lvl(cur["epoch"] + S.GRAN["M15"])
    tps = [s * (ref - m * d["height"]) for m in TP_FRACTIONS]
    zone = s * lvl(t_now)                          # retest de la ligne cassée
    otype, entry = S.pick_entry(dr, price, zone, sl, mode)
    if otype != dr:
        if abs(price - entry) > S.LIMIT_MAX_ATR * a_m15:
            funnel["stale"] += 1
            return None
    elif S.is_late(dr, price, cur["close"], a_m15):
        funnel["stale"] += 1
        return None
    # Confluence avec l'alerte de retournement (sweep sur niveau majeur + cassure de structure H1 contre une tendance H4 mûre) :
    # une figure de retournement qui la rejoint a un risque admis plus large ; sans elle, un ratio plus exigeant.
    conf, min_rr, cap = None, S6_MIN_RR, S6_RISK_CAP_ATR
    if d["kind"] == "retournement":
        rev = rev_fn()
        conf = bool(rev and rev["dir"] == dr)
        if conf:
            cap = S6_RISK_CAP_ATR * S6_CONF_RISK_FACTOR
        else:
            min_rr = S6_NOCONF_MIN_RR
    lv = S.build_levels(dr, entry, sl, a_m15, d["atr"], cap, tps=tps)
    if lv is None:
        return None
    gain = lambda t: ((t - entry) if dr == "BUY" else (entry - t)) / lv["risk"]
    if gain(tps[0]) <= 0 or gain(tps[2]) < min_rr:
        return None
    funnel["S6_signal"] += 1
    fam = d["kind"]
    return S._signal(
        "S6", "Figures & Retournement", dr, entry, lv, m15, "M15", f"{d['name']}|{tf}|{cur['epoch']}",
        [f"✅ Figure {tf} : {d['name']} ({fam})",
         f"✅ Cassure confirmée en M15 ({'sous' if dr == 'SELL' else 'au-dessus de'} la ligne)",
         f"✅ Objectif = hauteur de la figure ({d['height']:.{dec}f})"]
        + (["✅ Confluence : retournement possible (sweep sur niveau majeur + cassure de structure H1)"] if conf else [])
        + ([f"ℹ️ Pas de confluence de retournement : ratio minimal {S6_NOCONF_MIN_RR:g} exigé"] if conf is False else []),
        lines=[{"y": s * ref, "label": f"{d['name']} · cassure", "kind": "info"}],
        inval=sl, short=f"{d['name']} {tf} · {fam}", trig=cur["epoch"], otype=otype, price_now=price,
        ttl=S6_LIMIT_TTL if otype != dr else None,
        entry_note=f"Ordre limite au retest de la ligne cassée ({entry:.{dec}f})" if otype != dr else "",
        extra=dict({"origine": "figure", "figure": d["name"], "famille": fam, "tf_figure": tf},
                   **({"confluence_retournement": conf} if conf is not None else {})))


def scan_s6(provide, now, funnel, dec=2, kz=True, mode="market"):
    """S6 Figures & Retournement : figures H1 / H4 (cassure confirmée en M15) et retournement possible (ex-S7). Retourne une liste de signaux (au plus un par sens), ou None.
    `kz` n'a pas d'effet : la confirmation n'est pas limitée à des heures de session."""
    import strategies as S
    m15 = provide("M15")
    if not m15:
        return None
    m15c = m15[:-1]
    if len(m15c) < 20:
        return None
    a_m15 = S.atr(m15c)
    if a_m15 <= 0:
        return None
    memo = {}

    def rev_fn():                                   # alerte de retournement, calculée une seule fois par scan, et seulement si utile
        if "rev" not in memo:
            import reversal
            memo["rev"] = reversal.detect(provide, now)
        return memo["rev"]

    best = {}
    for tf in S6_TFS:
        cs = provide(tf)
        csc = (cs[:-1] if cs else [])[-300:]
        if len(csc) < 80:
            continue
        h = [x["high"] for x in csc]
        l = [x["low"] for x in csc]
        c = [x["close"] for x in csc]
        for flip in (False, True):
            for d in candidates(h, l, c, flip):
                funnel["S6_figure"] += 1
                sig = _trigger(S, d, tf, csc, m15c, m15, a_m15, funnel, dec, mode, rev_fn)
                if not sig:
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
        import reversal
        sig = reversal.reversal_signal(provide, now, funnel, dec, mode, rev=rev)
        if sig:
            out.append(sig)
    return out or None
