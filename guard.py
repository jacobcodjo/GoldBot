"""Garde-fous du bot (or, paires majeures, BTC et ETH) : fenêtres sans alerte (news, rollover, week-end),
un seul trade actif par actif, stratégie et sens, exposition corrélée par devise, surveillance du bot, entonnoir de filtres et bilan hebdomadaire.
Autonome : aucun import de bot.py (les fonctions d'envoi sont passées en argument)."""
import json, math, os, re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import tracker as T

NY = ZoneInfo("America/New_York")
GUARD_FILE = "guard.json"
NEWS_FILE = "news.json"

# --- Limites de risque ---
GROUP_LIMIT = 2            # exposition nette maximale par devise (USD, EUR, JPY…) et par groupe crypto, même sens
# --- Fenêtres sans alerte (forex et or) ---
ROLLOVER = (16 * 60 + 55, 17 * 60 + 15)     # minutes NY : élargissement des spreads
FRIDAY_CLOSE_FROM = 15 * 60 + 30            # vendredi : trop proche de la fermeture hebdomadaire
SUNDAY_OPEN = (17 * 60, 18 * 60)            # dimanche : ouverture de semaine (gap)
NFP = (8 * 60, 9 * 60 + 30)                 # premier vendredi du mois, publication à 8h30 NY
# --- Calendrier économique automatique (flux gratuit Forex Factory / Fair Economy) ---
CALENDAR_URLS = [u for u in (
    os.getenv("CALENDAR_URL"),                                   # pour forcer une autre source
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
) if u]
CALENDAR_REFRESH = 6 * 3600     # le flux n'est interrogé qu'une fois toutes les 6 h
CALENDAR_RETRY = 900            # nouvel essai après 15 min en cas d'échec
CALENDAR_ALERT_AFTER = 6 * 3600  # alerte Telegram si le flux reste indisponible plus de 6 h
CALENDAR_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"}
NEWS_BEFORE_MIN = 15            # pas d'alerte 15 min avant un événement à fort impact
NEWS_AFTER_MIN = 45             # ... ni 45 min après
BIG_AFTER_MIN = 90              # 90 min après une décision de taux ou une conférence de presse
BIG_EVENT = re.compile(r"rate|fomc|press conference|monetary policy|statement|minutes", re.I)
# Décisions de taux de la Fed 2026 (14h ET, conférence de presse à 14h30). Source : calendrier officiel de la Fed.
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
# --- Surveillance ---
GAP_ALERT_MIN = 30         # alerte si le bot reprend après plus de 30 min sans scan
FAILS_ALERT = 3            # alerte après 3 scans de suite sans aucune donnée Deriv
REPORT_EVERY = 7 * 86400   # bilan envoyé une fois par semaine

FUNNEL_ORDER = ["data", "S1_tendance", "S1_repli", "S1_signal", "S2_range", "S2_signal", "S3_niveau", "S3_sweep",
                "S3_biais", "S3_zone", "S3_signal", "S4_regime", "S4_signal", "S5_regime", "S5_tendance", "S5_impulsion", "S5_signal", "signal", "vol", "stale", "obst_entree", "obst_cible", "blackout", "dedupe", "risk", "alert"]
FUNNEL_LABEL = {"data": "données", "S1_tendance": "Trend Pullback : tendance H4", "S1_repli": "repli H1", "S1_signal": "signal Trend Pullback",
                "S2_range": "Asian Breakout : plage", "S2_signal": "signal Asian Breakout", "S3_niveau": "Sweep + CHoCH : niveaux",
                "S3_sweep": "sweep (niveau intact)", "S3_biais": "sens du biais H4/H1", "S3_zone": "sur zone H1/H4", "S3_signal": "signal Sweep + CHoCH", "S4_regime": "Mean Reversion : range H1", "S4_signal": "signal Mean Reversion",
                "S5_regime": "Impulsion : volatilité normale", "S5_tendance": "tendance HTF (naissante/établie)", "S5_impulsion": "impulsion + Fibonacci", "S5_signal": "signal Impulsion",
                "signal": "signaux valides", "vol": "écartés (volatilité faible)", "stale": "écartés (entrée tardive)", "obst_entree": "écartés (hors niveau H4/H1)", "obst_cible": "écartés (obstacle avant l'objectif)", "blackout": "bloqués (news/horaire)",
                "dedupe": "doublons", "risk": "bloqués (risque)", "alert": "alertes"}


def load_guard(path=GUARD_FILE):
    try:
        with open(path) as f:
            g = json.load(f)
    except Exception:
        g = {}
    g.setdefault("health", {})
    g.setdefault("funnel", {})
    g.setdefault("last_report", 0)
    return g


def save_guard(g, path=GUARD_FILE):
    with open(path, "w") as f:
        json.dump(g, f)


# --------------------------------------------------------------------------
# Fenêtres sans alerte : rollover, week-end, NFP, calendrier perso (news.json)
# --------------------------------------------------------------------------
def load_news(path=NEWS_FILE):
    """news.json : [{"start": "2026-10-28T18:00:00Z", "end": "2026-10-28T19:30:00Z",
    "note": "FOMC", "currencies": ["USD"]}] ; 'currencies' est facultatif (sinon tous les actifs réels)."""
    try:
        with open(path) as f:
            out = []
            for n in json.load(f):
                p = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
                out.append({"start": p(n["start"]), "end": p(n["end"]),
                            "note": n.get("note", "news"),
                            "cur": [c.upper() for c in n.get("currencies", [])]})
            return out
    except Exception:
        return []


def fomc_events():
    """Fenêtres FOMC intégrées : de 13h45 à 16h00 New York les jours de décision."""
    out = []
    for d in FOMC_2026:
        day = datetime.fromisoformat(d)
        t = lambda h, m: day.replace(hour=h, minute=m, tzinfo=NY).timestamp()
        out.append({"start": t(13, 45), "end": t(16, 0), "note": "FOMC", "cur": ["USD"]})
    return out


def fomc_check(g, now, notify):
    """Prévient (au plus tous les 14 jours) quand il reste moins de 30 jours de dates FOMC dans le code."""
    last = max(datetime.fromisoformat(d).replace(hour=16, tzinfo=NY).timestamp() for d in FOMC_2026)
    if last - now > 30 * 86400 or now - g.get("fomc_warned", 0) < 14 * 86400:
        return
    g["fomc_warned"] = int(now)
    if last < now:
        notify("⚠️ Plus aucune date FOMC dans guard.py (FOMC_2026). Ajoute les décisions de l'année à venir. "
               "Le calendrier automatique reste actif, mais ce filet de sécurité est vide.")
    else:
        notify(f"⚠️ La dernière date FOMC de guard.py (FOMC_2026) est le {max(FOMC_2026)}. "
               f"Ajoute bientôt les décisions de l'année suivante.")


def _parse_calendar(data):
    """Événements à fort impact des 8 grandes devises -> fenêtres sans alerte."""
    out = []
    for it in data if isinstance(data, list) else []:
        try:
            cur = str(it.get("country", "")).upper()
            if str(it.get("impact", "")).lower() != "high" or cur not in CALENDAR_CURRENCIES:
                continue
            ts = datetime.fromisoformat(str(it["date"]).replace("Z", "+00:00")).timestamp()
            title = str(it.get("title", "événement"))
            after = BIG_AFTER_MIN if BIG_EVENT.search(title) else NEWS_AFTER_MIN
            out.append({"start": ts - NEWS_BEFORE_MIN * 60, "end": ts + after * 60,
                        "note": f"{cur} {title}", "cur": [cur]})
        except Exception:
            continue
    return out


def calendar_events(g, now, http_get=None, notify=None):
    """Fenêtres sans alerte issues du calendrier automatique + des décisions FOMC intégrées.
    Le flux est rafraîchi toutes les 6 h ; en cas d'échec, les dernières données restent utilisées."""
    cal = g.setdefault("calendar", {"fetched": 0, "events": []})
    if now - cal["fetched"] >= CALENDAR_REFRESH:
        events, ok = [], False
        for url in CALENDAR_URLS:
            try:
                if http_get is None:
                    import requests
                    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; gold-bot/1.0)"})
                    r.raise_for_status()
                    data = r.json()
                else:
                    data = http_get(url)
                events += _parse_calendar(data)
                ok = True
            except Exception as e:
                print(f"Calendrier indisponible ({url.rsplit('/', 1)[-1]}) : {str(e)[:80]}")
        if ok:
            cal["events"], cal["fetched"] = events, int(now)
            print(f"Calendrier mis à jour : {len(events)} événement(s) à fort impact.")
            if cal.get("alerted") and notify:
                notify("✅ Calendrier économique de nouveau disponible : les annonces bloquent à nouveau les alertes.")
            cal["fail_since"], cal["alerted"] = 0, False
        else:
            cal["fetched"] = int(now) - CALENDAR_REFRESH + CALENDAR_RETRY
            cal["fail_since"] = cal.get("fail_since") or int(now)
            if notify and not cal.get("alerted") and now - cal["fail_since"] >= CALENDAR_ALERT_AFTER:
                cal["alerted"] = True
                notify(f"⚠️ Calendrier économique indisponible depuis {(now - cal['fail_since']) / 3600:.0f} h : "
                       "les annonces à venir ne bloquent plus les alertes (seules les décisions FOMC intégrées et "
                       "news.json restent actives). Vérifie le flux ou ajoute les annonces dans news.json.")
    upcoming = [e for e in cal["events"] if e["end"] >= now - 3600]
    return upcoming + fomc_events()


WEEKEND_EXIT_FROM = 16 * 60 + 30     # vendredi 16h30 New York : les trades forex/or encore ouverts sont clôturés


SYNTH_PREFIXES = ("R_", "1HZ")   # indices synthétiques Deriv : R_100, 1HZ100V...


def is_synthetic(sym):
    """Indice synthétique Deriv (Volatility) : prix aléatoire, 24h/24 et 7j/7, insensible aux news."""
    return sym.startswith(SYNTH_PREFIXES)


def weekend_exit_due(sym, now):
    """Vrai si un trade ouvert sur cet actif doit être clôturé avant (ou pendant) la fermeture du week-end.
    Cryptos (24/7) : jamais. Désactivable avec WEEKEND_EXIT=0."""
    if not sym.startswith("frx") or os.getenv("WEEKEND_EXIT", "1") == "0":
        return False
    dt = datetime.fromtimestamp(now, NY)
    mins, wd = dt.hour * 60 + dt.minute, dt.weekday()
    return (wd == 4 and mins >= WEEKEND_EXIT_FROM) or wd == 5 or (wd == 6 and mins < SUNDAY_OPEN[0])


def blackout(sym, now, news=()):
    """Motif de blocage si l'alerte tombe dans une fenêtre à éviter, sinon None."""
    if is_synthetic(sym):
        return None                    # indices synthétiques : ni news, ni rollover, ni fermeture hebdomadaire
    for n in news:
        if n["start"] <= now <= n["end"] and (not n["cur"] or any(c in sym.upper() for c in n["cur"])):
            return f"news : {n['note']}"
    if not sym.startswith("frx"):
        return None                    # cryptos : marché 24/7, pas de rollover ni de fermeture hebdomadaire
    dt = datetime.fromtimestamp(now, NY)
    mins, wd = dt.hour * 60 + dt.minute, dt.weekday()
    if ROLLOVER[0] <= mins < ROLLOVER[1]:
        return "rollover 17h NY"
    if wd == 5 or (wd == 6 and mins < SUNDAY_OPEN[0]):
        return "marché fermé (week-end)"
    if wd == 4 and mins >= FRIDAY_CLOSE_FROM:
        return "fermeture hebdomadaire proche"
    if wd == 6 and SUNDAY_OPEN[0] <= mins < SUNDAY_OPEN[1]:
        return "ouverture de semaine"
    if wd == 4 and dt.day <= 7 and NFP[0] <= mins < NFP[1]:
        return "NFP"
    return None


# --------------------------------------------------------------------------
# Doublons et exposition corrélée
# --------------------------------------------------------------------------
FIAT = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD")


def ccy_signs(sym, d):
    """{devise: +1 (long) | -1 (short)} d'un trade forex ou or. EURJPY acheté = long EUR, short JPY ; l'or (XAUUSD)
    est coté en USD : acheter l'or revient à vendre l'USD (l'or lui-même n'est pas une devise suivie)."""
    s = sym.upper()
    if not (s.startswith("FRX") and len(s) >= 9):
        return {}
    base, quote = s[3:6], s[6:9]
    buy = 1 if d == "BUY" else -1
    out = {}
    if base in FIAT:
        out[base] = buy
    if quote in FIAT:
        out[quote] = -buy
    return out


def usd_sign(sym, d):
    """+1 si le trade équivaut à être long USD, -1 s'il équivaut à être short USD, 0 sinon."""
    return ccy_signs(sym, d).get("USD", 0)


def crypto_sign(sym, d):
    """+1 pour un achat de crypto, -1 pour une vente, 0 pour un autre actif (BTC et ETH évoluent ensemble)."""
    return (1 if d == "BUY" else -1) if sym.startswith("cry") else 0


def risk_check(tr, sym, d, now, strat=None):
    """Retourne (ok, motif). Contrôle : doublon (même actif, stratégie et sens),
    exposition nette par devise et groupe crypto. Aucune limite sur le nombre total de trades ouverts. Aucun blocage lié aux pertes de la journée ou de la semaine."""
    act = T.active_list(tr)
    if any(t["sym"] == sym and t["dir"] == d and t.get("cascade") == strat for t in act):
        return False, "dedupe"
    signs = ccy_signs(sym, d)
    for ccy in sorted(signs, key=lambda c: c != "USD"):          # l'USD d'abord, puis les autres devises du trade
        net = sum(ccy_signs(t["sym"], t["dir"]).get(ccy, 0) for t in act)
        if net * signs[ccy] >= GROUP_LIMIT:
            return False, f"exposition {ccy} (même sens) au maximum"
    csign = crypto_sign(sym, d)
    cnet = sum(crypto_sign(t["sym"], t["dir"]) for t in act)
    if csign and cnet * csign >= GROUP_LIMIT:
        return False, "exposition crypto (même sens) au maximum"
    return True, ""


# --------------------------------------------------------------------------
# Surveillance du bot
# --------------------------------------------------------------------------
def health_start(g, bot, now, notify):
    h = g["health"].setdefault(bot, {"last_ok": 0, "fails": 0, "alerted": False})
    if h["last_ok"] and now - h["last_ok"] > GAP_ALERT_MIN * 60:
        notify(f"⚠️ {bot} : scan interrompu pendant {(now - h['last_ok']) / 3600:.1f} h, il reprend. "
               f"Les setups apparus pendant la coupure ont pu être manqués.")
    return h


def health_end(g, bot, got_data, now, notify):
    """got_data : au moins un symbole a renvoyé des bougies pendant ce scan."""
    h = g["health"].setdefault(bot, {"last_ok": 0, "fails": 0, "alerted": False})
    if got_data:
        if h["alerted"]:
            notify(f"✅ {bot} : les données Deriv sont de nouveau accessibles.")
        h.update(last_ok=int(now), fails=0, alerted=False)
    else:
        h["fails"] += 1
        if h["fails"] >= FAILS_ALERT and not h["alerted"]:
            notify(f"⚠️ {bot} : aucune donnée Deriv sur {h['fails']} scans de suite. "
                   f"Vérifie l'API Deriv ou le workflow.")
            h["alerted"] = True


# --------------------------------------------------------------------------
# Entonnoir de filtres et bilan
# --------------------------------------------------------------------------
def funnel_add(g, bot, counts):
    acc = g["funnel"].setdefault(bot, {})
    for k, v in counts.items():
        acc[k] = acc.get(k, 0) + v


def funnel_text(counts):
    parts = [f"{FUNNEL_LABEL[k]} {counts[k]}" for k in FUNNEL_ORDER if counts.get(k)]
    return " → ".join(parts) if parts else "aucune donnée"


def report_due(g, now):
    return now - g["last_report"] >= REPORT_EVERY


def _short(label, s):
    return f"· {label} : {s['n']} tr. · {s['win']:.0f} % · {s['total']:+.1f} R"


REPORT_VALID_TRADES = 100
REPORT_FILTERS = (("stale", "tardifs"), ("obst_entree", "hors niveau H4/H1"), ("obst_cible", "obstacle devant l'objectif"), ("vol", "volatilité faible"), ("blackout", "news/horaire"),
                  ("dedupe", "doublons"), ("risk", "risque"))


def build_report(g, tr, now):
    """Bilan hebdomadaire condensé : total 7 j, 30 j (une ligne si identique), par stratégie, par actif, filtres."""
    def window(days):
        return [t for t in tr["closed"] if t.get("t_close", 0) >= now - days * 86400 and t.get("r") is not None]
    t7, t30 = window(7), window(30)
    s7, s30 = T.summarize(t7), T.summarize(t30)
    lines = ["📊 Bilan hebdomadaire", T.fmt_summary("7 j", s7) if s7 else "7 j : aucun trade clôturé"]
    if s30:
        lines.append("30 j : identique" if s30 == s7 else T.fmt_summary("30 j", s30))
    if t7:
        lines.append("Par stratégie (7 j) :")
        strats = sorted({t.get("cascade") for t in t7 if t.get("cascade")},
                        key=lambda v: -sum(t["r"] for t in t7 if t.get("cascade") == v))
        for val in strats:
            lines.append(_short(val, T.summarize([t for t in t7 if t.get("cascade") == val])))
        names = sorted({t["name"] for t in t7 if t.get("name")},
                       key=lambda n: -sum(t["r"] for t in t7 if t.get("name") == n))
        if len(names) > 1:
            parts = [f"{n} {sum(t['r'] for t in t7 if t.get('name') == n):+.1f} R "
                     f"({sum(1 for t in t7 if t.get('name') == n)})" for n in names[:6]]
            lines.append("Par actif : " + " · ".join(parts) + (f" · +{len(names) - 6} autres" if len(names) > 6 else ""))
        own = [t for t in t7 if t.get("own_r") is not None]
        if own:
            lines.append(f"Mes résultats réels : {len(own)} trades · {sum(t['own_r'] for t in own):+.1f} R "
                         f"(simulé : {sum(t['r'] for t in own):+.1f} R)")
    counts = Counter()
    for c in g["funnel"].values():
        counts.update(c)
    lines.append(f"Trades actifs : {len(T.active_list(tr))} · alertes : {counts.get('alert', 0)}")
    n_all = sum(1 for t in tr["closed"] if t.get("r") is not None)
    if n_all < REPORT_VALID_TRADES:
        lines.append(f"Validation : {n_all} trades clôturés sur ~{REPORT_VALID_TRADES} pour juger (en dessous, tout reste du bruit).")
    flt = [f"{label} {counts[k]}" for k, label in REPORT_FILTERS if counts.get(k)]
    if flt:
        lines.append("Écartés (passages de scan) : " + " · ".join(flt))
    return "\n".join(lines)


def report_sent(g, now):
    g["last_report"] = int(now)
    g["funnel"] = {}
