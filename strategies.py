"""Quatre stratégies pour l'or (XAUUSD), les paires forex majeures et BTC/ETH. Toutes les règles sont décrites dans STRATEGIES.md.

Module autonome : aucune entrée/sortie réseau. Chaque stratégie reçoit provide(tf) -> bougies du
timeframe (la dernière est en formation) et renvoie un signal (dict) ou None.

  S1  Trend Pullback              H4 (tendance) > H1 (repli 50-79 %) > M15 (cassure de structure)
  S2  Asian Breakout                  M15, fenêtre 02h00-07h00 New York
  S3  Sweep + CHoCH                   M15 (sweep) > M5 (cassure de structure), killzones
  S4  Mean Reversion                  H1 (régime) > M15 (rejet des bandes de Bollinger)

Les heures sont en heure de New York ; D1 et H4 ouvrent à 17h New York.
"""
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
GRAN = {"D1": 86400, "H4": 14400, "H1": 3600, "M15": 900, "M5": 300}

# --- Paramètres communs ---
ATR_N = 14
DISP_MULT = 1.2           # corps de la bougie de cassure >= 1,2 x corps moyen (20 dernières bougies)
FRESH = 2                 # la bougie de déclenchement doit être l'une des 2 dernières clôturées
BUF_ATR = 0.15            # marge du stop au-delà de l'extrême : 0,15 x ATR du timeframe d'entrée
MIN_RISK_ATR = 0.5        # risque minimal : 0,5 x ATR du timeframe d'entrée (sinon le stop est éloigné)
CHASE_ATR = 0.75          # le prix ne doit pas avoir fui de plus de 0,75 x ATR de la clôture de déclenchement
TP_MULTS = (1.0, 2.0, 3.0)  # TP1, TP2, TP3 en multiples du risque (S1, S2, S3)
VOL_MIN_RATIO = 0.5       # signal écarté si l'ATR H1 actuel < 0,5 x sa médiane récente (marché mort : le spread domine) ; 0 = off
VOL_LOOKBACK = 240        # fenêtre (en bougies H1) de la médiane de l'ATR

KILLZONES_NY = [("Asie", 20, 24), ("Asie", 0, 2), ("Londres", 2, 5), ("New York", 7, 10), ("London Close", 10, 12)]

# --- S1 Trend Pullback ---
S1_EMA_FAST, S1_EMA_SLOW = 50, 200     # EMA du H4
S1_ADX_MIN = 18                        # ADX(14) du H4 minimal : écarte les marchés sans direction
S1_SWING_H4 = 2                        # fractale H4 : 2 bougies de chaque côté
S1_SWING_H1 = 3                        # fractale H1 : 3 bougies de chaque côté
S1_LEG_BARS = 24                       # la jambe démarre au plus bas (haut) des 24 H1 qui précèdent le sommet (creux)
S1_LEG_MIN_ATR, S1_LEG_MAX_ATR = 1.5, 5.0   # taille de la jambe impulsive H1, en ATR H1
S1_FIB_MIN, S1_FIB_MAX = 0.50, 0.85    # le repli doit atteindre 50 % et ne pas dépasser 85 % de la jambe
S1_ZONE = (0.50, 0.79)                 # zone de repli affichée (50 % - 79 %)
S1_RISK_CAP_H1 = 1.5                   # risque maximal : 1,5 x ATR H1

# --- S2 Cassure de la plage asiatique ---
S2_RANGE_MIN_ATR, S2_RANGE_MAX_ATR = 0.4, 2.0   # taille de la plage asiatique, en ATR H1
S2_WINDOW = (2, 7)                     # cassure valable de 02h00 à 07h00 New York
S2_CLOSE_STRENGTH = 0.7                # la bougie doit clôturer dans les 30 % extrêmes de son amplitude
S2_RISK_CAP_H1 = 2.0
S2_H4_FILTER = True                    # sens aligné avec l'EMA 50 du H4

# --- S3 Prise de liquidité + CHoCH ---
S3_EQ_TOL_ATR = 0.15                   # equal highs/lows : deux swings H1 à moins de 0,15 ATR H1
S3_SWEEP_BARS = 8                      # le sweep M15 date de 8 bougies M15 au plus (2 h)
S3_PIVOT_BARS = 36                     # pivot M5 à moins de 36 bougies M5 (3 h) du sommet/creux du sweep
S3_SESSIONS = ("Londres", "New York", "London Close")
S3_RISK_CAP_H1 = 1.5

# --- S4 Mean Reversion ---
S4_ADX_MAX = 20                        # ADX(14) du H1 sous 20
S4_FLAT_ATR = 0.6                      # EMA 50 du H1 : variation sur 12 bougies sous 0,6 x ATR H1
S4_BB_N, S4_BB_K = 20, 2.0
S4_RSI_N, S4_RSI_LOW, S4_RSI_HIGH = 14, 30, 70
S4_BUF_ATR = 0.3
S4_HOURS = [(20, 26), (11, 15)]        # 20h-02h et 11h-15h New York (26 = 02h du lendemain)
S4_MIN_RR1, S4_MIN_RR2 = 0.8, 1.5      # ratios minimaux vers TP1 et TP2
S4_RISK_CAP_H1 = 1.0


# ==========================================================================
# Indicateurs
# ==========================================================================
def body(c):
    return abs(c["close"] - c["open"])


def body_avg(cs, n=20):
    cs = cs[-n:]
    return sum(body(c) for c in cs) / len(cs) if cs else 0.0


def atr(cs, n=ATR_N):
    cs = cs[-(n + 1):]
    trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
           for p, c in zip(cs, cs[1:])]
    return sum(trs) / len(trs) if trs else 0.0


def ema(vals, n):
    """EMA (graine = moyenne simple des n premières valeurs). None avant la n-ième valeur."""
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    out[n - 1] = e
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi_series(closes, n=14):
    """RSI de Wilder pour chaque bougie (None au début)."""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, n + 1)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def adx(cs, n=14):
    """ADX de Wilder (dernière valeur), ou None si l'historique est insuffisant (< 2n + 1 bougies)."""
    if len(cs) < 2 * n + 1:
        return None
    tr, pdm, mdm = [], [], []
    for p, c in zip(cs, cs[1:]):
        up, dn = c["high"] - p["high"], p["low"] - c["low"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])))
    s_tr, s_p, s_m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    for i in range(n, len(tr) + 1):
        if i > n:
            s_tr = s_tr - s_tr / n + tr[i - 1]
            s_p = s_p - s_p / n + pdm[i - 1]
            s_m = s_m - s_m / n + mdm[i - 1]
        if s_tr <= 0:
            dxs.append(0.0)
            continue
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        dxs.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    if len(dxs) < n:
        return None
    a = sum(dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d) / n
    return a


def bollinger(closes, i, n=S4_BB_N, k=S4_BB_K):
    """(bande basse, moyenne, bande haute) à la bougie d'index i, ou None."""
    if i + 1 < n:
        return None
    w = closes[i + 1 - n:i + 1]
    m, sd = sum(w) / n, statistics.pstdev(w)
    return m - k * sd, m, m + k * sd


def swings(cs, kind, n):
    """Index des swings confirmés (fractales) : plus haut/bas strict sur n bougies de chaque côté.
    `cs` ne doit contenir que des bougies clôturées."""
    out = []
    for i in range(n, len(cs) - n):
        v = cs[i][kind]
        around = [cs[j][kind] for j in range(i - n, i + n + 1) if j != i]
        if (kind == "high" and v > max(around)) or (kind == "low" and v < min(around)):
            out.append(i)
    return out


# ==========================================================================
# Temps et sessions (heure de New York)
# ==========================================================================
def session_name(epoch):
    h = datetime.fromtimestamp(epoch, NY).hour
    for name, a, b in KILLZONES_NY:
        if a <= h < b:
            return name
    return "Hors session"


def asia_window(now):
    """(début, fin) en epoch de la plage asiatique en cours ou la plus récente : 20h00 -> 02h00 New York."""
    dt = datetime.fromtimestamp(now, NY)
    start = (dt - timedelta(days=1) if dt.hour < 20 else dt).replace(hour=20, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=1)).replace(hour=2)
    return int(start.timestamp()), int(end.timestamp())


def in_hours(epoch, windows):
    h = datetime.fromtimestamp(epoch, NY).hour
    return any(a <= h < b or a <= h + 24 < b for a, b in windows)


# ==========================================================================
# Niveaux d'entrée, stop et objectifs
# ==========================================================================
def build_levels(d, entry, sl, a_ltf, a_h1, cap_h1, tps=None):
    """Applique le risque minimal (stop élargi si trop proche) et le plafond (signal rejeté si le
    risque dépasse cap_h1 x ATR H1). tps : liste de 3 objectifs ; sinon 1R / 2R / 3R."""
    risk = abs(entry - sl)
    floor = MIN_RISK_ATR * a_ltf
    if risk < floor:
        sl = entry - floor if d == "BUY" else entry + floor
        risk = floor
    if risk <= 0 or (a_h1 > 0 and risk > cap_h1 * a_h1):
        return None
    sgn = 1 if d == "BUY" else -1
    return {"sl": sl, "risk": risk, "tp": tps or [entry + sgn * m * risk for m in TP_MULTS]}


def is_late(d, price, trig_close, a_ltf):
    """Vrai si le prix a déjà trop fui dans le sens du trade depuis la clôture de déclenchement."""
    move = (price - trig_close) if d == "BUY" else (trig_close - price)
    return a_ltf > 0 and move > CHASE_ATR * a_ltf


# --- Ordres limites (entrée au retest d'une zone plutôt qu'au marché) ---
LIMIT_OB_FRACTION = 0.0     # bloc d'ordre : 0 = bord proche (extrémité touchée en premier), 0,5 = milieu, 1 = bord lointain
LIMIT_FVG_FRACTION = 0.5    # FVG : 0,5 = milieu du déséquilibre
LIMIT_MAX_ATR = 1.5         # zone d'entrée à plus de 1,5 ATR du prix actuel : signal écarté (trop de retracement requis)
LIMIT_TTL = {"S1": 7200, "S2": 10800, "S3": 3600, "S4": 5400}   # validité de l'ordre limite, en secondes


def ob_zone(cs, lo_i, hi_i, d):
    """Dernier bloc d'ordre : la dernière bougie de sens opposé à d (baissière pour un achat) parmi cs[lo_i..hi_i].
    Retourne (bas, haut) ou None."""
    for j in range(hi_i, lo_i - 1, -1):
        c = cs[j]
        if (c["close"] < c["open"]) if d == "BUY" else (c["close"] > c["open"]):
            return c["low"], c["high"]
    return None


def ob_entry(d, zone):
    """Prix d'entrée dans le bloc d'ordre : par défaut son bord proche (haut pour un achat, bas pour une vente)."""
    lo, hi = zone
    return hi - LIMIT_OB_FRACTION * (hi - lo) if d == "BUY" else lo + LIMIT_OB_FRACTION * (hi - lo)


def fvg_zone(cs, lo_i, d):
    """Dernier FVG (déséquilibre sur 3 bougies) créé par un déplacement après cs[lo_i], dans le sens du trade d, et
    non comblé : achat, le haut de la bougie 1 est sous le bas de la bougie 3 ; vente, l'inverse. La bougie du milieu
    doit être un déplacement (corps >= DISP_MULT x corps moyen). Retourne (bas, haut) ou None."""
    avg = body_avg(cs[max(0, lo_i - 20):max(lo_i, 1)])
    for i in range(len(cs) - 2, lo_i, -1):               # i = bougie du milieu ; la bougie i+1 doit être clôturée
        a, m, b = cs[i - 1], cs[i], cs[i + 1]
        if d == "BUY" and a["high"] < b["low"]:
            gap = (a["high"], b["low"])
        elif d == "SELL" and a["low"] > b["high"]:
            gap = (b["high"], a["low"])
        else:
            continue
        if avg > 0 and body(m) < DISP_MULT * avg:
            continue
        later = cs[i + 2:]
        if (d == "BUY" and any(c["low"] <= gap[0] for c in later)) or \
                (d == "SELL" and any(c["high"] >= gap[1] for c in later)):
            continue                                       # déjà comblé
        return gap
    return None


def fvg_entry(d, gap):
    """Prix d'entrée dans le FVG : son milieu (LIMIT_FVG_FRACTION)."""
    lo, hi = gap
    return hi - LIMIT_FVG_FRACTION * (hi - lo) if d == "BUY" else lo + LIMIT_FVG_FRACTION * (hi - lo)


def entry_zone(cs, lo_i, hi_i, d):
    """Zone d'entrée d'un ordre limite : le bloc d'ordre en priorité (entrée à son bord proche), sinon le FVG (entrée
    à son milieu). Retourne (prix d'entrée, 'OB' | 'FVG', (bas, haut)) ou None. Les bougies de cs[lo_i] à cs[hi_i]
    cherchent le bloc d'ordre ; le FVG se cherche de cs[lo_i] à la dernière bougie clôturée."""
    ob = ob_zone(cs, lo_i, hi_i, d)
    if ob:
        return ob_entry(d, ob), "OB", ob
    gap = fvg_zone(cs, lo_i, d)
    if gap:
        return fvg_entry(d, gap), "FVG", gap
    return None


def poi_note(poi, tf, dec):
    kind, (lo, hi) = poi[1], poi[2]
    where = "au bord du bloc d'ordre" if kind == "OB" else "au milieu du FVG"
    return f"Ordre limite {where} {tf} ({lo:.{dec}f} - {hi:.{dec}f})"


def pick_entry(d, price, zone, sl, mode):
    """(type d'ordre, prix d'entrée). Mode 'limit' : ordre limite à `zone` si elle se trouve entre le stop et le prix
    actuel (au bon côté du prix), sinon ordre au marché."""
    if mode == "limit" and zone is not None:
        if d == "BUY" and sl < zone < price:
            return "BUY LIMIT", zone
        if d == "SELL" and price < zone < sl:
            return "SELL LIMIT", zone
    return d, price


def vol_ratio(h1c):
    """ATR H1 actuel rapporté à sa médiane sur les ~240 dernières bougies H1 (1 = volatilité normale)."""
    n = len(h1c)
    if n < 60:
        return 1.0
    pts = [atr(h1c[:i]) for i in range(max(ATR_N + 2, n - VOL_LOOKBACK), n + 1, 6)]
    med = statistics.median(pts) if pts else 0.0
    return atr(h1c) / med if med > 0 else 1.0


def _signal(strat, label, d, price, lv, ltf, ltf_n, key, details, **kw):
    sig = {"strat": strat, "label": label, "dir": d, "otype": d, "entry": price, "price_now": price, "ttl": None,
           "entry_note": "", "sl": lv["sl"],
           "tp1": lv["tp"][0], "tp2": lv["tp"][1], "tp3": lv["tp"][2], "ltf": ltf_n, "gran": GRAN[ltf_n],
           "key": f"{strat}|{d}|{key}", "details": details, "lines": [], "zones": [], "inval": None,
           "extra": {}, "short": "", "session": session_name(ltf[-1]["epoch"])}
    sig.update(kw)
    if "trig" in sig:                  # heure de clôture de la bougie de déclenchement
        sig["trig_close"] = sig.pop("trig") + GRAN[ltf_n]
    return sig


def h4_ema_bias(h4):
    """+1 si le dernier H4 clôturé est au-dessus de l'EMA 50, -1 sinon, 0 si inconnu."""
    closes = [c["close"] for c in h4[:-1]]
    e = ema(closes, S1_EMA_FAST)[-1] if closes else None
    if e is None:
        return 0
    return 1 if closes[-1] > e else -1


# ==========================================================================
# S1  Trend Pullback
# ==========================================================================
def s1_trend(h4c):
    """'BUY' / 'SELL' / None. Tendance haussière : EMA50 > EMA200, clôture > EMA200, ADX >= 18 et dernier
    creux H4 plus haut que le précédent. Baissière : l'inverse (sommet plus bas)."""
    if len(h4c) < S1_EMA_SLOW + 10:
        return None
    closes = [c["close"] for c in h4c]
    fast, slow = ema(closes, S1_EMA_FAST)[-1], ema(closes, S1_EMA_SLOW)[-1]
    a = adx(h4c)
    if fast is None or slow is None or a is None or a < S1_ADX_MIN:
        return None
    if fast > slow and closes[-1] > slow:
        lows = swings(h4c, "low", S1_SWING_H4)
        if len(lows) >= 2 and h4c[lows[-1]]["low"] > h4c[lows[-2]]["low"]:
            return "BUY"
    if fast < slow and closes[-1] < slow:
        highs = swings(h4c, "high", S1_SWING_H4)
        if len(highs) >= 2 and h4c[highs[-1]]["high"] < h4c[highs[-2]]["high"]:
            return "SELL"
    return None


def scan_s1(provide, now, funnel, dec=2, kz=True, mode="market"):
    h4, h1, m15 = provide("H4"), provide("H1"), provide("M15")
    if not (h4 and h1 and m15):
        return None
    h4c, h1c, m15c = h4[:-1], h1[:-1], m15[:-1]
    d = s1_trend(h4c)
    if d is None or len(h1c) < 60 or len(m15c) < 40:
        return None
    funnel["S1_tendance"] += 1
    buy = d == "BUY"
    a_h1, a_m15 = atr(h1c), atr(m15c)
    if a_h1 <= 0 or a_m15 <= 0:
        return None
    # --- jambe impulsive H1 : dernier swing (sommet si achat) et swing opposé qui le précède ---
    hk, lk = ("high", "low") if buy else ("low", "high")
    tops = swings(h1c, hk, S1_SWING_H1)
    if not tops:
        return None
    ti = tops[-1]
    if len(h1c) - 1 - ti > 48:
        return None                                  # sommet trop ancien
    top = h1c[ti][hk]
    if any((c["high"] > top) if buy else (c["low"] < top) for c in h1c[ti + 1:]):
        return None                                  # nouvel extrême en cours : on attend sa confirmation
    window = h1c[max(0, ti - S1_LEG_BARS):ti + 1]          # la jambe démarre au plus bas (haut) des 24 H1 précédents
    base = min(c["low"] for c in window) if buy else max(c["high"] for c in window)
    leg = abs(top - base)
    if not (S1_LEG_MIN_ATR * a_h1 <= leg <= S1_LEG_MAX_ATR * a_h1):
        return None
    # --- repli : extrême atteint depuis le sommet (M15 clôturées après la clôture de la bougie H1 du sommet) ---
    after = [(i, c) for i, c in enumerate(m15c) if c["epoch"] >= h1c[ti]["epoch"] + GRAN["H1"]]
    if len(after) < 4:
        return None
    pb_i, pb = (min(after, key=lambda x: (x[1]["low"], -x[0])) if buy
                else max(after, key=lambda x: (x[1]["high"], x[0])))
    pb_px = pb["low"] if buy else pb["high"]
    retr = abs(top - pb_px) / leg
    if not (S1_FIB_MIN <= retr <= S1_FIB_MAX):
        return None
    funnel["S1_repli"] += 1
    # --- déclencheur M15 : cassure du dernier swing contraire formé pendant le repli ---
    sk = "high" if buy else "low"
    piv = [i for i in swings(m15c, sk, 2) if i < pb_i and m15c[i]["epoch"] > h1c[ti]["epoch"]]
    if not piv:
        return None
    level = m15c[piv[-1]][sk]
    avg = body_avg(m15c[-21:-1])
    trig = None
    for i in range(pb_i + 1, len(m15c)):
        c = m15c[i]
        if (c["close"] > level) if buy else (c["close"] < level):
            trig = i
            break
    if trig is None or trig < len(m15c) - FRESH:
        return None
    tc = m15c[trig]
    if body(tc) < DISP_MULT * avg:
        return None
    price = m15[-1]["close"]
    sl = pb_px - BUF_ATR * a_m15 if buy else pb_px + BUF_ATR * a_m15
    poi = entry_zone(m15c, pb_i, trig - 1, d)
    otype, entry = pick_entry(d, price, poi[0] if poi else None, sl, mode)
    if otype != d:
        if abs(price - entry) > LIMIT_MAX_ATR * a_m15:
            funnel["stale"] += 1                      # zone d'entrée trop loin du prix
            return None
    elif is_late(d, price, tc["close"], a_m15):
        funnel["stale"] += 1
        return None
    lv = build_levels(d, entry, sl, a_m15, a_h1, S1_RISK_CAP_H1)
    if lv is None:
        return None
    funnel["S1_signal"] += 1
    zone = sorted([top - S1_ZONE[0] * leg, top - S1_ZONE[1] * leg]) if buy else \
        sorted([top + S1_ZONE[0] * leg, top + S1_ZONE[1] * leg])
    return _signal(
        "S1", "Trend Pullback", d, entry, lv, m15, "M15", f"{h1c[ti]['epoch']}|{pb['epoch']}|{tc['epoch']}",
        [f"✅ Tendance H4 {'haussière' if buy else 'baissière'} (EMA 50/200, ADX {adx(h4c):.0f})",
         f"✅ Repli H1 à {retr * 100:.0f} % de la jambe ({top:.{dec}f} → {base:.{dec}f})",
         f"✅ Cassure de structure M15 à {level:.{dec}f}"],
        lines=[{"y": level, "label": "Cassure", "kind": "range"}, {"y": pb_px, "label": "Repli", "kind": "sweep"}],
        zones=[{"lo": zone[0], "hi": zone[1], "label": "Fib 50-79 %", "kind": "fib"}],
        inval=pb_px, extra={"retr": round(retr, 2), "poi": poi[1] if otype != d else "marché"},
        short=f"Repli H1 {retr * 100:.0f} % · cassure M15", trig=tc["epoch"], otype=otype, price_now=price,
        ttl=LIMIT_TTL["S1"] if otype != d else None,
        entry_note=poi_note(poi, "M15", dec) if otype != d else "")


# ==========================================================================
# S2  Asian Breakout (cassure de la plage asiatique)
# ==========================================================================
def scan_s2(provide, now, funnel, dec=2, kz=True, mode="market"):
    h1, m15, h4 = provide("H1"), provide("M15"), provide("H4")
    if not (h1 and m15 and h4):
        return None
    a0, a1 = asia_window(now)
    hour = datetime.fromtimestamp(now, NY).hour
    if not (S2_WINDOW[0] <= hour < S2_WINDOW[1]) or now < a1:
        return None
    m15c, h1c = m15[:-1], h1[:-1]
    asia = [c for c in m15c if a0 <= c["epoch"] < a1]
    if len(asia) < 20:
        return None                                   # plage incomplète (données manquantes)
    hi, lo = max(c["high"] for c in asia), min(c["low"] for c in asia)
    a_h1, a_m15 = atr(h1c), atr(m15c)
    if a_h1 <= 0 or a_m15 <= 0 or not (S2_RANGE_MIN_ATR * a_h1 <= hi - lo <= S2_RANGE_MAX_ATR * a_h1):
        return None
    funnel["S2_range"] += 1
    post = [(i, c) for i, c in enumerate(m15c) if c["epoch"] >= a1]
    first = next(((i, c) for i, c in post if c["close"] > hi or c["close"] < lo), None)
    if first is None or first[0] < len(m15c) - FRESH:
        return None                                   # seule la première cassure compte, et elle doit être récente
    i, tc = first
    d = "BUY" if tc["close"] > hi else "SELL"
    rng = tc["high"] - tc["low"]
    strong = rng > 0 and ((tc["close"] - tc["low"]) / rng >= S2_CLOSE_STRENGTH if d == "BUY"
                          else (tc["high"] - tc["close"]) / rng >= S2_CLOSE_STRENGTH)
    if not strong or body(tc) < DISP_MULT * body_avg(m15c[-21:-1]):
        return None
    bias = h4_ema_bias(h4)
    if S2_H4_FILTER and bias != (1 if d == "BUY" else -1):
        return None
    price = m15[-1]["close"]
    sl = (lo - BUF_ATR * a_m15) if d == "BUY" else (hi + BUF_ATR * a_m15)
    edge = hi if d == "BUY" else lo                 # retest du bord de plage cassé
    otype, entry = pick_entry(d, price, edge, sl, mode)
    if otype != d:
        if abs(price - entry) > LIMIT_MAX_ATR * a_m15:
            funnel["stale"] += 1
            return None
    elif is_late(d, price, tc["close"], a_m15):
        funnel["stale"] += 1
        return None
    lv = build_levels(d, entry, sl, a_m15, a_h1, S2_RISK_CAP_H1)
    if lv is None:
        return None
    funnel["S2_signal"] += 1
    return _signal(
        "S2", "Asian Breakout", d, entry, lv, m15, "M15", f"{a0}|{tc['epoch']}",
        [f"✅ Plage asiatique {lo:.{dec}f} - {hi:.{dec}f} ({(hi - lo) / a_h1:.1f} x ATR H1)",
         f"✅ Première cassure {'haussière' if d == 'BUY' else 'baissière'} avec clôture forte",
         "✅ Sens aligné avec l'EMA 50 du H4"],
        lines=[{"y": hi, "label": "Asie H", "kind": "range"}, {"y": lo, "label": "Asie B", "kind": "range"}],
        zones=[{"lo": lo, "hi": hi, "label": "Plage asiatique", "kind": "fib"}], inval=None,
        short=f"Plage Asie cassée par le {'haut' if d == 'BUY' else 'bas'}", trig=tc["epoch"], otype=otype,
        price_now=price, ttl=LIMIT_TTL["S2"] if otype != d else None,
        entry_note=f"Ordre limite au retest du bord de plage ({edge:.{dec}f})" if otype != d else "")


# ==========================================================================
# S3  Sweep + CHoCH (prise de liquidité, dans le sens du biais, sur une zone H1/H4, puis cassure de structure)
# ==========================================================================
S3_FRESH_LEVELS = True      # un niveau déjà pris (mèche au-delà depuis sa formation) n'est plus de la liquidité ; False = ancien comportement
S3_BIAS_FILTER = True       # trade seulement dans le sens du biais de structure (BOS) H4, sinon H1 si le H4 n'a pas de tendance claire
S3_HTF_ZONE = True          # le sweep doit toucher un bloc d'ordre / FVG H4 ou H1 non retesté, dans le sens du trade
S3_HTF_BARS = {"H4": 40, "H1": 72}   # profondeur de recherche des zones (bougies clôturées)
S3_HTF_TOL_ATR = 0.25       # tolérance de contact avec la zone, en ATR H1
S3_HTF_UNTOUCHED = True     # zone non retestée : aucune mèche n'est revenue dedans ; False = seulement non invalidée par une clôture
S3_LIQ_TARGETS = True       # TP2 / TP3 sur la liquidité opposée intacte (sinon 2 R / 3 R fixes)
S3_TP_MIN_R, S3_TP_MAX_R = 2.0, 6.0  # une liquidité opposée n'est retenue comme objectif qu'entre 2 R et 6 R
S3_TP_BUF_ATR = 0.1         # l'objectif est placé 0,1 ATR M15 avant le niveau (pour ne pas le rater d'un spread)


def liquidity_levels(h1c, d1, m15c, now, a_h1):
    """[(nom, prix, 'high'|'low', t0)] : PDH/PDL, extrêmes de la plage asiatique, equal highs/lows H1.
    t0 = epoch à partir duquel le niveau existe : une mèche au-delà depuis t0 l'a déjà « pris »."""
    out = []
    if d1 and len(d1) >= 3:
        t0 = d1[-1]["epoch"]                                   # ouverture (17h NY) du jour en cours
        out += [("PDH", d1[-2]["high"], "high", t0), ("PDL", d1[-2]["low"], "low", t0)]
    a0, a1 = asia_window(now)
    if now >= a1:
        asia = [c for c in m15c if a0 <= c["epoch"] < a1]
        if len(asia) >= 20:
            out += [("Asie H", max(c["high"] for c in asia), "high", a1), ("Asie B", min(c["low"] for c in asia), "low", a1)]
    for kind, nm in (("high", "EQH"), ("low", "EQL")):
        sw = swings(h1c, kind, 2)[-8:]
        for x in range(len(sw)):
            hit = next((y for y in range(x + 1, len(sw))
                        if abs(h1c[sw[x]][kind] - h1c[sw[y]][kind]) <= S3_EQ_TOL_ATR * a_h1), None)
            if hit is not None:
                a, b = h1c[sw[x]][kind], h1c[sw[hit]][kind]
                out.append((nm, max(a, b) if kind == "high" else min(a, b), kind, h1c[sw[hit]]["epoch"] + GRAN["H1"]))
    return out


def level_taken(m15c, px, kind, t0, upto=None):
    """Vrai si une mèche M15 a déjà dépassé le niveau depuis t0 (jusqu'à l'index `upto` exclu) : la liquidité a été prise."""
    for c in m15c[:len(m15c) if upto is None else upto]:
        if c["epoch"] >= t0 and ((c["high"] > px) if kind == "high" else (c["low"] < px)):
            return True
    return False


def s3_bias(h4, h1):
    """(sens, 'H4' | 'H1') : biais de structure (BOS, règles de trend.py) du H4, sinon du H1 si le H4 n'a pas de
    tendance claire ; (None, None) si aucun. h4 et h1 : bougies dont la dernière est en formation."""
    import trend as TR                   # import tardif : trend.py importe ce module
    for tf, cs in (("H4", h4), ("H1", h1)):
        info = TR.trend_info(cs, tf)
        if info:
            return info["dir"], tf
    return None, None


def htf_zones(cs, d, tf, before):
    """Zones d'intérêt du timeframe `tf` dans le sens d (achat = zones de demande), nées d'un déplacement qui casse la
    structure : bloc d'ordre (dernière bougie opposée avant le déplacement) et FVG. Seules les bougies entièrement
    clôturées avant l'epoch `before` comptent. Une zone est écartée si elle a été retestée (S3_HTF_UNTOUCHED) ou
    invalidée par une clôture. Retourne [{'kind', 'tf', 'lo', 'hi', 'epoch'}]."""
    g = GRAN[tf]
    cs = [c for c in cs if c["epoch"] + g <= before]
    out = []
    for j in range(max(21, len(cs) - S3_HTF_BARS[tf]), len(cs)):
        c = cs[j]
        avg = body_avg(cs[j - 20:j])
        if (c["close"] > c["open"]) != (d == "BUY") or avg <= 0 or body(c) < DISP_MULT * avg:
            continue
        prev = cs[max(0, j - 5):j]
        if (d == "BUY" and c["close"] <= max(x["high"] for x in prev)) or \
                (d == "SELL" and c["close"] >= min(x["low"] for x in prev)):
            continue                                            # le déplacement ne casse pas la structure récente
        found = []
        ob = ob_zone(cs, max(0, j - 6), j - 1, d)
        if ob:
            found.append(("OB", ob, j + 1))
        if j + 1 < len(cs):
            a, b = cs[j - 1], cs[j + 1]
            if d == "BUY" and a["high"] < b["low"]:
                found.append(("FVG", (a["high"], b["low"]), j + 2))
            elif d == "SELL" and a["low"] > b["high"]:
                found.append(("FVG", (b["high"], a["low"]), j + 2))
        for kind, (lo, hi), k in found:
            later = cs[k:]
            if S3_HTF_UNTOUCHED:
                dead = any((x["low"] <= hi) if d == "BUY" else (x["high"] >= lo) for x in later)
            else:
                dead = any((x["close"] < lo) if d == "BUY" else (x["close"] > hi) for x in later)
            if not dead:
                out.append({"kind": kind, "tf": tf, "lo": lo, "hi": hi, "epoch": c["epoch"]})
    return out


def htf_zone_hit(h4c, h1c, d, sweep_epoch, px, ext_px, a_h1):
    """Zone H4 (à défaut H1) que touche le sweep : l'étendue [niveau pris, mèche extrême] doit recouper la zone,
    élargie de S3_HTF_TOL_ATR x ATR H1. Bloc d'ordre avant FVG, puis le plus récent. None si aucune."""
    lo, hi = min(px, ext_px), max(px, ext_px)
    tol = S3_HTF_TOL_ATR * a_h1
    for tf, cs in (("H4", h4c), ("H1", h1c)):
        zs = [z for z in htf_zones(cs, d, tf, sweep_epoch) if z["lo"] - tol <= hi and z["hi"] + tol >= lo]
        if zs:
            zs.sort(key=lambda z: (z["kind"] != "OB", -z["epoch"]))
            return zs[0]
    return None


def liquidity_targets(levels, m15c, d, entry, risk, a_m15):
    """[(nom, prix cible, distance en R)] du plus proche au plus lointain : liquidité opposée encore intacte, située
    entre S3_TP_MIN_R et S3_TP_MAX_R du risque. L'objectif est placé S3_TP_BUF_ATR x ATR M15 avant le niveau."""
    sgn, want = (1, "high") if d == "BUY" else (-1, "low")
    out = []
    for name, px, kind, t0 in levels:
        r = (px - entry) * sgn / risk if risk > 0 else 0
        if kind == want and S3_TP_MIN_R <= r <= S3_TP_MAX_R and not level_taken(m15c, px, kind, t0):
            out.append((name, px - sgn * S3_TP_BUF_ATR * a_m15, r))
    return sorted(out, key=lambda x: x[2])


def s3_tps(d, entry, risk, targets):
    """([TP1, TP2, TP3], cible TP2 ou None, cible TP3 ou None). TP1 = 1 R. TP2 = première liquidité opposée, sinon 2 R.
    TP3 = liquidité suivante (au moins 3 R et au-delà de TP2), sinon 3 R (ou TP2 + 1 R si TP2 est plus loin)."""
    sgn = 1 if d == "BUY" else -1
    t2 = targets[0] if targets else None
    tp2 = t2[1] if t2 else entry + sgn * 2 * risk
    d2 = abs(tp2 - entry) / risk
    t3 = next((t for t in targets[1:] if t[2] >= 3.0 and t[2] > d2 + 0.5), None)
    tp3 = t3[1] if t3 else entry + sgn * max(3.0, d2 + 1.0) * risk
    return [entry + sgn * risk, tp2, tp3], t2, t3


def scan_s3(provide, now, funnel, dec=2, kz=True, mode="market"):
    d1, h4, h1, m15, m5 = (provide(x) for x in ("D1", "H4", "H1", "M15", "M5"))
    if not (h1 and m15 and m5 and h4):
        return None
    h4c, h1c, m15c, m5c = h4[:-1], h1[:-1], m15[:-1], m5[:-1]
    if len(h1c) < 40 or len(m15c) < 40 or len(m5c) < 60:
        return None
    a_h1, a_m15, a_m5 = atr(h1c), atr(m15c), atr(m5c)
    if min(a_h1, a_m15, a_m5) <= 0:
        return None
    levels = liquidity_levels(h1c, d1, m15c, now, a_h1)
    if not levels:
        return None
    funnel["S3_niveau"] += 1
    best = None
    for name, px, kind, t0 in levels:
        for i in range(max(0, len(m15c) - S3_SWEEP_BARS), len(m15c)):
            c = m15c[i]
            if S3_FRESH_LEVELS and c["epoch"] < t0:
                continue
            swept = (c["high"] > px and c["close"] < px) if kind == "high" else (c["low"] < px and c["close"] > px)
            if not swept:
                continue
            later = m15c[i + 1:]
            if any((x["close"] > px) if kind == "high" else (x["close"] < px) for x in later):
                continue                              # le niveau a été franchi pour de bon
            if S3_FRESH_LEVELS and level_taken(m15c, px, kind, t0, upto=i):
                continue                              # liquidité déjà prise avant cette bougie : plus de stops à balayer
            if best is None or c["epoch"] > best[0]["epoch"]:
                best = (c, name, px, kind)
    if best is None:
        return None
    funnel["S3_sweep"] += 1
    sc, name, px, kind = best
    d = "SELL" if kind == "high" else "BUY"
    bias, bias_tf = s3_bias(h4, h1)
    if S3_BIAS_FILTER and bias != d:
        return None                                   # contre le biais de structure (ou aucun biais clair)
    funnel["S3_biais"] += 1
    after = [(i, c) for i, c in enumerate(m5c) if c["epoch"] >= sc["epoch"]]
    if len(after) < 3:
        return None
    ext_i, ext = (max(after, key=lambda x: (x[1]["high"], x[0])) if d == "SELL"
                  else min(after, key=lambda x: (x[1]["low"], -x[0])))
    ext_px = ext["high"] if d == "SELL" else ext["low"]
    pk = "low" if d == "SELL" else "high"
    piv = [i for i in swings(m5c, pk, 2) if ext_i - S3_PIVOT_BARS <= i < ext_i]
    if not piv:
        return None
    pivot = m5c[piv[-1]][pk]
    avg = body_avg(m5c[-21:-1])
    trig = next((i for i in range(ext_i + 1, len(m5c))
                 if ((m5c[i]["close"] < pivot) if d == "SELL" else (m5c[i]["close"] > pivot))), None)
    if trig is None or trig < len(m5c) - FRESH:
        return None
    tc = m5c[trig]
    if body(tc) < DISP_MULT * avg:
        return None
    sess = session_name(tc["epoch"])
    if kz and sess not in S3_SESSIONS:
        return None
    zone = htf_zone_hit(h4c, h1c, d, sc["epoch"], px, ext_px, a_h1) if S3_HTF_ZONE else None
    if S3_HTF_ZONE and zone is None:
        return None                                   # le sweep n'a touché aucune zone d'intérêt H1/H4
    funnel["S3_zone"] += 1
    price = m5[-1]["close"]
    sl = ext_px + BUF_ATR * a_m15 if d == "SELL" else ext_px - BUF_ATR * a_m15
    poi = entry_zone(m5c, ext_i, trig - 1, d)
    otype, entry = pick_entry(d, price, poi[0] if poi else None, sl, mode)
    if otype != d:
        if abs(price - entry) > LIMIT_MAX_ATR * a_m5:
            funnel["stale"] += 1
            return None
    elif is_late(d, price, tc["close"], a_m5):
        funnel["stale"] += 1
        return None
    lv = build_levels(d, entry, sl, a_m5, a_h1, S3_RISK_CAP_H1)
    if lv is None:
        return None
    funnel["S3_signal"] += 1
    tp_lines, tp_src = [], "fixe"
    if S3_LIQ_TARGETS:
        t2, t3 = None, None
        lv["tp"], t2, t3 = s3_tps(d, entry, lv["risk"], liquidity_targets(levels, m15c, d, entry, lv["risk"], a_m15))
        for label, t, px_tp in (("TP2", t2, lv["tp"][1]), ("TP3", t3, lv["tp"][2])):
            if t:
                tp_lines.append(f"🎯 {label} sur la liquidité {t[0]} ({px_tp:.{dec}f}, {abs(px_tp - entry) / lv['risk']:.1f} R)")
        tp_src = "liquidité" if tp_lines else "fixe"
        if not tp_lines:
            tp_lines.append("🎯 Pas de liquidité opposée intacte à 2-6 R : TP2 / TP3 à 2 R / 3 R")
    else:
        opp = [(n, p) for n, p, k, _ in levels if (k == "low" if d == "SELL" else k == "high")
               and abs(p - entry) >= lv["risk"] and ((p < entry) if d == "SELL" else (p > entry))]
        opp.sort(key=lambda x: abs(x[1] - entry))
        if opp:
            tp_lines.append(f"Liquidité opposée  {opp[0][0]} {opp[0][1]:.{dec}f}")
    emab = h4_ema_bias(h4)
    aligned = emab == (-1 if d == "SELL" else 1)
    details = [f"✅ Liquidité prise : {name} {px:.{dec}f} (mèche {ext_px:.{dec}f})"]
    if zone:
        zname = "bloc d'ordre" if zone["kind"] == "OB" else "FVG"
        details.append(f"✅ Sweep sur {zname} {zone['tf']} ({zone['lo']:.{dec}f} - {zone['hi']:.{dec}f})")
    if bias == d:
        details.append(f"✅ Biais {bias_tf} {'haussier' if d == 'BUY' else 'baissier'} (structure)")
    elif bias is None:
        details.append("⚠️ Aucun biais de structure clair (H4 et H1)")
    else:
        details.append(f"⚠️ Contre le biais {bias_tf} (contre-tendance)")
    details += [f"✅ CHoCH M5 sous {pivot:.{dec}f}" if d == "SELL" else f"✅ CHoCH M5 au-dessus de {pivot:.{dec}f}",
                f"✅ Killzone {sess}"]
    if not S3_BIAS_FILTER:
        details.append("✅ Aligné avec l'EMA 50 du H4" if aligned else "⚠️ Contre l'EMA 50 du H4 (contre-tendance)")
    details += tp_lines
    zones = [{"lo": zone["lo"], "hi": zone["hi"], "label": f"{zone['kind']} {zone['tf']}",
              "kind": "ob" if zone["kind"] == "OB" else "fvg"}] if zone else []
    return _signal(
        "S3", "Sweep + CHoCH", d, entry, lv, m5, "M5", f"{sc['epoch']}|{tc['epoch']}", details,
        lines=[{"y": px, "label": name, "kind": "range"}, {"y": ext_px, "label": "Sweep", "kind": "sweep"},
               {"y": pivot, "label": "CHoCH", "kind": "info"}],
        zones=zones, inval=ext_px, session=sess,
        extra={"liq": name, "h4": "aligné" if aligned else "contre", "poi": poi[1] if otype != d else "marché",
               "biais": bias_tf if bias == d else ("contre" if bias else "aucun"),
               "zone": f"{zone['tf']} {zone['kind']}" if zone else "aucune", "tp": tp_src},
        short=f"{name} pris · CHoCH M5", trig=tc["epoch"], otype=otype, price_now=price,
        ttl=LIMIT_TTL["S3"] if otype != d else None,
        entry_note=poi_note(poi, "M5", dec) if otype != d else "")


# ==========================================================================
# S4  Mean Reversion (marché sans tendance)
# ==========================================================================
def scan_s4(provide, now, funnel, dec=2, kz=True, mode="market"):
    h1, m15 = provide("H1"), provide("M15")
    if not (h1 and m15):
        return None
    h1c, m15c = h1[:-1], m15[:-1]
    if len(h1c) < 70 or len(m15c) < 60:
        return None
    a = adx(h1c)
    closes_h1 = [c["close"] for c in h1c]
    e50 = ema(closes_h1, 50)
    a_h1, a_m15 = atr(h1c), atr(m15c)
    if a is None or e50[-1] is None or e50[-13] is None or a_h1 <= 0 or a_m15 <= 0:
        return None
    if a >= S4_ADX_MAX or abs(e50[-1] - e50[-13]) >= S4_FLAT_ATR * a_h1:
        return None
    funnel["S4_regime"] += 1
    k = len(m15c) - 1
    for i in range(k, k - FRESH, -1):                 # bougie de rejet : l'une des 2 dernières clôturées
        c = m15c[i]
        if kz and not in_hours(c["epoch"], S4_HOURS):
            continue
        closes = [x["close"] for x in m15c[:i + 1]]
        bb = bollinger(closes, i)
        rsis = rsi_series(closes, S4_RSI_N)
        if bb is None or rsis[-1] is None:
            continue
        lo_b, mid, up_b = bb
        recent_rsi = [r for r in rsis[-2:] if r is not None]
        if c["low"] < lo_b and c["close"] > lo_b and c["close"] > c["open"] and min(recent_rsi) <= S4_RSI_LOW:
            d = "BUY"
        elif c["high"] > up_b and c["close"] < up_b and c["close"] < c["open"] and max(recent_rsi) >= S4_RSI_HIGH:
            d = "SELL"
        else:
            continue
        price = m15[-1]["close"]
        ext = c["low"] if d == "BUY" else c["high"]
        sl = ext - S4_BUF_ATR * a_m15 if d == "BUY" else ext + S4_BUF_ATR * a_m15
        far = up_b if d == "BUY" else lo_b
        band = lo_b if d == "BUY" else up_b             # retest de la bande de Bollinger rejetée
        otype, entry = pick_entry(d, price, band, sl, mode)
        if otype != d:
            if abs(price - entry) > LIMIT_MAX_ATR * a_m15:
                funnel["stale"] += 1
                return None
        elif is_late(d, price, c["close"], a_m15):
            funnel["stale"] += 1
            return None
        lv = build_levels(d, entry, sl, a_m15, a_h1, S4_RISK_CAP_H1, tps=[mid, far, None])
        if lv is None:
            return None
        gain = lambda t: ((t - entry) if d == "BUY" else (entry - t)) / lv["risk"]
        if gain(mid) < S4_MIN_RR1 or gain(far) < S4_MIN_RR2:
            return None
        funnel["S4_signal"] += 1
        return _signal(
            "S4", "Mean Reversion", d, entry, lv, m15, "M15", f"{c['epoch']}",
            [f"✅ Range H1 (ADX {a:.0f}, EMA 50 plate)",
             f"✅ Rejet de la bande de Bollinger {'basse' if d == 'BUY' else 'haute'} (RSI {min(recent_rsi) if d == 'BUY' else max(recent_rsi):.0f})",
             f"✅ Heure favorable ({session_name(c['epoch'])})"],
            lines=[{"y": mid, "label": "Moyenne", "kind": "info"}, {"y": ext, "label": "Rejet", "kind": "sweep"}],
            zones=[{"lo": lo_b, "hi": up_b, "label": "Bollinger", "kind": "fib"}], inval=ext,
            short=f"Rejet Bollinger {'basse' if d == 'BUY' else 'haute'} · RSI {min(recent_rsi) if d == 'BUY' else max(recent_rsi):.0f}", trig=c["epoch"],
            otype=otype, price_now=price, ttl=LIMIT_TTL["S4"] if otype != d else None,
            entry_note=f"Ordre limite sur la bande de Bollinger ({band:.{dec}f})" if otype != d else "")
    return None


STRATEGIES = [("S1", scan_s1), ("S2", scan_s2), ("S3", scan_s3), ("S4", scan_s4)]


def scan_all(provide, now, funnel, only=None, dec=2, kz=True, modes=None):
    """Évalue les stratégies (toutes, ou celles de `only`) et renvoie les signaux trouvés.
    dec : décimales du prix de l'actif (affichage uniquement).
    modes : {"S1": "limit"|"market", ...} (défaut : marché).
    kz : False pour un actif 24/7 (cryptos) : S3 et S4 ne sont alors pas limitées aux heures de session."""
    out = []
    for name, fn in STRATEGIES:
        if only and name not in only:
            continue
        sig = fn(provide, now, funnel, dec, kz, (modes or {}).get(name, "market"))
        if sig:
            funnel["signal"] += 1
            out.append(sig)
    return out
