"""Filtre d'actualité économique : aucune alerte autour des publications à fort impact des devises de l'actif.

Trois sources, fusionnées :
  1. NFP (emploi américain) : premier vendredi du mois à 8h30 New York. Règle fixe, valable aussi pour le backtest.
  2. Variable NEWS_EVENTS : événements ajoutés à la main, séparés par « ; », au format « ISO@DEVISE@titre »
     (ex. 2026-12-16T19:00:00Z@USD@FOMC ; l'heure sans fuseau est lue en heure de New York).
  3. Calendrier hebdomadaire public de Forex Factory (impact « High »), téléchargé au plus une fois toutes les 6 h et gardé dans
     cache.json. Si le téléchargement échoue, le filtre continue avec les sources 1 et 2 (jamais de blocage faute de réseau).

Fenêtre : NEWS_BEFORE_MIN minutes avant (30) jusqu'à NEWS_AFTER_MIN minutes après (15). NEWS_FILTER=0 désactive le filtre."""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FEED_TTL = 6 * 3600


def _num(name, default):
    try:
        v = (os.getenv(name) or "").strip()
        return float(v) if v else default
    except ValueError:
        return default


def enabled():
    return (os.getenv("NEWS_FILTER") or "1").strip().lower() not in ("0", "false", "non", "off", "no")


BEFORE_MIN = _num("NEWS_BEFORE_MIN", 30.0)
AFTER_MIN = _num("NEWS_AFTER_MIN", 15.0)

_FETCHED = []        # événements du calendrier public (alimentés par load_feed)


def _to_epoch(text, default_tz=NY):
    """Epoch d'une date ISO (avec « Z » ou décalage) ; sans fuseau : heure de New York. None si illisible."""
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return int(dt.timestamp())


def nfp_events(now):
    """NFP des mois voisins de `now` : premier vendredi, 8h30 New York, devise USD."""
    out = []
    base = datetime.fromtimestamp(now, NY).replace(day=1, hour=8, minute=30, second=0, microsecond=0)
    for shift in (-1, 0, 1):
        m = base.month - 1 + shift
        first = base.replace(year=base.year + m // 12, month=m % 12 + 1)
        friday = first + timedelta(days=(4 - first.weekday()) % 7)
        out.append({"t": int(friday.timestamp()), "ccy": "USD", "title": "NFP"})
    return out


def parse_env(text):
    """NEWS_EVENTS : « ISO@DEVISE@titre ; ... ». Les entrées illisibles sont ignorées."""
    out = []
    for part in (text or "").split(";"):
        bits = [b.strip() for b in part.split("@")]
        if len(bits) < 2 or not bits[0] or not bits[1]:
            continue
        t = _to_epoch(bits[0])
        if t is not None:
            out.append({"t": t, "ccy": bits[1].upper(), "title": bits[2] if len(bits) > 2 else "événement"})
    return out


def parse_feed(items):
    """Événements « High » du calendrier public : {title, country, date, impact}."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or str(it.get("impact", "")).lower() != "high":
            continue
        t = _to_epoch(str(it.get("date", "")))
        if t is not None and it.get("country"):
            out.append({"t": t, "ccy": str(it["country"]).upper(), "title": str(it.get("title", "événement"))})
    return out


def load_feed(cache, now, fetch=None):
    """Met à jour le calendrier public (au plus toutes les 6 h) et le range dans `cache['news']`. `fetch` : fonction sans argument
    qui renvoie la liste JSON (remplaçable en test). Retourne le nombre d'événements connus ; ne lève jamais d'exception."""
    global _FETCHED
    saved = cache.get("news") or {}
    if now - saved.get("t", 0) >= FEED_TTL:
        try:
            if fetch is None:
                req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0 (gold-bot)"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    items = json.loads(r.read().decode("utf-8"))
            else:
                items = fetch()
            events = parse_feed(items)
            saved = {"t": int(now), "events": events}
            cache["news"] = saved
        except Exception as ex:                      # réseau absent, format changé : on garde l'ancien calendrier
            print(f"Calendrier économique indisponible : {str(ex)[:80]}")
            if saved:
                saved = dict(saved, t=int(now) - FEED_TTL + 900)   # nouvel essai dans 15 minutes
                cache["news"] = saved
    _FETCHED = list(saved.get("events") or [])
    return len(_FETCHED)


def events(now):
    return nfp_events(now) + parse_env(os.getenv("NEWS_EVENTS")) + _FETCHED


def currencies(sym):
    """Devises sensibles à l'actualité : les deux devises d'une paire ; USD pour l'or et les cryptos ; rien pour les synthétiques."""
    if sym == "frxXAUUSD" or sym.startswith("cry"):
        return {"USD"}
    if sym.startswith("frx") and len(sym) == 9:
        return {sym[3:6], sym[6:9]}
    return set()


def blackout(sym, now):
    """Motif (texte) si `now` est dans la fenêtre d'une publication à fort impact d'une devise de l'actif, sinon None."""
    if not enabled():
        return None
    ccys = currencies(sym)
    if not ccys:
        return None
    for ev in events(now):
        if ev["ccy"] in ccys and ev["t"] - BEFORE_MIN * 60 <= now <= ev["t"] + AFTER_MIN * 60:
            hh = datetime.fromtimestamp(ev["t"], NY).strftime("%Hh%M")
            return f"actualité {ev['ccy']} {ev['title']} à {hh} New York"
    return None
