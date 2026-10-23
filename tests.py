"""Tests automatisés : python -m unittest tests -v

Aucun accès réseau : les données viennent d'une marche aléatoire (backtest.gen_sim) ou de séries construites.
Ces tests vérifient la mécanique du bot (indicateurs, tendance, suivi des trades, garde-fous, messages,
backtest), pas la rentabilité des stratégies.
"""
import os
import unittest
from collections import Counter
from datetime import datetime
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

    def test_lots(self):
        os.environ["ACCOUNT_BALANCE"], os.environ["RISK_PCT"] = "10000", "1"
        self.assertEqual(G.lot_size("frxEURUSD", 1.0850, 1.0820), 0.33)
        self.assertEqual(G.lot_size("frxUSDJPY", 150.0, 149.7), 0.5)
        self.assertEqual(G.lot_size("frxXAUUSD", 2650, 2646), 0.25)
        self.assertEqual(G.lot_size("cryBTCUSD", 70000, 69500), 0.2)

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
        self.assertEqual(gold.alert_format(), "complet")
        self.assertIn("signal il y a 3 min", gold.gold_message(self.sig, 15))
        self.assertEqual(gold.age_txt({"age_min": 0.2}), "à l'instant")

    def test_variables_vides(self):
        self.assertEqual(gold.parse_strategies(""), ["S1", "S2", "S3", "S4"])      # variable GitHub non définie
        self.assertEqual(gold.parse_strategies(None), ["S1", "S2", "S3", "S4"])
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
        data = B.gen_sim(70, 3)
        rp, funnel = B.Replay(data), Counter()
        found = {"limit": 0, "market": 0}
        for mode in ("limit", "market"):
            gold.ENTRY_MODE, sent = mode, {}
            for t in range(7200, 10500):
                provide = lambda tf, force=False, _t=t: rp.provide(tf, _t)
                for sig, _ in gold.scan("frxXAUUSD", provide, data[t]["epoch"] + 300, sent, funnel, ()):
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


if __name__ == "__main__":
    unittest.main()
