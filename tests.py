"""Tests automatisés : python -m unittest tests -v

Aucun accès réseau : les données viennent d'une marche aléatoire (backtest.gen_sim) ou de séries construites.
Ces tests vérifient la mécanique du bot (indicateurs, tendance, suivi des trades, garde-fous, messages,
backtest), pas la rentabilité des stratégies.
"""
import glob, os, re
os.environ.setdefault("INTRADAY", "0")      # les tests historiques décrivent l'ancien comportement ; le cadre intraday a ses propres tests
import random
import unittest
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import backtest as B
import gold
import guard as G
import strategies as S
import tracker as T
import trend as TR

NY = ZoneInfo("America/New_York")


def ts(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=NY).timestamp()


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp()


def zigzag(legs, step=10.0, n=6, up=True):
    """Série H1 : `legs`+2 montées de 2 x step suivies d'un repli de step, plus une bougie en formation."""
    cs, t, price = [], 1_700_000_000, 1000.0

    def add(o, c):
        nonlocal t
        w = 0.3 + 0.01 * len(cs) % 0.2 + (0.6 if len(cs) % 12 in (n - 1, n) else 0)   # pas d'égalités exactes
        cs.append({"epoch": t, "open": o, "high": max(o, c) + w, "low": min(o, c) - w, "close": c})
        t += 3600
    for _ in range(legs + 2):
        a, b = price, price + 2 * step
        for i in range(n):
            add(a + (b - a) * i / n, a + (b - a) * (i + 1) / n)
        for i in range(n):
            add(b - step * i / n, b - step * (i + 1) / n)
        price += step
    last = cs[-1]["close"]
    cs.append({"epoch": t, "open": last, "high": last + 1, "low": last - 1, "close": last})
    if not up:
        cs = [{"epoch": c["epoch"], "open": 3000 - c["open"], "high": 3000 - c["low"], "low": 3000 - c["high"],
               "close": 3000 - c["close"]} for c in cs]
    return cs


def candle(epoch, o, h, l, c):
    return {"epoch": epoch, "open": o, "high": h, "low": l, "close": c}


def new_buy(entry=100.0, sl=99.0, tp=(101.0, 102.0, 103.0), now=1000):
    return T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", "BUY", "BUY", entry, sl, tp[0], tp[1], tp[2],
                       "M5", 300, 2, "Test", now, 3600)


class Indicateurs(unittest.TestCase):
    def test_ema_rsi_adx(self):
        cs = [{"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i} for i in range(80)]
        closes = [c["close"] for c in cs]
        self.assertIsNone(S.ema(closes, 10)[8])
        self.assertAlmostEqual(S.ema(closes, 10)[9], sum(closes[:10]) / 10)
        self.assertEqual(S.rsi_series(closes)[-1], 100.0)
        self.assertGreater(S.adx(cs), 90)
        self.assertIsNone(S.adx(cs[:20]))

    def test_swings_strict(self):
        cs = [candle(i, 10, 10 + (3 if i == 5 else 1) + 0.01 * i, 9, 10) for i in range(11)]
        self.assertEqual(S.swings(cs, "high", 2), [5])

    def test_volatilite(self):
        calm = [candle(i, 100, 100.5 + 0.001 * (i % 5), 99.5, 100) for i in range(300)]
        self.assertAlmostEqual(S.vol_ratio(calm), 1.0, delta=0.1)
        dead = calm[:-20] + [candle(300 + i, 100, 100.05, 99.95, 100) for i in range(20)]
        self.assertLess(S.vol_ratio(dead), S.VOL_MIN_RATIO)


class Tendance(unittest.TestCase):
    def test_age_par_nombre_de_jambes(self):
        for legs, age in ((1, "naissante"), (2, "établie"), (3, "établie"), (5, "mûre")):
            info = TR.trend_info(zigzag(legs))
            self.assertEqual((info["dir"], info["legs"], info["age"]), ("BUY", legs, age))

    def test_baissier_et_plat(self):
        info = TR.trend_info(zigzag(4, up=False))
        self.assertEqual((info["dir"], info["age"]), ("SELL", "mûre"))
        flat = [candle(k, 100, 100.5 + 0.01 * (k % 7), 99.5 - 0.01 * (k % 5), 100) for k in range(60)]
        self.assertIsNone(TR.trend_info(flat))

    def test_structure_cassee(self):
        cs = zigzag(3)
        cs[-2] = dict(cs[-2], close=900.0, low=899.0)       # clôture sous le dernier creux
        self.assertIsNone(TR.trend_info(cs))

    def test_messages(self):
        info = TR.trend_info(zigzag(3))
        lines, extra = TR.alert_lines("BUY", {"D1": info, "H4": None}, info["start_epoch"] + 86400 * 3)
        self.assertIn("✅ Tendance D1 haussière", lines[0])
        self.assertIn("pas de tendance claire", lines[1])
        self.assertEqual(extra["tend_h4"], "aucune")
        self.assertIn("contre le trade", TR.alert_lines("SELL", {"D1": info, "H4": info}, 1_700_100_000)[0][0])


class Suivi(unittest.TestCase):
    def test_tp1_puis_stop_a_l_entree(self):
        t = new_buy()
        T.advance(t, [candle(1200, 100, 101.2, 99.8, 101), candle(1500, 101, 101.1, 99.9, 100)], 2000)
        self.assertEqual((t["status"], t["result"]), ("closed", "TP1+BE"))
        self.assertAlmostEqual(t["r"], 0.5)

    def test_stop_simple(self):
        t = new_buy()
        T.advance(t, [candle(1200, 100, 100.2, 98.9, 99)], 2000)
        self.assertEqual((t["result"], t["r"]), ("SL", -1.0))

    def test_gap_a_travers_le_stop(self):
        t = new_buy()
        T.advance(t, [candle(1200, 98.0, 98.5, 97.5, 98.0)], 2000)       # ouvre 2 sous le stop
        self.assertEqual(t["result"], "SL")
        self.assertAlmostEqual(t["r"], -2.0)

    def test_cloture_forcee(self):
        t = new_buy()
        self.assertEqual(T.force_close(t, 100.5, "weekend", 2000), "weekend")
        self.assertAlmostEqual(t["r"], 0.5)
        self.assertIsNone(T.force_close(t, 100.5, "weekend", 2000))      # déjà clôturé

    def test_cout_du_spread_une_seule_fois(self):
        t = new_buy()
        T.advance(t, [candle(1200, 100, 100.2, 98.9, 99)], 2000)
        gold.apply_cost(t, 0.1)                                          # 0,1 % de 100 = 0,1 ; risque 1 -> 0,1 R
        self.assertAlmostEqual(t["r"], -1.1)
        gold.apply_cost(t, 0.1)
        self.assertAlmostEqual(t["r"], -1.1)


class Garde(unittest.TestCase):
    def setUp(self):
        for k in ("WEEKEND_EXIT", "ACCOUNT_BALANCE", "RISK_PCT", "ALERT_FORMAT"):
            os.environ.pop(k, None)

    def test_usd_et_crypto(self):
        self.assertEqual(G.usd_sign("frxXAUUSD", "BUY"), -1)
        self.assertEqual(G.usd_sign("frxUSDJPY", "BUY"), 1)
        self.assertEqual(G.usd_sign("cryBTCUSD", "BUY"), 0)
        self.assertEqual(G.crypto_sign("cryETHUSD", "SELL"), -1)

    def test_risk_check(self):
        tr = {"active": {}, "closed": []}

        def add(sym, d, strat):
            k = f"{sym}{d}{strat}"
            tr["active"][k] = T.new_trade("OR", k, sym, sym[3:], d, d, 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, strat, 1e9, 3600)
        add("frxXAUUSD", "BUY", "A")
        add("frxEURUSD", "BUY", "A")
        self.assertEqual(G.risk_check(tr, "frxXAUUSD", "BUY", 1e9, "A"), (False, "dedupe"))
        self.assertFalse(G.risk_check(tr, "frxGBPUSD", "BUY", 1e9, "B")[0])         # 3e position short USD
        self.assertTrue(G.risk_check(tr, "frxUSDJPY", "BUY", 1e9, "B")[0])          # sens USD opposé
        add("cryBTCUSD", "BUY", "A")
        add("cryETHUSD", "BUY", "A")
        self.assertFalse(G.risk_check(tr, "cryBTCUSD", "BUY", 1e9, "B")[0])         # groupe crypto plein

    def test_aucun_blocage_apres_des_pertes(self):
        now = ts(2026, 10, 21, 10)
        tr = {"active": {}, "closed": [dict(sym="frxXAUUSD", dir="BUY", cascade="A", r=-1.0, t_close=now - 60 * k)
                                         for k in range(1, 8)]}                  # 7 stops dans la journée
        self.assertEqual(G.risk_check(tr, "frxEURUSD", "SELL", now, "B"), (True, ""))
        self.assertFalse(hasattr(G, "MAX_DAILY_LOSS_R"))

    def test_fenetres(self):
        self.assertIn("week-end", G.blackout("frxEURUSD", ts(2026, 10, 24, 12)))      # samedi
        self.assertIn("fermeture", G.blackout("frxXAUUSD", ts(2026, 10, 23, 16)))     # vendredi 16h
        self.assertIsNone(G.blackout("cryBTCUSD", ts(2026, 10, 24, 12)))              # crypto 24/7
        self.assertIsNone(G.blackout("frxEURUSD", ts(2026, 10, 21, 9)))               # mercredi matin

    def test_sortie_week_end(self):
        self.assertTrue(G.weekend_exit_due("frxEURUSD", ts(2026, 10, 23, 16, 45)))
        self.assertFalse(G.weekend_exit_due("frxEURUSD", ts(2026, 10, 23, 16, 0)))
        self.assertFalse(G.weekend_exit_due("cryBTCUSD", ts(2026, 10, 24, 12)))
        os.environ["WEEKEND_EXIT"] = "0"
        self.assertFalse(G.weekend_exit_due("frxEURUSD", ts(2026, 10, 23, 16, 45)))

    def test_alerte_calendrier_indisponible(self):
        sent, g = [], {}

        def boom(url):
            raise OSError("réseau")
        t0 = ts(2026, 10, 21, 9)
        G.calendar_events(g, t0, http_get=boom, notify=sent.append)
        G.calendar_events(g, t0 + 3600, http_get=boom, notify=sent.append)
        self.assertEqual(sent, [])                                                  # trop tôt pour alerter
        G.calendar_events(g, t0 + 7 * 3600, http_get=boom, notify=sent.append)
        G.calendar_events(g, t0 + 8 * 3600, http_get=boom, notify=sent.append)
        self.assertEqual(len(sent), 1)                                              # une seule alerte
        G.calendar_events(g, t0 + 9 * 3600, http_get=lambda u: [], notify=sent.append)
        self.assertEqual(len(sent), 2)
        self.assertIn("de nouveau disponible", sent[1])


class Messages(unittest.TestCase):
    def setUp(self):
        for k in ("ALERT_FORMAT", "ACCOUNT_BALANCE"):
            os.environ.pop(k, None)
        info = TR.trend_info(zigzag(3))
        infos = {"D1": info, "H4": None}
        tl, _ = TR.alert_lines("BUY", infos, info["start_epoch"] + 86400)
        e = 2652.40
        self.sig = {"label": "Sweep + CHoCH", "dir": "BUY", "sym": "frxXAUUSD", "name": "XAUUSD", "dec": 2,
                    "ltf": "M5", "session": "Londres", "entry": e, "sl": e - 3.6, "tp1": e + 3.6, "tp2": e + 7.2,
                    "tp3": e + 10.8, "inval": 2648.2, "short": "PDL pris · CHoCH M5", "details": ["✅ test"],
                    "trend_lines": tl, "trend_short": TR.alert_short("BUY", infos, info["start_epoch"] + 86400),
                    "age_min": 3.0}

    def test_quatre_formats(self):
        for fmt, longueur in (("complet", 600), ("compact", 400), ("contexte", 500), ("minimal", 150)):
            os.environ["ALERT_FORMAT"] = fmt
            txt = gold.gold_message(self.sig, 15)
            self.assertIn("XAUUSD", txt)
            self.assertIn("15", txt)
            self.assertLess(len(txt), longueur + 400)
            self.assertNotIn("None", txt)
        os.environ["ALERT_FORMAT"] = "minimal"
        self.assertLess(len(gold.gold_message(self.sig, 15)), 160)

    def test_format_inconnu_et_age(self):
        os.environ["ALERT_FORMAT"] = "n'importe quoi"
        self.assertEqual(gold.alert_format(), "essentiel")
        self.assertIn("signal il y a 3 min", gold.gold_message(self.sig, 15))
        os.environ.pop("ALERT_FORMAT", None)
        self.assertEqual(gold.alert_format(), "essentiel")                  # format par défaut
        os.environ["ALERT_FORMAT"] = "complet"
        self.assertEqual(gold.alert_format(), "complet")
        self.assertEqual(gold.age_txt({"age_min": 0.2}), "à l'instant")

    def test_variables_vides(self):
        self.assertEqual(gold.parse_strategies(""), ["S1", "S2", "S3", "S4"])      # variable GitHub non définie
        self.assertEqual(gold.parse_strategies(None), ["S1", "S2", "S3", "S4"])
        self.assertEqual(gold.parse_strategies("S1,S5,S2"), ["S1", "S2"])               # ancien code S5 = Pullback (S1), sans doublon
        self.assertEqual(gold.parse_strategies(" s2 , S3 "), ["S2", "S3"])

    def test_heure_du_recapitulatif(self):
        for k in ("RECAP_HEURE", "RECAP_FUSEAU"):
            os.environ.pop(k, None)
        g = {}
        self.assertIsNone(gold.recap_slot(g, ts(2026, 10, 21, 0, 50)))              # mercredi, trop tôt
        self.assertEqual(gold.recap_slot(g, ts(2026, 10, 21, 1, 5)), "2026-10-21")   # 01h05 New York
        self.assertEqual(gold.recap_slot(g, ts(2026, 10, 21, 6, 59)), "2026-10-21")  # encore dans la fenêtre de 6 h
        self.assertIsNone(gold.recap_slot(g, ts(2026, 10, 21, 7, 30)))               # trop tard : journée sautée
        self.assertIsNone(gold.recap_slot({"recap_day": "2026-10-21"}, ts(2026, 10, 21, 1, 5)))   # déjà envoyé
        self.assertIsNone(gold.recap_slot(g, ts(2026, 10, 24, 1, 5)))                # samedi
        self.assertIsNone(gold.recap_slot(g, ts(2026, 10, 25, 1, 5)))                # dimanche
        self.assertEqual(gold.recap_slot(g, ts(2026, 10, 26, 1, 5)), "2026-10-26")   # lundi
        os.environ["RECAP_HEURE"], os.environ["RECAP_FUSEAU"] = "07:00", "Europe/Paris"
        paris = lambda h, m: datetime(2026, 10, 21, h, m, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        self.assertIsNone(gold.recap_slot(g, paris(6, 55)))
        self.assertEqual(gold.recap_slot(g, paris(7, 5)), "2026-10-21")
        os.environ["RECAP_HEURE"], os.environ["RECAP_FUSEAU"] = "n'importe quoi", "Pas/UnFuseau"
        self.assertEqual(gold.recap_config()[1:], (1, 0))                            # valeurs invalides : défauts
        for k in ("RECAP_HEURE", "RECAP_FUSEAU"):
            os.environ.pop(k, None)

    def test_heure_locale_dans_les_alertes(self):
        for k in ("ALERT_FUSEAU", "ALERT_FUSEAU_NOM", "ALERT_FORMAT"):
            os.environ.pop(k, None)
        t_ny = ts(2026, 10, 21, 3, 15)                                              # 03h15 New York (heure d'été US)
        self.assertEqual(gold.alert_clock(t_ny), "08h15 Bénin")                       # UTC+1, sans heure d'été
        self.assertEqual(gold.alert_clock(ts(2026, 11, 18, 3, 15)), "09h15 Bénin")    # heure d'hiver US : un cran de plus
        sig = dict(self.sig, ts=t_ny, ttl=3600, otype="BUY LIMIT", price_now=2653.0, entry_note="x")
        for fmt in gold.ALERT_FORMATS:
            os.environ["ALERT_FORMAT"] = fmt
            self.assertIn("08h15 Bénin", gold.gold_message(sig, 3))
        os.environ["ALERT_FORMAT"] = "complet"
        self.assertIn("valable jusqu'à 09h15 Bénin", gold.gold_message(sig, 3))
        os.environ["ALERT_FUSEAU"] = "none"
        self.assertIsNone(gold.alert_clock(t_ny))
        self.assertNotIn("Bénin", gold.gold_message(sig, 3))
        self.assertIn("valable 60 min", gold.gold_message(sig, 3))
        os.environ["ALERT_FUSEAU"], os.environ["ALERT_FUSEAU_NOM"] = "Europe/Paris", "Paris"
        self.assertEqual(gold.alert_clock(t_ny), "09h15 Paris")
        os.environ["ALERT_FUSEAU"] = "Pas/UnFuseau"
        self.assertIsNone(gold.alert_clock(t_ny))
        for k in ("ALERT_FUSEAU", "ALERT_FUSEAU_NOM", "ALERT_FORMAT"):
            os.environ.pop(k, None)
        ev = gold.trade_event_message(new_buy(), "tp1", t_ny)
        self.assertIn("08h15 Bénin", ev)

    def test_strategies_par_actif(self):
        self.assertEqual(gold.parse_sym_strats("frxEURUSD:S1,S2;cryBTCUSD:s2 , S3"),
                         {"frxEURUSD": ["S1", "S2"], "cryBTCUSD": ["S2", "S3"]})
        self.assertEqual(gold.parse_sym_strats(""), {})


class Strategies(unittest.TestCase):
    def test_niveaux_et_plafond(self):
        lv = S.build_levels("BUY", 100, 99.99, a_ltf=1.0, a_h1=5.0, cap_h1=1.5)
        self.assertAlmostEqual(lv["risk"], S.MIN_RISK_ATR)                  # stop éloigné au risque minimal
        self.assertAlmostEqual(lv["tp"][2], 100 + 3 * S.MIN_RISK_ATR)
        self.assertIsNone(S.build_levels("SELL", 100, 110, 1.0, 5.0, 1.5))   # risque > 1,5 x ATR H1

    def test_sessions(self):
        self.assertEqual(S.session_name(ts(2026, 10, 21, 3)), "Londres")
        self.assertEqual(S.session_name(ts(2026, 10, 21, 8)), "New York")
        self.assertEqual(S.session_name(ts(2026, 10, 21, 14)), "Hors session")

    def test_scan_sans_erreur_et_signaux_valides(self):
        data = B.gen_sim(70, 3)
        rp, sent, funnel = B.Replay(data), {}, Counter()
        n = 0
        for t in range(7200, 9500):
            provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
            for sig, _ in gold.scan("frxXAUUSD", provide, data[t]["epoch"] + 300, sent, funnel, ()):
                n += 1
                buy = sig["dir"] == "BUY"
                self.assertTrue((sig["sl"] < sig["entry"] < sig["tp1"]) if buy else (sig["tp1"] < sig["entry"] < sig["sl"]))
                self.assertTrue(sig["short"] and sig["key"].startswith("frxXAUUSD|"))
                self.assertIsNotNone(sig["age_min"])
        self.assertGreater(funnel["data"], 2000)

    def test_backtest_complet(self):
        m5 = B.gen_sim(45, 5)
        tr, funnel, _ = B.run(m5, "frxEURUSD", spread_pct=0.01, warmup_days=25, progress=False, split=0.6)
        self.assertGreater(len(tr["closed"]), 0)
        for t in tr["closed"]:
            self.assertIsNotNone(t["cost_r"])
            self.assertIn(t["period"], ("1", "2"))


def s2_scenario(stale, pad=10):
    """M5 artificiels : oscillations, deux sommets égaux (EQH), puis un sweep M15 et une chute (CHoCH M5).
    stale=True : le niveau balayé avait déjà été dépassé pendant des heures avant le sweep."""
    def build(wp, start):
        out, t, px = [], start, wp[0][1]
        for dur, tgt in wp[1:]:
            n = max(1, dur // 5)
            for i in range(n):
                o, c, k = px, px + (tgt - px) / (n - i), len(out)
                out.append({"epoch": t, "open": o, "high": max(o, c) + 0.15 + 0.05 * ((k * 7) % 11) / 11,
                            "low": min(o, c) - 0.15 - 0.05 * ((k * 5 + 3) % 13) / 13, "close": c})
                px, t = c, t + 300
        return out
    wp = [(0, 1998)]
    for _ in range(18):
        wp += [(120, 2003), (120, 1996)]
    wp += [(120, 2005.0), (120, 1999), (120, 2005.1), (120, 1998)]
    wp += [(120, 2020), (240, 2021), (180, 2002)] if stale else [(300, 2002)]
    wp += [(pad, 2002), (30, 2004.0), (15, 2003.2), (15, 2005.9), (15, 2002.4), (20, 2001.0)]
    return build(wp, int(datetime(2026, 10, 12, 0, 0, tzinfo=NY).timestamp()))


def s2_first_signal(m5, **patches):
    from unittest import mock
    rp = B.Replay(m5)
    with mock.patch.multiple(S, **patches):
        for t in range(len(m5) - 40, len(m5)):
            provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
            sig = S.scan_s2(provide, m5[t]["epoch"] + 300, Counter(), 2, kz=False, mode="limit")
            if sig:
                return sig
    return None


class ListeDesActifs(unittest.TestCase):
    DERIV_MAJEURES = {"frxAUDJPY", "frxAUDUSD", "frxEURAUD", "frxEURCAD", "frxEURCHF", "frxEURGBP", "frxEURJPY",
                      "frxEURUSD", "frxGBPAUD", "frxGBPJPY", "frxGBPUSD", "frxUSDCAD", "frxUSDCHF", "frxUSDJPY"}

    def setUp(self):
        for k in ("WEEKEND_EXIT", "SPREAD_PCT"):
            os.environ.pop(k, None)

    def test_toutes_les_majeures_deriv_sont_suivies(self):
        self.assertTrue(self.DERIV_MAJEURES <= set(gold.ALL_SYMBOLS))
        self.assertIn("frxNZDUSD", gold.ALL_SYMBOLS)                      # déjà suivie : conservée
        self.assertIn("frxXAUUSD", gold.ALL_SYMBOLS)
        self.assertEqual(len(gold.ALL_SYMBOLS), len(set(gold.ALL_SYMBOLS)))   # aucun doublon
        self.assertEqual(len(gold.ALL_SYMBOLS), 1 + 7 + 8 + 2 + 10)

    def test_decimales_et_spreads(self):
        for sym in ("frxAUDJPY", "frxEURJPY", "frxGBPJPY", "frxUSDJPY"):
            self.assertEqual(gold.dec_of(sym), 3)
        for sym in ("frxEURGBP", "frxEURAUD", "frxEURUSD"):
            self.assertEqual(gold.dec_of(sym), 5)
        self.assertEqual(gold.dec_of("frxXAUUSD"), 2)
        for sym in gold.FOREX_CROSSES:
            self.assertGreater(gold.spread_pct(sym), gold.SPREAD_OTHER)  # croisements : plus larges que les majeures USD
        self.assertEqual(gold.name_of("frxGBPJPY"), "GBPJPY")

    def test_exposition_par_devise(self):
        self.assertEqual(G.ccy_signs("frxEURJPY", "BUY"), {"EUR": 1, "JPY": -1})
        self.assertEqual(G.ccy_signs("frxEURJPY", "SELL"), {"EUR": -1, "JPY": 1})
        self.assertEqual(G.ccy_signs("frxXAUUSD", "BUY"), {"USD": -1})        # l'or n'est pas une devise suivie
        self.assertEqual(G.ccy_signs("cryBTCUSD", "BUY"), {})
        self.assertEqual(G.usd_sign("frxEURJPY", "BUY"), 0)                   # un croisement n'expose pas à l'USD

    def test_limite_par_devise_sur_les_croisements(self):
        tr = {"active": {}, "closed": []}

        def add(sym, d, strat):
            k = f"{sym}{d}{strat}"
            tr["active"][k] = T.new_trade("OR", k, sym, sym[3:], d, d, 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, strat, 1e9, 3600)
        add("frxEURJPY", "BUY", "A")                                           # long EUR, short JPY
        add("frxEURGBP", "BUY", "A")                                           # long EUR, short GBP
        ok, why = G.risk_check(tr, "frxEURCAD", "BUY", 1e9, "B")
        self.assertFalse(ok)
        self.assertIn("EUR", why)                                              # 3e position longue EUR
        self.assertTrue(G.risk_check(tr, "frxEURCAD", "SELL", 1e9, "B")[0])    # sens opposé : autorisé
        self.assertTrue(G.risk_check(tr, "frxGBPAUD", "BUY", 1e9, "B")[0])     # long GBP (déjà short GBP) : autorisé
        ok, why = G.risk_check(tr, "frxAUDJPY", "SELL", 1e9, "B")              # long JPY : une seule position short JPY ouverte
        self.assertTrue(ok)
        add("frxGBPJPY", "BUY", "A")                                           # 2e short JPY
        ok, why = G.risk_check(tr, "frxAUDJPY", "BUY", 1e9, "B")               # 3e short JPY
        self.assertFalse(ok)
        self.assertIn("JPY", why)


class IndicesVolatility(unittest.TestCase):
    ATTENDUS = {"R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"}

    def setUp(self):
        for k in ("WEEKEND_EXIT", "ACCOUNT_BALANCE", "SPREAD_PCT", "SYMBOL_STRATEGIES"):
            os.environ.pop(k, None)

    def test_liste_et_noms(self):
        self.assertEqual(set(gold.SYNTHETICS), self.ATTENDUS)
        self.assertTrue(self.ATTENDUS <= set(gold.ALL_SYMBOLS))
        self.assertEqual(gold.name_of("R_75"), "V75")
        self.assertEqual(gold.name_of("1HZ100V"), "V100 (1s)")
        self.assertEqual(gold.name_of("frxEURUSD"), "EURUSD")
        for sym in gold.SYNTHETICS:
            self.assertTrue(G.is_synthetic(sym))
            self.assertIn(sym, gold.DECIMALS)
        self.assertFalse(any(G.is_synthetic(s) for s in gold.ALL_SYMBOLS if s not in self.ATTENDUS))

    def test_synthetiques_recoivent_toutes_les_strategies_actives(self):
        gold.ENABLED = ["S1", "S2", "S3"]
        for sym in gold.SYNTHETICS:
            self.assertEqual(gold.strategies_for(sym), ["S1", "S2", "S3"])       # aucun filtre par classe
        self.assertEqual(gold.strategies_for("frxEURUSD"), ["S1", "S2", "S3"])

    def test_scan_sans_killzone_sur_les_synthetiques(self):
        from unittest import mock
        seen = {}

        def fake(provide, now, funnel, only=None, dec=2, kz=True, modes=None):
            seen.update(only=only, kz=kz, dec=dec)
            return []
        data = B.gen_sim(20, 4)
        rp = B.Replay(data)
        t = 5000
        provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
        with mock.patch.object(S, "scan_all", fake):
            gold.scan("R_75", provide, data[t]["epoch"] + 300, {}, Counter(), ())
        self.assertEqual(seen, {"only": list(gold.ENABLED), "kz": False, "dec": 4})

    def test_marche_24h_sur_24_sans_news_ni_week_end(self):
        samedi, news = ts(2026, 10, 24, 12), [{"start": ts(2026, 10, 24, 11), "end": ts(2026, 10, 24, 13), "note": "NFP", "cur": []}]
        for sym in ("R_100", "1HZ100V"):
            self.assertIsNone(G.blackout(sym, samedi, news))
            self.assertIsNone(G.blackout(sym, ts(2026, 10, 23, 17, 5), news))      # pas de rollover
            self.assertFalse(G.weekend_exit_due(sym, ts(2026, 10, 23, 16, 45)))
            self.assertTrue(gold.is_247(sym))
        self.assertIsNotNone(G.blackout("frxEURUSD", samedi, news))                 # le forex reste bloqué

    def test_pas_dans_le_recap_de_tendance(self):
        asked = []

        def fake(api, cache, sym, tf):
            asked.append(sym)
            return None
        from unittest import mock
        with mock.patch.object(gold, "tf_candles", fake):
            gold.build_recap(None, {}, 1.8e9)
        self.assertFalse(any(G.is_synthetic(s) for s in asked))
        self.assertIn("frxEURUSD", asked)

    def test_alerte_s2_sans_ligne_killzone_sur_actif_24_7(self):
        from unittest import mock
        sig = None
        for pad in range(0, 60, 5):
            m5 = s2_scenario(False, pad)
            sig = s2_first_signal(m5, S2_BIAS_FILTER=False, S2_HTF_ZONE=False, S2_LIQ_TARGETS=False)
            if sig:
                break
        self.assertIsNotNone(sig)
        self.assertFalse(any("Killzone" in x for x in sig["details"]))                 # s2_first_signal scanne avec kz=False


class SansLotNiLimite(unittest.TestCase):
    def test_plus_de_lot(self):
        for name in ("lot_size", "lot_line", "contract_units", "quote_to_usd", "RATES"):
            self.assertFalse(hasattr(G, name), name)
        self.assertFalse(hasattr(gold, "lot_short"))
        os.environ["ACCOUNT_BALANCE"], os.environ["RISK_PCT"] = "10000", "1"      # anciennes variables : sans effet
        try:
            sig = dict(dir="BUY", name="XAUUSD", ltf="M5", label="Sweep + CHoCH", session="Londres", entry=2650.0, sl=2646.0,
                       tp1=2654.0, tp2=2658.0, tp3=2662.0, dec=2, otype="BUY", short="x", ts=1_700_000_000, key="k")
            for fmt in (gold.message_compact, gold.message_minimal, gold.message_contexte):
                self.assertNotIn("Lot", fmt(sig, 7))
        finally:
            os.environ.pop("ACCOUNT_BALANCE"), os.environ.pop("RISK_PCT")

    def test_plus_de_limite_de_trades_ouverts(self):
        self.assertFalse(hasattr(G, "MAX_OPEN_TRADES"))
        tr = {"active": {}, "closed": []}
        for i in range(20):                                                       # 20 trades sur des actifs non corrélés
            sym = f"cryXXX{i}USD" if i % 2 else f"frxZZZ{i}QQQ"
            tr["active"][f"k{i}"] = T.new_trade("OR", f"k{i}", sym, sym[3:], "BUY", "BUY", 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, "A", 1e9, 3600)
        self.assertTrue(G.risk_check(tr, "R_100", "BUY", 1e9, "S2")[0])

    def test_l_exposition_par_devise_reste_active(self):
        tr = {"active": {}, "closed": []}
        for i, sym in enumerate(("frxEURUSD", "frxEURJPY")):
            tr["active"][f"k{i}"] = T.new_trade("OR", f"k{i}", sym, sym[3:], "BUY", "BUY", 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, "A", 1e9, 3600)
        self.assertFalse(G.risk_check(tr, "frxEURGBP", "BUY", 1e9, "B")[0])        # 3e position longue EUR


class RecapDuMatinParClasse(unittest.TestCase):
    def run_recap(self, symbols=None, data=lambda sym, tf: None, fmt="complet"):
        from unittest import mock
        sent, cs = [], zigzag(3)
        fake = lambda api, cache, sym, tf: (data(sym, tf) if data(sym, tf) is not None else cs)
        with mock.patch.object(gold, "tf_candles", fake), mock.patch.object(gold, "RECAP_FORMAT", fmt), \
                mock.patch.object(gold, "SYMBOLS", symbols or gold.ALL_SYMBOLS), \
                mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
            ok = gold.send_recap(None, {}, cs[-1]["epoch"] + 600)
        return ok, sent

    def test_un_message_par_classe(self):
        ok, sent = self.run_recap()
        self.assertTrue(ok)
        self.assertEqual(len(sent), 4)                                             # or, forex USD, croisements, cryptos
        self.assertIn("Or ·", sent[0])
        self.assertIn("XAUUSD", sent[0])
        self.assertIn("Forex · paires contre USD", sent[1])
        self.assertIn("Forex · croisements majeurs", sent[2])
        self.assertIn("Cryptos", sent[3])
        for name in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"):
            self.assertIn(name, sent[1])
            self.assertNotIn(name, sent[0] + sent[2] + sent[3])
        for name in ("AUDJPY", "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "GBPAUD", "GBPJPY"):
            self.assertIn(name, sent[2])
        self.assertIn("BTCUSD", sent[3])
        self.assertIn("ETHUSD", sent[3])
        self.assertTrue(all("XAUUSD" not in m for m in sent[1:]))

    def test_legende_une_seule_fois_et_pas_d_indices(self):
        _, sent = self.run_recap()
        self.assertIn("Âge = jambes consécutives", sent[0])
        self.assertTrue(all("Âge = jambes consécutives" not in m for m in sent[1:]))
        self.assertTrue(all("V75" not in m and "V100" not in m for m in sent))   # indices : récapitulatif du soir

    def test_marche_ferme_liste_a_la_fin(self):
        old = zigzag(3)

        def data(sym, tf):                                                         # forex : données trop anciennes (week-end)
            if sym.startswith("frx") and sym != "frxXAUUSD":
                return [dict(c, epoch=c["epoch"] - 86400 * 5) for c in old]
            return None
        ok, sent = self.run_recap(data=data)
        self.assertTrue(ok)
        self.assertEqual(len(sent), 3)                                             # or, cryptos, et la liste des marchés fermés
        self.assertTrue(sent[-1].startswith("Marché fermé : "))
        self.assertIn("EURUSD", sent[-1])
        self.assertIn("GBPJPY", sent[-1])

    def test_aucune_donnee(self):
        ok, sent = self.run_recap(data=lambda sym, tf: [])
        self.assertFalse(ok)
        self.assertEqual(sent, [])


class RecapIndices(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SYNTH_RECAP_HEURES", None)

    def test_creneau_du_soir_4h_avant_la_cloture_daily_de_deriv(self):
        g = {}
        close = int(utc(2026, 10, 22, 0))                                          # clôture daily Deriv : 00h GMT
        self.assertIsNone(gold.synth_recap_slot(g, utc(2026, 10, 21, 19, 59)))    # trop tôt
        self.assertEqual(gold.synth_recap_slot(g, utc(2026, 10, 21, 20, 0)), close)   # 4 h avant (21h au Bénin)
        self.assertEqual(gold.synth_recap_slot(g, utc(2026, 10, 21, 23, 59)), close)
        self.assertIsNone(gold.synth_recap_slot(g, utc(2026, 10, 22, 0, 0)))      # nouvelle bougie : prochain envoi à 20h GMT
        self.assertIsNone(gold.synth_recap_slot(g, utc(2026, 10, 21, 8, 0)))      # jamais le matin
        self.assertIsNone(gold.synth_recap_slot({"synth_recap_close": close}, utc(2026, 10, 21, 22, 0)))   # déjà envoyé
        self.assertEqual(gold.synth_recap_slot({"synth_recap_close": close}, utc(2026, 10, 22, 20, 5)), int(utc(2026, 10, 23, 0)))
        for jour in (24, 25):                                                      # samedi et dimanche : marché 24/7
            self.assertIsNotNone(gold.synth_recap_slot(g, utc(2026, 10, jour, 21, 0)))
        self.assertEqual(gold.daily_close(utc(2026, 11, 10, 20, 0)), int(utc(2026, 11, 11, 0)))   # indépendant de l'heure d'hiver

    def test_reglage_du_delai(self):
        os.environ["SYNTH_RECAP_HEURES"] = "2"
        try:
            self.assertIsNone(gold.synth_recap_slot({}, utc(2026, 10, 21, 21, 0)))
            self.assertIsNotNone(gold.synth_recap_slot({}, utc(2026, 10, 21, 22, 30)))
        finally:
            os.environ.pop("SYNTH_RECAP_HEURES")

    def test_bougie_daily_de_deriv_pour_les_indices(self):
        from unittest import mock
        h1 = [candle(int(utc(2026, 10, 19, 0)) + 3600 * i, 100, 101, 99, 100) for i in range(24 * 6)]
        with mock.patch.object(gold, "get_candles", lambda *a, **k: h1):
            d_synth = gold.tf_candles(None, {}, "R_100", "D1")
            d_forex = gold.tf_candles(None, {}, "frxEURUSD", "D1")
            h4_synth = gold.tf_candles(None, {}, "R_100", "H4")
        self.assertTrue(all(c["epoch"] % 86400 == 0 for c in d_synth))             # 00h GMT
        self.assertEqual(len(d_synth), 6)
        self.assertTrue(all(c["epoch"] % 86400 != 0 for c in d_forex))             # forex : 17h New York
        self.assertTrue(all(datetime.fromtimestamp(c["epoch"], NY).hour == 17 for c in d_forex))
        self.assertTrue(all(datetime.fromtimestamp(c["epoch"], NY).hour % 4 == 1 for c in h4_synth))   # H4 inchangé (17h New York)

    def test_replay_daily_gmt(self):
        m5 = [candle(int(utc(2026, 10, 19, 0)) + 300 * i, 100, 101, 99, 100) for i in range(288 * 4)]
        self.assertTrue(all(c["epoch"] % 86400 == 0 for c in B.Replay(m5, utc_daily=True).provide("D1", 288 * 3, 5)))
        self.assertTrue(all(c["epoch"] % 86400 != 0 for c in B.Replay(m5).provide("D1", 288 * 3, 5)))

    def test_un_message_par_classe(self):
        from unittest import mock
        sent = []
        cs = zigzag(3)
        now = cs[-1]["epoch"] + 600
        with mock.patch.object(gold, "tf_candles", lambda api, cache, sym, tf: cs), \
                mock.patch.object(gold, "RECAP_FORMAT", "complet"), \
                mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
            ok = gold.send_synth_recap(None, {}, now)
        self.assertTrue(ok)
        self.assertEqual(len(sent), 2)                                             # deux classes, deux messages séparés
        self.assertIn("Volatility Indices", sent[0])
        self.assertIn("Volatility (1s) Indices", sent[1])
        for name in ("V10", "V25", "V50", "V75", "V100"):
            self.assertIn(name, sent[0])
            self.assertNotIn("(1s)", sent[0].split("\n\n", 1)[1])
            self.assertIn(f"{name} (1s)", sent[1])
        self.assertIn("Biais S2", sent[0])
        self.assertIn("Bougie daily en cours", sent[0])
        self.assertNotIn("EURUSD", sent[0] + sent[1])

    def test_classe_absente_de_symbols_non_envoyee(self):
        from unittest import mock
        sent = []
        cs = zigzag(3)
        with mock.patch.object(gold, "tf_candles", lambda api, cache, sym, tf: cs), \
                mock.patch.object(gold, "RECAP_FORMAT", "complet"), \
                mock.patch.object(gold, "SYMBOLS", ["frxEURUSD", "R_100"]), \
                mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
            gold.send_synth_recap(None, {}, cs[-1]["epoch"] + 600)
        self.assertEqual(len(sent), 1)
        self.assertIn("V100", sent[0])
        self.assertNotIn("1s", sent[0].split("\n", 2)[0])


class SweepCHoCH(unittest.TestCase):
    OFF = dict(S2_BIAS_FILTER=False, S2_HTF_ZONE=False, S2_LIQ_TARGETS=False)

    def first_pad(self, stale, **patches):
        for pad in range(0, 60, 5):
            sig = s2_first_signal(s2_scenario(stale, pad), **patches)
            if sig:
                return sig
        return None

    def test_niveau_intact_donne_un_signal(self):
        sig = self.first_pad(False, **self.OFF)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["dir"], "SELL")

    def test_niveau_deja_pris_ecarte(self):
        # ancien comportement : signal sur un niveau déjà dépassé de 15 points pendant des heures
        self.assertIsNotNone(self.first_pad(True, S2_FRESH_LEVELS=False, **self.OFF))
        # corrigé : ce niveau n'est plus de la liquidité
        self.assertIsNone(self.first_pad(True, S2_FRESH_LEVELS=True, **self.OFF))

    def test_niveau_pris_une_seule_fois(self):
        m15 = [candle(1000 + 900 * i, 100, 100.5, 99.5, 100) for i in range(10)]
        m15[3] = candle(1000 + 900 * 3, 100, 101.2, 99.8, 100.2)       # mèche au-dessus de 101 : liquidité prise
        self.assertTrue(S.level_taken(m15, 101.0, "high", 1000))
        self.assertFalse(S.level_taken(m15, 101.0, "high", 1000, upto=3))   # avant cette bougie : intact
        self.assertFalse(S.level_taken(m15, 101.0, "high", 1000 + 900 * 4))  # niveau né après la mèche

    def test_biais_h4_puis_h1(self):
        up, dn, flat = zigzag(3), zigzag(3, up=False), [candle(1_700_000_000 + 3600 * i, 100, 100.5, 99.5, 100) for i in range(60)]
        self.assertEqual(S.s2_bias(up, dn), ("BUY", "H4"))           # le H4 prime sur le H1
        self.assertEqual(S.s2_bias(flat, dn), ("SELL", "H1"))        # H4 sans tendance : on lit le H1
        self.assertEqual(S.s2_bias(flat, flat), (None, None))

    def test_filtre_de_biais(self):
        from unittest import mock
        patches = dict(S2_HTF_ZONE=False, S2_LIQ_TARGETS=False, S2_BIAS_FILTER=True)
        with mock.patch.object(S, "s2_bias", return_value=("SELL", "H4")):
            self.assertIsNotNone(self.first_pad(False, **patches))
        with mock.patch.object(S, "s2_bias", return_value=("BUY", "H4")):
            self.assertIsNone(self.first_pad(False, **patches))      # SELL contre un biais haussier
        with mock.patch.object(S, "s2_bias", return_value=(None, None)):
            self.assertIsNone(self.first_pad(False, **patches))      # aucun biais clair

    def test_zones_h1_h4(self):
        t0 = 1_700_000_000
        cs = [candle(t0 + 3600 * i, 100, 100.6, 99.4, 100 + (0.1 if i % 2 else -0.1)) for i in range(30)]
        cs[26] = candle(t0 + 3600 * 26, 100.1, 100.3, 99.5, 99.7)    # bougie baissière : bloc d'ordre
        cs[27] = candle(t0 + 3600 * 27, 99.7, 102.6, 99.6, 102.5)    # déplacement haussier qui casse la structure
        cs[28] = candle(t0 + 3600 * 28, 102.5, 103.4, 102.1, 103.0)
        cs[29] = candle(t0 + 3600 * 29, 103.0, 103.6, 102.8, 103.2)
        before = t0 + 3600 * 40
        zs = S.htf_zones(cs, "BUY", "H1", before)
        kinds = {z["kind"] for z in zs}
        self.assertIn("OB", kinds)
        self.assertIn("FVG", kinds)                                  # trou entre la bougie 26 et la bougie 28
        self.assertTrue(all(z["lo"] < z["hi"] for z in zs))
        self.assertEqual(S.htf_zones(cs, "SELL", "H1", before), [])   # aucune zone d'offre dans ce marché
        cs2 = cs + [candle(t0 + 3600 * 30, 103.2, 103.3, 100.0, 100.2)]   # retour dans les zones
        self.assertEqual([z for z in S.htf_zones(cs2, "BUY", "H1", before) if z["kind"] == "OB"], [])   # retestée
        self.assertEqual(S.htf_zones(cs, "BUY", "H1", t0 + 3600 * 27), [])   # le déplacement n'est pas encore clôturé

    def test_signal_exige_une_zone_htf(self):
        from unittest import mock
        patches = dict(S2_BIAS_FILTER=False, S2_LIQ_TARGETS=False, S2_HTF_ZONE=True)
        with mock.patch.object(S, "htf_zone_hit", return_value=None):
            self.assertIsNone(self.first_pad(False, **patches))
        fake = {"kind": "OB", "tf": "H1", "lo": 2004.0, "hi": 2005.0, "epoch": 0}
        with mock.patch.object(S, "htf_zone_hit", return_value=fake):
            sig = self.first_pad(False, **patches)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["extra"]["zone"], "H1 OB")
        self.assertTrue(any("bloc d'ordre H1" in x for x in sig["details"]))
        self.assertEqual(sig["zones"][0]["kind"], "ob")

    def test_objectifs_sur_la_liquidite(self):
        m15 = [candle(1000 + 900 * i, 100, 100.4, 99.6, 100) for i in range(20)]
        levels = [("PDL", 96.0, "low", 1000), ("Asie B", 94.0, "low", 1000), ("EQL", 99.0, "low", 1000),
                  ("PDH", 104.0, "high", 1000), ("EQL", 90.0, "low", 1000 + 900 * 30)]
        tg = S.liquidity_targets(levels, m15, "SELL", 100.0, 1.0, a_m15=1.0)
        self.assertEqual([t[0] for t in tg], ["PDL", "Asie B"])      # 99 trop proche (1 R), 104 du mauvais côté, 90 pas encore né
        tps, t2, t3 = S.s2_tps("SELL", 100.0, 1.0, tg)
        self.assertAlmostEqual(tps[0], 99.0)
        self.assertAlmostEqual(tps[1], 96.1)                          # 0,1 ATR avant PDL
        self.assertAlmostEqual(tps[2], 94.1)
        self.assertTrue(tps[0] > tps[1] > tps[2])
        # niveau déjà pris : plus un objectif
        m15[5] = candle(1000 + 900 * 5, 100, 100.2, 95.5, 99.9)
        self.assertEqual([t[0] for t in S.liquidity_targets(levels, m15, "SELL", 100.0, 1.0, 1.0)], ["Asie B"])
        # sans liquidité : 2 R / 3 R, TP3 toujours au-delà de TP2
        self.assertEqual([round(x, 2) for x in S.s2_tps("BUY", 100.0, 1.0, [])[0]], [101.0, 102.0, 103.0])
        tps = S.s2_tps("BUY", 100.0, 1.0, [("PDH", 104.9, 4.9)])[0]
        self.assertTrue(tps[0] < tps[1] < tps[2])

    def test_signal_complet_avec_objectifs(self):
        sig = self.first_pad(False, S2_BIAS_FILTER=False, S2_HTF_ZONE=False, S2_LIQ_TARGETS=True)
        self.assertIsNotNone(sig)
        self.assertTrue(sig["tp3"] < sig["tp2"] < sig["tp1"] < sig["entry"] < sig["sl"])
        self.assertIn(sig["extra"]["tp"], ("fixe", "liquidité"))


class OrdresLimites(unittest.TestCase):
    def test_choix_de_l_ordre(self):
        self.assertEqual(S.pick_entry("BUY", 105, 102, 99, "limit"), ("BUY LIMIT", 102))
        self.assertEqual(S.pick_entry("SELL", 95, 98, 101, "limit"), ("SELL LIMIT", 98))
        self.assertEqual(S.pick_entry("BUY", 105, 102, 99, "market"), ("BUY", 105))     # mode marché
        self.assertEqual(S.pick_entry("BUY", 101, 102, 99, "limit"), ("BUY", 101))      # zone au-dessus du prix
        self.assertEqual(S.pick_entry("BUY", 105, 98, 99, "limit"), ("BUY", 105))       # zone sous le stop
        self.assertEqual(S.pick_entry("BUY", 105, None, 99, "limit"), ("BUY", 105))     # pas de zone

    def test_bloc_d_ordre(self):
        cs = [candle(0, 10, 11, 9, 10.5), candle(1, 10.5, 10.8, 9.5, 9.8), candle(2, 9.8, 12, 9.7, 11.9)]
        self.assertEqual(S.ob_zone(cs, 0, 2, "BUY"), (9.5, 10.8))       # dernière bougie baissière
        self.assertEqual(S.ob_zone(cs, 0, 2, "SELL"), (9.7, 12))
        self.assertAlmostEqual(S.ob_entry("BUY", (9.5, 10.8)), 10.8)    # bord proche : le haut pour un achat
        self.assertAlmostEqual(S.ob_entry("SELL", (9.7, 12)), 9.7)      # le bas pour une vente

    def test_fvg(self):
        base = [candle(i, 10, 10.6, 9.4, 10.1) for i in range(20)]       # corps moyens de 0,1
        up = base + [candle(20, 10.1, 10.2, 9.9, 10.0), candle(21, 10.0, 12.0, 10.0, 11.9), candle(22, 11.9, 12.5, 11.5, 12.3)]
        self.assertEqual(S.fvg_zone(up, 19, "BUY"), (10.2, 11.5))        # haut de la bougie 1 -> bas de la bougie 3
        self.assertAlmostEqual(S.fvg_entry("BUY", (10.2, 11.5)), 10.85)  # milieu
        self.assertIsNone(S.fvg_zone(up, 19, "SELL"))
        dn = base + [candle(20, 10.1, 10.3, 10.0, 10.2), candle(21, 10.2, 10.2, 8.2, 8.3), candle(22, 8.3, 8.9, 7.8, 7.9)]
        self.assertEqual(S.fvg_zone(dn, 19, "SELL"), (8.9, 10.0))
        self.assertAlmostEqual(S.fvg_entry("SELL", (8.9, 10.0)), 9.45)
        filled = up + [candle(23, 12.3, 12.4, 10.0, 10.5)]               # le prix a traversé toute la zone
        self.assertIsNone(S.fvg_zone(filled, 19, "BUY"))
        weak = base + [candle(20, 10.1, 10.2, 9.9, 10.0), candle(21, 10.0, 10.9, 10.0, 10.12), candle(22, 10.1, 10.9, 10.3, 10.6)]
        self.assertIsNone(S.fvg_zone(weak, 19, "BUY"))                   # gap sans déplacement : refusé

    def test_priorite_bloc_d_ordre_puis_fvg(self):
        base = [candle(i, 10, 10.6, 9.4, 10.1) for i in range(20)]
        with_ob = base + [candle(20, 10.1, 10.2, 9.9, 10.0), candle(21, 10.0, 12.0, 10.0, 11.9), candle(22, 11.9, 12.5, 11.5, 12.3)]
        e, kind, _ = S.entry_zone(with_ob, 19, 21, "BUY")
        self.assertEqual((kind, e), ("OB", 10.2))                        # bougie baissière 20 : bord proche = son haut
        only_fvg = base[:20] + [candle(20, 10.1, 10.2, 10.0, 10.15), candle(21, 10.15, 12.0, 10.15, 11.9), candle(22, 11.9, 12.5, 11.5, 12.3)]
        e, kind, _ = S.entry_zone(only_fvg, 20, 20, "BUY")               # aucune bougie baissière dans la plage
        self.assertEqual(kind, "FVG")
        self.assertAlmostEqual(e, (10.2 + 11.5) / 2)

    def limit_trade(self, now=1000):
        return T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", "BUY", "BUY LIMIT", 100.0, 99.0, 101.0, 102.0, 103.0,
                           "M5", 300, 2, "Test", now, 3600)

    def test_cycle_de_vie(self):
        t = self.limit_trade()
        T.advance(t, [candle(1200, 100.9, 100.95, 100.4, 100.6)], 1500)       # n'atteint pas l'entrée
        self.assertEqual(t["status"], "pending")
        ev = T.advance(t, [candle(1500, 100.6, 100.8, 99.9, 100.4), candle(1800, 100.4, 101.3, 100.2, 101.2)], 2100)
        self.assertEqual(ev[0], "filled")
        self.assertEqual(t["status"], "open")
        self.assertIn("tp1", ev)

    def test_annulations(self):
        t = self.limit_trade()
        self.assertEqual(T.advance(t, [candle(1200, 101.2, 101.6, 100.9, 101.4)], 1500), ["cancel_tp"])   # TP1 sans fill
        t = self.limit_trade()
        self.assertEqual(T.advance(t, [candle(1200, 100.9, 100.95, 100.4, 100.6)], 1500), [])
        t = self.limit_trade()
        self.assertEqual(T.advance(t, [candle(1200, 100.9, 100.95, 100.4, 100.6)], 1000 + 3601), ["expired"])
        t = self.limit_trade()
        self.assertEqual(T.cancel_pending(t, "weekend", 1500), "cancel_weekend")
        self.assertIsNone(T.cancel_pending(t, "weekend", 1500))

    def test_signaux_limites_et_marche(self):
        from unittest import mock
        data = B.gen_sim(70, 1)                          # jeu simulé qui produit à la fois des ordres limites et des ordres au marché
        rp, funnel = B.Replay(data), Counter()
        found = {"limit": 0, "market": 0}
        for mode in ("limit", "market"):
            gold.ENTRY_MODE, sent = mode, {}
            for t in range(7200, 10500):
                provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
                # toutes les stratégies sur l'or, indépendamment de sa classe : le test porte sur les ordres, pas sur les classes
                with mock.patch.dict(gold.SYMBOL_OVERRIDES, {"frxXAUUSD": ["S1", "S2", "S3", "S4"]}):
                    scanned = gold.scan("frxXAUUSD", provide, data[t]["epoch"] + 300, sent, funnel, ())
                for sig, _ in scanned:
                    buy = sig["dir"] == "BUY"
                    if gold.is_limit(sig):
                        found["limit"] += 1
                        self.assertEqual(sig["otype"], f"{sig['dir']} LIMIT")
                        self.assertTrue(sig["sl"] < sig["entry"] < sig["price_now"] if buy else sig["price_now"] < sig["entry"] < sig["sl"])
                        self.assertTrue(sig["ttl"] and sig["entry_note"])
                    else:
                        found["market"] += 1
                        self.assertEqual(sig["entry"], sig["price_now"])
            gold.ENTRY_MODE = "auto"
        self.assertGreater(found["limit"], 0)
        self.assertGreater(found["market"], 0)

    def test_modes_d_entree(self):
        try:
            gold.ENTRY_MODE = "market"
            self.assertEqual(set(gold.entry_modes().values()), {"market"})
            gold.ENTRY_MODE = "limit"
            self.assertEqual(set(gold.entry_modes().values()), {"limit"})
            gold.ENTRY_MODE = "auto"
            self.assertEqual(gold.entry_modes(), gold.ENTRY_MODES)
        finally:
            gold.ENTRY_MODE = "auto"

    def test_messages_et_compteurs(self):
        e, p = 2650.10, 2652.40
        sig = {"label": "Trend Pullback", "dir": "BUY", "otype": "BUY LIMIT", "sym": "frxXAUUSD", "name": "XAUUSD",
               "dec": 2, "ltf": "M15", "session": "New York", "entry": e, "price_now": p, "sl": e - 4, "tp1": e + 4,
               "tp2": e + 8, "tp3": e + 12, "inval": None, "short": "Repli H1 62 %", "details": ["✅ test"],
               "ttl": 7200, "entry_note": "Ordre limite au bord du bloc d'ordre M15 (2649.00 - 2651.20)"}
        for fmt in gold.ALERT_FORMATS:
            os.environ["ALERT_FORMAT"] = fmt
            txt = gold.gold_message(sig, 9)
            self.assertIn("BUY LIMIT", txt)
            self.assertIn("2650.10", txt)
            if fmt in ("complet", "compact", "contexte"):
                self.assertIn("2652.40", txt)                              # prix actuel visible
        os.environ["ALERT_FORMAT"] = "complet"
        txt = gold.gold_message(sig, 9)
        self.assertIn("valable 120 min", txt)
        self.assertIn("Annule l'ordre", txt)
        os.environ.pop("ALERT_FORMAT")
        t = self.limit_trade()
        for ev in ("filled", "cancel_tp", "cancel_sl", "cancel_weekend", "expired"):
            self.assertNotIn("ANNULER", gold.trade_event_message(t, ev))
        self.assertIsNone(gold.limits_text({}))
        self.assertIn("2 touchés (50 %)", gold.limits_text({"limits": {"placed": 4, "filled": 2, "cancelled": 1, "expired": 0}}))


# ==========================================================================
# S5 Impulsion + retracement Fibonacci (portée du crt-bot)
# ==========================================================================
def s5_series(seed, n=7000):
    """Série M5 déterministe avec régimes (tendance haussière, baissière, range) + agrégats M15/H1/H4/D1."""
    import random
    rnd = random.Random(seed)
    px, m5, drift, left, t0 = 100.0, [], 0.0, 0, 1_760_000_000 - 1_760_000_000 % 300
    for i in range(n):
        if left <= 0:
            drift, left = rnd.choice([-0.06, -0.03, 0.0, 0.03, 0.06, 0.1, -0.1]), rnd.randint(40, 400)
        left -= 1
        vol = 0.12 * (3.0 if rnd.random() < 0.04 else 1.0)
        o = px
        c = o + drift + rnd.gauss(0, vol)
        m5.append({"epoch": t0 + i * 300, "open": o, "high": max(o, c) + abs(rnd.gauss(0, vol * 0.6)),
                   "low": min(o, c) - abs(rnd.gauss(0, vol * 0.6)), "close": c})
        px = c

    def agg(secs):
        out = {}
        for c in m5:
            k = c["epoch"] - c["epoch"] % secs
            b = out.setdefault(k, {"epoch": k, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]})
            b["high"], b["low"], b["close"] = max(b["high"], c["high"]), min(b["low"], c["low"]), c["close"]
        return list(out.values())
    return {"M5": m5, "M15": agg(900), "H1": agg(3600), "H4": agg(14400), "D1": agg(86400)}


def s5_mirror(tfs, pivot=200.0):
    """Miroir des prix autour de `pivot` : un achat devient une vente aux niveaux symétriques."""
    return {tf: [{"epoch": c["epoch"], "open": pivot - c["open"], "high": pivot - c["low"], "low": pivot - c["high"],
                  "close": pivot - c["close"]} for c in cs] for tf, cs in tfs.items()}


def s5_provider(tfs, i):
    """provide(tf) comme en direct : fenêtre de bougies à l'instant de la bougie M5 d'index i (la dernière est en formation)."""
    import bisect
    t, lim = tfs["M5"][i]["epoch"], {"M5": 300, "M15": 400, "H1": 600, "H4": 150, "D1": 40}
    eps = {tf: [c["epoch"] for c in cs] for tf, cs in tfs.items()}

    def provide(tf, force=False):
        j = bisect.bisect_right(eps[tf], t)
        return tfs[tf][max(0, j - lim[tf]):j]
    return provide, t


# Scénarios déterministes (graine, index M5) trouvés sur la série ci-dessus.
S5_RELAX = dict(S5_FRESH=60, S5_MIN_RR=0.3, S5_FVG_MIN_ATR=0.0, S5_MAX_PROGRESS=0.9, S5_LATE_CANDLES=6)


class ImpulsionS5(unittest.TestCase):
    def test_enregistree_partout(self):
        from unittest import mock
        self.assertNotIn("S5", dict(S.STRATEGIES))                 # fusionnée dans S1 « Pullback » (variante structure)
        self.assertIn("S1", dict(S.STRATEGIES))
        self.assertIn("S5", S.LIMIT_TTL)                          # durée de l'ordre limite de la variante structure
        self.assertNotIn("S5", gold.ENTRY_MODES)
        self.assertEqual(S.LIMIT_TTL["S5"], 86400)
        for k in ("S5_regime", "S5_tendance", "S5_impulsion", "S5_signal"):
            self.assertIn(k, G.FUNNEL_ORDER)
            self.assertIn(k, G.FUNNEL_LABEL)
        # l'ordre des cascades : la plus haute d'abord (le garde-fou garde la première en cas de doublon)
        self.assertEqual([c[0] for c in S.S5_CASCADES], ["D1", "H4", "H1"])

    def test_helpers(self):
        cs = [{"epoch": i, "open": 10.0 + i, "high": 12.0 + i, "low": 9.0 + i, "close": 11.0 + i} for i in range(5)]
        self.assertEqual(S.mirror(S.mirror(cs)), cs)                         # le miroir est une involution
        f = S.mirror(cs)[0]
        self.assertEqual((f["high"], f["low"]), (-9.0, -12.0))

    def test_tendance_s5_est_celle_de_trend_py(self):
        # une seule définition de la structure (S2, S5 et alertes) : s5_trend délègue à trend._up
        import trend as TR
        random.seed(11)
        p, cs = 100.0, []
        for i in range(120):
            o = p
            p = o + 0.25 + random.uniform(-1.2, 1.2)
            cs.append({"epoch": 1_790_000_000 + i * 14400, "open": o, "high": max(o, p) + 0.3, "low": min(o, p) - 0.3, "close": p})
        info = TR._up(cs[:-1], TR.SWING_N)
        got = S.s5_trend(cs)
        self.assertEqual(got, ({"age": info["age"], "legs": info["legs"]} if info else None))
        self.assertFalse(hasattr(S, "S5_BOS_BY_CLOSE"))

    def test_vente_limite_reglages_par_defaut(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        sigs = S.scan_s5(provide, t + 60, Counter(), 3, True, "limit")
        self.assertIsInstance(sigs, list)
        sig = next(x for x in sigs if x["extra"]["cascade"] == "H4>H1>M15")
        self.assertEqual((sig["strat"], sig["label"], sig["dir"], sig["otype"]), ("S5", "Impulsion", "SELL", "SELL LIMIT"))
        self.assertGreater(sig["sl"], sig["entry"])
        self.assertGreater(sig["entry"], sig["tp1"])
        self.assertGreater(sig["tp1"], sig["tp2"])
        self.assertGreater(sig["tp2"], sig["tp3"])
        self.assertGreaterEqual((sig["entry"] - sig["tp2"]) / (sig["sl"] - sig["entry"]), S.S5_MIN_RR - 1e-9)   # ratio 1:3 sur TP2
        self.assertTrue(sig["key"].startswith("S5|SELL|H4>H1>M15|"))
        self.assertEqual(sig["ttl"], 86400)
        self.assertEqual(sig["ltf"], "M15")
        self.assertIn(sig["extra"]["tendance"], S.S5_TREND_AGES_OK)
        self.assertIn(sig["extra"]["zone"], ("Golden Zone", "OTE"))
        self.assertIsNotNone(sig["trig_close"])
        self.assertTrue(sig["details"])

    def test_achat_et_miroir_vente(self):
        from unittest import mock
        tfs = s5_series(2)
        with mock.patch.multiple(S, **S5_RELAX):
            provide, t = s5_provider(tfs, 6088)
            buys = [x for x in S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") if x["dir"] == "BUY"]
            self.assertTrue(buys)
            buy = buys[0]
            mprov, mt = s5_provider(s5_mirror(tfs), 6088)
            sells = [x for x in S.scan_s5(mprov, mt + 60, Counter(), 3, True, "limit")
                     if x["dir"] == "SELL" and x["extra"]["cascade"] == buy["extra"]["cascade"]]
            self.assertTrue(sells)
            sell = sells[0]
        self.assertEqual(buy["otype"], "BUY LIMIT")
        self.assertEqual(sell["otype"], "SELL LIMIT")
        for k in ("entry", "sl", "tp1", "tp2", "tp3", "inval"):
            self.assertAlmostEqual(sell[k], 200.0 - buy[k], places=6, msg=k)      # niveaux symétriques
        self.assertLess(buy["sl"], buy["entry"])
        self.assertLess(buy["entry"], buy["tp1"])
        self.assertLess(buy["tp1"], buy["tp2"])
        self.assertLess(buy["tp2"], buy["tp3"])

    def test_mode_marche_sans_ordre_limite(self):
        from unittest import mock
        tfs = s5_series(2)
        with mock.patch.multiple(S, **S5_RELAX):
            provide, t = s5_provider(tfs, 6088)
            limit = S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") or []
            market = S.scan_s5(provide, t + 60, Counter(), 3, True, "market") or []
        self.assertTrue(any(x["otype"].endswith("LIMIT") for x in limit))
        self.assertTrue(all(x["otype"] in ("BUY", "SELL") and x["ttl"] is None for x in market))

    def test_marche_instantane_et_entree_tardive(self):
        from unittest import mock
        tfs = s5_series(4)
        with mock.patch.multiple(S, **S5_RELAX):
            provide, t = s5_provider(tfs, 5566)
            sigs = S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") or []
        mk = [x for x in sigs if x["otype"] == "BUY"]
        self.assertTrue(mk)
        self.assertEqual(mk[0]["entry"], mk[0]["price_now"])                  # au marché : entrée = prix actuel
        self.assertEqual(mk[0]["extra"]["poi"], "marché")

    def test_pas_de_signal_sans_tendance_ni_donnees(self):
        funnel = Counter()
        self.assertIsNone(S.scan_s5(lambda tf, force=False: None, 1_760_000_000, funnel, 2, True, "limit"))
        flat = [{"epoch": 1_700_000_000 + i * 3600, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0} for i in range(300)]
        self.assertIsNone(S.scan_s5(lambda tf, force=False: flat, 1_700_000_000 + 300 * 3600, funnel, 2, True, "limit"))
        self.assertEqual(funnel["S5_signal"], 0)

    def test_scan_all_accepte_une_liste(self):
        from unittest import mock
        a, b = {"strat": "S5", "key": "S5|BUY|x"}, {"strat": "S5", "key": "S5|SELL|y"}
        for ret, n in (([a, b], 2), (a, 1), (None, 0), ([], 0)):
            funnel = Counter()
            with mock.patch.object(S, "STRATEGIES", [("S5", lambda *args: ret)]):
                out = S.scan_all(lambda tf, force=False: None, 0, funnel)
            self.assertEqual(len(out), n)
            self.assertEqual(funnel["signal"], n)

    def test_message_des_quatre_formats(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        sig = next(x for x in S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") if x["extra"]["cascade"] == "H4>H1>M15")
        sig.update(sym="frxEURUSD", name="EURUSD", dec=3, ts=t + 60, age_min=1.0, trend_lines=[], trend_short="")
        for fmt in ("complet", "compact", "minimal", "contexte"):
            os.environ["ALERT_FORMAT"] = fmt
            try:
                txt = gold.gold_message(sig, 7)
            finally:
                os.environ.pop("ALERT_FORMAT", None)
            self.assertIn("Impulsion", txt)
            self.assertIn("SELL", txt)
        os.environ["ALERT_FORMAT"] = "complet"
        try:
            self.assertIn("SELL LIMIT", gold.gold_message(sig, 7))
        finally:
            os.environ.pop("ALERT_FORMAT", None)



# ==========================================================================
# Confluence : étiquette quand plusieurs stratégies s'accordent (aucun filtre)
# ==========================================================================
class ConfluenceStrategies(unittest.TestCase):
    NOW = 1_760_000_000

    def sig(self, strat="S2", d="BUY", sym="frxXAUUSD"):
        return {"strat": strat, "label": S.STRAT_LABELS[strat], "sym": sym, "dir": d, "details": ["✅ test"],
                "short": "setup", "extra": {}}

    def trade(self, tr, strat, d="BUY", sym="frxXAUUSD", age=600, status=None, with_code=True):
        t = T.new_trade("OR", f"{strat}|{sym}|{d}|{age}", sym, sym[3:], d, "BUY LIMIT" if d == "BUY" else "SELL LIMIT",
                        100.0, 99.0, 101.0, 102.0, 103.0, "M5", 300, 2, S.STRAT_LABELS[strat], self.NOW - age, 3600,
                        extra={"strat": strat} if with_code else None)
        if status:
            t["status"] = status
        tr["active"][t["key"]] = t
        return t

    def test_registre_coherent(self):
        self.assertEqual(sorted(S.STRAT_LABELS), [c for c, _ in S.STRATEGIES])
        self.assertEqual(gold.LABEL_CODE["Sweep + CHoCH"], "S2")
        self.assertEqual(gold.LABEL_CODE["Mean Reversion"], "S3")
        self.assertEqual((gold.LABEL_CODE["Trend Pullback"], gold.LABEL_CODE["Impulsion"]), ("S1", "S1"))   # libellés d'avant la fusion

    def test_aucune_confluence(self):
        sig = gold.add_confluence(self.sig(), {"active": {}, "closed": []}, [], self.NOW)
        self.assertEqual(sig["confluence"], [])
        self.assertEqual(sig["extra"]["confluence"], "aucune")
        self.assertEqual((sig["details"], sig["short"]), (["✅ test"], "setup"))

    def test_trade_actif_meme_sens(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", age=600)
        sig = gold.add_confluence(self.sig("S2"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], ["S3"])
        self.assertEqual(sig["extra"]["confluence"], "S2+S3")
        self.assertIn("⚡ Confluence : S3 Mean Reversion (il y a 10 min)", sig["details"])
        self.assertTrue(sig["short"].endswith("confluence S3"))
        self.assertEqual(sig["details"][0], "✅ test")

    def test_ce_qui_ne_compte_pas(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", d="SELL")                                   # autre sens
        self.trade(tr, "S1", sym="frxEURUSD")                            # autre actif
        self.trade(tr, "S3", age=3601)                                   # hors fenêtre (60 min)
        self.trade(tr, "S2", age=60)                                     # même stratégie
        self.trade(tr, "S3", age=60, status="cancelled")                 # ordre annulé
        done = self.trade(tr, "S1", age=61)                              # trade déjà clôturé : archivé, il ne compte pas
        done["status"] = "closed"
        T.archive(tr, done["key"])
        self.assertEqual(len(tr["closed"]), 1)
        sig = gold.add_confluence(self.sig("S2"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], [])
        self.assertEqual(sig["extra"]["confluence"], "aucune")

    def test_fenetre_limite_incluse(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", age=3600)
        self.assertEqual(gold.add_confluence(self.sig("S2"), tr, [], self.NOW)["confluence"], ["S3"])

    def test_trade_sans_code_retrouve_par_libelle(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", with_code=False)
        self.assertEqual(gold.add_confluence(self.sig("S2"), tr, [], self.NOW)["confluence"], ["S3"])

    def test_meme_scan_dans_les_deux_sens(self):
        a, b, same = self.sig("S2"), self.sig("S3"), self.sig("S3")
        batch = [a, b, same]
        for sg in batch:
            gold.add_confluence(sg, {"active": {}, "closed": []}, batch, self.NOW)
        self.assertEqual(a["confluence"], ["S3"])
        self.assertEqual(b["confluence"], ["S2"])            # la S3 ne se compte pas elle-même, même en double
        self.assertEqual(b["extra"]["confluence"], "S2+S3")
        self.assertIn("au même scan", " ".join(a["details"]))

    def test_plusieurs_strategies(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", age=300)
        self.trade(tr, "S1", age=900)
        sig = gold.add_confluence(self.sig("S2"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], ["S1", "S3"])
        self.assertEqual(sig["extra"]["confluence"], "S1+S2+S3")

    def test_desactivee(self):
        from unittest import mock
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3")
        with mock.patch.object(gold, "CONFLUENCE_MIN", 0):
            sig = gold.add_confluence(self.sig("S2"), tr, [], self.NOW)
        self.assertEqual((sig["confluence"], sig["extra"]["confluence"]), ([], "aucune"))

    def test_lecture_du_reglage(self):
        for txt, want in (("", 60.0), (None, 60.0), ("abc", 60.0), ("30", 30.0), ("0", 0.0), ("-5", 0.0), ("90,5", 90.5)):
            self.assertEqual(gold.parse_confluence(txt), want, txt)

    def test_colonne_du_backtest(self):
        ts = [{"confluence": "S2+S3", "r": 1.0, "result": "tp"}, {"confluence": "aucune", "r": -1.0, "result": "sl"},
              {"r": 0.5, "result": "tp"}]
        rows = " | ".join(B.breakdown(ts, "confluence"))
        self.assertIn("confluence S2+S3", rows)
        self.assertIn("confluence aucune", rows)

    def test_backtest_marque_la_confluence_sur_les_trades(self):
        from unittest import mock
        m5 = B.gen_sim(3, 1)
        steps = {"n": 0}

        def fake_scan(sym, provide, now, sent, funnel, news=()):
            steps["n"] += 1
            if steps["n"] not in (50, 51):                     # deux alertes seulement : S2 puis S3, 5 min plus tard
                return []
            px = provide("M5")[-1]["close"]
            strat = "S2" if steps["n"] == 50 else "S3"
            return [({"strat": strat, "label": S.STRAT_LABELS[strat], "sym": sym, "name": "EURUSD", "dir": "BUY",
                      "otype": "BUY", "entry": px, "sl": px - 5, "tp1": px + 5, "tp2": px + 10, "tp3": px + 15,
                      "ltf": "M5", "gran": 300, "dec": 5, "ttl": None, "inval": None, "session": "Londres",
                      "key": f"{sym}|{strat}|{now}", "details": [], "short": "x", "extra": {}}, [])]
        for one_per_side in (False, True):
            steps["n"] = 0
            with mock.patch.object(gold, "scan", fake_scan), mock.patch.object(G, "ONE_TRADE_PER_SIDE", one_per_side):
                tr, _, _ = B.run(m5, "frxEURUSD", spread_pct=0.0, warmup_days=0, progress=False)
            trades = list(tr["active"].values()) + tr["closed"]
            by = {t["strat"]: t["confluence"] for t in trades}
            if one_per_side:     # un seul trade par actif et par sens : la seconde stratégie est bloquée, il reste le premier trade
                self.assertEqual(by, {"S2": "aucune"})
            else:                # une par stratégie : la seconde alerte porte la confluence, pas la première
                self.assertEqual(by, {"S2": "aucune", "S3": "S2+S3"})

    def test_messages_des_quatre_formats(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        sig = next(x for x in S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") if x["extra"]["cascade"] == "H4>H1>M15")
        sig.update(sym="frxEURUSD", name="EURUSD", dec=3, ts=t + 60, age_min=1.0, trend_lines=[], trend_short="")
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S2", d="SELL", sym="frxEURUSD", age=300)
        tr["active"] = {k: dict(v, t0=t + 60 - 300) for k, v in tr["active"].items()}
        gold.add_confluence(sig, tr, [], t + 60)
        self.assertEqual(sig["confluence"], ["S2"])
        for fmt in ("complet", "compact", "minimal", "contexte"):
            os.environ["ALERT_FORMAT"] = fmt
            try:
                txt = gold.gold_message(sig, 7)
            finally:
                os.environ.pop("ALERT_FORMAT", None)
            self.assertIn("S2", txt, fmt)
            self.assertIn("⚡" if fmt in ("complet", "minimal") else "confluence", txt, fmt)



# ==========================================================================
# Classes d'actifs : simple regroupement, aucun filtre de stratégie
# ==========================================================================
class ClassesDActifs(unittest.TestCase):
    TOUTES = ["S1", "S2", "S3"]

    def setUp(self):
        self._enabled = gold.ENABLED
        gold.ENABLED = list(self.TOUTES)

    def tearDown(self):
        gold.ENABLED = self._enabled

    def test_filtre_par_classe_supprime(self):
        for name in ("CLASS_FILTER", "CLASS_TIERS", "DEFAULT_CLASS_TIERS", "TIER_MAX", "TIER_NAMES", "tier_of", "add_tier",
                     "parse_class_strats", "parse_tier_max"):
            self.assertFalse(hasattr(gold, name), name)

    def test_toutes_les_strategies_sur_chaque_actif(self):
        for sym in gold.ALL_SYMBOLS + ["frxINCONNU"]:
            self.assertEqual(gold.strategies_for(sym), self.TOUTES, sym)
        gold.ENABLED = ["S1", "S2"]                  # la variable STRATEGIES reste la seule restriction globale
        for sym in gold.ALL_SYMBOLS:
            self.assertEqual(gold.strategies_for(sym), ["S1", "S2"], sym)

    def test_reglage_manuel_par_actif(self):
        from unittest import mock
        with mock.patch.dict(gold.SYMBOL_OVERRIDES, {"frxEURUSD": ["S3"]}):
            self.assertEqual(gold.strategies_for("frxEURUSD"), ["S3"])
            self.assertEqual(gold.strategies_for("frxGBPUSD"), self.TOUTES)            # les autres gardent toutes les stratégies

    def test_les_classes_couvrent_tous_les_actifs_une_fois(self):
        listed = [s for _, syms in gold.ASSET_CLASSES.values() for s in syms]
        self.assertEqual(sorted(listed), sorted(gold.ALL_SYMBOLS))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(gold.ASSET_CLASSES["synthetique"][1], gold.SYNTHETICS)
        self.assertEqual(gold.CLASS_OF["frxXAUUSD"], "or")
        self.assertEqual(gold.CLASS_OF["frxGBPJPY"], "forex_jpy")
        self.assertEqual(gold.CLASS_OF["cryETHUSD"], "crypto")
        self.assertEqual(gold.CLASS_OF["frxEURCHF"], "forex_calme")

    def test_classe_ajoutee_au_signal_sans_marquage(self):
        base = lambda: {"strat": "S1", "details": ["✅ x"], "short": "setup", "extra": {}}
        a = gold.add_class(base(), "frxXAUUSD")
        self.assertEqual(a["extra"], {"classe": "Or"})
        self.assertEqual((a["details"], a["short"]), (["✅ x"], "setup"))               # ni ligne ajoutée, ni marquage
        self.assertEqual(gold.add_class(base(), "R_100")["extra"]["classe"], "Indices synthétiques")
        self.assertEqual(gold.add_class(base(), "frxINCONNU")["extra"]["classe"], "Hors classe")

    def test_resolution_des_actifs_du_backtest(self):
        self.assertEqual(gold.resolve_symbols("all"), gold.ALL_SYMBOLS)
        self.assertEqual(gold.resolve_symbols("synth"), gold.SYNTHETICS)
        self.assertEqual(gold.resolve_symbols("forex_jpy"), ["frxUSDJPY", "frxEURJPY", "frxGBPJPY", "frxAUDJPY"])
        self.assertEqual(len(gold.resolve_symbols("forex")), 15)
        self.assertEqual(gold.resolve_symbols("or, crypto"), ["frxXAUUSD", "cryBTCUSD", "cryETHUSD"])
        self.assertEqual(gold.resolve_symbols("frxEURUSD,forex_jpy,frxEURUSD"), ["frxEURUSD", "frxUSDJPY", "frxEURJPY", "frxGBPJPY", "frxAUDJPY"])
        self.assertEqual(gold.resolve_symbols("frxXYZ"), ["frxXYZ"])

    def test_scan_donne_toutes_les_strategies_a_chaque_actif(self):
        from unittest import mock
        data = B.gen_sim(20, 4)
        rp = B.Replay(data)
        t = 5000
        provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
        for sym in ("frxUSDJPY", "frxXAUUSD", "frxEURUSD", "cryBTCUSD", "frxUSDCHF", "R_75"):
            seen = {}

            def fake(provide, now, funnel, only=None, dec=2, kz=True, modes=None, _seen=seen):
                _seen["only"] = only
                return []
            with mock.patch.object(S, "scan_all", fake):
                gold.scan(sym, provide, data[t]["epoch"] + 300, {}, Counter(), ())
            self.assertEqual(sorted(seen.get("only", [])), sorted(self.TOUTES), sym)


class TestBougieDeFillEtSpreads(unittest.TestCase):
    """Hypothèses prudentes du suivi (bougie de fill, stop remonté) et spreads par actif."""

    @staticmethod
    def _trade(otype):
        return T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", "BUY", otype, 100, 98, 102, 104, 106,
                           "M5", 300, 2, "c", 1000, 3600)

    def test_ordre_limite_rempli_aucun_objectif_dans_la_meme_bougie(self):
        t = self._trade("BUY LIMIT")
        ev = T.advance(t, [{"epoch": 1200, "open": 101, "high": 103, "low": 99.5, "close": 100.5}], 1600)
        self.assertEqual(ev, ["filled"])
        self.assertEqual((t["status"], t["stage"]), ("open", 0))
        ev = T.advance(t, [{"epoch": 1500, "open": 100.5, "high": 103, "low": 100.2, "close": 102.5}], 1900)
        self.assertEqual(ev, ["tp1"])                          # l'objectif compte à la bougie suivante

    def test_ordre_limite_rempli_et_stop_touche_dans_la_meme_bougie(self):
        t = self._trade("BUY LIMIT")
        ev = T.advance(t, [{"epoch": 1200, "open": 101, "high": 101, "low": 97, "close": 97.5}], 1600)
        self.assertEqual(ev, ["filled", "sl"])                 # le stop reste évalué (prudent)

    def test_retour_a_l_entree_dans_la_bougie_de_tp1_ferme_a_break_even(self):
        t = self._trade("BUY")
        ev = T.advance(t, [{"epoch": 1200, "open": 100.5, "high": 102.5, "low": 99, "close": 99.5}], 1600)
        self.assertEqual(ev, ["tp1", "be"])
        self.assertEqual((t["status"], t["result"]), ("closed", "TP1+BE"))
        self.assertAlmostEqual(t["r"], 0.5 * 1.0, places=2)    # moitié à TP1 (+1 R), reste à l'entrée

    def test_spread_par_actif(self):
        for k in ("SPREAD_TABLE", "SPREAD_PCT"):
            os.environ.pop(k, None)
        defaut = gold.spread_pct("frxXAUUSD")
        os.environ["SPREAD_TABLE"] = "frxXAUUSD=0.03, frxEURUSD=0.008,mauvais,cryBTCUSD=abc"
        try:
            self.assertEqual(gold.spread_pct("frxXAUUSD"), 0.03)
            self.assertEqual(gold.spread_pct("frxEURUSD"), 0.008)
            self.assertEqual(gold.spread_pct("cryBTCUSD"), gold.SPREAD_DEFAULT["cryBTCUSD"])   # valeur invalide ignorée
            os.environ["SPREAD_PCT"] = "0.5"
            self.assertEqual(gold.spread_pct("frxXAUUSD"), 0.03)    # la table l'emporte sur SPREAD_PCT
            self.assertEqual(gold.spread_pct("frxGBPUSD"), 0.5)
        finally:
            os.environ.pop("SPREAD_TABLE", None)
            os.environ.pop("SPREAD_PCT", None)
        self.assertEqual(gold.spread_pct("frxXAUUSD"), defaut)

    def test_workflow_transmet_les_variables_documentees(self):
        with open(os.path.join(os.path.dirname(__file__), ".github", "workflows", "gold.yml"), encoding="utf-8") as f:
            wf = f.read()
        for k in ("SPREAD_TABLE", "SYNTH_RECAP_HEURES", "ALERT_FUSEAU_NOM", "SPREAD_PCT"):
            self.assertIn(f"{k}: ${{{{ vars.{k} }}}}", wf, k)


class TestIntervalleParJours(unittest.TestCase):
    def test_bootstrap_par_jours_plus_large_quand_les_trades_d_un_jour_sont_correles(self):
        # 40 jours, 5 trades par jour qui finissent tous pareil : le bootstrap par trade sous-estime l'incertitude
        rs, jours = [], []
        for j in range(40):
            r = 1.0 if j % 2 else -1.0
            rs += [r] * 5
            jours += [j] * 5
        lo1, hi1 = B.mean_ci(rs)
        lo2, hi2 = B.mean_ci(rs, groups=jours)
        self.assertGreater(hi2 - lo2, hi1 - lo1)

    def test_verdict_et_avertissement_tests_multiples(self):
        rs = [1.0, -1.0] * 20
        self.assertIn("jours rééchantillonnés", B.verdict(rs, groups=list(range(len(rs)))))
        ts = [{"sym": "frxXAUUSD", "cascade": "A", "r": 1.0}, {"sym": "frxEURUSD", "cascade": "B", "r": -1.0}]
        self.assertIn("2 combinaisons", B.multiple_tests_warning(ts))
        self.assertIsNone(B.multiple_tests_warning(ts[:1]))


class TestFormatEssentiel(unittest.TestCase):
    @staticmethod
    def _sig(**kw):
        sig = {"label": "Sweep + CHoCH", "dir": "SELL", "otype": "SELL LIMIT", "sym": "frxXAUUSD", "name": "XAUUSD",
               "dec": 2, "ltf": "M15", "session": "Londres", "entry": 4012.5, "price_now": 4010.0, "sl": 4018.2,
               "tp1": 4001.3, "tp2": 3992.4, "tp3": 3980.1, "short": "x", "details": [], "ttl": 7200, "ts": 1_700_000_000}
        sig.update(kw)
        return sig

    def _msg(self, sig, tid=12):
        os.environ["ALERT_FORMAT"] = "essentiel"
        try:
            return gold.gold_message(sig, tid)
        finally:
            os.environ.pop("ALERT_FORMAT", None)

    def test_ordre_limite_trois_lignes(self):
        txt = self._msg(self._sig())
        lines = txt.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertIn("SELL LIMIT", lines[0])
        self.assertIn("XAUUSD M15", lines[0])
        self.assertNotIn("⚡", txt)
        for v in ("4012.50", "4018.20", "4001.30", "3992.40", "3980.10"):
            self.assertIn(v, lines[1])
        self.assertTrue(lines[2].startswith("Valable"))
        self.assertTrue(lines[2].endswith("#12"))

    def test_confluence_dans_le_nom_de_la_strategie(self):
        txt = self._msg(self._sig(confluence=["S3"]))
        self.assertIn("⚡ Sweep + CHoCH + ", txt.split("\n")[0])
        self.assertIn(S.STRAT_LABELS["S3"], txt.split("\n")[0])

    def test_age_affiche_seulement_si_alerte_tardive(self):
        self.assertNotIn("signal il y a", self._msg(self._sig(age_min=1.0)))
        txt = self._msg(self._sig(age_min=7.0))
        self.assertIn("signal il y a 7 min", txt)
        self.assertEqual(len(txt.split("\n")), 3)

    def test_ordre_au_marche_et_signal_test(self):
        txt = self._msg(self._sig(dir="BUY", otype="BUY"), tid=13)
        lines = txt.split("\n")
        self.assertEqual(lines[0].split(" · ")[0].split()[-1], "BUY")
        self.assertNotIn("🧪", lines[0])
        self.assertIn("Marché", lines[1])
        self.assertEqual(lines[2], "#13")


class TestRemplissageEtCouts(unittest.TestCase):
    @staticmethod
    def _trade(otype, entry=100.0, fill_buf=0.0):
        sl, tps = (98.0, (102, 104, 106)) if otype.startswith("BUY") else (102.0, (98, 96, 94))
        t = T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", otype.split()[0], otype, entry, sl, *tps,
                        "M5", 300, 2, "c", 1000, 3600)
        t["fill_buf"] = fill_buf
        return t

    def test_ordre_limite_exige_de_traverser_le_niveau_du_demi_spread(self):
        t = self._trade("BUY LIMIT", fill_buf=0.2)
        T.advance(t, [{"epoch": 1200, "open": 101, "high": 101, "low": 99.9, "close": 100.5}], 1600)
        self.assertEqual(t["status"], "pending")                # touché mais pas traversé : pas rempli
        T.advance(t, [{"epoch": 1500, "open": 100.5, "high": 101, "low": 99.7, "close": 100.5}], 1900)
        self.assertEqual(t["status"], "open")
        s = self._trade("SELL LIMIT", fill_buf=0.2)
        T.advance(s, [{"epoch": 1200, "open": 99, "high": 100.1, "low": 99, "close": 99.5}], 1600)
        self.assertEqual(s["status"], "pending")
        T.advance(s, [{"epoch": 1500, "open": 99, "high": 100.3, "low": 99, "close": 99.5}], 1900)
        self.assertEqual(s["status"], "open")

    def test_sans_fill_buf_comportement_inchange(self):
        t = self._trade("BUY LIMIT")
        T.advance(t, [{"epoch": 1200, "open": 101, "high": 101, "low": 99.95, "close": 100.5}], 1600)
        self.assertEqual(t["status"], "open")

    def test_cout_moyen_par_strategie(self):
        ts = [{"cascade": "A", "r": 0.9, "cost_r": 0.1}, {"cascade": "A", "r": -1.1, "cost_r": 0.1},
              {"cascade": "B", "r": 0.0, "cost_r": 0.3}]
        rows = B.cost_lines(ts)
        self.assertEqual(len(rows), 2)
        self.assertIn("A : coût 0.10 R/trade", rows[0])
        self.assertIn("-0.10 après", rows[0])
        self.assertIn("+0.30 R/trade avant coût", rows[1])


class TestBilanHebdomadaire(unittest.TestCase):
    NOW = 1_800_000_000

    def _tr(self, specs):
        closed = [{"name": n, "cascade": c, "r": r, "t_close": self.NOW - j * 86400, "t0": self.NOW - j * 86400 - 600}
                  for (n, c, r, j) in specs]
        return {"closed": closed, "active": {}}

    def _g(self):
        return {"funnel": {"OR": {"alert": 28, "stale": 21, "blackout": 2, "dedupe": 1, "risk": 6, "data": 999}}}

    def test_bilan_court_sans_repetition(self):
        tr = self._tr([("OR", "Sweep + CHoCH", 1.4, 1), ("OR", "Sweep + CHoCH", 1.4, 2),
                       ("OR", "Mean Reversion", -1.1, 2), ("OR", "Mean Reversion", 3.0, 3)])
        txt = G.build_report(self._g(), tr, self.NOW)
        lines = txt.split("\n")
        self.assertEqual(lines[0], "📊 Bilan hebdomadaire")
        self.assertTrue(lines[1].startswith("7 j : 4 trades"))
        self.assertEqual(lines[2], "30 j : identique")
        self.assertLess(txt.index("Sweep + CHoCH"), txt.index("Mean Reversion"))     # meilleure stratégie d'abord
        self.assertNotIn("Par actif", txt)                                              # un seul actif : pas de ligne en plus
        self.assertNotIn("Entonnoir", txt)
        self.assertIn("alertes : 28", txt)
        self.assertIn("tardifs 21 · news/horaire 2 · doublons 1 · risque 6", txt)
        self.assertNotIn("données", txt)
        self.assertLess(len(lines), 12)

    def test_trente_jours_differents_et_plusieurs_actifs(self):
        tr = self._tr([("OR", "A", 1.0, 1), ("EURUSD", "A", -1.0, 2), ("OR", "A", 2.0, 20)])
        txt = G.build_report(self._g(), tr, self.NOW)
        self.assertTrue(any(l.startswith("30 j : 3 trades") for l in txt.split("\n")))
        self.assertIn("Par actif : OR +1.0 R (1) · EURUSD -1.0 R (1)", txt)

    def test_aucun_trade(self):
        txt = G.build_report({"funnel": {}}, {"closed": [], "active": {}}, self.NOW)
        self.assertIn("7 j : aucun trade clôturé", txt)
        self.assertIn("Trades actifs : 0 · alertes : 0", txt)


class TestSurveillanceEtVariables(unittest.TestCase):
    ENV_RE = re.compile(r'(?:getenv|environ\.get|environ)\(?\[?\s*"([A-Z][A-Z0-9_]+)"')

    def _lire(self, nom):
        with open(os.path.join(os.path.dirname(__file__), nom), encoding="utf-8") as f:
            return f.read()

    def test_toute_variable_lue_par_le_code_est_transmise_par_le_workflow(self):
        wf = self._lire(os.path.join(".github", "workflows", "gold.yml"))
        manquantes = []
        for fichier in glob.glob(os.path.join(os.path.dirname(__file__), "*.py")):
            if fichier.endswith("tests.py"):
                continue
            with open(fichier, encoding="utf-8") as f:
                for nom in self.ENV_RE.findall(f.read()):
                    if nom.startswith("GITHUB_") or f"{nom}:" in wf:
                        continue
                    manquantes.append(nom)
        self.assertEqual(sorted(set(manquantes)), [], "variables lues par le code mais absentes de gold.yml")

    def test_le_backtest_recoit_les_variables_qui_changent_ses_resultats(self):
        wf = self._lire(os.path.join(".github", "workflows", "backtest.yml"))
        for nom in ("SPREAD_TABLE", "SYMBOL_STRATEGIES", "CONFLUENCE_MIN",
                    "ENTRY_MODE", "ENTRY_MODES", "WEEKEND_EXIT", "INTRADAY", "INTRADAY_RUNNERS"):
            self.assertIn(f"{nom}:", wf, nom)

    def test_variable_vide_ne_casse_pas_l_url_deriv(self):
        src = self._lire("gold.py")
        self.assertIn('os.getenv("DERIV_APP_ID") or "1089"', src)

    def test_ping_de_surveillance(self):
        appels = []
        vrai = gold.requests.get
        gold.requests.get = lambda url, timeout=0: appels.append((url, timeout))
        try:
            os.environ.pop("HEARTBEAT_URL", None)
            self.assertFalse(gold.ping_heartbeat())
            self.assertEqual(appels, [])
            os.environ["HEARTBEAT_URL"] = "https://hc-ping.example/abc"
            self.assertTrue(gold.ping_heartbeat())
            self.assertEqual(appels, [("https://hc-ping.example/abc", 10)])
            def boom(url, timeout=0):
                raise RuntimeError("réseau")
            gold.requests.get = boom
            self.assertFalse(gold.ping_heartbeat())                   # n'interrompt jamais le bot
        finally:
            gold.requests.get = vrai
            os.environ.pop("HEARTBEAT_URL", None)

    def test_bilan_indique_combien_de_trades_pour_valider(self):
        tr = {"closed": [{"name": "OR", "cascade": "A", "r": 1.0, "t_close": 1_799_000_000, "t0": 1_798_999_000}], "active": {}}
        txt = G.build_report({"funnel": {}}, tr, 1_800_000_000)
        self.assertIn("Validation : 1 trades clôturés sur ~100", txt)


class TestCadreIntraday(unittest.TestCase):
    NY = ZoneInfo("America/New_York")

    def setUp(self):
        self._t, self._s = T.INTRADAY, S.INTRADAY
        T.INTRADAY = S.INTRADAY = True
        self._ho = S.htf_obstacles

    def tearDown(self):
        T.INTRADAY, S.INTRADAY = self._t, self._s
        S.htf_obstacles = self._ho

    def _ts(self, h, m=0, day=10):
        return int(datetime(2026, 11, day, h, m, tzinfo=self.NY).timestamp())

    def test_fin_de_seance(self):
        ts = self._ts(10)
        self.assertEqual(T.intraday_deadline(ts), self._ts(16, 45))                 # avant 16h45 : clôture le jour même
        ts = self._ts(20)
        self.assertEqual(T.intraday_deadline(ts), ts + 10 * 3600)                    # la nuit : durée maximale de 10 h
        ts = self._ts(17, 30)
        self.assertEqual(T.intraday_deadline(ts), ts + 10 * 3600)                    # après 16h45 : jamais plus de 10 h
        T.INTRADAY = False
        self.assertIsNone(T.intraday_deadline(self._ts(10)))
        self.assertEqual(T.intraday_ttl(86400, self._ts(10)), 86400)

    def test_ordre_en_attente_plafonne_a_la_fin_de_seance(self):
        ts = self._ts(14)
        self.assertEqual(T.intraday_ttl(86400, ts), 2 * 3600 + 45 * 60)
        self.assertEqual(T.intraday_ttl(3600, ts), 3600)

    def test_position_clôturée_en_fin_de_seance(self):
        t = T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", "BUY", "BUY", 100, 98, 102, 104, 106, "M5", 300, 2, "c", 1000, 3600,
                        extra={"eod": 2000})
        quiet = lambda ep: {"epoch": ep, "open": 100.5, "high": 101, "low": 99.5, "close": 100.8}
        self.assertEqual(T.advance(t, [quiet(1500)], 1800), [])
        self.assertEqual(T.advance(t, [quiet(1800)], 2100), ["eod"])
        self.assertEqual((t["status"], t["result"]), ("closed", "eod"))
        self.assertAlmostEqual(t["r"], 0.4, places=2)

    def test_fin_de_seance_ferme_aussi_le_reste_apres_tp1(self):
        mk = lambda: T.new_trade("OR", "k", "frxXAUUSD", "XAUUSD", "BUY", "BUY", 100, 98, 102, 104, 106, "M5", 300, 2, "c",
                                 1000, 3600, extra={"eod": 2000})
        c_tp1 = {"epoch": 1500, "open": 100.5, "high": 102.2, "low": 100.3, "close": 102.0}
        calme = {"epoch": 1800, "open": 102.0, "high": 102.5, "low": 101.0, "close": 101.5}
        t = mk()
        self.assertEqual(T.advance(t, [c_tp1], 1800), ["tp1"])
        self.assertEqual(T.advance(t, [calme], 2100), ["eod"])               # par défaut : forex et or, tout est clôturé
        self.assertEqual((t["status"], t["result"]), ("closed", "eod"))
        old = T.INTRADAY_RUNNERS
        T.INTRADAY_RUNNERS = True                                            # option : le reste court après TP1
        try:
            t = mk()
            T.advance(t, [c_tp1], 1800)
            self.assertEqual(T.advance(t, [calme], 2100), [])
            self.assertEqual(t["status"], "open")
            self.assertEqual(T.advance(t, [{"epoch": 2100, "open": 101.5, "high": 104.5, "low": 102.5, "close": 104.2}], 2400),
                             ["tp2"])
        finally:
            T.INTRADAY_RUNNERS = old

    def test_indices_synthetiques_sans_fin_de_seance(self):
        now = self._ts(10)
        self.assertIsNone(gold.intraday_exit("R_100", now))
        self.assertEqual(gold.intraday_ttl_for("R_100", 86400, now), 86400)
        self.assertEqual(gold.intraday_exit("frxXAUUSD", now), self._ts(16, 45))
        self.assertEqual(gold.intraday_exit("frxEURUSD", now), self._ts(16, 45))
        self.assertEqual(gold.intraday_ttl_for("frxXAUUSD", 86400, now), 6 * 3600 + 45 * 60)

    def test_cryptos_sans_fin_de_seance_par_defaut(self):
        now = self._ts(10)
        self.assertIsNone(gold.intraday_exit("cryBTCUSD", now))
        self.assertEqual(gold.intraday_ttl_for("cryETHUSD", 86400, now), 86400)
        old = gold.CRYPTO_INTRADAY
        gold.CRYPTO_INTRADAY = True                                                  # option : couper aussi les cryptos
        try:
            self.assertEqual(gold.intraday_exit("cryBTCUSD", now), self._ts(16, 45))
        finally:
            gold.CRYPTO_INTRADAY = old

    def _sig(self, strat="S1", d="BUY", entry=100.0, sl=98.0, tp1=106.0):
        k = 1 if d == "BUY" else -1
        return {"strat": strat, "dir": d, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp1 + 4 * k, "tp3": tp1 + 8 * k, "dec": 2,
                "details": []}

    def _obs(self, sup=(), res=()):
        S.htf_obstacles = lambda provide, now: {"sup": list(sup), "res": list(res), "atr": 2.0}

    def test_entree_sur_un_niveau_h4_h1(self):
        self._obs(sup=[(99.6, 99.6, "creux H1")])
        sig = self._sig()
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertIn("✅ Entrée sur creux H1", sig["details"])
        self._obs(sup=[(90.0, 90.0, "creux H4")])
        self.assertEqual(S.obstacle_filter(self._sig(), None, 0), "obst_entree")      # niveau trop loin (tolérance 1,0)
        self.assertIsNone(S.obstacle_filter(self._sig(strat="S3"), None, 0))

    def test_zone_contenant_l_entree(self):
        self._obs(sup=[(99.0, 100.5, "bloc d'ordre H1")])
        self.assertIsNone(S.obstacle_filter(self._sig(), None, 0))

    def test_objectif_ramene_avant_l_obstacle(self):
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(104.0, 104.0, "sommet H1")])
        sig = self._sig()
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertAlmostEqual(sig["tp1"], 104.0 - 0.1 * 2.0)                         # 0,1 ATR avant l'obstacle
        self.assertTrue(any(x.startswith("🧱 Obstacle sommet H1") for x in sig["details"]))
        # l'obstacle qui arrête TP1 arrête aussi TP2 et TP3 : tout le reste sort à ce niveau
        self.assertAlmostEqual(sig["tp2"], sig["tp1"])
        self.assertIsNone(sig["tp3"])

    def test_obstacle_entre_tp1_et_tp2_ne_touche_que_les_objectifs_suivants(self):
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(108.0, 108.0, "sommet H1")])   # TP1 106, TP2 110, TP3 114
        sig = self._sig()
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertEqual(sig["tp1"], 106.0)                                             # TP1 inchangé
        self.assertAlmostEqual(sig["tp2"], 108.0 - 0.1 * 2.0)                           # TP2 ramené avant l'obstacle
        self.assertIsNone(sig["tp3"])

    def test_obstacle_apres_tp2_ramene_seulement_tp3(self):
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(112.0, 112.0, "sommet H1")])
        sig = self._sig()
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertEqual((sig["tp1"], sig["tp2"]), (106.0, 110.0))
        self.assertAlmostEqual(sig["tp3"], 112.0 - 0.1 * 2.0)

    def test_obstacle_ne_cree_pas_de_tp3_absent(self):
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(120.0, 120.0, "sommet H1")])    # au-delà de tous les objectifs
        sig = self._sig(strat="S3")
        sig["tp3"] = None                                                               # Mean Reversion : pas de TP3
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertIsNone(sig["tp3"])
        self.assertEqual((sig["tp1"], sig["tp2"]), (106.0, 110.0))

    def test_s2_deja_sur_zone_h4_h1_pas_de_second_controle_d_entree(self):
        self._obs(sup=[(90.0, 90.0, "creux H4")])                                        # entrée loin de tout niveau
        self.assertEqual(S.obstacle_filter(self._sig(strat="S1"), None, 0), "obst_entree")
        self.assertIsNone(S.obstacle_filter(self._sig(strat="S2"), None, 0))
        old = S.S2_HTF_ZONE
        S.S2_HTF_ZONE = False                                                           # sans zone exigée au sweep : contrôle conservé
        try:
            self.assertEqual(S.obstacle_filter(self._sig(strat="S2"), None, 0), "obst_entree")
        finally:
            S.S2_HTF_ZONE = old

    def test_obstacle_trop_proche_ecarte_le_signal(self):
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(101.0, 101.0, "sommet H1")])   # 0,5 R seulement
        self.assertEqual(S.obstacle_filter(self._sig(), None, 0), "obst_cible")

    def test_ratio_minimum_recontrole_apres_obstacle(self):
        # entrée 100, stop 98 (R = 2) ; obstacle à 103 (1,5 R) : toléré par la règle des 1 R, mais TP1, TP2 et TP3 sont ramenés à 102,8
        self._obs(sup=[(100.0, 100.0, "creux H1")], res=[(103.0, 103.0, "sommet H1")])
        sig = self._sig(strat="S1")
        sig["rr_rule"] = [(2, 3.0)]                                                     # Pullback : 3 R minimum vers TP2
        self.assertEqual(S.obstacle_filter(sig, None, 0), "obst_rr")
        self.assertIsNone(S.obstacle_filter(self._sig(strat="S1"), None, 0))             # sans règle (S2, retournement) : le signal passe
        ok = self._sig(strat="S1")
        ok["rr_rule"] = [(3, 1.0)]                                                       # 1 R vers TP3 : l'objectif le plus lointain (102,8) suffit
        self.assertIsNone(S.obstacle_filter(ok, None, 0))
        s3 = self._sig(strat="S3")
        s3["tp3"] = None
        s3["rr_rule"] = [(1, 0.8), (2, 1.5)]
        self.assertEqual(S.obstacle_filter(s3, None, 0), "obst_rr")                      # TP2 ramené à 1,4 R : sous 1,5 R

    def test_rr_ok(self):
        sig = {"dir": "BUY", "entry": 100.0, "sl": 98.0, "tp1": 103.0, "tp2": 106.0, "tp3": None, "rr_rule": [(2, 3.0)]}
        self.assertTrue(S.rr_ok(sig))
        sig["tp2"] = 105.9
        self.assertFalse(S.rr_ok(sig))
        sell = {"dir": "SELL", "entry": 100.0, "sl": 102.0, "tp1": 98.0, "tp2": 96.0, "tp3": None, "rr_rule": [(3, 2.0)]}
        self.assertTrue(S.rr_ok(sell))                                                   # TP3 absent : l'objectif le plus lointain compte
        self.assertTrue(S.rr_ok({"dir": "BUY", "entry": 1.0, "sl": 0.5, "tp1": 2.0, "tp2": 3.0, "tp3": 4.0}))   # sans règle

    def test_vente_symetrique(self):
        self._obs(res=[(100.2, 100.2, "sommet H1")], sup=[(96.0, 96.0, "creux H1")])
        sig = self._sig(d="SELL", sl=102.0, tp1=94.0)
        self.assertIsNone(S.obstacle_filter(sig, None, 0))
        self.assertAlmostEqual(sig["tp1"], 96.0 + 0.2)

    def test_sans_donnees_le_signal_passe(self):
        S.htf_obstacles = lambda provide, now: None
        self.assertIsNone(S.obstacle_filter(self._sig(), None, 0))

    def test_obstacles_reels_sur_des_bougies(self):
        random.seed(3)
        def bougies(n, pas, base=2000.0, vol=2.0):
            out, p = [], base
            for i in range(n):
                o = p
                p = o + random.uniform(-vol, vol)
                out.append({"epoch": 1_790_000_000 + i * pas, "open": o, "high": max(o, p) + random.uniform(0, 1),
                            "low": min(o, p) - random.uniform(0, 1), "close": p})
            return out
        h1, h4, d1 = bougies(200, 3600), bougies(80, 14400, vol=5.0), bougies(12, 86400, vol=9.0)
        S.htf_obstacles = self._ho
        obs = S.htf_obstacles(lambda tf: {"H1": h1, "H4": h4, "D1": d1}[tf], 1_790_000_000 + 200 * 3600)
        self.assertIsNotNone(obs)
        self.assertGreater(obs["atr"], 0)
        self.assertTrue(obs["sup"] and obs["res"])
        self.assertTrue(all(lo <= hi for lo, hi, _ in obs["sup"] + obs["res"]))
        self.assertIsNone(S.htf_obstacles(lambda tf: None, 0))

    def test_cascade_s5_unique_en_intraday(self):
        self.assertEqual(S.S5_CASCADES_INTRADAY, [("H4", "H1", "M15")])
        self.assertIn(S.S5_CASCADES_INTRADAY[0], S.S5_CASCADES)


class TestCoherenceEntreStrategies(unittest.TestCase):
    """Règles ajoutées pour que les stratégies ne se contredisent pas."""

    def _add(self, tr, sym, d, label, strat=None, now=1e9):
        k = f"{sym}{d}{label}"
        tr["active"][k] = T.new_trade("OR", k, sym, sym[3:], d, d, 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, label, now, 3600,
                                      extra={"strat": strat} if strat else None)

    def test_s1_et_s5_sont_une_seule_famille(self):
        tr = {"active": {}, "closed": []}
        self._add(tr, "frxEURUSD", "BUY", "Trend Pullback")
        self.assertEqual(G.risk_check(tr, "frxEURUSD", "BUY", 1e9, "Impulsion"), (False, "dedupe"))
        self.assertEqual(G.risk_check(tr, "frxEURUSD", "BUY", 1e9, "Trend Pullback"), (False, "dedupe"))
        self.assertEqual(S.LABEL_FAMILY["Impulsion"], S.LABEL_FAMILY["Trend Pullback"])
        old_flag, G.ONE_TRADE_PER_SIDE = G.ONE_TRADE_PER_SIDE, False                         # règle par stratégie (ancien comportement)
        try:
            self.assertEqual(G.risk_check(tr, "frxEURUSD", "BUY", 1e9, "Impulsion"), (False, "dedupe"))
            self.assertTrue(G.risk_check(tr, "frxEURUSD", "BUY", 1e9, "Sweep + CHoCH")[0])      # autre famille : autorisée
        finally:
            G.ONE_TRADE_PER_SIDE = old_flag

    def test_pas_de_sens_oppose_sur_un_actif(self):
        tr = {"active": {}, "closed": []}
        self._add(tr, "frxEURUSD", "BUY", "Sweep + CHoCH")
        ok, why = G.risk_check(tr, "frxEURUSD", "SELL", 1e9, "Mean Reversion")
        self.assertFalse(ok)
        self.assertIn("opposé", why)
        self.assertTrue(G.risk_check(tr, "frxGBPUSD", "SELL", 1e9, "Mean Reversion")[0])    # autre actif : autorisé
        self.assertTrue(G.risk_check({"active": {}, "closed": []}, "frxEURUSD", "SELL", 1e9, "Mean Reversion")[0])

    def test_pas_de_confluence_entre_s1_et_s5(self):
        tr = {"active": {}, "closed": []}
        self._add(tr, "frxEURUSD", "BUY", "Trend Pullback", strat="S1")
        now = 1e9 + 60
        sig = lambda strat: {"sym": "frxEURUSD", "dir": "BUY", "strat": strat}
        self.assertEqual(gold.confluence_with(sig("S5"), tr, [], now), [])
        self.assertEqual([c for c, _, _ in gold.confluence_with(sig("S2"), tr, [], now)], ["S1"])
        # même scan : S1 et S5 trouvées ensemble ne se confirment pas, S1 et S2 oui
        batch = [sig("S1"), sig("S5"), sig("S2")]
        self.assertEqual([c for c, _, _ in gold.confluence_with(batch[1], {"active": {}, "closed": []}, batch, now)], ["S2"])

    def _candles(self, n, step, base=100.0):
        return [{"epoch": 1_790_000_000 + i * step, "open": base, "high": base + 0.5, "low": base - 0.5, "close": base}
                for i in range(n)]

    def test_s2_un_sweep_recent_contre_le_biais_ne_masque_pas_un_sweep_valide(self):
        m15 = self._candles(60, 900)
        # sweep d'un PDL (achat) il y a 6 bougies, puis sweep d'un PDH (vente) plus récent : le biais est haussier
        m15[-7] = dict(m15[-7], low=94.0, close=96.0)
        m15[-4] = dict(m15[-4], high=106.0, close=104.0)
        provide = lambda tf: {"D1": self._candles(5, 86400), "H4": self._candles(30, 14400), "H1": self._candles(60, 3600),
                              "M15": m15, "M5": self._candles(80, 300)}[tf]
        saved = (S.liquidity_levels, S.s2_bias, S._s2_setup, S.S2_BIAS_FILTER)
        seen = []
        S.liquidity_levels = lambda *a, **k: [("PDH", 105.0, "high", 0), ("PDL", 95.0, "low", 0)]
        S.s2_bias = lambda *a, **k: ("BUY", "H4")
        S._s2_setup = lambda cand, *a, **k: (seen.append(cand[3]) or {"sweep": cand[1]})
        S.S2_BIAS_FILTER = True
        try:
            sig = S.scan_s2(provide, 1_790_000_000 + 60 * 900, Counter(), 2, kz=False, mode="limit")
        finally:
            S.liquidity_levels, S.s2_bias, S._s2_setup, S.S2_BIAS_FILTER = saved
        self.assertEqual(sig, {"sweep": "PDL"})
        self.assertEqual(seen, ["low"])                  # seul le sweep dans le sens du biais est tenté

    def test_obstacles_utilisent_la_veille_de_s2(self):
        h1, h4 = self._candles(60, 3600), self._candles(30, 14400)
        d1 = self._candles(5, 86400)
        d1[-2] = dict(d1[-2], high=123.0, low=77.0)                                  # veille D1 de S2
        obs = S.htf_obstacles(lambda tf: {"H1": h1, "H4": h4, "D1": d1}[tf], 1_790_000_000 + 60 * 3600)
        self.assertIn((123.0, 123.0, "plus haut de la veille"), obs["res"])
        self.assertIn((77.0, 77.0, "plus bas de la veille"), obs["sup"])
        obs = S.htf_obstacles(lambda tf: {"H1": h1, "H4": h4, "D1": None}[tf], 1_790_000_000 + 60 * 3600)   # repli sans D1
        self.assertIsNotNone(obs)


class TestSmcPrimitives(unittest.TestCase):
    """smc.py : primitives communes à S1 (structure), S2 et aux zones d'entrée."""

    def c(self, o, h, l, cl):
        return {"epoch": 1, "open": o, "high": h, "low": l, "close": cl}

    def test_sweep_de_meche(self):
        import smc
        self.assertTrue(smc.wick_sweep(self.c(99, 102, 98, 99.5), 100, "high"))      # mèche au-dessus, clôture dessous
        self.assertFalse(smc.wick_sweep(self.c(99, 102, 98, 101), 100, "high"))      # clôture au-dessus : vraie cassure
        self.assertTrue(smc.wick_sweep(self.c(101, 102, 98, 100.5), 100, "low"))
        self.assertFalse(smc.wick_sweep(self.c(101, 102, 100.5, 101), 100, "low"))   # mèche n'atteint pas le niveau

    def test_cassure_et_deplacement(self):
        import smc
        a, b = self.c(99, 100, 98, 99.5), self.c(99.5, 102, 99, 101)
        self.assertTrue(smc.fresh_break(b, a, 100, True))
        self.assertFalse(smc.fresh_break(b, b, 100, True))                            # déjà au-dessus à la clôture précédente
        self.assertTrue(smc.close_beyond(b, 100, True) and not smc.close_beyond(b, 100, False))
        self.assertTrue(smc.is_displacement(b, 1.0, 1.2) and not smc.is_displacement(a, 1.0, 1.2))
        self.assertTrue(smc.is_displacement(a, 0.0, 1.2))                             # corps moyen nul : tout corps passe

    def test_miroir_et_corps_moyen(self):
        import smc
        cs = [self.c(99, 100, 98, 99.5), self.c(99.5, 102, 99, 101)]
        self.assertEqual(smc.mirror(smc.mirror(cs)), cs)
        self.assertAlmostEqual(smc.mean_body(cs), (0.5 + 1.5) / 2)
        self.assertEqual(smc.mean_body([]), 0.0)

    def test_s1_et_s2_utilisent_les_memes_primitives(self):
        self.assertIs(S.wick_sweep, __import__("smc").wick_sweep)
        self.assertIs(S.is_displacement, __import__("smc").is_displacement)
        self.assertIs(S.mirror, __import__("smc").mirror)


class UnTradeParSens(unittest.TestCase):
    """Un seul trade par actif et par sens, toutes stratégies confondues."""

    def setUp(self):
        self.tr = {"active": {}, "closed": []}
        k = "k1"
        self.tr["active"][k] = T.new_trade("OR", k, "frxEURUSD", "EURUSD", "BUY", "BUY", 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2,
                                           "Pullback", 1e9, 3600)

    def test_deux_strategies_meme_sens_ne_doublent_pas_l_exposition(self):
        self.assertTrue(G.ONE_TRADE_PER_SIDE)                                              # actif par défaut
        for label in ("Pullback", "Sweep + CHoCH", "Mean Reversion", "Figures & Retournement"):
            self.assertEqual(G.risk_check(self.tr, "frxEURUSD", "BUY", 1e9, label), (False, "dedupe"), label)
        self.assertTrue(G.risk_check(self.tr, "frxGBPUSD", "BUY", 1e9, "Sweep + CHoCH")[0])   # autre actif : autorisé
        ok, why = G.risk_check(self.tr, "frxEURUSD", "SELL", 1e9, "Sweep + CHoCH")
        self.assertFalse(ok)
        self.assertIn("opposé", why)                                                          # le sens opposé reste refusé

    def test_option_pour_revenir_a_une_par_strategie(self):
        old, G.ONE_TRADE_PER_SIDE = G.ONE_TRADE_PER_SIDE, False
        try:
            self.assertEqual(G.risk_check(self.tr, "frxEURUSD", "BUY", 1e9, "Pullback"), (False, "dedupe"))
            self.assertTrue(G.risk_check(self.tr, "frxEURUSD", "BUY", 1e9, "Sweep + CHoCH")[0])
        finally:
            G.ONE_TRADE_PER_SIDE = old

    def test_un_trade_clos_libere_l_actif(self):
        self.tr["closed"].append(self.tr["active"].pop("k1"))
        self.assertTrue(G.risk_check(self.tr, "frxEURUSD", "BUY", 1e9, "Sweep + CHoCH")[0])

    def test_confluence_signalee_meme_si_un_seul_trade(self):
        sigs = [{"strat": "S1", "sym": "frxEURUSD", "dir": "BUY", "label": "Pullback", "key": "a", "extra": {}, "details": [], "short": "x"},
                {"strat": "S2", "sym": "frxEURUSD", "dir": "BUY", "label": "Sweep + CHoCH", "key": "b", "extra": {}, "details": [], "short": "y"}]
        empty = {"active": {}, "closed": []}
        gold.add_confluence(sigs[0], empty, sigs, 1000)
        self.assertEqual(sigs[0]["extra"].get("confluence"), "S1+S2")                        # le premier signal porte l'accord


class RrVisePuisObtenu(unittest.TestCase):
    """tracker.planned_rr / target_hits / target_lines : RR visé contre R obtenu."""

    def trade(self, **kw):
        base = dict(entry=100.0, sl=98.0, tp1=102.0, tp2=104.0, tp3=106.0, tp1_hit=False, stage=0, result="SL", r=-1.0,
                    cascade="Pullback")
        base.update(kw)
        return base

    def test_rr_vise_pondere(self):
        self.assertEqual(T.planned_rr(self.trade()), (1.0, 2.0, 3.0, 1.75))                # 0,5 x 1 + 0,25 x 2 + 0,25 x 3
        r = T.planned_rr(self.trade(tp1=101.0, tp2=103.0, tp3=None))                       # sans TP3 : 50 % à TP1, 50 % à TP2
        self.assertEqual((r[0], r[1], r[2], r[3]), (0.5, 1.5, None, 1.0))
        self.assertIsNone(T.planned_rr(self.trade(sl=100.0)))                              # risque nul

    def test_objectifs_atteints(self):
        self.assertEqual(T.target_hits(self.trade()), (False, False, False))
        self.assertEqual(T.target_hits(self.trade(tp1_hit=True, stage=1, result="TP1+BE")), (True, False, False))
        self.assertEqual(T.target_hits(self.trade(tp1_hit=True, stage=2, result="TP2+stop")), (True, True, False))
        self.assertEqual(T.target_hits(self.trade(tp1_hit=True, stage=2, result="TP3")), (True, True, True))
        self.assertEqual(T.target_hits(self.trade(tp3=None, tp1_hit=True, stage=1, result="TP2")), (True, True, False))

    def test_lignes_par_strategie(self):
        ts = [self.trade(tp1_hit=True, stage=2, result="TP3", r=1.75),
              self.trade(),
              self.trade(cascade="Mean Reversion", tp1=101.0, tp2=103.0, tp3=None, tp1_hit=True, stage=1, result="TP2", r=1.0)]
        rows = T.target_lines(ts)
        self.assertEqual(len(rows), 2)
        mr, pb = rows                                                                      # ordre alphabétique des libellés
        self.assertIn("Mean Reversion : RR visé 1.00 (TP1 0.5 · TP2 1.5 · TP3 -) · R obtenu +1.00", mr)
        self.assertIn("capture 100 % du visé", mr)
        self.assertIn("Pullback : RR visé 1.75", pb)
        self.assertIn("R obtenu +0.38", pb)                                                # (1,75 - 1) / 2
        self.assertIn("atteints TP1 50 % · TP2 50 % · TP3 50 % (2 trades)", pb)
        self.assertEqual(T.target_lines([self.trade(r=None)]), [])                         # trade non clôturé : ignoré

    def test_present_dans_le_bilan_et_le_rapport_du_backtest(self):
        tr = {"active": {}, "closed": [dict(self.trade(tp1_hit=True, stage=2, result="TP3", r=1.75), t_close=1000, bot="OR")]}
        txt = T.stats_text(tr, 2000)
        self.assertIn("RR visé et R obtenu :", txt)
        self.assertIn("Pullback : RR visé 1.75", txt)
        rep = "\n".join(B.report([("frxEURUSD", {"closed": tr["closed"], "active": {}}, Counter(), Counter())], 30, 0.0))
        self.assertIn("RR visé et R obtenu par stratégie :", rep)


class TestCodesRenumerotes(unittest.TestCase):
    """Après la suppression d'Asian Breakout, les stratégies restantes sont numérotées S1 à S4 sans trou."""

    def test_numerotation(self):
        self.assertEqual([n for n, _ in S.STRATEGIES], ["S1", "S2", "S3", "S4"])
        self.assertEqual(S.STRAT_LABELS, {"S1": "Pullback", "S2": "Sweep + CHoCH", "S3": "Mean Reversion", "S4": "Figures & Retournement"})
        self.assertEqual(S.STRAT_ALIAS, {"S5": "S1", "S7": "S4"})                      # anciens codes de fusion
        self.assertEqual(gold.parse_strategies(""), ["S1", "S2", "S3", "S4"])
        self.assertEqual(gold.parse_strategies("S5, s7"), ["S1", "S4"])
        for name, code in (("scan_pullback", "S1"), ("scan_s2", "S2"), ("scan_s3", "S3"), ("scan_s4", "S4")):
            self.assertTrue(callable(getattr(S, name)), name)
            self.assertIs(dict(S.STRATEGIES)[code], getattr(S, name))

    def test_anciens_libelles_vers_les_nouveaux_codes(self):
        for label, code in (("Trend Pullback", "S1"), ("Impulsion", "S1"), ("Pullback", "S1"), ("Sweep + CHoCH", "S2"),
                            ("Mean Reversion", "S3"), ("Chart Patterns", "S4"), ("Reversal", "S4"), ("Figures & Retournement", "S4")):
            self.assertEqual(gold.LABEL_CODE[label], code, label)
        self.assertNotIn(gold.LABEL_CODE["Asian Breakout"], S.STRAT_LABELS)               # ancienne stratégie supprimée : aucun code actif

    def test_noms_de_variables_d_environnement_inchanges(self):
        import patterns, reversal
        src = open(os.path.join(os.path.dirname(__file__), "patterns.py"), encoding="utf-8").read()
        self.assertIn('_f("S6_MIN_RR"', src)                                             # les variables GitHub existantes gardent leur nom
        self.assertTrue(hasattr(patterns, "S4_MIN_RR") and hasattr(reversal, "S7_RISK_CAP_ATR"))

    def test_confluence_lit_le_libelle_avant_l_ancien_code(self):
        tr = {"active": {}, "closed": []}
        t = T.new_trade("gold", "k", "frxXAUUSD", "Or", "BUY", "BUY LIMIT", 100.0, 98.0, 102.0, 104.0, 106.0, "M15", 900, 2,
                        "Sweep + CHoCH", 1000, 3600, extra={"strat": "S3"})              # enregistré avant : « S3 » était Sweep + CHoCH
        t["status"] = "open"
        tr["active"]["k"] = t
        sig = {"strat": "S3", "sym": "frxXAUUSD", "dir": "BUY"}
        self.assertEqual(gold.confluence_with(sig, tr, [], 1000 + 60), [("S2", "Sweep + CHoCH", 1.0)])


class TestPullbackFusionne(unittest.TestCase):
    """S1 Pullback = l'ancienne S5 (structure + Fibonacci) ; la variante classique (ex-S1, EMA/ADX) est supprimée."""

    def test_classique_supprimee(self):
        for name in ("scan_s1", "s1_trend", "parse_variant", "PULLBACK_VARIANT", "S1_EMA_SLOW", "S1_ADX_MIN"):
            self.assertFalse(hasattr(S, name), name)
        self.assertFalse(hasattr(gold, "pullback_variants"))
        self.assertEqual(S.H4_EMA_FAST, 50)                                    # utilisée par le biais H4 de S2

    def test_pullback_renvoie_la_structure_sous_le_code_s1(self):
        from unittest import mock
        stub = lambda *a, **k: [{"strat": "S5", "label": "Impulsion", "extra": {}, "key": "S5|x"}]
        with mock.patch.object(S, "scan_s5", stub):
            out = S.scan_pullback(None, 0, Counter(), 2, True, "limit")
        self.assertEqual([(x["strat"], x["label"], x["extra"]["variante"]) for x in out], [("S1", "Pullback", "structure")])

    def test_variante_structure_sur_des_donnees_reelles_de_test(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        out = S.scan_pullback(provide, t + 60, Counter(), 3, True, "limit")
        self.assertTrue(out)
        sig = out[0]
        self.assertEqual((sig["strat"], sig["label"], sig["extra"]["variante"]), ("S1", "Pullback", "structure"))
        self.assertIn(sig["strat"], S.OBST_ENTRY_STRATS)                        # soumise au cadre intraday comme avant
        trade = T.new_trade("OR", "k", "frxEURUSD", "EURUSD", sig["dir"], sig["otype"], sig["entry"], sig["sl"], sig["tp1"],
                            sig["tp2"], sig["tp3"], sig["ltf"], sig["gran"], 3, sig["label"], t, 3600, extra=sig["extra"])
        self.assertEqual(trade["variante"], "structure")                         # colonne « variante » du backtest

    def test_option_adx_de_la_variante_structure(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        old = S.S5_ADX_MIN
        try:
            S.S5_ADX_MIN = 0
            self.assertTrue(S.scan_s5(provide, t + 60, Counter(), 3, True, "limit"))      # désactivée : comme avant
            S.S5_ADX_MIN = 1000                                                          # ADX impossible : plus aucun signal
            funnel = Counter()
            self.assertFalse(S.scan_s5(provide, t + 60, funnel, 3, True, "limit"))
            self.assertEqual(funnel["S5_adx"], 0)
        finally:
            S.S5_ADX_MIN = old

    def test_anciens_codes_et_libelles_reconnus(self):
        self.assertEqual(gold.canon_codes(["S1", "S5", "S2", "S5"]), ["S1", "S2"])
        self.assertEqual(gold.parse_sym_strats("frxEURUSD:S5,S2"), {"frxEURUSD": ["S1", "S2"]})
        self.assertEqual(S.STRAT_LABELS["S1"], "Pullback")
        tr = {"active": {}, "closed": []}                                        # trade enregistré avant la fusion
        k = "old"
        tr["active"][k] = T.new_trade("OR", k, "frxEURUSD", "EURUSD", "BUY", "BUY", 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, "Impulsion", 1e9, 3600)
        self.assertEqual(G.risk_check(tr, "frxEURUSD", "BUY", 1e9, "Pullback"), (False, "dedupe"))


class RecapCompact(unittest.TestCase):
    """Récapitulatif réduit : une ligne par actif (RECAP_FORMAT=complet pour l'ancien format)."""

    def test_ligne_compacte(self):
        import trend as TR
        cs = zigzag(3)
        infos = {tf: TR.trend_info(cs, tf) for tf in TR.TIMEFRAMES}
        line = TR.symbol_line("XAUUSD", infos, cs[-1]["epoch"] + 600, 2)
        self.assertEqual(line.count("\n"), 0)
        self.assertTrue(line.startswith("XAUUSD  "))
        for tf in TR.TIMEFRAMES:
            self.assertIn(tf, line)
        self.assertNotIn("invalidation", line)
        none = TR.symbol_line("EURUSD", {}, 0, 5)
        self.assertEqual(none, "EURUSD  ⚪ D1 · ⚪ H4 · ⚪ H1")

    def _run(self, fmt):
        from unittest import mock
        sent, cs = [], zigzag(3)
        with mock.patch.object(gold, "tf_candles", lambda api, cache, sym, tf: cs), mock.patch.object(gold, "RECAP_FORMAT", fmt), \
                mock.patch.object(gold, "SYMBOLS", gold.ALL_SYMBOLS), \
                mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
            ok = gold.send_recap(None, {}, cs[-1]["epoch"] + 600)
        return ok, sent

    def test_recap_du_matin_plus_court(self):
        ok, short = self._run("compact")
        _, full = self._run("complet")
        self.assertTrue(ok)
        self.assertEqual(len(short), 4)                                            # toujours un message par classe
        self.assertLess(sum(map(len, short)), 0.5 * sum(map(len, full)))           # au moins deux fois plus court
        self.assertIn("Or · tendance", short[0])
        self.assertNotIn("avant l'ouverture de Londres", short[0])
        self.assertIn("Âge : naissante", short[0])                                 # légende courte, dans le premier message seulement
        self.assertTrue(all("Âge :" not in m for m in short[1:]))
        self.assertEqual(len([l for l in short[1].split("\n") if "D1" in l]), 7)  # une ligne par paire contre USD
        self.assertTrue(all("invalidation" not in m for m in short))

    def test_recap_du_soir_des_indices_plus_court(self):
        from unittest import mock
        outs = {}
        for fmt in ("compact", "complet"):
            sent, cs = [], zigzag(3)
            with mock.patch.object(gold, "tf_candles", lambda api, cache, sym, tf: cs), mock.patch.object(gold, "RECAP_FORMAT", fmt), \
                    mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
                self.assertTrue(gold.send_synth_recap(None, {}, cs[-1]["epoch"] + 600))
            outs[fmt] = sent
        short = outs["compact"]
        self.assertEqual(len(short), 2)
        self.assertLess(sum(map(len, short)), 0.5 * sum(map(len, outs["complet"])))
        self.assertIn("soir", short[0].split("\n")[0])
        for name in ("V10", "V25", "V50", "V75", "V100"):
            line = next(l for l in short[0].split("\n") if l.startswith(f"{name}  "))
            self.assertIn("biais S2", line)
            self.assertIn("jour ", line)

    def test_format_par_defaut_compact(self):
        self.assertEqual(gold.RECAP_FORMAT, "compact")


class RetournementPossible(unittest.TestCase):
    """Alerte d'information : tendance H4 mûre + sweep H1 sur un niveau majeur + cassure de structure + essoufflement."""

    @staticmethod
    def h1_sweep():
        cs = []

        def add(o, hi, lo, cl):
            cs.append({"epoch": 1_790_000_000 + len(cs) * 3600, "open": o, "high": hi, "low": lo, "close": cl})
        for i in range(60):                                   # hausse régulière, corps de 0,5, sans fractale
            p = 100 + 0.17 * i
            add(p, p + 0.7, p - 0.2, p + 0.5)
        add(110.0, 112.0, 109.6, 110.4)                        # 60 : sommet qui sera pris
        add(110.4, 110.8, 109.9, 110.3)
        add(110.3, 110.7, 109.8, 110.2)
        add(110.2, 110.6, 109.4, 110.1)
        add(110.1, 110.5, 108.0, 110.2)                        # 64 : creux
        add(110.2, 110.6, 110.2, 110.3)
        add(110.3, 110.7, 110.0, 110.4)
        add(110.4, 110.9, 109.6, 110.5)                        # 67 : creux de structure (pivot 109,6)
        add(110.5, 111.0, 110.3, 110.6)
        add(111.3, 113.0, 111.0, 111.2)                        # 69 : sweep du sommet 112, mèche haute longue
        add(111.2, 111.4, 109.3, 109.4)                        # 70 : clôture sous le pivot
        add(109.4, 109.8, 109.2, 109.5)                        # 71 : en formation
        return cs

    OBS_UP = {"res": [(112.0, 112.0, "sommet H4")], "sup": [], "atr": 1.0}
    TREND_UP = {"dir": "BUY", "age": "mûre", "legs": 5, "start_epoch": 1, "invalid": 100.0, "impulsive": False}

    def run_detect(self, h1=None, trend="up", obs="up", **patch):
        from unittest import mock
        import reversal as R
        h1 = h1 or self.h1_sweep()
        now = h1[-1]["epoch"] + 600
        provide = lambda tf: {"H4": h1[::4] or h1, "H1": h1, "D1": None}[tf]
        info = self.TREND_UP if trend == "up" else trend
        obstacles = self.OBS_UP if obs == "up" else obs
        with mock.patch.object(R.TR, "trend_info", lambda c, tf=None: info), \
                mock.patch.object(R.S, "htf_obstacles", lambda pr, n: obstacles), \
                (mock.patch.multiple(R, **patch) if patch else __import__("contextlib").nullcontext()):
            return R.detect(provide, now)

    def test_retournement_baissier_apres_tendance_haussiere_mure(self):
        rev = self.run_detect()
        self.assertIsNotNone(rev)
        self.assertEqual((rev["dir"], rev["trend_dir"], rev["age"]), ("SELL", "BUY", "mûre"))
        self.assertEqual(rev["level"], (112.0, "sommet H4"))
        self.assertEqual((rev["ext"], rev["pivot"]), (113.0, 109.6))
        self.assertEqual(rev["signs"], ["divergence RSI H1", "bougies qui rétrécissent", "mèche de rejet"])

    def test_retournement_haussier_apres_tendance_baissiere_mure(self):
        mirror = S.mirror(self.h1_sweep())                   # même scénario en miroir : creux pris, remontée
        obs = {"res": [], "sup": [(-112.0, -112.0, "creux H4")], "atr": 1.0}
        trend = dict(self.TREND_UP, dir="SELL")
        rev = self.run_detect(mirror, trend=trend, obs=obs)
        self.assertIsNotNone(rev)
        self.assertEqual((rev["dir"], rev["trend_dir"]), ("BUY", "SELL"))
        self.assertEqual((rev["level"][0], rev["ext"], rev["pivot"]), (-112.0, -113.0, -109.6))

    def test_pas_d_alerte_sans_tendance_mure_ou_apres_cassure_du_h4(self):
        self.assertIsNone(self.run_detect(trend=dict(self.TREND_UP, age="établie")))
        self.assertIsNone(self.run_detect(trend=dict(self.TREND_UP, age="naissante")))
        self.assertIsNone(self.run_detect(trend=None))                                # le H4 a déjà cassé : trop tard

    def test_niveau_majeur_exige(self):
        mineur = {"res": [(112.0, 112.0, "sommet H1")], "sup": [], "atr": 1.0}
        loin = {"res": [(120.0, 120.0, "sommet H4")], "sup": [], "atr": 1.0}
        self.assertIsNone(self.run_detect(obs=mineur))
        self.assertIsNone(self.run_detect(obs=loin))
        self.assertIsNone(self.run_detect(obs=None))
        self.assertIsNotNone(self.run_detect(obs=mineur, REQUIRE_LEVEL=False))
        veille = {"res": [(112.2, 112.2, "plus haut de la veille")], "sup": [], "atr": 1.0}
        self.assertEqual(self.run_detect(obs=veille)["level"][1], "plus haut de la veille")

    def test_signes_d_essoufflement_minimaux(self):
        self.assertIsNone(self.run_detect(MIN_SIGNS=4))                               # 3 signes seulement
        self.assertIsNotNone(self.run_detect(MIN_SIGNS=3))

    def test_cassure_trop_ancienne_donnees_anciennes_ou_sommet_deja_pris(self):
        h1 = self.h1_sweep()
        for k in range(3):                                                            # 3 bougies de plus : la cassure date de 4 bougies
            h1.insert(-1, {"epoch": h1[-2]["epoch"] + 3600, "open": 109.4, "high": 109.6, "low": 109.0, "close": 109.3})
            h1[-1]["epoch"] += 3600
        self.assertIsNone(self.run_detect(h1))
        import reversal as R
        h = self.h1_sweep()
        self.assertIsNone(R.find_reversal(h[:30]))                                    # historique trop court
        pris = self.h1_sweep()
        pris[68] = dict(pris[68], high=112.6, close=112.3)                            # le sommet 112 a déjà été dépassé (clôture au-dessus)
        self.assertIsNone(R.find_reversal(pris[:-1]))

    def test_marche_ferme(self):
        from unittest import mock
        import reversal as R
        h1 = self.h1_sweep()
        with mock.patch.object(R.TR, "trend_info", lambda c, tf=None: self.TREND_UP), \
                mock.patch.object(R.S, "htf_obstacles", lambda pr, n: self.OBS_UP):
            self.assertIsNone(R.detect(lambda tf: h1, h1[-1]["epoch"] + 3 * 86400))    # week-end : données H1 anciennes

    def test_indicateurs(self):
        import reversal as R
        h = self.h1_sweep()[:-1]
        plat = [dict(c, open=100.0, close=100.5) for c in h]                          # corps constants : pas de rétrécissement
        self.assertFalse(R.shrinking_candles(plat, 69))
        self.assertTrue(R.shrinking_candles(h, 69))
        self.assertFalse(R.shrinking_candles(h, 5))                                   # pas assez d'historique
        self.assertTrue(R.rejection_wick({"open": 111.3, "high": 113.0, "low": 111.0, "close": 111.2}))
        self.assertFalse(R.rejection_wick({"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.9}))
        self.assertFalse(R.rejection_wick({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}))
        up = [{"epoch": i, "open": 100 + i, "high": 101 + i, "low": 99.5 + i, "close": 100.8 + i} for i in range(40)]
        self.assertFalse(R.rsi_divergence(up, 30, 39))                                # RSI au plus haut avec le prix : pas de divergence
        self.assertFalse(R.rsi_divergence(up, 39, 30))                                # ordre invalide
        self.assertTrue(R.rsi_divergence(h, 60, 69))

    def test_message(self):
        import reversal as R
        rev = self.run_detect()
        txt = R.message(rev, "XAUUSD", 2, "08h15 Bénin")
        self.assertTrue(txt.startswith("🔄 Retournement possible · XAUUSD · baissier"))
        for part in ("tendance H4 haussier mûre (5 jambes)", "sommet H1 112.00 (sommet H4)", "extrême 113.00",
                     "sous le dernier creux (109.60)", "divergence RSI H1 · bougies qui rétrécissent · mèche de rejet",
                     "Invalidation : retour au-dessus de 113.00", "aucun ordre, aucun suivi", "08h15 Bénin"):
            self.assertIn(part, txt)
        buy = dict(rev, dir="BUY", trend_dir="SELL")
        self.assertIn("haussier", R.message(buy, "EURUSD", 5).split("\n")[0])
        self.assertIn("au-dessus du dernier sommet", R.message(buy, "EURUSD", 5))
        self.assertIn("retour en dessous de", R.message(buy, "EURUSD", 5))

    def test_une_seule_alerte_par_sweep_pas_de_synthetiques_et_desactivable(self):
        from unittest import mock
        h1 = self.h1_sweep()
        now = h1[-1]["epoch"] + 600
        provide = lambda tf: h1
        state = {}
        with mock.patch.object(gold.REV.TR, "trend_info", lambda c, tf=None: self.TREND_UP), \
                mock.patch.object(gold.REV.S, "htf_obstacles", lambda pr, n: self.OBS_UP), \
                mock.patch.object(gold, "ENABLED", ["S1", "S2", "S3"]):
            text = gold.reversal_alert("frxXAUUSD", provide, now, state)
            self.assertIn("🔄 Retournement possible · XAUUSD", text)
            self.assertEqual(len(state), 1)
            self.assertIsNone(gold.reversal_alert("frxXAUUSD", provide, now + 300, state))   # déjà signalé
            self.assertIn("🔄 Retournement possible · ", gold.reversal_alert("R_100", provide, now, {}))   # indices synthétiques : oui
            with mock.patch.object(gold.REV, "ENABLED", False):
                self.assertIsNone(gold.reversal_alert("frxEURUSD", provide, now, {}))
        self.assertTrue(gold.REV.ENABLED)                                                    # activée par défaut
        with mock.patch.object(gold.REV.TR, "trend_info", lambda c, tf=None: self.TREND_UP), \
                mock.patch.object(gold.REV.S, "htf_obstacles", lambda pr, n: self.OBS_UP), \
                mock.patch.object(gold, "ENABLED", ["S1", "S4"]):
            self.assertIsNone(gold.reversal_alert("frxXAUUSD", provide, now, {}))            # S4 active : l'ordre remplace l'information

    def s7_provide(self, price=109.5):
        h1 = self.h1_sweep()
        now = h1[-1]["epoch"] + 600
        t0 = (now // 900) * 900 - 80 * 900
        m15 = [{"epoch": t0 + i * 900, "open": price, "high": price + 0.15, "low": price - 0.15, "close": price} for i in range(81)]
        return now, (lambda tf, force=False: {"H4": h1[::4] or h1, "H1": h1, "M15": m15, "M5": m15, "D1": None}[tf])

    def run_s7(self, mode="limit", price=109.5, **patch):
        from unittest import mock
        now, provide = self.s7_provide(price)
        with mock.patch.object(gold.REV.TR, "trend_info", lambda c, tf=None: self.TREND_UP), \
                mock.patch.object(gold.REV.S, "htf_obstacles", lambda pr, n: self.OBS_UP), \
                mock.patch.object(gold.REV, "S7_RISK_CAP_ATR", patch.get("cap", 10.0)):
            funnel = Counter()
            sig = gold.REV.reversal_signal(provide, now, funnel, 2, mode)
            return ([sig] if sig else None), funnel

    def test_s7_ordre_de_retournement(self):
        sigs, funnel = self.run_s7()
        self.assertEqual(len(sigs), 1)
        sig = sigs[0]
        self.assertEqual((sig["strat"], sig["label"], sig["dir"]), ("S4", "Figures & Retournement", "SELL"))
        self.assertEqual(sig["extra"]["origine"], "retournement")
        self.assertEqual(sig["otype"], "SELL LIMIT")
        self.assertAlmostEqual(sig["entry"], 109.6)                       # retest du creux de structure cassé
        self.assertGreater(sig["sl"], 113.0)                              # au-delà de l'extrême du sweep (113,00)
        self.assertTrue(sig["entry"] > sig["tp1"] > sig["tp2"] > sig["tp3"])
        self.assertTrue(sig["extra"]["contre_tendance"])
        self.assertEqual(sig["ttl"], gold.REV.S7_LIMIT_TTL)
        self.assertEqual((funnel["S4_retournement"], funnel["S4_signal"]), (1, 1))

    def test_retournement_objectifs_sur_la_liquidite_opposee(self):
        from unittest import mock
        sigs, _ = self.run_s7()
        self.assertEqual(sigs[0]["extra"]["tp"], "fixe")                                  # aucune liquidité opposée dans ce jeu de données
        self.assertTrue(any("Pas de liquidité opposée intacte" in x for x in sigs[0]["details"]))
        cibles = [("EQL", 105.0, 4.5), ("PDL", 99.0, 8.0)]
        with mock.patch.object(gold.REV.S, "liquidity_targets", lambda *a, **k: cibles):
            sigs, _ = self.run_s7()
        sig = sigs[0]
        self.assertEqual((sig["tp2"], sig["tp3"]), (105.0, 99.0))                          # TP2 = 1re liquidité, TP3 = la suivante (3 R et plus)
        self.assertEqual(sig["extra"]["tp"], "liquidité")
        self.assertTrue(sig["entry"] > sig["tp1"] > sig["tp2"] > sig["tp3"])
        self.assertTrue(any("TP2 sur la liquidité EQL" in x for x in sig["details"]))

    def test_s7_marche_et_ecartes(self):
        sigs, _ = self.run_s7(mode="market")
        self.assertEqual(sigs[0]["otype"], "SELL")
        far, funnel = self.run_s7(price=105.0)                            # retest du creux à plus de 1 ATR H1 du prix
        self.assertIsNone(far)
        self.assertEqual(funnel["stale"], 1)
        capped, _ = self.run_s7(cap=0.5)                                  # risque au-delà du plafond
        self.assertIsNone(capped)

    def test_s7_fusionnee_dans_s4_et_sur_tous_les_actifs(self):
        self.assertNotIn("S7", dict(S.STRATEGIES))
        self.assertEqual((S.STRAT_LABELS["S4"], gold.LABEL_CODE["Reversal"], gold.LABEL_CODE["Chart Patterns"], gold.ENTRY_MODES["S4"]),
                         ("Figures & Retournement", "S4", "S4", "limit"))
        self.assertEqual(gold.canon_codes(["S7", "S4", "S1"]), ["S4", "S1"])        # l'ancien code S7 est lu comme S4
        self.assertEqual(gold.parse_strategies("S1,S7"), ["S1", "S4"])
        self.assertEqual(S.LABEL_FAMILY["Reversal"], S.LABEL_FAMILY["Chart Patterns"])   # même famille : un seul trade par actif et sens
        self.assertIn("S4_retournement", G.FUNNEL_ORDER)
        from unittest import mock
        now, provide = self.s7_provide()
        for sym, attendu in (("frxXAUUSD", True), ("R_100", True)):
            with mock.patch.object(gold.REV.TR, "trend_info", lambda c, tf=None: self.TREND_UP), \
                    mock.patch.object(gold.REV.S, "htf_obstacles", lambda pr, n: self.OBS_UP), \
                    mock.patch.object(gold.REV, "S7_RISK_CAP_ATR", 10.0), \
                    mock.patch.object(gold, "ENABLED", ["S4"]):
                out = gold.scan(sym, provide, now, {}, Counter(), ())
            self.assertEqual(any(sig["strat"] == "S4" and sig["extra"].get("origine") == "retournement" for sig, _ in out), attendu, sym)


class ChartPatterns(unittest.TestCase):
    """S4 Chart Patterns : figure H1 détectée, cassure confirmée en M15 (données synthétiques, sans réseau)."""
    T0 = 1_800_000_000 - (1_800_000_000 % 14400)

    def setUp(self):                                    # les séries synthétiques sont plus volatiles (en ATR) que les marchés réels
        import patterns
        from unittest import mock
        for name, val in (("S4_RISK_CAP_ATR", 12.0), ("S4_NOCONF_MIN_RR", 1.0)):
            p = mock.patch.object(patterns, name, val)
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def m15_series(way, seed=1, noise=0.04, flip=False):
        """M15 construites par interpolation de points (indice H1, prix) : chaque point H1 vaut 4 bougies M15."""
        rnd = random.Random(seed)
        pts = sorted((i * 4, p) for i, p in way)
        c = []
        for (i1, p1), (i2, p2) in zip(pts, pts[1:]):
            c += [p1 + (p2 - p1) * (i - i1) / (i2 - i1) for i in range(i1, i2)]
        c.append(pts[-1][1])
        c = [x + rnd.uniform(-noise, noise) for x in c]
        if flip:
            c = [200 - x for x in c]
        o = [c[0]] + c[:-1]
        return [{"epoch": ChartPatterns.T0 + 900 * i, "open": a, "high": max(a, b) + 0.12, "low": min(a, b) - 0.12, "close": b}
                for i, (a, b) in enumerate(zip(o, c))]

    @staticmethod
    def agg(m15, size, upto):
        """Bougies de `size` M15 ; la dernière est la bougie en formation (construite jusqu'à la M15 d'indice upto)."""
        out = []
        for g in range(0, upto + 1, size):
            grp = m15[g:min(g + size, upto + 1)]
            out.append({"epoch": grp[0]["epoch"], "open": grp[0]["open"], "high": max(x["high"] for x in grp),
                        "low": min(x["low"] for x in grp), "close": grp[-1]["close"]})
        return out

    def replay(self, way, flip=False, mode="market", start=420):
        m15 = self.m15_series(way, flip=flip)
        for e in range(start, len(m15) - 1):
            provide = lambda tf, force=False, _e=e: {"M15": m15[:_e + 1], "H1": self.agg(m15, 4, _e), "H4": self.agg(m15, 16, _e), "D1": None}[tf]
            funnel = Counter()
            sigs = [x for x in (S.scan_s4(provide, m15[e]["epoch"] + 900, funnel, 2, True, mode) or [])
                    if x["extra"].get("origine") == "figure"]      # la partie retournement (ex-S7) est testée à part
            if sigs:
                return sigs, funnel
        return None, None

    DOUBLE_TOP = [(0, 80), (60, 90), (100, 100), (115, 94), (130, 100), (155, 88), (180, 84)]

    def test_double_sommet_vente(self):
        sigs, funnel = self.replay(self.DOUBLE_TOP)
        self.assertIsNotNone(sigs)
        sig = sigs[0]
        self.assertEqual((sig["strat"], sig["label"], sig["dir"]), ("S4", "Figures & Retournement", "SELL"))
        self.assertEqual(sig["extra"]["figure"], "Double sommet")
        self.assertEqual(sig["extra"]["famille"], "retournement")
        self.assertEqual(sig["ltf"], "M15")
        self.assertGreater(sig["sl"], sig["entry"])
        self.assertTrue(sig["entry"] > sig["tp1"] > sig["tp2"] > sig["tp3"])
        self.assertGreaterEqual(funnel["S4_cassure"], 1)

    REV_SELL = {"dir": "SELL", "trend_dir": "BUY", "age": "mûre", "legs": 5, "level": (100.0, "sommet H4"), "ext": 100.5,
                "pivot": 94.0, "signs": ["mèche de rejet"], "epoch": 1}

    def test_confluence_avec_alerte_de_retournement(self):
        from unittest import mock
        with mock.patch("reversal.detect", return_value=dict(self.REV_SELL)):
            sigs, _ = self.replay(self.DOUBLE_TOP)
        self.assertIs(sigs[0]["extra"]["confluence_retournement"], True)
        self.assertTrue(any("Confluence : retournement possible" in x for x in sigs[0]["details"]))
        with mock.patch("reversal.detect", return_value=dict(self.REV_SELL, dir="BUY")):    # alerte dans l'autre sens : pas de confluence
            sigs, _ = self.replay(self.DOUBLE_TOP)
        self.assertIs(sigs[0]["extra"]["confluence_retournement"], False)

    def test_sans_confluence_ratio_plus_exigeant(self):
        from unittest import mock
        import patterns
        with mock.patch("reversal.detect", return_value=None), mock.patch.object(patterns, "S4_NOCONF_MIN_RR", 5.0):
            sigs, _ = self.replay(self.DOUBLE_TOP)
            self.assertIsNone(sigs)                                                        # ratio TP3 insuffisant sans confluence
        with mock.patch("reversal.detect", return_value=dict(self.REV_SELL)), mock.patch.object(patterns, "S4_NOCONF_MIN_RR", 5.0):
            sigs, _ = self.replay(self.DOUBLE_TOP)
            self.assertIsNotNone(sigs)                                                     # avec confluence, le ratio normal suffit

    def test_continuation_sans_effet_de_la_confluence(self):
        from unittest import mock
        w = [(0, 100), (50, 100), (60, 90), (66, 92.5), (70, 90.8), (76, 92.9), (82, 91.4), (88, 93.1), (94, 91.4), (108, 85)]
        with mock.patch("reversal.detect", return_value=dict(self.REV_SELL)):          # même avec un retournement détecté : sans effet sur une continuation
            sigs, _ = self.replay(w, start=330)
        if sigs:
            self.assertNotIn("confluence_retournement", sigs[0]["extra"])

    def test_fusion_un_seul_signal_par_sens(self):
        """Au scan où la figure de retournement casse, avec un retournement détecté dans le même sens : un seul signal, celui de la figure."""
        from unittest import mock
        m15 = self.m15_series(self.DOUBLE_TOP)
        step = None
        with mock.patch("reversal.detect", return_value=dict(self.REV_SELL)):
            for e in range(420, len(m15) - 1):
                provide = lambda tf, force=False, _e=e: {"M15": m15[:_e + 1], "H1": self.agg(m15, 4, _e), "H4": self.agg(m15, 16, _e), "D1": None}[tf]
                sigs = S.scan_s4(provide, m15[e]["epoch"] + 900, Counter(), 2, True, "market") or []
                if any(x["extra"].get("origine") == "figure" for x in sigs):
                    step = sigs
                    break
        self.assertIsNotNone(step)
        self.assertEqual([(x["dir"], x["extra"]["origine"]) for x in step], [("SELL", "figure")])

    def test_double_creux_achat_miroir(self):
        sigs, _ = self.replay(self.DOUBLE_TOP, flip=True)
        self.assertIsNotNone(sigs)
        sig = sigs[0]
        self.assertEqual((sig["dir"], sig["extra"]["figure"]), ("BUY", "Double creux"))
        self.assertLess(sig["sl"], sig["entry"])
        self.assertTrue(sig["entry"] < sig["tp1"] < sig["tp2"] < sig["tp3"])

    def test_ordre_limite_au_retest(self):
        sigs, _ = self.replay(self.DOUBLE_TOP, mode="limit")
        sig = sigs[0]
        if sig["otype"] != sig["dir"]:                      # ordre limite posé au retest de la ligne cassée
            self.assertEqual(sig["otype"], "SELL LIMIT")
            self.assertGreater(sig["entry"], sig["price_now"])
            self.assertEqual(sig["ttl"], S.LIMIT_TTL["S4"])

    def test_tete_epaules(self):
        way = [(0, 80), (60, 90), (90, 100), (100, 95), (115, 105), (130, 95.5), (142, 100.5), (170, 90), (190, 85)]
        sigs, _ = self.replay(way)
        self.assertIsNotNone(sigs)
        self.assertEqual(sigs[0]["extra"]["figure"], "Tête et épaules")

    def test_pas_de_signal_sans_figure(self):
        rnd = random.Random(3)
        way = [(i, 100 + rnd.uniform(-0.3, 0.3)) for i in range(0, 200)]      # bruit autour d'un niveau
        sigs, _ = self.replay(way, start=420)
        self.assertIsNone(sigs)

    def test_donnees_insuffisantes(self):
        self.assertIsNone(S.scan_s4(lambda tf, force=False: [], 0, Counter()))

    def test_enregistree_dans_le_bot(self):
        self.assertIn("S4", dict(S.STRATEGIES))
        self.assertEqual(S.STRAT_LABELS["S4"], "Figures & Retournement")
        self.assertEqual(gold.LABEL_CODE["Chart Patterns"], "S4")
        self.assertEqual(gold.ENTRY_MODES["S4"], "limit")
        self.assertIn("S4_signal", G.FUNNEL_ORDER)


# ==========================================================================
# Fibonacci par stratégie : S2 (premium / discount), S3 (extrémités du range), S4 (profondeur du repli, plafond du TP3)
# ==========================================================================
def range_candles(n, hi, lo, hi_i, lo_i, step=3600, t0=1_800_000_000, mid=None):
    """n bougies plates autour de `mid`, avec un sommet isolé `hi` en hi_i et un creux isolé `lo` en lo_i (swings de fractale évidents)."""
    mid = (hi + lo) / 2 if mid is None else mid
    cs = [candle(t0 + step * i, mid, mid + 0.5, mid - 0.5, mid) for i in range(n)]
    cs[hi_i] = candle(cs[hi_i]["epoch"], mid, hi, mid - 0.5, mid)
    cs[lo_i] = candle(cs[lo_i]["epoch"], mid, mid + 0.5, lo, mid)
    return cs


class FibonacciModule(unittest.TestCase):
    def test_jambe_de_reference(self):
        import fib as FB
        cs = range_candles(60, 110.0, 100.0, 20, 40)
        self.assertEqual(FB.dealing_range(cs, 3, 120), (100.0, 110.0))
        self.assertIsNone(FB.dealing_range(cs[:30], 3, 120))                       # pas de creux confirmé : pas de jambe
        self.assertIsNone(FB.dealing_range([candle(i, 1, 1.5, 0.5, 1) for i in range(40)], 3, 120))   # série plate

    def test_profondeur_vue_du_sens_du_trade(self):
        import fib as FB
        self.assertAlmostEqual(FB.retrace("BUY", 102.0, 100.0, 110.0), 0.8)        # un achat bas dans la jambe : profond
        self.assertAlmostEqual(FB.retrace("BUY", 110.0, 100.0, 110.0), 0.0)
        self.assertAlmostEqual(FB.retrace("SELL", 108.0, 100.0, 110.0), 0.8)       # une vente haute dans la jambe : profond
        self.assertAlmostEqual(FB.retrace("SELL", 105.0, 100.0, 110.0), 0.5)
        self.assertGreater(FB.retrace("BUY", 98.0, 100.0, 110.0), 1.0)             # sous la jambe : au-delà de 100 %
        self.assertIsNone(FB.retrace("BUY", 100.0, 100.0, 100.0))

    def test_noms_de_zones(self):
        import fib as FB
        self.assertEqual([FB.zone_name(r) for r in (0.2, 0.499, 0.5, 0.6, 0.618, 0.75, 0.79, 0.85, 1.2)],
                         ["mauvais côté", "mauvais côté", "Golden Zone", "Golden Zone", "OTE", "OTE", "OTE", "extrême", "extrême"])
        self.assertEqual((FB.side_word("BUY"), FB.side_word("SELL")), ("discount", "premium"))

    def test_profondeur_d_un_repli(self):
        import fib as FB
        self.assertAlmostEqual(FB.pullback_depth(100.0, 90.0, 96.18), 0.618)
        self.assertAlmostEqual(FB.pullback_depth(100.0, 90.0, 90.0), 0.0)
        self.assertIsNone(FB.pullback_depth(90.0, 90.0, 95.0))                     # jambe nulle

    def test_cles_d_entonnoir_declarees(self):
        for k in ("S2_fib", "S3_fib", "S4_fib"):
            self.assertIn(k, G.FUNNEL_ORDER)
            self.assertIn(k, G.FUNNEL_LABEL)


class FibonacciS2(unittest.TestCase):
    """S2 : un achat se prend dans le discount (sous 50 %) de la jambe H4/H1, une vente dans le premium."""
    T0 = 1_800_000_000
    OFF = dict(S2_BIAS_FILTER=False, S2_HTF_ZONE=False, S2_LIQ_TARGETS=False)

    def check(self, d, entry, tf="H1", a_h1=1.0, **kw):
        step = 3600 if tf == "H1" else 14400
        cs = range_candles(60, 110.0, 100.0, 20, 40, step=step, t0=self.T0)
        h1c, h4c = (cs, []) if tf == "H1" else ([], cs)
        return S.s2_fib_check(d, entry, tf, h4c, h1c, kw.get("before", self.T0 + step * 61), a_h1)

    def test_achat_discount_accepte_premium_refuse(self):
        r = self.check("BUY", 102.0)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["r"], 0.8)
        self.assertEqual((r["lo"], r["hi"], r["eq"], r["tf"]), (100.0, 110.0, 105.0, "H1"))
        self.assertFalse(self.check("BUY", 108.0)["ok"])                         # acheter en premium
        self.assertTrue(self.check("BUY", 104.9)["ok"])                          # juste sous l'équilibre : encore dans le discount
        self.assertFalse(self.check("BUY", 105.1)["ok"])                         # juste au-dessus de l'équilibre : déjà dans le premium

    def test_vente_premium_accepte_discount_refuse(self):
        self.assertTrue(self.check("SELL", 108.0)["ok"])
        self.assertFalse(self.check("SELL", 102.0)["ok"])                        # vendre en discount

    def test_jambe_h4_quand_le_biais_vient_du_h4(self):
        r = self.check("BUY", 102.0, tf="H4")
        self.assertEqual(r["tf"], "H4")
        self.assertTrue(r["ok"])

    def test_sans_information_le_filtre_laisse_passer(self):
        self.assertIsNone(self.check("BUY", 108.0, a_h1=10.0))                   # jambe de 10 < 1,5 x ATR 10 : pas d'avis
        self.assertIsNone(self.check("BUY", 108.0, before=self.T0 + 3600 * 35))   # le sommet de la jambe naît après le sweep : calcul sur le passé seulement
        from unittest import mock
        with mock.patch.object(S, "S2_FIB_FILTER", False):
            self.assertIsNone(self.check("BUY", 108.0))                          # désactivé

    def scan(self, **patches):
        from unittest import mock
        for pad in range(0, 60, 5):
            m5 = s2_scenario(False, pad)
            rp = B.Replay(m5)
            with mock.patch.multiple(S, **patches):
                for t in range(len(m5) - 40, len(m5)):
                    funnel = Counter()
                    provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
                    sig = S.scan_s2(provide, m5[t]["epoch"] + 300, funnel, 2, kz=False, mode="limit")
                    if sig or funnel["S2_fib"]:
                        return sig, funnel
        return None, Counter()

    def test_signal_accepte_avec_ligne_et_detail(self):
        ok = {"ok": True, "r": 0.7, "tf": "H1", "eq": 2000.0, "lo": 1990.0, "hi": 2010.0}
        sig, funnel = self.scan(s2_fib_check=lambda *a, **k: ok, **self.OFF)
        self.assertIsNotNone(sig)
        self.assertTrue(any("Fibonacci 70 %" in x and "OTE" in x for x in sig["details"]))
        self.assertEqual(sig["extra"]["fib"], "70%")
        self.assertTrue(any(l["y"] == 2000.0 for l in sig["lines"]))
        self.assertEqual(funnel["S2_fib"], 0)

    def test_signal_ecarte_du_mauvais_cote(self):
        bad = {"ok": False, "r": 0.2, "tf": "H1", "eq": 2000.0, "lo": 1990.0, "hi": 2010.0}
        sig, funnel = self.scan(s2_fib_check=lambda *a, **k: bad, **self.OFF)
        self.assertIsNone(sig)
        self.assertGreaterEqual(funnel["S2_fib"], 1)

    def test_filtre_desactive_ne_change_rien(self):
        sig, funnel = self.scan(S2_FIB_FILTER=False, **self.OFF)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["extra"]["fib"], "aucune")
        self.assertFalse(any("Fibonacci" in x for x in sig["details"]))


class FibonacciS3(unittest.TestCase):
    """S3 : le rejet des bandes de Bollinger ne se prend qu'aux extrémités (38,2 % extérieurs) du range H1 de 48 bougies."""

    def check(self, d, entry, a_h1=1.0, n=60):
        return S.s3_fib_check(d, entry, range_candles(n, 110.0, 100.0, 20, 40, t0=1_800_000_000), a_h1)   # sommet et creux dans les 48 dernières bougies

    def test_extremites_acceptees_milieu_refuse(self):
        self.assertTrue(self.check("BUY", 101.0)["ok"])                          # près du bas du range
        self.assertTrue(self.check("SELL", 109.0)["ok"])                         # près du haut du range
        mid = self.check("BUY", 105.0)
        self.assertFalse(mid["ok"])                                              # au milieu : rien à ramener vers la moyenne
        self.assertFalse(self.check("SELL", 105.0)["ok"])
        self.assertFalse(self.check("BUY", 108.0)["ok"])                         # achat en haut du range
        self.assertAlmostEqual(mid["r"], 0.5)
        self.assertEqual(mid["eq"], 105.0)

    def test_frontiere_618(self):
        self.assertTrue(self.check("BUY", 103.8)["ok"])                          # profondeur 0,62
        self.assertFalse(self.check("BUY", 104.0)["ok"])                         # profondeur 0,60

    def test_sans_information_le_filtre_laisse_passer(self):
        self.assertIsNone(self.check("BUY", 105.0, a_h1=10.0))                   # range de 10 < 2 x ATR 10
        self.assertIsNone(S.s3_fib_check("BUY", 105.0, range_candles(10, 110.0, 100.0, 2, 5), 1.0))   # trop peu de bougies
        from unittest import mock
        with mock.patch.object(S, "S3_FIB_FILTER", False):
            self.assertIsNone(self.check("BUY", 105.0))

    def test_le_range_est_les_48_dernieres_bougies(self):
        # le sommet à 110 date de plus de 48 bougies : il ne fait plus partie du range, qui devient [100, 105,5]
        cs = range_candles(80, 110.0, 100.0, 5, 70, t0=1_800_000_000)
        r = S.s3_fib_check("BUY", 101.0, cs, 1.0)
        self.assertEqual((r["lo"], r["hi"]), (100.0, 105.5))
        self.assertTrue(r["ok"])


class FibonacciS4(unittest.TestCase):
    """S4 : figures de continuation filtrées par la profondeur du repli ; TP3 des retournements plafonné à l'origine de la jambe précédente."""
    FLAG = [(0, 100), (50, 100), (60, 90), (66, 92.5), (70, 90.8), (76, 92.9), (82, 91.4), (88, 93.1), (94, 91.4), (108, 85)]

    def setUp(self):
        self.cp = ChartPatterns("test_double_sommet_vente")                      # on réutilise ses séries synthétiques et son setUp
        self.cp.setUp()
        self.addCleanup(self.cp.doCleanups)

    def test_jambe_precedente_continuation_et_retournement(self):
        import patterns
        cs = [candle(i, 95, 96, 94, 95) for i in range(30)]
        cs[3] = candle(3, 99, 100, 98, 99)                                       # origine : plus haut avant la figure
        cs[12] = candle(12, 91, 92, 90, 91)                                      # fin de jambe : plus bas jusqu'à la fin de la figure
        d = {"s": 1, "start": 10, "end": 20, "kind": "continuation"}
        self.assertEqual(patterns.prior_leg(S, d, cs), (100, 90))
        cs2 = [candle(i, 95, 96, 94, 95) for i in range(30)]
        cs2[4] = candle(4, 85, 86, 84, 85)                                       # origine d'une jambe haussière
        self.assertEqual(patterns.prior_leg(S, dict(d, kind="retournement"), cs2), (84, None))
        # espace miroir (figure haussière, s = -1) : les prix sont retournés
        d2 = {"s": -1, "start": 10, "end": 20, "kind": "retournement"}
        cs3 = [candle(i, 95, 96, 94, 95) for i in range(30)]
        cs3[5] = candle(5, 99, 100, 98, 99)                                      # plus haut avant la figure = origine miroir (-100)
        self.assertEqual(patterns.prior_leg(S, d2, cs3), (-100, None))

    def test_plafond_tp3_du_retournement(self):
        from unittest import mock
        res = {}
        for cap in (False, True):
            with mock.patch.object(S, "S4_FIB_CAP_TP3", cap), mock.patch("reversal.detect", return_value=None):
                sigs, _ = self.cp.replay(self.cp.DOUBLE_TOP)
            self.assertIsNotNone(sigs)
            res[cap] = sigs[0]
        off, on = res[False], res[True]
        self.assertGreater(on["tp3"], off["tp3"])                                # vente : l'objectif est plus proche (plafonné)
        self.assertTrue(on["tp1"] > on["tp2"] > on["tp3"])                       # l'ordre des objectifs reste valide
        self.assertEqual((on["tp1"], on["tp2"]), (off["tp1"], off["tp2"]))       # TP1 et TP2 ne bougent pas
        self.assertTrue(any("TP3 plafonné" in x for x in on["details"]))
        self.assertFalse(any("TP3 plafonné" in x for x in off["details"]))

    def test_continuation_repli_leger_accepte(self):
        from unittest import mock
        with mock.patch("reversal.detect", return_value=None):
            sigs, funnel = self.cp.replay(self.FLAG, start=330)
        self.assertIsNotNone(sigs)
        self.assertEqual(sigs[0]["extra"]["famille"], "continuation")
        self.assertTrue(any("Repli de" in x and "Fibonacci" in x for x in sigs[0]["details"]))
        self.assertEqual(funnel["S4_fib"], 0)

    def test_continuation_repli_trop_profond_ecarte(self):
        from unittest import mock
        import patterns
        # jambe précédente à peine plus haute que la figure : le repli reprend ~89 % de la jambe
        with mock.patch("reversal.detect", return_value=None), mock.patch.object(patterns, "prior_leg", return_value=(93.5, 90.0)):
            sigs, _ = self.cp.replay(self.FLAG, start=330)
            self.assertIsNone(sigs)
            m15 = self.cp.m15_series(self.FLAG)
            seen = Counter()
            for e in range(330, len(m15) - 1):
                provide = lambda tf, force=False, _e=e: {"M15": m15[:_e + 1], "H1": self.cp.agg(m15, 4, _e), "H4": self.cp.agg(m15, 16, _e), "D1": None}[tf]
                S.scan_s4(provide, m15[e]["epoch"] + 900, seen, 2, True, "market")
            self.assertGreaterEqual(seen["S4_fib"], 1)
            self.assertEqual(seen["S4_signal"], 0)
        with mock.patch("reversal.detect", return_value=None), mock.patch.object(patterns, "prior_leg", return_value=(93.5, 90.0)), \
                mock.patch.object(S, "S4_FIB_FILTER", False):
            sigs, _ = self.cp.replay(self.FLAG, start=330)
            self.assertIsNotNone(sigs)                                           # filtre désactivé : la figure repasse

    def test_les_retournements_ne_sont_pas_filtres_par_la_profondeur(self):
        from unittest import mock
        import patterns
        with mock.patch("reversal.detect", return_value=None), mock.patch.object(patterns, "prior_leg", return_value=(80.0, None)):
            sigs, _ = self.cp.replay(self.cp.DOUBLE_TOP)
        self.assertIsNotNone(sigs)


if __name__ == "__main__":
    unittest.main()
