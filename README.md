# Bot or (XAUUSD) + forex + BTC/ETH + indices Volatility

Bot d'**alertes Telegram** pour l'or, 15 paires forex (7 majeures contre USD, 8 croisements), BTC, ETH et les 10 indices Volatility de Deriv, avec quatre stratégies (règles précises : [STRATEGIES.md](STRATEGIES.md)). Il reprend l'architecture du bot CRT/Impulsion (client Deriv, suivi des trades, garde-fous, graphique, boutons Telegram, backtest) mais aucune de ses stratégies, sauf Pullback (ex-Impulsion + Fibonacci).

| Code | Stratégie | Unités de temps |
|---|---|---|
| S1 | Pullback (structure + retracement Fibonacci 50-79 %) | H4 > H1 > M15 |
| S2 | Sweep + CHoCH (SMC) | H4/H1 > M15 > M5 |
| S3 | Figures & Retournement (figures chartistes + retournement contre une tendance H4 mûre ; ex-Chart Patterns et Reversal) | H1/H4 > M15 |
| S4 | CRT (Candle Range Theory : C1/C2 en H4 ou H1, cassure de structure après C2) | H4/H1 > M15 |

Le bot **n'exécute aucun ordre** : il envoie des alertes (entrée, stop, TP1 à TP3 avec ratio, graphique) et suit leur résultat en R. Aucune stratégie n'est garantie ; les paramètres sont des points de départ à valider par backtest.

## Actifs

| Actif | Symboles Deriv |
|---|---|
| Or | `frxXAUUSD` |
| Majeures contre USD | `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxUSDCHF`, `frxAUDUSD`, `frxUSDCAD`, `frxNZDUSD` |
| Croisements | `frxAUDJPY`, `frxEURAUD`, `frxEURCAD`, `frxEURCHF`, `frxEURGBP`, `frxEURJPY`, `frxGBPAUD`, `frxGBPJPY` |
| Cryptos | `cryBTCUSD`, `cryETHUSD` |
| Indices Volatility | `R_10`, `R_25`, `R_50`, `R_75`, `R_100` et `1HZ10V`, `1HZ25V`, `1HZ50V`, `1HZ75V`, `1HZ100V` |

- **Par défaut, toutes les stratégies actives tournent sur chaque actif**, indices synthétiques compris. Les distances sont en ATR, mais les règles ont été pensées pour l'or : compare actif par actif au backtest et retire ceux qui ne tiennent pas (variable `SYMBOLS`).
- **Exposition par devise** : un trade compte long ou short sur chacune de ses deux devises (EURJPY acheté = long EUR, short JPY ; or acheté = short USD) ; 2 trades au plus dans le même sens sur une même devise. BTC et ETH : 2 au plus dans le même sens. Pas de limite pour les indices.
- **Cryptos et indices (24h/24)** : pas de rollover ni de fermeture de week-end ; seules les annonces USD bloquent les alertes (pas les indices) ; S2 et S4 sans limite d'horaire de session.
- **Indices Volatility** : prix généré aléatoirement, insensible aux news, sans récapitulatif du matin. Rien ne garantit qu'une stratégie ait un avantage sur un prix aléatoire : valide au backtest (`--sym synth`) avant de te fier aux alertes. La variante Pullback « classique » (EMA/ADX) n'a pas de sens sur un prix généré ; la variante « structure » y est imposée. D1 = bougie daily de Deriv (00h GMT). **Récapitulatif du soir** : chaque jour, 4 h avant la clôture de cette bougie (`SYNTH_RECAP_HEURES`), un message par classe (« Volatility Indices », « Volatility (1s) Indices »).
- **Spreads par défaut** (estimations, `SPREAD_PCT` ou `SPREAD_TABLE`) : or 0,015 %, majeures 0,006 %, croisements 0,007 à 0,014 %, BTC/ETH 0,05 %, indices 0,02 %.

### Classes d'actifs

Les actifs sont regroupés en classes (Or, Forex de session, Forex JPY, Forex calme, Cryptos, Indices synthétiques) pour les récapitulatifs, l'option `--sym` du backtest (`--sym forex_jpy`) et la colonne « classe » du rapport. **Aucune stratégie n'est filtrée par classe** : toutes les stratégies actives (`STRATEGIES`) tournent sur chaque actif. Pour restreindre un actif précis, utilise `SYMBOL_STRATEGIES` (ex. `frxEURUSD:S1,S2;cryBTCUSD:S1,S2`) ; un actif absent reçoit toutes les stratégies actives. Garde une stratégie sur un actif seulement si le backtest la montre positive sur les deux périodes avec au moins 30 trades.

## Fichiers

| Fichier | Rôle |
|---|---|
| `gold.py` | Scan, client Deriv, alertes et commandes Telegram, suivi |
| `strategies.py` | Stratégies S1 et S2 (S3 et S4 y sont enregistrées), indicateurs, sessions |
| `crt.py` | Stratégie S4 CRT (Candle Range Theory) : C1/C2 en H4 ou H1, cassure M15 |
| `patterns.py` | S3 : figures sur H1/H4, cassure confirmée en M15, confluence avec le retournement |
| `reversal.py` | Retournement possible (message d'information) et ordre de retournement de S3 |
| `trend.py` | Tendance et âge (D1, H4, H1) pour les récapitulatifs |
| `tracker.py` | Suivi des trades (TP1/TP2/TP3, break-even, sorties de structure et au temps) |
| `guard.py` | Fenêtres sans alerte, limites d'exposition, santé du bot, bilan |
| `charts.py` | Graphique joint à l'alerte |
| `backtest.py` | Rejeu M5 de toutes les stratégies, deux périodes, grille de réglages |
| `tests.py` | 183 tests (`python -m unittest tests -v`, aussi lancés par `tests.yml`) |
| `STRATEGIES.md` | Règles précises de chaque stratégie |
| `.github/workflows/` | `gold.yml` (scan, déclenché par cron externe, état sauvegardé sur la branche `data`), `tests.yml`, `backtest.yml` (manuel) |

## Installation

1. Crée un dépôt GitHub avec ce dossier (`.github/workflows` inclus).
2. **Settings > Secrets and variables > Actions** : secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` (facultatif : `HEARTBEAT_URL`, ping de surveillance de type healthchecks.io appelé à chaque passage réussi).
3. **Settings > Actions > General > Workflow permissions : Read and write** (pour sauvegarder l'état sur la branche `data`).
4. Le workflow n'a pas de `schedule` : déclenche-le toutes les 5 minutes avec ton cron externe (`workflow_dispatch`). Un scan de 28 actifs dure environ 50 secondes.
5. Lance une fois le workflow avec `test = true` : tu reçois un message de contrôle avec l'entonnoir.

**Variables facultatives** (onglet Variables) :

| Variable | Rôle (défaut) |
|---|---|
| `STRATEGIES` | Stratégies actives, ex. `S2,S3` (défaut `S1,S2,S3,S4` ; Mean Reversion (ancien `S3`) est supprimée ; l'ancien `S5` est lu comme `S1`, l'ancien `S7` comme `S3`, l'ancien `S8` comme `S4`) |
| `SYMBOLS` | Actifs suivis (défaut : les 28 ci-dessus) |
| `SYMBOL_STRATEGIES` | Stratégies par actif, ex. `frxEURUSD:S1,S2;cryBTCUSD:S2,S3` |
| `SYMBOL_STRATEGIES` | Stratégies imposées actif par actif (voir « Classes d'actifs »). Les anciennes variables `CLASS_FILTER`, `CLASS_STRATEGIES` et `TIER_MAX` sont ignorées |
| `ENTRY_MODE` / `ENTRY_MODES` | `auto` (défaut : ordres limites), `market` ou `limit` ; par stratégie, ex. `S2:market,S3:market` |
| `INTRADAY` | `0` désactive le cadre intraday ; `INTRADAY_RUNNERS=1` laisse courir le reste après TP1 en fin de séance ; `CRYPTO_INTRADAY=1` y soumet les cryptos |
| `REVERSAL_ALERTS` | Message d'information de retournement (défaut actif) |
| `S6_TOL_ATR` | Réglage de S3 : figures et retournement (les noms `S6_*` et `S7_*` sont conservés tels quels, même après la renumérotation des stratégies ; voir STRATEGIES.md) |
| `S1_MIN_RR`, `S1_RISK_CAP_H1`, `S1_ADX_MIN`, `S1_D1_ALIGN`, `S1_OBST_ENTRY` | Garde-fous de S1 Pullback : ratio minimal sur TP2 (défaut 3 ; 0 = désactivé), risque maximal en ATR H1 (défaut 2 ; 0 = aucun), ADX minimal du timeframe de tendance (défaut 20 ; 0 = désactivé), pas de trade contre le D1 (défaut actif), entrée sur un niveau H4/H1 en intraday (défaut actif) ; voir STRATEGIES.md |
| `S2_BIAS_FILTER`, `S2_HTF_ZONE`, `S2_FIB_FILTER` | Garde-fous de S2 Sweep + CHoCH : sens du biais de structure H4/H1, sweep sur une zone H4/H1, entrée du bon côté de l'équilibre Fibonacci (défaut actifs ; `0` désactive) |
| `S2_MIN_RR`, `S2_RISK_CAP_H1`, `S2_MAX_AGE_MIN`, `S2_VOL_MIN_RATIO`, `S2_SWEEP_MIN_ATR` | Garde-fous de S2 : ratio minimal sur TP2 (défaut : celui de S1, 3), risque maximal en ATR H1 (1,5), âge maximal du signal en minutes (20), ATR H1 minimal par rapport à sa médiane (0,5), dépassement minimal de la mèche du sweep en ATR M15 (0,1) ; `0` désactive |
| `S1_CONFIRM_TF`, `S2_CONFIRM_TF`, `S3_CONFIRM_TF`, `S4_CONFIRM_TF` | Timeframe de confirmation / d'entrée de chaque stratégie : `M15` ou `M5` (vide = historique : M15, sauf S2 qui suit `INTRADAY`). Voir STRATEGIES.md, « Confirmation en M15 ou en M5 » |
| `ONE_TRADE_PER_SIDE` | `1` (défaut) : un seul trade par actif et par sens, toutes stratégies confondues ; `0` : un par stratégie |
| `CONFLUENCE_MIN` | Fenêtre de confluence entre stratégies, en minutes (défaut 60, `0` désactive) |
| `SPREAD_PCT`, `SPREAD_TABLE` | Spread supposé en % du prix : global, ou par actif ex. `frxXAUUSD=0.02,cryBTCUSD=0.04` (prioritaire) |
| `WEEKEND_EXIT` | `0` désactive la clôture du vendredi |
| `ALERT_FORMAT`, `CHARTS` | Format du texte (voir plus bas) ; `CHARTS=0` retire le graphique |
| `ALERT_FUSEAU`, `ALERT_FUSEAU_NOM` | Fuseau affiché (défaut `Africa/Porto-Novo`, heure du Bénin ; `none` pour ne plus afficher d'heure) |
| `RECAP_FORMAT`, `RECAP_HEURE`, `RECAP_FUSEAU`, `SYNTH_RECAP_HEURES` | Récapitulatifs de tendance (voir plus bas) |
| `DERIV_APP_ID`, `DERIV_WS_URL`, `CALENDAR_URL` | Réglages techniques : identifiant d'application Deriv, point d'accès forcé (plusieurs séparés par des virgules), calendrier économique |

**État.** `trades.json`, `guard.json` et `state.json` sont sauvegardés à chaque scan sur la branche `data` (une seule révision, écrasée) ; si le dépôt est public, cette branche est lisible par tous (aucun secret). Les bougies restent dans le cache GitHub : sa perte ne fait que ralentir un scan. Pour les annonces non couvertes par le calendrier automatique, copie `news.example.json` en `news.json`.

## Figures chartistes et retournement (S3)

- **S3, partie figures** : figures de **retournement** (double et triple sommet/creux, tête et épaules et inversée, biseaux, tasse avec anse) et de **continuation** (drapeau, fanion, triangles, rectangle, canal, élargissement). Détection sur les bougies clôturées H1 ou H4, cassure de la ligne confirmée par une clôture M15. Entrée en ordre limite au retest de la ligne, stop au-delà de la figure, objectifs 0,5 / 1 / 1,5 fois la hauteur de la figure. Retournement ou continuation selon la tendance qui précède.
- **S3, partie retournement** (ex-S7) : l'alerte de retournement devient un ordre (tendance H4 mûre, sweep d'un niveau majeur, cassure de structure H1, essoufflement). Entrée au retest du creux (sommet) cassé, stop au-delà de l'extrême du sweep, objectifs sur la liquidité opposée intacte (TP1 = 1 R, TP2 entre 2 R et 6 R, TP3 à 3 R ou plus, sinon 2 R / 3 R). **Contre la tendance H4** : prendre une taille réduite (le bot ne calcule pas de taille de position).
- **Confluence** : une figure de retournement de S3 qui va dans le sens du retournement détecté est admise avec un risque maximal 1,4 fois plus large et porte « Confluence : retournement possible » ; sans confluence, son ratio minimal vers TP3 passe de 1 à 1,5. Les figures de continuation ne sont pas concernées.
- **Un seul signal par sens** : si une figure de retournement et le retournement détecté vont dans le même sens, c'est la figure qui porte le signal (avec sa confluence).
- **Alerte d'information** : tant que S3 est active, le retournement n'arrive qu'en ordre (pas de doublon). Pour le seul message d'information, retire S3 de `STRATEGIES` ; `REVERSAL_ALERTS=0` supprime ce message.
- Seuils **non validés** : lance `python backtest.py --only S3` (le rapport sépare chaque figure et la confluence) avant de t'y fier.

## Récapitulatifs de tendance

Chaque matin du lundi au vendredi, à **01h00 New York** (une heure avant Londres), le bot envoie un message par classe (Or, Forex USD, Forex croisements, Cryptos) avec, par actif, la tendance **D1, H4, H1** (🟢 haussière, 🔴 baissière, ⚪ pas de tendance claire) et son **âge** (⚡ = cassure impulsive) :

```
XAUUSD  🟢 D1 établie ⚡ · 🟢 H4 mûre · 🔴 H1 naissante
```

- **Âge** = nombre de jambes consécutives (sommet et creux plus hauts pour une hausse) : naissante 1, établie 2-3, mûre 4 et plus. Deux swings suffisent ; la structure doit être intacte et le sommet précédent cassé par une **clôture**. L'invalidation est le dernier creux (hausse) ou sommet (baisse).
- `RECAP_FORMAT=complet` : trois lignes par actif (durée, invalidation) et une phrase de synthèse. `RECAP_HEURE` et `RECAP_FUSEAU` changent l'heure (défaut `America/New_York`). Journée sautée si le scan a plus de 6 h de retard. `/tendance` renvoie le récapitulatif au prochain scan.
- **Dans chaque alerte** : tendance D1 et H4 avec âge, ✅ dans le sens du trade, ⚠️ à contre-sens. Ce n'est **pas un filtre** (sauf S2, qui suit le biais de structure H4/H1). Le backtest enregistre ces informations (`tend_d1`, `tend_h4`) pour comparer avant d'en faire un filtre.

## Ordres limites

Par défaut, chaque alerte est un **ordre limite** posé au retest d'une zone (bloc d'ordre à son bord proche, FVG à son milieu ; sinon marché) :

| Stratégie | Zone d'entrée | Validité |
|---|---|---|
| Pullback | bloc d'ordre M15 (sinon FVG M15) | 2 h |
| Sweep + CHoCH | bloc d'ordre M5 (sinon FVG M5) | 1 h |
| Figures & Retournement (figure) | ligne de la figure cassée | 3 h |
| Figures & Retournement (retournement) | dernier creux (sommet) H1 cassé | 2 h |

Le bot signale « Ordre limite touché », « Ordre annulé » (TP1 atteint sans fill, stop franchi, week-end) ou « Ordre expiré » pour que tu annules chez ton courtier. Une zone à plus de 1,5 ATR du prix, ou du mauvais côté, écarte le signal ou laisse l'alerte au marché. `/bilan` affiche le taux de remplissage. **Contrepartie** : meilleur prix et stop plus court, mais certains trades ne sont jamais remplis (souvent les meilleurs). Compare : `--set gold.ENTRY_MODE=market,limit`.

## Cadre intraday (par défaut ; `INTRADAY=0` pour le désactiver)

Contexte et obstacles majeurs en H4/H1, confirmation en M15, trade de la journée.

- **Entrée sur réaction à un niveau** (S1, S2) : à moins de 0,5 ATR H1 d'un niveau ou dans une zone H4/H1 du bon côté, sinon « hors niveau H4/H1 ». S3 et S4 n'y sont pas soumises.
- **Objectif avant le prochain obstacle** (toutes) : TP1 ne dépasse jamais le prochain obstacle opposé (sommet/creux H1/H4, plus haut/bas de la veille, zone d'offre ou de demande). À moins de 1 R de l'entrée : signal écarté ; sinon TP1 est ramené 0,1 ATR H1 avant l'obstacle, et les objectifs au-delà aussi ; le ratio minimal de la stratégie est alors recontrôlé et le signal écarté s'il n'est plus atteint. Après TP1, stop à l'entrée.
- **Fin de séance** (forex et or) : trades clôturés au plus tard à 16h45 New York ou 10 h après l'ouverture, **même après TP1** ; ordre en attente annulé au même moment. Cryptos et indices : aucune fin de séance.
- Les seuils sont des choix de départ. Pour comparer : backtest avec `INTRADAY` vide, puis `0` (ou `--no-intraday`).

## Réalisme et fiabilité

- **Spread** retiré de chaque trade en direct comme au backtest (« spread inclus »). Remplace les estimations par ceux de ton courtier ; compare quelques alertes à ta plateforme (l'écart de prix avec ton courtier n'est pas mesurable ici).
- **Gaps** : si une bougie ouvre au-delà du stop, clôture à l'ouverture (perte possible supérieure à 1 R).
- **Week-end** : trades or et forex ouverts le vendredi à 16h30 New York clôturés, ordres en attente annulés, aucune alerte le week-end. Cryptos et indices non concernés.
- **Retard** : chaque alerte indique son âge (plus de limite d'âge ni de filtre de volatilité : le filtrage est à reconstruire, voir STRATEGIES.md).
- **Calendrier économique** indisponible plus de 6 h : message d'alerte, puis message de retour ; les annonces ne bloquent plus les alertes entre-temps.
- **Hypothèses prudentes du suivi et du backtest** : un ordre limite n'est rempli que si le prix traverse le niveau d'au moins un demi-spread ; dans la bougie du fill, aucun objectif n'est compté (le stop, si) ; TP1 puis retour à l'entrée = break-even.
- **Bilan** : `/bilan` (30 jours, par stratégie et par actif, réel vs simulé avec `/r`, RR visé contre R obtenu). Le bilan hebdomadaire est envoyé automatiquement (total 7 jours, une ligne par stratégie, signaux écartés, « Validation : N trades sur ~100 pour juger »).

## Format des alertes et heures

Le graphique est joint à chaque alerte. Le texte (variable `ALERT_FORMAT`, défaut `essentiel`) existe en cinq formats : `essentiel` (3 lignes), `minimal` (3 lignes), `compact` (~10 lignes), `contexte` (~11 lignes), `complet` (~24 lignes).

```
🔴 SELL LIMIT · XAUUSD M15 · ⚡ Sweep + CHoCH + Pullback · 14:35
4012.50 · SL 4018.20 · TP 4001.30 / 3992.40 / 3980.10
Valable jusqu'à 16:30 · #12
```

Toutes les heures sont en heure du Bénin (UTC+1, sans heure d'été). Le bot raisonne en heure de New York : les horaires glissent d'une heure selon l'heure d'été américaine (2e dimanche de mars au 1er dimanche de novembre).

| Événement | New York | Bénin (été US) | Bénin (hiver US) |
|---|---|---|---|
| **Récapitulatif de tendance** | 01h00 | **06h00** | **07h00** |
| Début de la plage asiatique | 20h00 | 01h00 | 02h00 |
| Killzone de Londres | 02h00-05h00 | 07h00-10h00 | 08h00-11h00 |
| Killzone de New York | 07h00-10h00 | 12h00-15h00 | 13h00-16h00 |
| London Close | 10h00-12h00 | 15h00-17h00 | 16h00-18h00 |
| Rollover (plus d'alerte dès) | 16h55 | 21h55 | 22h55 |
| Ouverture des bougies D1 et H4 | 17h00 | 22h00 | 23h00 |
| Vendredi : plus d'alerte dès / clôture dès | 15h30 / 16h30 | 20h30 / 21h30 | 21h30 / 22h30 |

## Commandes Telegram

Boutons **Pris / Ignoré** sous chaque alerte, et `/pris N`, `/ignore N`, `/r N X` (ton résultat réel du trade #N en R, ex. `/r 12 -0.8`), `/bilan`, `/tendance`. Les commandes sont lues à chaque scan (réponse sous 5 minutes).

## Backtest

Workflow **Backtest Or** ou, en local : `python backtest.py --days 120 --split 0.6`.

- Rejoue les mêmes fonctions que le bot, sans regarder le futur, avec spread (`--spread-pct` ou `SPREAD_TABLE`). Prévois environ 25 jours d'échauffement (EMA 200 du H4) : demande `--days` en plus.
- `--sym frxXAUUSD,frxEURUSD`, `--sym all` (28 actifs), `--sym synth`, ou une classe (`forex_jpy`, `crypto`…) ; `--only S2,S3` (`--only S3` pour figures et retournement) ; `--set strategies.S5_ADX_MIN=15,18,22` pour une grille ; `--source csv` (un seul actif) ou `--source sim` (marche aléatoire, contrôle de bon sens).
- Rapport par actif, stratégie, sens, session, alignement H4, coût du spread et stabilité entre deux périodes ; l'intervalle de confiance rééchantillonne des jours entiers.
- **Lecture** : sous quelques centaines de trades, un taux de gain n'est que du bruit. Retiens une stratégie seulement si l'espérance est positive sur les deux périodes, avec un intervalle de confiance qui exclut zéro, après ton vrai spread.

## Ce qui a été vérifié, et ce qui ne l'a pas été

**Vérifié** (données simulées, sans réseau) : le code s'exécute de bout en bout, les stratégies produisent des signaux, le suivi, les messages et le graphique fonctionnent, et sur une marche aléatoire l'espérance est proche de zéro.

**Non vérifié** : la connexion à l'API Deriv, l'envoi Telegram et surtout **la rentabilité sur marché réel**. Fais d'abord un run avec `test = true`, puis un backtest sur Deriv, avant de suivre les alertes.
