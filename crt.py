"""S4 CRT (Candle Range Theory) pur : le range d'une bougie de référence (C1) est balayé par la bougie suivante (C2), qui clôture à
l'intérieur de ce range ; on entre en M15 (ou M5, S4_CONFIRM_TF) sur la cassure de structure qui suit la clôture de C2, vers le milieu puis le bord opposé de C1.

  C1  bougie de référence H4 ou H1 (la dernière clôturée avant C2) : son range est la jambe de livraison.
  C2  bougie clôturée qui dépasse le plus haut (vente) ou le plus bas (achat) de C1 et clôture DANS le range de C1.
      Une bougie qui dépasse les deux côtés (englobante) ou qui clôture hors du range n'est pas un CRT.
  C3  la bougie en formation : la livraison se fait pendant C3, donc la confirmation (M15 ou M5) doit arriver avant sa clôture.
  Entrée : première clôture M15 (ou M5) au-delà du dernier swing de ce timeframe, après la clôture de C2 (CHoCH avec déplacement), ordre limite sur le
          bloc d'ordre ou le FVG de ce timeframe s'il y en a un. Stop : au-delà de l'extrême de C2. Objectifs : milieu de C1, bord opposé de C1,
          bord opposé + 50 % du range ; ratio minimal 1 pour 3 calculé sur TP2.

Les réglages (CRT_*) sont dans strategies.py. strategies importe ce module en fin de fichier : on n'importe donc strategies qu'à
l'appel (comme patterns.py), pas au chargement.
"""
from smc import is_displacement, close_beyond


def crt_pair(S, rc):
    """(sens, C1, C2, ATR) si les deux dernières bougies clôturées `rc` forment un CRT : C2 balaie UN côté de C1 et clôture dans
    son range, et le range de C1 est raisonnable (entre CRT_MIN_RANGE_ATR et CRT_MAX_RANGE_ATR x ATR). Sinon None."""
    if len(rc) < S.ATR_N + 3:
        return None
    c1, c2 = rc[-2], rc[-1]
    a = S.atr(rc)
    rng = c1["high"] - c1["low"]
    if a <= 0 or not (S.CRT_MIN_RANGE_ATR * a <= rng <= S.CRT_MAX_RANGE_ATR * a):
        return None
    up, dn = c2["high"] > c1["high"], c2["low"] < c1["low"]
    if up == dn:                                         # aucun sweep, ou bougie englobante (les deux côtés)
        return None
    if not (c1["low"] < c2["close"] < c1["high"]):       # C2 doit clôturer dans le range de C1
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
    pair = crt_pair(S, ref[:-1])
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
    if kz and sess not in S.CRT_SESSIONS:
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
        if abs(price - entry) > S.LIMIT_MAX_ATR * a_m15:
            funnel["stale"] += 1
            return None
    elif S.is_late(d, price, tc["close"], a_m15):
        funnel["stale"] += 1
        return None
    tp1 = mid
    tp2 = hi1 if d == "BUY" else lo1
    tp3 = tp2 + sgn * S.CRT_TP3_EXT * rng
    if sgn * (tp1 - entry) <= 0:                         # le milieu de C1 est déjà atteint : la livraison a eu lieu
        funnel["stale"] += 1
        return None
    lv = S.build_levels(d, entry, sl, a_m15, a_h1, S.CRT_RISK_CAP_H1, tps=[tp1, tp2, tp3])
    if lv is None:
        return None
    if abs(tp2 - entry) / lv["risk"] < S.CRT_MIN_RR:
        funnel["CRT_rr"] += 1
        return None
    funnel["CRT_signal"] += 1
    side_hi = d == "SELL"
    details = [f"✅ CRT {tf} : C2 a balayé le {'plus haut' if side_hi else 'plus bas'} de C1 ({hi1 if side_hi else lo1:.{dec}f}, "
               f"mèche {ext_px:.{dec}f}) et clôturé dans son range",
               f"✅ Range C1 {lo1:.{dec}f} - {hi1:.{dec}f} ({rng / a_ref:.1f} ATR {tf})",
               f"✅ CHoCH {cf_n} {'sous' if side_hi else 'au-dessus de'} {pivot:.{dec}f} après la clôture de C2"]
    if kz:
        details.append(f"✅ Killzone {sess}")
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
        entry_note=S.poi_note(poi, cf_n, dec) if otype != d else "",
        rr_rule=[(2, S.CRT_MIN_RR)])


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
    out = []
    for tf in S.CRT_REFS:
        ref = provide(tf)
        if not ref:
            continue
        sig = _crt_one(S, tf, ref, m15, m15c, a_m15, a_h1, funnel, dec, kz, mode, cf_n)
        if sig:
            out.append(sig)
    return out
