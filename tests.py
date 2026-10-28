"""Tests automatisés : python -m unittest tests -v

Aucun accès réseau : les données viennent d'une marche aléatoire (backtest.gen_sim) ou de séries construites.
Ces tests vérifient la mécanique du bot (indicateurs, tendance, suivi des trades, garde-fous, messages,
backtest), pas la rentabilité des stratégies.
"""
import os
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
        self.assertEqual(gold.parse_strategies(""), ["S1", "S2", "S3", "S4", "S5"])      # variable GitHub non définie
        self.assertEqual(gold.parse_strategies(None), ["S1", "S2", "S3", "S4", "S5"])
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
        self.assertEqual(gold.parse_sym_strats("frxEURUSD:S1,S2;cryBTCUSD:s2 , S4"),
                         {"frxEURUSD": ["S1", "S2"], "cryBTCUSD": ["S2", "S4"]})
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


def s3_scenario(stale, pad=10):
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


def s3_first_signal(m5, **patches):
    from unittest import mock
    rp = B.Replay(m5)
    with mock.patch.multiple(S, **patches):
        for t in range(len(m5) - 40, len(m5)):
            provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
            sig = S.scan_s3(provide, m5[t]["epoch"] + 300, Counter(), 2, kz=False, mode="limit")
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
        self._cf = gold.CLASS_FILTER
        gold.CLASS_FILTER = True            # ces tests décrivent le filtrage par classe (CLASS_FILTER=1)

    def tearDown(self):
        gold.CLASS_FILTER = self._cf

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

    def test_synthetiques_s3_principale_s5_secondaire(self):
        gold.ENABLED = ["S1", "S2", "S3", "S4", "S5"]
        for sym in gold.SYNTHETICS:
            self.assertEqual([x for x in gold.ENABLED if x in gold.strategies_for(sym)], ["S3", "S5"])
        # les autres classes suivent leur propre liste (principale, secondaires, à tester)
        self.assertEqual(gold.strategies_for("frxEURUSD"), ["S3", "S2", "S1", "S5"])

    def test_scan_lance_s3_et_s5_sans_killzone_sur_les_synthetiques(self):
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
        self.assertEqual(seen, {"only": ["S3", "S5"], "kz": False, "dec": 4})

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

    def test_alerte_s3_sans_ligne_killzone_sur_actif_24_7(self):
        from unittest import mock
        sig = None
        for pad in range(0, 60, 5):
            m5 = s3_scenario(False, pad)
            sig = s3_first_signal(m5, S3_BIAS_FILTER=False, S3_HTF_ZONE=False, S3_LIQ_TARGETS=False)
            if sig:
                break
        self.assertIsNotNone(sig)
        self.assertFalse(any("Killzone" in x for x in sig["details"]))                 # s3_first_signal scanne avec kz=False


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
        self.assertTrue(G.risk_check(tr, "R_100", "BUY", 1e9, "S3")[0])

    def test_l_exposition_par_devise_reste_active(self):
        tr = {"active": {}, "closed": []}
        for i, sym in enumerate(("frxEURUSD", "frxEURJPY")):
            tr["active"][f"k{i}"] = T.new_trade("OR", f"k{i}", sym, sym[3:], "BUY", "BUY", 1, .9, 1.1, 1.2, 1.3, "M15", 900, 2, "A", 1e9, 3600)
        self.assertFalse(G.risk_check(tr, "frxEURGBP", "BUY", 1e9, "B")[0])        # 3e position longue EUR


class RecapDuMatinParClasse(unittest.TestCase):
    def run_recap(self, symbols=None, data=lambda sym, tf: None):
        from unittest import mock
        sent, cs = [], zigzag(3)
        fake = lambda api, cache, sym, tf: (data(sym, tf) if data(sym, tf) is not None else cs)
        with mock.patch.object(gold, "tf_candles", fake), \
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
        self.assertIn("Biais S3", sent[0])
        self.assertIn("Bougie daily en cours", sent[0])
        self.assertNotIn("EURUSD", sent[0] + sent[1])

    def test_classe_absente_de_symbols_non_envoyee(self):
        from unittest import mock
        sent = []
        cs = zigzag(3)
        with mock.patch.object(gold, "tf_candles", lambda api, cache, sym, tf: cs), \
                mock.patch.object(gold, "SYMBOLS", ["frxEURUSD", "R_100"]), \
                mock.patch.object(gold, "notify", lambda text, *a, **k: sent.append(text) or 1):
            gold.send_synth_recap(None, {}, cs[-1]["epoch"] + 600)
        self.assertEqual(len(sent), 1)
        self.assertIn("V100", sent[0])
        self.assertNotIn("1s", sent[0].split("\n", 2)[0])


class SweepCHoCH(unittest.TestCase):
    OFF = dict(S3_BIAS_FILTER=False, S3_HTF_ZONE=False, S3_LIQ_TARGETS=False)

    def first_pad(self, stale, **patches):
        for pad in range(0, 60, 5):
            sig = s3_first_signal(s3_scenario(stale, pad), **patches)
            if sig:
                return sig
        return None

    def test_niveau_intact_donne_un_signal(self):
        sig = self.first_pad(False, **self.OFF)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["dir"], "SELL")

    def test_niveau_deja_pris_ecarte(self):
        # ancien comportement : signal sur un niveau déjà dépassé de 15 points pendant des heures
        self.assertIsNotNone(self.first_pad(True, S3_FRESH_LEVELS=False, **self.OFF))
        # corrigé : ce niveau n'est plus de la liquidité
        self.assertIsNone(self.first_pad(True, S3_FRESH_LEVELS=True, **self.OFF))

    def test_niveau_pris_une_seule_fois(self):
        m15 = [candle(1000 + 900 * i, 100, 100.5, 99.5, 100) for i in range(10)]
        m15[3] = candle(1000 + 900 * 3, 100, 101.2, 99.8, 100.2)       # mèche au-dessus de 101 : liquidité prise
        self.assertTrue(S.level_taken(m15, 101.0, "high", 1000))
        self.assertFalse(S.level_taken(m15, 101.0, "high", 1000, upto=3))   # avant cette bougie : intact
        self.assertFalse(S.level_taken(m15, 101.0, "high", 1000 + 900 * 4))  # niveau né après la mèche

    def test_biais_h4_puis_h1(self):
        up, dn, flat = zigzag(3), zigzag(3, up=False), [candle(1_700_000_000 + 3600 * i, 100, 100.5, 99.5, 100) for i in range(60)]
        self.assertEqual(S.s3_bias(up, dn), ("BUY", "H4"))           # le H4 prime sur le H1
        self.assertEqual(S.s3_bias(flat, dn), ("SELL", "H1"))        # H4 sans tendance : on lit le H1
        self.assertEqual(S.s3_bias(flat, flat), (None, None))

    def test_filtre_de_biais(self):
        from unittest import mock
        patches = dict(S3_HTF_ZONE=False, S3_LIQ_TARGETS=False, S3_BIAS_FILTER=True)
        with mock.patch.object(S, "s3_bias", return_value=("SELL", "H4")):
            self.assertIsNotNone(self.first_pad(False, **patches))
        with mock.patch.object(S, "s3_bias", return_value=("BUY", "H4")):
            self.assertIsNone(self.first_pad(False, **patches))      # SELL contre un biais haussier
        with mock.patch.object(S, "s3_bias", return_value=(None, None)):
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
        patches = dict(S3_BIAS_FILTER=False, S3_LIQ_TARGETS=False, S3_HTF_ZONE=True)
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
        tps, t2, t3 = S.s3_tps("SELL", 100.0, 1.0, tg)
        self.assertAlmostEqual(tps[0], 99.0)
        self.assertAlmostEqual(tps[1], 96.1)                          # 0,1 ATR avant PDL
        self.assertAlmostEqual(tps[2], 94.1)
        self.assertTrue(tps[0] > tps[1] > tps[2])
        # niveau déjà pris : plus un objectif
        m15[5] = candle(1000 + 900 * 5, 100, 100.2, 95.5, 99.9)
        self.assertEqual([t[0] for t in S.liquidity_targets(levels, m15, "SELL", 100.0, 1.0, 1.0)], ["Asie B"])
        # sans liquidité : 2 R / 3 R, TP3 toujours au-delà de TP2
        self.assertEqual([round(x, 2) for x in S.s3_tps("BUY", 100.0, 1.0, [])[0]], [101.0, 102.0, 103.0])
        tps = S.s3_tps("BUY", 100.0, 1.0, [("PDH", 104.9, 4.9)])[0]
        self.assertTrue(tps[0] < tps[1] < tps[2])

    def test_signal_complet_avec_objectifs(self):
        sig = self.first_pad(False, S3_BIAS_FILTER=False, S3_HTF_ZONE=False, S3_LIQ_TARGETS=True)
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
        data = B.gen_sim(70, 3)
        rp, funnel = B.Replay(data), Counter()
        found = {"limit": 0, "market": 0}
        for mode in ("limit", "market"):
            gold.ENTRY_MODE, sent = mode, {}
            for t in range(7200, 10500):
                provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
                # toutes les stratégies sur l'or, indépendamment de sa classe : le test porte sur les ordres, pas sur les classes
                with mock.patch.dict(gold.SYMBOL_OVERRIDES, {"frxXAUUSD": ["S1", "S2", "S3", "S4", "S5"]}):
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
        self.assertIn("S5", dict(S.STRATEGIES))
        self.assertIn("S5", S.LIMIT_TTL)
        self.assertIn("S5", gold.ENTRY_MODES)
        self.assertEqual(S.LIMIT_TTL["S5"], 86400)
        for k in ("S5_regime", "S5_tendance", "S5_impulsion", "S5_signal"):
            self.assertIn(k, G.FUNNEL_ORDER)
            self.assertIn(k, G.FUNNEL_LABEL)
        # l'ordre des cascades : la plus haute d'abord (le garde-fou garde la première en cas de doublon)
        self.assertEqual([c[0] for c in S.S5_CASCADES], ["D1", "H4", "H1"])

    def test_helpers(self):
        cs = [{"epoch": i, "open": 10.0 + i, "high": 12.0 + i, "low": 9.0 + i, "close": 11.0 + i} for i in range(5)]
        self.assertEqual(S._s5_flip(S._s5_flip(cs)), cs)                         # le miroir est une involution
        f = S._s5_flip(cs)[0]
        self.assertEqual((f["high"], f["low"]), (-9.0, -12.0))
        self.assertEqual(S._s5_run([1, 2, 3]), 2)
        self.assertEqual(S._s5_run([3, 2, 1]), 0)
        self.assertEqual(S._s5_run([1, 3, 2, 4, 5]), 2)

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

    def sig(self, strat="S3", d="BUY", sym="frxXAUUSD"):
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
        self.assertEqual(gold.LABEL_CODE["Sweep + CHoCH"], "S3")
        self.assertEqual(gold.LABEL_CODE["Impulsion"], "S5")

    def test_aucune_confluence(self):
        sig = gold.add_confluence(self.sig(), {"active": {}, "closed": []}, [], self.NOW)
        self.assertEqual(sig["confluence"], [])
        self.assertEqual(sig["extra"]["confluence"], "aucune")
        self.assertEqual((sig["details"], sig["short"]), (["✅ test"], "setup"))

    def test_trade_actif_meme_sens(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S5", age=600)
        sig = gold.add_confluence(self.sig("S3"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], ["S5"])
        self.assertEqual(sig["extra"]["confluence"], "S3+S5")
        self.assertIn("⚡ Confluence : S5 Impulsion (il y a 10 min)", sig["details"])
        self.assertTrue(sig["short"].endswith("confluence S5"))
        self.assertEqual(sig["details"][0], "✅ test")

    def test_ce_qui_ne_compte_pas(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S5", d="SELL")                                   # autre sens
        self.trade(tr, "S1", sym="frxEURUSD")                            # autre actif
        self.trade(tr, "S2", age=3601)                                   # hors fenêtre (60 min)
        self.trade(tr, "S3", age=60)                                     # même stratégie
        self.trade(tr, "S4", age=60, status="cancelled")                 # ordre annulé
        done = self.trade(tr, "S1", age=61)                              # trade déjà clôturé : archivé, il ne compte pas
        done["status"] = "closed"
        T.archive(tr, done["key"])
        self.assertEqual(len(tr["closed"]), 1)
        sig = gold.add_confluence(self.sig("S3"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], [])
        self.assertEqual(sig["extra"]["confluence"], "aucune")

    def test_fenetre_limite_incluse(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S2", age=3600)
        self.assertEqual(gold.add_confluence(self.sig("S3"), tr, [], self.NOW)["confluence"], ["S2"])

    def test_trade_sans_code_retrouve_par_libelle(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S5", with_code=False)
        self.assertEqual(gold.add_confluence(self.sig("S3"), tr, [], self.NOW)["confluence"], ["S5"])

    def test_meme_scan_dans_les_deux_sens(self):
        a, b, same = self.sig("S3"), self.sig("S5"), self.sig("S5")
        batch = [a, b, same]
        for sg in batch:
            gold.add_confluence(sg, {"active": {}, "closed": []}, batch, self.NOW)
        self.assertEqual(a["confluence"], ["S5"])
        self.assertEqual(b["confluence"], ["S3"])            # la S5 ne se compte pas elle-même, même en double
        self.assertEqual(b["extra"]["confluence"], "S3+S5")
        self.assertIn("au même scan", " ".join(a["details"]))

    def test_plusieurs_strategies(self):
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S5", age=300)
        self.trade(tr, "S1", age=900)
        sig = gold.add_confluence(self.sig("S3"), tr, [], self.NOW)
        self.assertEqual(sig["confluence"], ["S1", "S5"])
        self.assertEqual(sig["extra"]["confluence"], "S1+S3+S5")

    def test_desactivee(self):
        from unittest import mock
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S5")
        with mock.patch.object(gold, "CONFLUENCE_MIN", 0):
            sig = gold.add_confluence(self.sig("S3"), tr, [], self.NOW)
        self.assertEqual((sig["confluence"], sig["extra"]["confluence"]), ([], "aucune"))

    def test_lecture_du_reglage(self):
        for txt, want in (("", 60.0), (None, 60.0), ("abc", 60.0), ("30", 30.0), ("0", 0.0), ("-5", 0.0), ("90,5", 90.5)):
            self.assertEqual(gold.parse_confluence(txt), want, txt)

    def test_colonne_du_backtest(self):
        ts = [{"confluence": "S3+S5", "r": 1.0, "result": "tp"}, {"confluence": "aucune", "r": -1.0, "result": "sl"},
              {"r": 0.5, "result": "tp"}]
        rows = " | ".join(B.breakdown(ts, "confluence"))
        self.assertIn("confluence S3+S5", rows)
        self.assertIn("confluence aucune", rows)

    def test_backtest_marque_la_confluence_sur_les_trades(self):
        from unittest import mock
        m5 = B.gen_sim(3, 1)
        steps = {"n": 0}

        def fake_scan(sym, provide, now, sent, funnel, news=()):
            steps["n"] += 1
            if steps["n"] not in (50, 51):                     # deux alertes seulement : S3 puis S5, 5 min plus tard
                return []
            px = provide("M5")[-1]["close"]
            strat = "S3" if steps["n"] == 50 else "S5"
            return [({"strat": strat, "label": S.STRAT_LABELS[strat], "sym": sym, "name": "EURUSD", "dir": "BUY",
                      "otype": "BUY", "entry": px, "sl": px - 5, "tp1": px + 5, "tp2": px + 10, "tp3": px + 15,
                      "ltf": "M5", "gran": 300, "dec": 5, "ttl": None, "inval": None, "session": "Londres",
                      "key": f"{sym}|{strat}|{now}", "details": [], "short": "x", "extra": {}}, [])]
        with mock.patch.object(gold, "scan", fake_scan):
            tr, _, _ = B.run(m5, "frxEURUSD", spread_pct=0.0, warmup_days=0, progress=False)
        trades = list(tr["active"].values()) + tr["closed"]
        by = {t["strat"]: t["confluence"] for t in trades}
        self.assertEqual(by, {"S3": "aucune", "S5": "S3+S5"})   # la seconde alerte porte la confluence, pas la première

    def test_messages_des_quatre_formats(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        sig = next(x for x in S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") if x["extra"]["cascade"] == "H4>H1>M15")
        sig.update(sym="frxEURUSD", name="EURUSD", dec=3, ts=t + 60, age_min=1.0, trend_lines=[], trend_short="")
        tr = {"active": {}, "closed": []}
        self.trade(tr, "S3", d="SELL", sym="frxEURUSD", age=300)
        tr["active"] = {k: dict(v, t0=t + 60 - 300) for k, v in tr["active"].items()}
        gold.add_confluence(sig, tr, [], t + 60)
        self.assertEqual(sig["confluence"], ["S3"])
        for fmt in ("complet", "compact", "minimal", "contexte"):
            os.environ["ALERT_FORMAT"] = fmt
            try:
                txt = gold.gold_message(sig, 7)
            finally:
                os.environ.pop("ALERT_FORMAT", None)
            self.assertIn("S3", txt, fmt)
            self.assertIn("⚡" if fmt in ("complet", "minimal") else "confluence", txt, fmt)



# ==========================================================================
# Classes d'actifs et niveaux de stratégie (principale / secondaire / à tester)
# ==========================================================================
class ClassesEtNiveaux(unittest.TestCase):
    TOUTES = ["S1", "S2", "S3", "S4", "S5"]

    def setUp(self):
        self._enabled, self._cf = gold.ENABLED, gold.CLASS_FILTER
        gold.ENABLED = list(self.TOUTES)
        gold.CLASS_FILTER = True            # le filtrage par classe est optionnel (CLASS_FILTER=1)

    def tearDown(self):
        gold.ENABLED, gold.CLASS_FILTER = self._enabled, self._cf

    def test_par_defaut_toutes_les_strategies_sur_chaque_actif(self):
        gold.CLASS_FILTER = False
        for sym in gold.ALL_SYMBOLS:
            self.assertEqual(gold.strategies_for(sym), self.TOUTES, sym)
            self.assertIsNone(gold.tier_of(sym, "S2"), sym)
        sig = gold.add_tier({"strat": "S2", "details": [], "short": "x", "extra": {}}, "frxXAUUSD")
        self.assertEqual(sig["extra"]["tier"], "toutes")
        self.assertNotIn("🧪", sig["short"])
        gold.ENABLED = ["S1", "S3"]                  # la variable STRATEGIES reste prioritaire
        self.assertEqual(gold.strategies_for("frxXAUUSD"), ["S1", "S3"])

    def test_les_classes_couvrent_tous_les_actifs_une_fois(self):
        listed = [s for _, syms in gold.ASSET_CLASSES.values() for s in syms]
        self.assertEqual(sorted(listed), sorted(gold.ALL_SYMBOLS))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(gold.DEFAULT_CLASS_TIERS), set(gold.ASSET_CLASSES))
        self.assertEqual(gold.ASSET_CLASSES["synthetique"][1], gold.SYNTHETICS)
        self.assertEqual(gold.CLASS_OF["frxXAUUSD"], "or")
        self.assertEqual(gold.CLASS_OF["frxGBPJPY"], "forex_jpy")
        self.assertEqual(gold.CLASS_OF["cryETHUSD"], "crypto")
        self.assertEqual(gold.CLASS_OF["frxEURCHF"], "forex_calme")

    def test_tableau_par_defaut(self):
        want = {"or": [["S3"], ["S1", "S5"], []], "forex_session": [["S3"], ["S2"], ["S1", "S5"]],
                "forex_jpy": [["S1"], ["S5"], []], "forex_calme": [["S4"], ["S3"], []],
                "crypto": [["S1"], ["S3", "S5"], []], "synthetique": [["S3"], ["S5"], []]}
        self.assertEqual(gold.DEFAULT_CLASS_TIERS, want)
        for tiers in want.values():
            self.assertEqual(len(tiers), 3)
            for c in sum(tiers, []):
                self.assertIn(c, S.STRAT_LABELS)
            flat = sum(tiers, [])
            self.assertEqual(len(flat), len(set(flat)))          # une stratégie n'est que dans un niveau

    def test_strategies_par_classe_et_niveau_max(self):
        from unittest import mock
        cas = {"frxXAUUSD": (["S3"], ["S3", "S1", "S5"], ["S3", "S1", "S5"]),
               "frxEURUSD": (["S3"], ["S3", "S2"], ["S3", "S2", "S1", "S5"]),
               "frxUSDJPY": (["S1"], ["S1", "S5"], ["S1", "S5"]),
               "frxUSDCHF": (["S4"], ["S4", "S3"], ["S4", "S3"]),
               "cryBTCUSD": (["S1"], ["S1", "S3", "S5"], ["S1", "S3", "S5"]),
               "R_75": (["S3"], ["S3", "S5"], ["S3", "S5"])}
        for sym, (t1, t2, t3) in cas.items():
            for tmax, want in ((1, t1), (2, t2), (3, t3)):
                with mock.patch.object(gold, "TIER_MAX", tmax):
                    self.assertEqual(gold.strategies_for(sym), want, f"{sym} niveau {tmax}")

    def test_reglage_manuel_prioritaire_et_actif_hors_classe(self):
        from unittest import mock
        with mock.patch.dict(gold.SYMBOL_OVERRIDES, {"frxEURUSD": ["S4"]}):
            self.assertEqual(gold.strategies_for("frxEURUSD"), ["S4"])
            self.assertIsNone(gold.tier_of("frxEURUSD", "S4"))
            self.assertEqual(gold.strategies_for("frxGBPUSD"), ["S3", "S2", "S1", "S5"])   # les autres gardent leur classe
        self.assertEqual(gold.strategies_for("frxINCONNU"), self.TOUTES)                  # hors classe : toutes

    def test_niveau_d_une_strategie(self):
        from unittest import mock
        self.assertEqual(gold.tier_of("frxXAUUSD", "S3"), 1)
        self.assertEqual(gold.tier_of("frxXAUUSD", "S5"), 2)
        self.assertEqual(gold.tier_of("frxEURUSD", "S5"), 3)
        self.assertIsNone(gold.tier_of("frxXAUUSD", "S4"))                 # pas dans la classe
        with mock.patch.object(gold, "TIER_MAX", 2):
            self.assertIsNone(gold.tier_of("frxEURUSD", "S5"))             # niveau 3 désactivé

    def test_lecture_des_reglages(self):
        self.assertEqual(gold.parse_class_strats("or:S3/S1,S5/;forex_jpy:s1/s5/s2"),
                         {"or": [["S3"], ["S1", "S5"], []], "forex_jpy": [["S1"], ["S5"], ["S2"]]})
        self.assertEqual(gold.parse_class_strats("synth:S5"), {"synthetique": [["S5"], [], []]})      # alias, niveaux manquants
        self.assertEqual(gold.parse_class_strats("n_importe:S1;or:"), {})                              # classe inconnue, vide
        self.assertEqual(gold.parse_class_strats("or:S9,S2/zz/"), {"or": [["S2"], [], []]})            # codes inconnus ignorés
        self.assertEqual(gold.parse_class_strats(None), {})
        for txt, want in (("", 3), (None, 3), ("abc", 3), ("1", 1), ("2", 2), ("3", 3), ("0", 3), ("7", 3), ("2.0", 2)):
            self.assertEqual(gold.parse_tier_max(txt), want, txt)

    def test_etiquette_de_niveau(self):
        base = lambda strat: {"strat": strat, "details": ["✅ x"], "short": "setup", "extra": {}}
        a = gold.add_tier(base("S3"), "frxXAUUSD")
        self.assertEqual((a["tier"], a["extra"]["classe"], a["extra"]["tier"]), (1, "Or", "principale"))
        self.assertIn("🏷️ Or · stratégie principale", a["details"])
        self.assertEqual(a["short"], "setup")
        b = gold.add_tier(base("S5"), "frxXAUUSD")
        self.assertEqual(b["extra"]["tier"], "secondaire")
        c = gold.add_tier(base("S5"), "frxEURUSD")
        self.assertEqual((c["tier"], c["extra"]["tier"]), (3, "à tester"))
        self.assertIn("🧪 À tester · Forex de session", c["details"])
        self.assertTrue(c["short"].endswith("🧪 à tester"))
        d = gold.add_tier(base("S5"), "R_100")
        self.assertEqual((d["tier"], d["extra"]["classe"], d["extra"]["tier"]), (2, "Indices synthétiques", "secondaire"))

    def test_etiquette_manuelle_et_hors_classe(self):
        from unittest import mock
        with mock.patch.dict(gold.SYMBOL_OVERRIDES, {"frxEURUSD": ["S4"]}):
            m = gold.add_tier({"strat": "S4", "details": [], "short": "s", "extra": {}}, "frxEURUSD")
        self.assertEqual((m["tier"], m["extra"]["tier"], m["details"]), (None, "manuelle", []))
        h = gold.add_tier({"strat": "S1", "details": [], "short": "s", "extra": {}}, "frxINCONNU")
        self.assertEqual((h["extra"]["classe"], h["extra"]["tier"]), ("Hors classe", "hors classe"))

    def test_resolution_des_actifs_du_backtest(self):
        self.assertEqual(gold.resolve_symbols("all"), gold.ALL_SYMBOLS)
        self.assertEqual(gold.resolve_symbols("synth"), gold.SYNTHETICS)
        self.assertEqual(gold.resolve_symbols("forex_jpy"), ["frxUSDJPY", "frxEURJPY", "frxGBPJPY", "frxAUDJPY"])
        self.assertEqual(len(gold.resolve_symbols("forex")), 15)
        self.assertEqual(gold.resolve_symbols("or, crypto"), ["frxXAUUSD", "cryBTCUSD", "cryETHUSD"])
        self.assertEqual(gold.resolve_symbols("frxEURUSD,forex_jpy,frxEURUSD"), ["frxEURUSD", "frxUSDJPY", "frxEURJPY", "frxGBPJPY", "frxAUDJPY"])
        self.assertEqual(gold.resolve_symbols("frxXYZ"), ["frxXYZ"])

    def test_scan_donne_a_chaque_classe_ses_strategies(self):
        from unittest import mock
        data = B.gen_sim(20, 4)
        rp = B.Replay(data)
        t = 5000
        provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
        for sym, tmax, want in (("frxUSDJPY", 3, ["S1", "S5"]), ("frxXAUUSD", 1, ["S3"]), ("frxEURUSD", 3, ["S2", "S1", "S3", "S5"]),
                                ("cryBTCUSD", 2, ["S1", "S3", "S5"]), ("frxUSDCHF", 3, ["S3", "S4"])):
            seen = {}

            def fake(provide, now, funnel, only=None, dec=2, kz=True, modes=None, _seen=seen):
                _seen["only"] = only
                return []
            with mock.patch.object(S, "scan_all", fake), mock.patch.object(gold, "TIER_MAX", tmax):
                gold.scan(sym, provide, data[t]["epoch"] + 300, {}, Counter(), ())
            self.assertEqual(sorted(seen.get("only", [])), sorted(want), f"{sym} niveau {tmax}")

    def test_marque_a_tester_dans_les_formats_courts(self):
        tfs = s5_series(4)
        provide, t = s5_provider(tfs, 5998)
        sig = next(x for x in S.scan_s5(provide, t + 60, Counter(), 3, True, "limit") if x["extra"]["cascade"] == "H4>H1>M15")
        sig.update(sym="frxEURUSD", name="EURUSD", dec=3, ts=t + 60, age_min=1.0, trend_lines=[], trend_short="")
        gold.add_tier(sig, "frxEURUSD")
        self.assertEqual(sig["tier"], 3)
        for fmt, mark in (("complet", "🧪 À tester"), ("compact", "🧪"), ("minimal", "🧪"), ("contexte", "🧪")):
            os.environ["ALERT_FORMAT"] = fmt
            try:
                self.assertIn(mark, gold.gold_message(sig, 7), fmt)
            finally:
                os.environ.pop("ALERT_FORMAT", None)


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
        for k in ("SPREAD_TABLE", "SYNTH_RECAP_HEURES", "ALERT_FUSEAU_NOM", "SPREAD_PCT", "CLASS_FILTER"):
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
        txt = self._msg(self._sig(confluence=["S2"]))
        self.assertIn("⚡ Sweep + CHoCH + ", txt.split("\n")[0])
        self.assertIn(S.STRAT_LABELS["S2"], txt.split("\n")[0])

    def test_age_affiche_seulement_si_alerte_tardive(self):
        self.assertNotIn("signal il y a", self._msg(self._sig(age_min=1.0)))
        txt = self._msg(self._sig(age_min=7.0))
        self.assertIn("signal il y a 7 min", txt)
        self.assertEqual(len(txt.split("\n")), 3)

    def test_ordre_au_marche_et_signal_test(self):
        txt = self._msg(self._sig(dir="BUY", otype="BUY", tier=3), tid=13)
        lines = txt.split("\n")
        self.assertEqual(lines[0].split(" · ")[0].split()[-1], "BUY")
        self.assertIn("🧪", lines[0])
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


if __name__ == "__main__":
    unittest.main()
