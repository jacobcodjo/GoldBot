# Bot or (XAUUSD) + forex + BTC/ETH + indices Volatility

Bot d'**alertes Telegram** pour l'or, 15 paires forex (7 majeures contre USD, 8 croisements), BTC, ETH et les 10 indices Volatility de Deriv, avec quatre stratégies (règles précises : [la section Stratégies](la section Stratégies)). Il reprend l'architecture du bot CRT/Impulsion (client Deriv, suivi des trades, garde-fous, graphique, boutons Telegram, backtest) mais aucune de ses stratégies, sauf Pullback (ex-Impulsion + Fibonacci).

| Code | Stratégie | Unités de temps |
|---|---|---|
| S1 | Pullback (structure + retracement Fibonacci 50-79 %) | H4 > H1 > M15 |
| S2 | Sweep + CHoCH (SMC) | H4/H1 > M15 > M5 |
| S3 | Figures & Retournement (figures chartistes + retournement contre une tendance H4 mûre ; ex-Chart Patterns et Reversal) | H1/H4 > M15 |
| S4 | CRT (Candle Range Theory : C1/C2 en D1 ou H4, cassure de structure après C2) | D1/H4 > M15 |

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
| `strategies.py` | Stratégies S1 et S2 (S3 et S4 y sont enregistrées), indicateurs, primitives SMC, Fibonacci, sessions |
| `setups.py` | S3 (figures H1/H4, retournement), S4 (CRT), tendance et âge (D1, H4, H1) pour les récapitulatifs, alerte de retournement |
| `tracker.py` | Suivi des trades (TP1/TP2/TP3, break-even, sorties de structure et au temps) |
| `guard.py` | Fenêtres sans alerte, limites d'exposition, santé du bot, bilan |
| `charts.py` | Graphique joint à l'alerte |
| `backtest.py` | Rejeu M5 de toutes les stratégies, deux périodes, grille de réglages |
| `tests.py` | 262 tests (`python -m unittest tests -v`, aussi lancés par `tests.yml`) |
| `.github/workflows/` | `gold.yml` (scan, déclenché par cron externe, état sauvegardé sur la branche `data`), `tests.yml`, `backtest.yml` (manuel) |

### Calendrier personnalisé (`news.json`, optionnel)

Pour ajouter des annonces que le flux de calendrier ne couvre pas, crée un fichier `news.json` à la racine : une liste de fenêtres sans alerte (heures UTC),
avec les devises concernées. Exemple :

```json
[
  {"start": "2026-10-28T17:30:00Z", "end": "2026-10-28T19:30:00Z", "note": "FOMC", "currencies": ["USD"]},
  {"start": "2026-11-06T13:00:00Z", "end": "2026-11-06T14:30:00Z", "note": "NFP", "currencies": ["USD"]}
]
```

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
| `S6_TOL_ATR` | Réglage de S3 : figures et retournement (les noms `S6_*` et `S7_*` sont conservés tels quels, même après la renumérotation des stratégies ; voir la section Stratégies) |
| `S1_MIN_RR`, `S1_RISK_CAP_H1`, `S1_ADX_MIN`, `S1_D1_ALIGN`, `S1_OBST_ENTRY` | Garde-fous de S1 Pullback : ratio minimal sur TP1 (défaut 3 ; 0 = désactivé), risque maximal en ATR H1 (défaut 2 ; 0 = aucun), ADX minimal du timeframe de tendance (défaut 20 ; 0 = désactivé), pas de trade contre le D1 (défaut actif), entrée sur un niveau H4/H1 en intraday (défaut actif) ; voir la section Stratégies |
| `S2_BIAS_FILTER`, `S2_HTF_ZONE`, `S2_FIB_FILTER` | Garde-fous de S2 Sweep + CHoCH : sens du biais de structure H4/H1, sweep sur une zone H4/H1, entrée du bon côté de l'équilibre Fibonacci (défaut actifs ; `0` désactive) |
| `S2_MIN_RR`, `S2_RISK_CAP_H1`, `S2_MAX_AGE_MIN`, `S2_VOL_MIN_RATIO`, `S2_SWEEP_MIN_ATR` | Garde-fous de S2 : ratio minimal sur TP1 (défaut : celui de S1, 3), risque maximal en ATR H1 (1,5), âge maximal du signal en minutes (20), ATR H1 minimal par rapport à sa médiane (0,5), dépassement minimal de la mèche du sweep en ATR M15 (0,1) ; `0` désactive |
| `S3_FIB_FILTER`, `S3_FIB_CAP_TP3`, `S3_CONTEXT_ALIGN`, `S3_VOL_MIN_RATIO`, `S3_MAX_AGE_MIN`, `S3_REV_MIN_RR`, `S6_RISK_CAP_ATR`, `S6_MIN_RR`, `S6_NOCONF_MIN_RR`, `S6_CONF_RISK_FACTOR`, `S7_RISK_CAP_ATR`, `S7_ENTRY_MAX_ATR`, `REVERSAL_MIN_SIGNS` | Garde-fous de S3 Figures & Retournement : repli Fibonacci et plafond de TP3, contexte H4/D1, volatilité, âge du déclencheur, ratio du retournement sur TP1 (celui de S1), risque maximal, ratios vers TP3 des figures (1 ; 1,5 sans confluence), facteur de confluence, retest maximal, signes d'essoufflement ; voir la section Stratégies |
| `S4_MIN_RR`, `S4_MAX_AGE_MIN`, `S4_VOL_MIN_RATIO`, `S4_CONTEXT_ALIGN`, `S4_SWEEP_MIN_ATR` | Garde-fous de S4 CRT : ratio minimal jusqu'au milieu de C1 (défaut : celui de S1, 3), âge maximal du signal en minutes (20), ATR H1 minimal par rapport à sa médiane (0,5), pas contre la tendance H4/D1 (défaut actif), dépassement minimal de C2 en ATR de référence (0,1) ; `0` désactive. Références : range daily et H4 |
| `S1_CONFIRM_TF`, `S2_CONFIRM_TF`, `S3_CONFIRM_TF`, `S4_CONFIRM_TF` | Timeframe de confirmation / d'entrée de chaque stratégie : `M15` ou `M5` (vide = historique : M15, sauf S2 qui suit `INTRADAY`). Voir la section Stratégies, « Confirmation en M15 ou en M5 » |
| `ONE_TRADE_PER_SIDE` | `1` (défaut) : un seul trade par actif et par sens, toutes stratégies confondues ; `0` : un par stratégie |
| `CONFLUENCE_MIN` | Fenêtre de confluence entre stratégies, en minutes (défaut 60, `0` désactive) |
| `SPREAD_PCT`, `SPREAD_TABLE` | Spread supposé en % du prix : global, ou par actif ex. `frxXAUUSD=0.02,cryBTCUSD=0.04` (prioritaire) |
| `WEEKEND_EXIT` | `0` désactive la clôture du vendredi |
| `ALERT_FORMAT`, `CHARTS` | Format du texte (voir plus bas) ; `CHARTS=0` retire le graphique |
| `ALERT_FUSEAU`, `ALERT_FUSEAU_NOM` | Fuseau affiché (défaut `Africa/Porto-Novo`, heure du Bénin ; `none` pour ne plus afficher d'heure) |
| `RECAP_FORMAT`, `RECAP_HEURE`, `RECAP_FUSEAU`, `SYNTH_RECAP_HEURES` | Récapitulatifs de tendance (voir plus bas) |
| `DERIV_APP_ID`, `DERIV_WS_URL`, `CALENDAR_URL` | Réglages techniques : identifiant d'application Deriv, point d'accès forcé (plusieurs séparés par des virgules), calendrier économique |

**État.** `trades.json`, `guard.json` et `state.json` sont sauvegardés à chaque scan sur la branche `data` (une seule révision, écrasée) ; si le dépôt est public, cette branche est lisible par tous (aucun secret). Les bougies restent dans le cache GitHub : sa perte ne fait que ralentir un scan. Pour les annonces non couvertes par le calendrier automatique, crée un fichier `news.json` (format et exemple dans la section « Calendrier personnalisé »).

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
- **Retard** : chaque alerte indique son âge (plus de limite d'âge ni de filtre de volatilité : voir la section Stratégies).
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

---

## Stratégies

Quatre stratégies indépendantes, évaluées à chaque scan (toutes les 5 minutes). Chacune a son nom dans les
alertes Telegram (le code S1, S2, S3 et S4 sert seulement aux réglages : variable `STRATEGIES`, option `--only`), son propre suivi et ses propres statistiques. Les noms entre parenthèses sont les
paramètres de `strategies.py` (modifiables, et testables avec `backtest.py --set`).

> **Important.** Aucune stratégie n'a un taux de réussite élevé garanti. Les valeurs ci-dessous sont des
> points de départ classiques, **pas des valeurs optimisées ni validées** sur l'or. Lance le backtest
> (`backtest.yml`) sur plusieurs mois avant de t'y fier, et vérifie sur deux périodes (`--split 0.6`).
> Ce document n'est pas un conseil financier.

### Numérotation des stratégies (changement de codes)

Les quatre stratégies actives sont numérotées **S1 à S4 sans trou**. **Les codes S3 et S4 changent de sens** : si tes variables GitHub
(`STRATEGIES`, `SYMBOL_STRATEGIES`, `ENTRY_MODES`) ou le champ « only » du workflow de backtest contiennent encore les anciens codes, mets-les à jour.

| Ancien code | Nouveau code | Stratégie |
|---|---|---|
| S1 (et S5) | **S1** | Pullback |
| S2 | **S2** | Sweep + CHoCH |
| S4 (et S7) | **S3** | Figures & Retournement |
| S8 | **S4** | CRT |
| S3 (ancienne) | *(supprimée, code « MR »)* | Mean Reversion |

**Variables d'environnement GitHub.** Celles qui portent un code suivent le nouveau code : `S4_CONFIRM_TF`
(Figures & Retournement) deviennent `S3_CONFIRM_TF` ; `S8_CONFIRM_TF` (CRT) devient `S4_CONFIRM_TF`. Renomme-les dans
Settings > Variables, sinon la valeur de l'ancien `S4_CONFIRM_TF` s'appliquerait à la CRT. `S6_*` (figures) et `S7_*` (retournement) gardent leur nom.

**Mean Reversion supprimée.** La stratégie est retirée du bot et ne porte plus de code actif : un `MR` (ou l'ancien `S3` Mean Reversion) écrit dans `STRATEGIES` est ignoré,
mais `S3` désigne désormais Figures & Retournement. Les trades Mean Reversion déjà enregistrés restent suivis et reconnus par leur libellé.

**Anciens codes lus comme les nouveaux.** `S5` est lu comme `S1`, `S7` comme `S3`, `S8` comme `S4`. Les trades déjà enregistrés sont reconnus par
leur libellé (« Sweep + CHoCH », « Chart Patterns », « CRT »…), pas par leur ancien code ; un setup déjà alerté peut l'être une seconde fois
au premier scan après la mise à jour, car sa clé de déduplication contient le code.

---

### Filtrage : reconstruit stratégie par stratégie

Tous les filtres de qualité avaient été retirés, puis ont été reconstruits un par un : S1, S2, S3 et S4 ont chacun leurs garde-fous (voir leur section).
Restent partout les garde-fous d'exploitation : fenêtres news / rollover / week-end, doublons, une position par actif et par sens, exposition par devise.
Règle commune : **ratio minimal 1:3 sur TP1** pour S1, S2, le retournement de S3 et S4 (TP1 = extrême de l'impulsion pour S1, première liquidité opposée pour S2 et le retournement,
milieu de C1 pour S4) ; les figures de S3 gardent un ratio vers TP3 car leurs objectifs sont des fractions de la hauteur de la figure. Les seuils sont des points de départ non validés
par un backtest.

### Actifs

L'or (`frxXAUUSD`), les 7 majeures contre USD (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD), les 8 autres
paires classées « Forex majeures » par Deriv (AUDJPY, EURAUD, EURCAD, EURCHF, EURGBP, EURJPY, GBPAUD, GBPJPY) deux cryptos
(`cryBTCUSD`, `cryETHUSD`) et les 10 indices synthétiques Volatility de Deriv (V10 à V100 et variantes 1s), regroupés par **classe d'actifs** (simple regroupement : **toutes les stratégies actives tournent sur chaque actif**, voir plus bas). Les règles sont
identiques pour tous : seuils en ATR, heures de New York, D1/H4 à 17h. Les stratégies ont été conçues pour l'or ;
leur comportement sur chaque paire est à vérifier au backtest (`--sym all`), actif par actif. Les cryptos ont une volatilité et des spreads très différents de l'or : ne
les juge pas sur les résultats des autres actifs. Exposition **par devise** : un trade est long ou short
sur chacune de ses deux devises (EURJPY acheté = long EUR, short JPY ; l'or acheté = short USD), 2 trades au plus dans le
même sens sur une même devise ; BTC et ETH forment un groupe : 2 trades au plus dans le même sens.

**Cryptos** : marché 24h/24, 7j/7. Les fenêtres de rollover, vendredi soir, dimanche et NFP non plus.
La plage asiatique (liquidité de S2) et les niveaux PDH/PDL gardent leur définition en heure de New York.

### Conventions communes

- **Heures** : heure de New York. **D1 et H4 ouvrent à 17h New York** (reconstruits depuis le H1) ; exception : le D1 des indices synthétiques ouvre à 00h GMT (bougie daily de Deriv).
- **Bougies clôturées** : toutes les conditions utilisent des bougies clôturées ; la bougie en formation ne
  sert qu'à connaître le prix actuel.
- **Déclenchement récent** : la bougie de déclenchement doit être l'une des 2 dernières clôturées (`FRESH`).
- **Tendance dans l'alerte** : chaque alerte indique la tendance D1 et H4 avec son âge (règles de tendance de `setups.py`,
  voir plus bas), ✅ dans le sens du trade, ⚠️ à contre-sens. Information seulement, jamais un filtre.
- **Zones d'entrée de Sweep + CHoCH** : 1) le **bloc d'ordre** (dernière bougie de sens opposé entre
  l'extrême du repli ou du sweep et la bougie de cassure) avec entrée à son **bord proche** (le haut pour un achat, le
  bas pour une vente ; `LIMIT_OB_FRACTION = 0`, 1 = bord lointain) ; 2) à défaut, le **FVG** non comblé créé par le
  déplacement (3 bougies, la bougie du milieu doit être un déplacement : corps >= 1,2 x le corps moyen) avec entrée
  à son **milieu** (`LIMIT_FVG_FRACTION = 0.5`) ; 3) à défaut, l'ordre reste au marché. Le type de zone (OB, FVG ou
  marché) est enregistré (`poi` dans le rapport du backtest).
- **Ordres limites** (défaut, `ENTRY_MODE=auto`) : l'entrée est un ordre limite au retest d'une zone propre à chaque
  stratégie, à condition que la zone soit entre le stop et le prix actuel, sinon l'ordre est au marché.
  L'ordre est **annulé** si TP1 est atteint avant l'entrée, si une bougie clôture au-delà du stop, si le marché ferme pour
  le week-end, ou après sa durée de validité (S1 24 h, S2 1 h, S3 3 h, S4 1 h, ou 2 h pour son ordre de retournement : `LIMIT_TTL`). Les ordres limites améliorent le prix d'entrée mais manquent
  les mouvements qui ne reviennent pas : compare les rendements **totaux** au backtest, pas seulement par trade.
  Le suivi ne considère l'ordre posé qu'à partir de la bougie suivant l'alerte.
- **Ordre au marché** (`ENTRY_MODE=market`, ou stratégie listée dans `ENTRY_MODES`) : au prix du scan.
- **Stop** : au-delà de l'extrême de la structure, plus une marge de 0,15 x ATR (`BUF_ATR`). Risque minimal
  0,5 x ATR du timeframe d'entrée (`MIN_RISK_ATR`) : si le stop est plus proche, il est éloigné jusque-là.
- **Objectifs** : S1 : extrême de l'impulsion puis extensions 1,272 et 1,618 (voir sa section). S2 : TP1, TP2 et TP3 sur les liquidités opposées successives (voir S2).
- **Gestion** (`tracker.py`) : 50 % clôturés à TP1 et stop à l'entrée ; 25 % à TP2 et stop à TP1 ; 25 % vers
  TP3. Sortie avant TP1 si une bougie clôture au-delà du niveau d'invalidation, ou après 150 bougies sans TP1.
  Si stop et cible sont touchés dans la même bougie, le stop est supposé touché en premier. Hypothèses prudentes : un ordre limite n'est rempli que si le prix
  traverse le niveau d'au moins un demi-spread ; aucun objectif n'est compté dans la bougie de remplissage ; si une bougie atteint TP1 puis revient à l'entrée
  (ou TP2 puis revient à TP1), le trade ferme à ce stop.
- **Week-end** (or et forex) : trades encore ouverts clôturés le vendredi à 16h30 New York ; pas d'alerte le week-end.
- **Gap** : si une bougie ouvre au-delà du stop, la sortie se fait à l'ouverture (perte possible supérieure à 1 R).
- **Spread** : retiré du résultat de chaque trade (en R), en direct comme au backtest.
- **Fenêtres sans alerte** : rollover 16h55-17h15, vendredi dès 15h30, ouverture de dimanche 17h-18h, NFP,
  FOMC, annonces à fort impact de la devise de l'actif (USD pour l'or ; les deux devises pour une paire),
  15 min avant et 45 min après (90 min après une décision de taux).
- **Risque** : pas de limite sur le nombre total de trades ouverts ; exposition nette de 2 trades au plus dans le même sens sur une même devise (USD, EUR, JPY…), une seule
  position par actif, stratégie et sens. Aucun blocage après une série de pertes : le bot n'arrête pas les alertes
  selon les résultats de la journée ou de la semaine.

---

### Asian Breakout : supprimée

L'ancienne stratégie Asian Breakout (cassure de la plage asiatique à l'ouverture de Londres) est supprimée : plus de code, de réglages ni de
fenêtre de scan. Les trades de cette stratégie déjà ouverts restent suivis jusqu'à leur sortie. La plage asiatique sert toujours de niveau
de liquidité à Sweep + CHoCH (« Asie H » / « Asie B »).

---

### Pullback (code S1) · HTF > MTF > LTF

S1 est l'ancienne Impulsion + Fibonacci (S5) : tendance HTF (structure), repli de 50-79 % d'une impulsion MTF, entrée sur la
confirmation LTF. L'ancienne Trend Pullback (variante « classique » : EMA 50/200 + ADX, cassure M15) est **supprimée** ; son code, ses
constantes `S1_*` et la variable `PULLBACK_VARIANT` (désormais ignorée) n'existent plus. Les anciens codes (`S5` dans `STRATEGIES`,
`SYMBOL_STRATEGIES`, `ENTRY_MODES`) sont lus comme `S1`, et les trades enregistrés avant la suppression
(libellés « Trend Pullback », « Impulsion ») restent suivis. Chaque trade porte `variante = structure`. Le détail des règles est
dans la section « Règles de Pullback » plus bas.

---

### Sweep + CHoCH (code S2) · H4/H1 > M15 > M5

**Idée** (Smart Money Concepts) : dans le sens de la structure H4/H1, le prix balaie un niveau où s'accumulent des stops
**en entrant dans une zone d'intérêt H1/H4**, puis casse sa structure M5 en sens inverse. On entre contre le balayage.

**1. Biais de structure** (`s2_bias`, règles de `setups.py`, `S2_BIAS_FILTER`)
- Biais H4 : sommet et creux plus hauts (plus bas) avec cassure par clôture du sommet (creux) précédent. Si le H4 n'a pas
  de tendance claire, on lit le H1. Aucun biais clair : pas de signal.
- On ne trade que dans le sens du biais (un achat exige un biais haussier). Le filtre s'applique avant le choix du sweep : un sweep récent contre le biais ne masque pas un sweep valide plus ancien. Un repli H1 contre un H4 haussier ne change pas le biais.

**2. Niveaux de liquidité** (chacun a une date de naissance t0)
- PDH / PDL : plus haut / plus bas de la veille (journée 17h-17h New York ; **00h-00h GMT, la bougie daily de Deriv, pour les indices synthétiques**), valables dès l'ouverture du jour.
- Asie H / Asie B : extrêmes de la plage asiatique, valables dès 02h00.
- EQH / EQL : deux swings H1 (fractale de 2) à moins de 0,15 x ATR H1 l'un de l'autre, parmi les 8 derniers
  (`S2_EQ_TOL_ATR`), valables dès la bougie du second swing.
- **Un niveau n'est de la liquidité qu'une fois** (`S2_FRESH_LEVELS`) : si une mèche M15 l'a déjà dépassé depuis t0,
  les stops ont déjà été pris et il est ignoré (y compris pour un second sweep du même niveau).

**3. Sweep M15** (dans les 8 dernières bougies M15, `S2_SWEEP_BARS`)
- Une bougie dont la mèche dépasse le niveau mais qui **clôture de l'autre côté**. Si une bougie M15 ultérieure
  clôture au-delà du niveau, c'est une vraie cassure : le setup est annulé.

**4. Zone d'intérêt H4/H1** (`htf_zones`, `S2_HTF_ZONE`) : le sweep doit toucher une zone
- Zone de demande (achat) ou d'offre (vente) née d'un **déplacement** (corps >= 1,2 x le corps moyen) qui casse les
  5 bougies précédentes : le **bloc d'ordre** (dernière bougie de sens opposé avant le déplacement) ou le **FVG** de 3 bougies.
  Recherche sur les 40 dernières bougies H4, puis les 72 dernières H1, entièrement clôturées avant le sweep.
- La zone doit être **non retestée** (`S2_HTF_UNTOUCHED` : aucune mèche n'y est revenue ; sinon, seulement non invalidée par une clôture).
- Le sweep la touche si l'étendue [niveau pris, mèche extrême] recoupe la zone élargie de 0,25 x ATR H1 (`S2_HTF_TOL_ATR`).
  Le H4 prime sur le H1, le bloc d'ordre sur le FVG, puis la zone la plus récente.

**5. CHoCH M5**
- Extrême du sweep : plus haut (vente) ou plus bas (achat) atteint en M5 depuis la bougie de sweep.
- Pivot : dernier creux (sommet) M5 (fractale de 2) formé juste avant cet extrême, à 36 bougies M5 au plus.
- Une bougie M5 **clôture sous** le pivot (au-dessus pour un achat), avec un corps d'au moins 1,2 x le corps
  moyen, et c'est l'une des 2 dernières clôturées.

**6. Killzone** de la bougie de cassure : Londres 02h-05h, New York 07h-10h ou London Close 10h-12h (`S2_SESSIONS`). Hors de ces heures, pas de signal. Sans effet sur les marchés 24h/24 (cryptos, indices synthétiques).

**Entrée** : ordre **limite** sur la zone du CHoCH (bloc d'ordre M5 en priorité, sinon FVG M5 ; règles de zone plus bas). **Stop** : au-delà de l'extrême du sweep (+ marge, calculée sur l'ATR M15).
**Invalidation** : clôture M5 au-delà de l'extrême du sweep.

**7. Garde-fous** (tous réglables, voir README) :
- **Fibonacci premium / discount** (`S2_FIB_FILTER`) : l'entrée doit être du bon côté de l'équilibre (50 %) de la jambe de référence H4 (ou H1 si le biais vient du H1) : discount pour un achat, premium pour une vente. Jambe < 1,5 ATR H1 : le filtre laisse passer.
- **Ratio minimal** 1:3 sur **TP1** (la première liquidité opposée), le même que S1 (`S2_MIN_RR`) : si la première liquidité opposée est à moins de 3 R, le signal est écarté. Sans aucune liquidité, TP1 est placé au ratio minimal (3 R), donc il le respecte par construction.
- **Risque maximal** 1,5 x ATR H1 (`S2_RISK_CAP_H1`).
- **Distance et fraîcheur** : zone d'ordre limite à plus de 1,5 ATR de confirmation du prix : écartée ; au marché, prix déjà parti de plus de 0,75 ATR depuis la cassure : écarté ; signal dont le déclencheur date de plus de 20 minutes : écarté (`S2_MAX_AGE_MIN`).
- **Volatilité** : ATR H1 actuel d'au moins 0,5 x sa médiane des 240 dernières bougies H1 (`S2_VOL_MIN_RATIO`).
- **Force du sweep** : la mèche dépasse le niveau d'au moins 0,1 ATR M15 (`S2_SWEEP_MIN_ATR`).
- **Obstacles H4/H1** (intraday) : TP1 ne dépasse pas le prochain obstacle opposé (à moins de 1 R : signal écarté, sinon objectifs ramenés 0,1 ATR H1 avant lui puis ratio recontrôlé). Pas de contrôle d'entrée sur un niveau tant que la zone H4/H1 est exigée au sweep.

**Objectifs** (`S2_LIQ_TARGETS`) : **TP1 = première liquidité opposée intacte** située entre 1 R et 6 R (`S2_TP_MIN_R`, `S2_TP_MAX_R`),
50 % clôturés à TP1 avec stop à l'entrée. **TP2 = la liquidité suivante** (plus de 0,5 R au-delà de TP1), sinon TP1 + 1 R ; **TP3 = la suivante
au-delà de TP2**, sinon TP2 + 1 R. Chaque objectif est placé 0,1 x ATR M15 avant le niveau (`S2_TP_BUF_ATR`). Sans aucune liquidité dans la
fourchette : TP1 au ratio minimal exigé (3 R, `S2_MIN_RR` ; `S2_FALLBACK_R` si le ratio est désactivé), TP2 = TP1 + 1 R, TP3 = TP1 + 2 R. Une liquidité opposée déjà prise n'est plus un objectif.

**Réglages et comparaison au backtest** : `python backtest.py --only S2 --split 0.6 --set strategies.S2_BIAS_FILTER=true,false` (idem `S2_HTF_ZONE`,
`S2_HTF_UNTOUCHED`, `S2_FRESH_LEVELS`, `S2_LIQ_TARGETS`). Le rapport enregistre `biais` (H4/H1/contre/aucun), `zone` (ex. `H1 OB`) et `tp` (`liquidité`/`fixe`) de chaque trade.

---

#### Règles de Pullback (ex-S5, Impulsion + Fibonacci) · HTF > MTF > LTF

**Origine** : stratégie du module `impulse.py` du crt-bot, portée telle quelle (mêmes règles et mêmes valeurs), avec les
adaptations listées en bas de section. Elle partage avec S2 les mêmes primitives SMC (module `strategies.py` : sweep de mèche, cassure par clôture, déplacement, miroir).

**Idée** : dans le sens d'une tendance HTF, trader le retracement 50-79 % d'une impulsion MTF, en entrant sur la
confirmation LTF (sweep d'un creux, cassure de structure avec déplacement, FVG, bloc d'ordre dans la zone).

**Cascades** (une alerte par cascade et par sens) : D1 > H4 > H1, H4 > H1 > M15, H1 > M15 > M5. Le garde-fou « un trade par
actif et par sens » écarte les doublons d'un même mouvement : la cascade la plus haute passe en premier.
Les calculs sont écrits pour un achat ; une vente passe par le miroir des prix.

**0. Régime de volatilité** (`s5_vol_ok`) : ATR 14 / ATR 100 du timeframe d'impulsion entre 0,6 et 2 (`S5_VOL_MIN/MAX`). Sans assez d'historique, le filtre ne s'applique pas.

**1. Tendance HTF** (`s5_trend`) : dernier sommet et dernier creux plus hauts que les précédents (fractale de 2 bougies, 2 swings suffisent),
structure intacte (aucune clôture sous le dernier creux), dernier sommet dépassé par une **clôture**. Âge = jambes consécutives : 1 naissante, 2-3 établie,
4 et plus mûre. Seules « naissante » et « établie » donnent un signal (`S5_TREND_AGES_OK`). **ADX** du timeframe de tendance >= 20 (`S1_ADX_MIN`, 0 = désactivé).
**Alignement D1** : pas de trade contre une tendance D1 claire (`S1_D1_ALIGN`) ; sans effet si D1 est la tendance de la cascade ou si le D1 n'a pas de tendance claire.


**2. Impulsion MTF** (`s5_find_impulse`) : cassure de structure avec déplacement (une bougie >= 1,5 x le corps moyen), jambe d'au
moins 2 ATR MTF (`S5_IMPULSE_ATR`). Le Fibonacci va de l'origine (creux) à l'extrême (plus haut, mèche comprise). Setup
annulé si une clôture dépasse 79 %, si l'origine est reprise, ou si l'extrême date de plus de 48 bougies MTF (`S5_IMPULSE_MAX_AGE`).

**3. Entrée LTF** (`s5_find_entry`) : le prix touche la zone 50-79 %, balaie un creux LTF formé pendant le retracement,
puis une bougie clôture au-dessus du dernier sommet (déplacement >= 1,2 x le corps moyen, `S5_DISP`), l'une des 2 dernières
clôturées (`S5_FRESH`), en laissant un **FVG** (bougie centrale >= 1,5 x le corps moyen, taille >= 0,1 ATR). Le **bloc d'ordre**
(dernière bougie baissière avant ce déplacement) doit chevaucher la zone. Si plusieurs combinaisons existent, la plus
rentable en ratio est gardée. Étiquette : « Golden Zone » (50-61,8 %) ou « OTE » (61,8-79 %).

**Entrée** (dans cet ordre) : 1) ordre **limite** au milieu du FVG, sinon à l'extrémité du bloc d'ordre, si le niveau est dans la zone, pas
encore atteint, si le prix n'a pas fait plus de 50 % du chemin vers TP1 (`S5_MAX_PROGRESS`) et si le ratio vers TP1 est >= 1:3 ; 2) au marché si le prix est dans le bloc d'ordre ; 3) au marché « entrée tardive » si le prix vient de quitter le bloc d'ordre (2 bougies
au plus, moins d'une demi-hauteur de bloc, moins de 25 % du chemin vers TP1). Sinon, pas de signal.

**Stop** : sous l'extrême du sweep (+ 0,15 x ATR LTF). **Objectifs** : TP1 = extrême de l'impulsion, TP2 = extension 1,272, TP3 = extension
1,618. **Ratio minimal** 1:3 sur TP1 (`S1_MIN_RR`). **Risque maximal** 2 x ATR H1 (`S1_RISK_CAP_H1`, 0 = aucun). **Session** : le déclencheur doit tomber à Londres,
New York ou London Close (`S5_SESSIONS`) ; sans effet sur les marchés 24h/24 (cryptos, indices synthétiques). **Cadre intraday** : l'entrée doit être sur un niveau ou une zone
H4/H1 du bon côté (0,5 ATR H1, `S1_OBST_ENTRY`) ; TP1 ne dépasse jamais le prochain obstacle opposé (à moins de 1 R : signal écarté, sinon objectifs ramenés 0,1 ATR H1 avant lui, puis ratio
recontrôlé). **Invalidation** : clôture au-delà du bord du bloc d'ordre côté stop.
Gestion habituelle (50 % à TP1, 25 % à TP2, 25 % vers TP3).

**Adaptations au gold-bot** (le reste est identique au crt-bot) :
- Elle suit les règles communes du bot : fenêtres sans alerte (news, rollover, week-end), exposition par devise, ordre limite valable 24 h comme dans le
  crt-bot (`LIMIT_TTL`), et `ENTRY_MODE=market` qui supprime l'étape 1.
- Garde-fous propres au gold-bot : session, plafond de risque, ADX, alignement D1 et cadre intraday (absents du crt-bot).
- **Actifs** : tous.
- Réglages testables : `python backtest.py --only S1 --split 0.6 --set strategies.S5_IMPULSE_ATR=1.5,2,2.5`.

**Vérification du portage** : sur 12 séries simulées (plus de 20 000 évaluations par fonction), `s5_trend`, `s5_find_impulse` et
`s5_find_entry` donnent des résultats identiques à ceux de `impulse.py` (tendance, impulsion, entrée limite FVG, limite bloc d'ordre,
marché, entrée tardive). Le backtest bout en bout (suivi, garde-fous, rapport) fonctionne avec S5. Comme pour les autres stratégies,
aucun avantage statistique n'est démontré : à valider sur de l'historique réel.



---

### Figures & Retournement (code S3) : deux parties

S3 regroupe l'ancienne Chart Patterns (figures) et l'ancienne S7 Reversal (retournement). Le code `S7` est lu comme `S3` ; les trades
enregistrés avec les libellés « Chart Patterns » et « Reversal » restent suivis et comptent comme la même stratégie (un seul trade par actif et par sens).
**Un signal par sens et par scan** : si une figure de retournement et le retournement détecté vont dans le même sens, la figure porte le signal (avec sa confluence) ;
le retournement seul n'est émis que s'il n'y a pas de figure dans ce sens.

#### Partie figures (ex-Chart Patterns) · figures H1/H4 > confirmation M15

Figures chartistes de **retournement** et de **continuation**, dans le cadre intraday du bot : la figure est détectée sur les
bougies **clôturées H1 ou H4** (les obstacles majeurs), la **cassure de sa ligne clé est confirmée en M15** (une des 2 dernières
bougies M15 clôturées finit au-delà de la ligne, la précédente non). Module : `setups.py`.

- **Pivots** : fractales à 4 bougies de chaque côté (`S6_PIVOT_K`), alternées haut/bas, swing minimal 0,8 ATR (`S6_MIN_SWING_ATR`).
- **Figures de retournement** (la tendance qui précède doit être inverse à la cassure) : double sommet / creux, triple sommet / creux,
  tête et épaules (et inversée), biseau montant / descendant, tasse avec anse (et inversée).
- **Figures de continuation** (tendance précédente dans le sens de la cassure) : drapeau et fanion (mât >= 3,5 ATR, figure <= 60 % du
  mât), triangle ascendant / descendant / symétrique, rectangle, canal, élargissement. Pour les triangles, rectangle, canal, biseau et
  élargissement, le type dépend de la tendance qui précède (30 bougies, >= 1,5 ATR) : tendance inverse = retournement, même sens =
  continuation ; sans tendance, la figure est ignorée.
- **Lignes** : les pivots intermédiaires doivent toucher la ligne à 0,5 ATR près (`S6_TOL_ATR`) et les clôtures rester dans la figure.
  Hauteur minimale 1,5 ATR (2 ATR pour les sommets/creux). Dernier pivot de moins de 40 bougies (`S6_MAX_AGE`).
- **Déclencheur** : clôture M15 au-delà de la ligne de cassure (marge 0,1 ATR de la figure), la clôture M15 précédente encore en deçà.
- **Entrée** : ordre limite au **retest de la ligne cassée** (`ENTRY_MODES`), sinon au marché. Zone à plus de 1,5 ATR M15 du prix : signal écarté ; au marché, prix déjà parti de plus de 0,75 ATR depuis la cassure : écarté. Validité de l'ordre : 3 h (`LIMIT_TTL`).
- **Stop** : au-delà de la figure (sommet pour une vente, creux pour un achat) + 0,2 ATR de la figure ; risque minimal 0,5 ATR M15 ; **risque maximal 5 x ATR de la figure** (`S6_RISK_CAP_ATR`).
- **Objectifs** : mesure de la figure à partir de la ligne cassée : TP1 = 0,5 x hauteur, TP2 = 1 x hauteur, TP3 = 1,5 x hauteur (pour
  drapeau et fanion, la hauteur est celle du mât). **Ratio minimal vers TP3** : 1 (`S6_MIN_RR`). Les objectifs étant des fractions de la hauteur, un ratio de 1:3 sur TP1 comme S1, S2 et le retournement serait inatteignable pour une figure.
- **Invalidation** : le niveau du stop. Pas de filtre de session : la confirmation M15 n'est pas limitée aux killzones.
- **Confluence avec l'alerte de retournement** (figures de retournement seulement) : si l'alerte de retournement possible (voir plus bas)
  va dans le même sens, le signal porte « Confluence : retournement possible » et son risque admis est multiplié par 1,4 (`S6_CONF_RISK_FACTOR`) ; sans confluence, une figure de retournement exige un ratio vers TP3 d'au moins 1,5 (`S6_NOCONF_MIN_RR`).
- **Un signal par sens** : si plusieurs figures cassent en même temps, la meilleure (ratio TP3) est gardée.
- **Entonnoir** : `S3_figure` (figures présentes), `S3_cassure` (cassure confirmée en M15), `S3_signal`.

> **Important.** Ces seuils sont des points de départ classiques, **non optimisés ni validés** sur l'or. Lance le backtest
> (`backtest.yml`, option `--only S3`) avant de t'y fier, et compare chaque figure (`extra.figure` dans le rapport).
> Retire la stratégie sans toucher au code avec `STRATEGIES=S1,S2,S4`.

#### Partie retournement (ex-S7 Reversal) · H4 > H1 > M15

L'alerte de retournement possible (voir plus bas) devient un **ordre**. Mêmes conditions (`reversal.detect`) : tendance H4 mûre
(4 jambes ou plus) encore intacte, sweep H1 d'un sommet (creux) récent sur un niveau majeur H4 / veille, cassure de structure H1 contre
la tendance, avec au moins 2 signes d'essoufflement sur 3 (divergence RSI, bougies qui rétrécissent, mèche de rejet ; `REVERSAL_MIN_SIGNS`).

- **Entrée** : ordre limite au **retest du dernier creux (sommet) H1 cassé** ; au marché si le mode est `market` ou si le niveau n'est pas
  atteignable. Retest à plus de 1 ATR H1 du prix : écarté (`S7_ENTRY_MAX_ATR`) ; au marché, prix déjà parti de plus de 0,75 ATR : écarté. Validité de l'ordre : 2 h.
- **Stop** : au-delà de l'extrême du sweep + 0,2 ATR H1 ; **risque maximal 3 x ATR H1** (`S7_RISK_CAP_ATR`). **Ratio minimal 1:3 sur TP1** (première liquidité opposée), le même que S1 et S2 (`S3_REV_MIN_RR`).
- **Objectifs** : sur la liquidité opposée intacte, comme S2 : TP1 = première liquidité entre 1 R et 6 R, TP2 et TP3 = les suivantes (sinon +1 R) ; sans liquidité, TP1 au ratio minimal (3 R) puis +1 R / +2 R. Ramenés avant le prochain obstacle par le cadre intraday.
- **Contre la tendance H4** : le message le rappelle (taille réduite conseillée) et `extra.contre_tendance` est enregistré.
- **Un ordre par sweep** (clé = bougie de l'extrême). Quand S3 est active, l'alerte d'information n'est plus envoyée (même événement) ;
  `STRATEGIES=S1,S2,S4` la rétablit. `REVERSAL_ALERTS=0` supprime seulement le message d'information (S3 n'en dépend pas).
- **Tous les actifs, indices synthétiques compris** (S3). Sur un indice synthétique le prix est généré : les niveaux et figures y ont
  moins de sens, le backtest dira si S3 y tient (`--sym` pour les isoler).
- **Entonnoir** : `S3_retournement` (retournements détectés) ; les signaux comptent dans `S3_signal`.

> Stratégie contre la tendance, non validée : backtest (`--only S3`) avant de t'y fier.

#### Garde-fous communs aux figures et au retournement (S3)

- **Volatilité** : ATR H1 actuel d'au moins 0,5 x sa médiane des 240 dernières bougies H1 (`S3_VOL_MIN_RATIO`).
- **Session** : le déclencheur doit tomber à Londres, New York ou London Close ; sans effet sur les marchés 24h/24.
- **Âge du déclencheur** : au plus 20 minutes (`S3_MAX_AGE_MIN`).
- **Contexte** (figures de continuation seulement) : pas contre une tendance H4 ou D1 claire (`S3_CONTEXT_ALIGN`). Un retournement va par définition contre la tendance précédente : non concerné.
- **Fibonacci** (figures) : une continuation dont le repli reprend plus de 61,8 % de la jambe précédente est écartée (`S3_FIB_FILTER`) ; le TP3 d'une figure de retournement est plafonné à l'origine de la jambe précédente (`S3_FIB_CAP_TP3`).
- **Obstacles H4/H1** (intraday) : TP1 ne dépasse pas le prochain obstacle opposé (à moins de 1 R : signal écarté, sinon objectifs ramenés 0,1 ATR H1 avant lui puis ratio recontrôlé, vers TP3 pour les figures et sur TP1 pour le retournement).

### CRT (code S4) · D1/H4 > M15 : Candle Range Theory pur

Le range d'une bougie de référence (daily ou H4) est balayé, puis livré dans l'autre sens. Le CRT se lit sur deux bougies. Le range H1 a été supprimé. Code : `setups.py` ; réglages `CRT_*` dans `strategies.py`.

| Étape | Règle |
|---|---|
| C1 | Dernière bougie **D1 (range daily) ou H4** clôturée avant C2. **Taille raisonnable** : entre 0,8 et 3,5 x ATR du timeframe de référence (`CRT_MIN_RANGE_ATR`, `CRT_MAX_RANGE_ATR`), assez grande pour qu'un stop serré donne au moins 1:3 jusqu'au milieu du range, sans être démesurée. |
| C2 | Bougie clôturée qui dépasse **un seul** côté de C1 d'au moins 0,1 x ATR du timeframe de référence (`S4_SWEEP_MIN_ATR`) et **clôture dans le range de C1**. Dépasser les deux côtés (englobante) ou clôturer hors du range n'est pas un CRT. |
| C3 | Bougie en formation : la livraison se fait pendant C3. La confirmation M15 doit arriver avant sa clôture. |
| Entrée | Première clôture M15 au-delà du dernier swing M15 (CHoCH avec déplacement), **après la clôture de C2** et à moins de `CRT_PIVOT_BARS` bougies de l'extrême de C2. Si le prix reprend l'extrême de C2 pendant C3, le sweep est annulé. Ordre limite sur le bloc d'ordre ou le FVG M15 s'il y en a un, sinon au marché. Zone à plus de 1,5 ATR M15 du prix : écartée ; au marché, prix déjà parti de plus de 0,75 ATR : écarté. Sessions : Londres, New York, London Close (`CRT_SESSIONS`, sauf actifs 24/7). |
| Stop | Au-delà de l'extrême de C2, plus 0,15 x ATR M15 (`CRT_SL_BUF_ATR`). |
| Objectifs | TP1 milieu de C1, TP2 bord opposé de C1, TP3 bord opposé + 50 % du range (`CRT_TP3_EXT`). **Ratio minimal 1:3 jusqu'au milieu de C1 (TP1)**, comme S1, S2 et le retournement : peut être supérieur, jamais inférieur (`S4_MIN_RR`). Le risque est ainsi borné à un sixième du range de C1. |
| Garde-fous | Volatilité (ATR H1 d'au moins 0,5 x sa médiane, `S4_VOL_MIN_RATIO`) ; déclencheur de 20 minutes au plus (`S4_MAX_AGE_MIN`) ; **contexte** : pas contre une tendance H4 ou D1 claire (`S4_CONTEXT_ALIGN`) ; **obstacles H4/H1** (intraday) : TP1 ne dépasse pas le prochain obstacle opposé (à moins de 1 R : signal écarté, sinon objectifs ramenés avant lui puis ratio recontrôlé). Pas de plafond de risque séparé : le ratio au milieu de C1 et la taille du range le bornent. |

Différences avec S2 : S2 balaie des niveaux de liquidité (veille, Asie, equal highs/lows) avec un biais de structure et une zone H4/H1, et vise la liquidité
opposée. S4 ne regarde que le range de C1 et vise ses repères (milieu, bord opposé). Les deux peuvent signaler le même retournement : la règle « un trade par actif et par sens » les départage.

Absent par rapport au CRT de tes autres bots : l'entrée « OTE de C2 » (mode strict) et le Breaker (la zone d'entrée est le bloc d'ordre, puis le FVG).

### Confirmation en M15 ou en M5 (un réglage par stratégie)

Chaque stratégie a son timeframe de confirmation / d'entrée, réglable séparément. Le cadre H4 / H1 ne change pas : seuls la cassure de structure,
le bloc d'ordre, le FVG, le stop et la fraîcheur du signal passent sur les bougies M5.

| Stratégie | Variable | Ce qui passe en M5 | Défaut (vide) |
|---|---|---|---|
| S1 Pullback | `S1_CONFIRM_TF` | Entrée de chaque cascade (sweep, cassure, FVG, bloc d'ordre) : `H4 > H1 > M5` en intraday. Seule la valeur `M5` a un effet. | Cascade selon `INTRADAY` (`H4 > H1 > M15`) |
| S2 Sweep + CHoCH | `S2_CONFIRM_TF` | CHoCH, bloc d'ordre et FVG (le sweep reste détecté en M15) ; pivot cherché sur 36 bougies M5 au lieu de 12 | M15 en intraday, sinon M5 |
| S3 Figures & Retournement | `S3_CONFIRM_TF` | Confirmation de la cassure de la figure (les figures restent H1 / H4) ; entrée du retournement | M15 |
| S4 CRT | `S4_CONFIRM_TF` | Cassure de structure après C2, zone d'entrée ; pivot cherché sur 48 bougies M5 au lieu de 16 | M15 |

Valeurs : `M15` ou `M5` ; toute autre valeur est ignorée (comportement par défaut). Les durées écrites en bougies M15 sont converties (x 3 en M5).

**Ce que M5 change.** Entrée plus précoce, stop plus serré (ratio plus facile à atteindre, notamment pour le 1 pour 3 de S4), mais cassures plus bruyantes
et spread plus lourd par rapport au stop. Les objectifs de S4 (milieu, bord de C1) et ceux de S1 (impulsion) ne dépendent pas du timeframe d'entrée.

**À tester avant de s'y fier** : un passage en M5 doit se comparer au backtest, avec un spread réaliste, stratégie par stratégie :
`python backtest.py --only S2 --split 0.6 --set strategies.S2_CONFIRM_TF=M15,M5` (idem `S1_CONFIRM_TF` avec `,M5`, `S3_CONFIRM_TF`, `S4_CONFIRM_TF`).
On ne garde M5 que là où le rendement **total** monte, pas seulement le R par trade.

### Classes d'actifs (regroupement, sans filtre de stratégie)

Chaque actif a une classe : **Or**, **Forex de session**, **Forex JPY**, **Forex calme**, **Cryptos**, **Indices synthétiques**. Elle sert à
regrouper les actifs (récapitulatifs, `--sym forex_jpy` du backtest) et alimente la ligne `classe` du rapport. **Elle ne filtre aucune
stratégie** : le filtre par classe (variables `CLASS_FILTER`, `CLASS_STRATEGIES`, `TIER_MAX`, niveaux principale / secondaire / à tester,
marquage « 🧪 À tester ») est supprimé, et ces variables sont ignorées si elles existent encore dans GitHub. Le classement qu'il appliquait
n'avait jamais été validé par backtest.

Pour restreindre un actif précis, `SYMBOL_STRATEGIES` (ex. `frxEURUSD:S1,S2;cryBTCUSD:S2,S3`) ; un actif absent reçoit toutes les stratégies
actives (variable `STRATEGIES`). Indices synthétiques : prix généré par un algorithme, aucune liquidité réelle, aucune stratégie n'y a de base
logique : à traiter comme une expérience.

**Valider** : `python backtest.py --sym forex_jpy --split 0.6` (classes : `or`, `forex`, `forex_session`, `forex_jpy`, `forex_calme`, `crypto`,
`synth`). Le rapport détaille la ligne `classe`. Garde une stratégie sur un actif seulement si elle est positive sur les deux périodes avec au
moins 30 trades, puis fixe le résultat avec `SYMBOL_STRATEGIES`.

---

### RR visé et R obtenu (rapport)

Le rapport du backtest (section « RR visé et R obtenu par stratégie ») et le bilan `/bilan` donnent, pour chaque stratégie :
- le **RR visé** : ratio gain/risque pondéré par la gestion de la position (50 % à TP1, 25 % à TP2, 25 % à TP3 ; sans TP3, 50 % et 50 %), avec le ratio
  moyen de chaque objectif ;
- le **R obtenu** moyen, après spread dans le backtest ;
- le **taux d'atteinte** de TP1, TP2 et TP3 ;
- la **capture** : part du RR visé réellement obtenue. Une capture faible, avec un RR visé élevé que le prix atteint rarement, montre des objectifs
  trop ambitieux ; une capture proche de 100 % avec un taux de TP1 élevé montre au contraire que le bot pourrait viser plus loin.

Même avec ces chiffres, le RR visé n'est pas un rendement : seul le R obtenu, sur assez de trades et sur deux périodes, compte.

---

### Confluence (étiquette, hors stratégies)

Quand deux stratégies ou plus signalent **le même actif dans le même sens** à moins de `CONFLUENCE_MIN` minutes d'écart
(60 par défaut ; `0` pour désactiver), l'alerte le dit : une ligne « ⚡ Confluence : S3 Figures & Retournement (il y a 10 min) »
(format complet), « confluence S3 » dans le résumé (formats compact et contexte), « ⚡S3 » dans l'en-tête (format minimal).

- **Information seulement** : rien n'est filtré, chaque stratégie alerte comme avant, avec ses propres niveaux.
- **Qui compte** : les trades des autres stratégies encore en attente ou ouverts, alertés dans la fenêtre, et les signaux trouvés au même
  scan. Un trade clôturé, annulé ou expiré ne compte pas. Une même stratégie ne se compte pas elle-même (S1 et son ancien code S5 = une seule ; S3 et son ancien code S7 = une seule).
- **Une seule étiquette, sur la seconde alerte** : si S2 alerte à 10h00 puis S3 à 10h20, c'est l'alerte de S3 qui porte la confluence ;
  celle de S2, déjà envoyée, n'est pas modifiée. Au même scan, les deux alertes la portent. Avec `ONE_TRADE_PER_SIDE` (défaut), la seconde
  alerte est bloquée : l'étiquette ne sort donc que pour des signaux trouvés au même scan (voir « Cohérence entre stratégies »).
- **Mesure au backtest** : chaque trade enregistre `confluence` (ex. `S2+S3`, ou `aucune`) et le rapport ajoute une ligne par valeur.
  Pour comparer les fenêtres : `python backtest.py --sym all --split 0.6 --set gold.CONFLUENCE_MIN=0,30,60,120`.
  Compare le rendement par trade de `aucune` et des confluences, **sur les deux périodes** (`--split 0.6`) : il faut au moins
  30 trades par ligne, et une confluence qui ne tient que sur une période est du sur-ajustement.
- **Étape suivante possible** (non faite) : en faire un filtre (n'alerter que s'il y a confluence), seulement si le backtest le justifie.

---

### Récapitulatif de tendance (information, hors stratégies)

Message quotidien (lundi au vendredi, 01h00 New York par défaut, réglable) : tendance D1 / H4 / H1 de chaque actif, avec son âge (naissante 1 jambe,
établie 2-3, mûre 4 et plus). Règles de `setups.py` (fractales de 2 bougies, 1 en D1) : dernier sommet et dernier creux plus hauts (plus bas pour une
baisse), structure intacte, sommet précédent cassé par une clôture. Il est indépendant des filtres de tendance de
Trend Pullback (EMA 50/200 du H4) : les deux lectures peuvent différer.

### Ce que le bot ne fait pas

- Il ne passe aucun ordre : il envoie des alertes et suit leur résultat théorique en R.
- Il ne prédit rien : chaque signal est un scénario, pas une certitude.
- Le suivi suppose un remplissage au prix du signal, sans glissement. Le backtest applique un spread constant.

### Cadre intraday (par défaut)

Toutes les stratégies sont des stratégies de la journée : obstacles majeurs en H4 / H1, confirmation en M15 (Pullback structure : cascade H4>H1>M15 uniquement ; S2 : CHoCH, bloc d'ordre et FVG en M15), puis clôture de fin de séance (16h45 New York, ou 10 h après l'ouverture) pour le forex et l'or, y compris le reste d'un trade dont TP1 est atteint (`INTRADAY_RUNNERS=1` le laisse courir). Les cryptos et les indices synthétiques, ouverts 24h/24, n'ont pas de fin de séance : ils courent jusqu'au TP final (`CRYPTO_INTRADAY=1` coupe aussi les cryptos).
Plus aucun contrôle d'obstacle : ni zone d'entrée exigée, ni plafonnement de TP1.
`INTRADAY=0` restaure l'ancien comportement (cascades M5, confirmation S2 en M5, pas de clôture de fin de séance). Les seuils sont des choix de départ, non validés par un backtest.


### Cohérence entre stratégies (v30)

- **Un seul trade par actif et par sens, toutes stratégies confondues** (`ONE_TRADE_PER_SIDE`, actif par défaut ; `0` pour revenir à un trade par
  stratégie) : deux stratégies d'accord sur le même mouvement ne doublent plus l'exposition. Au même scan, la première stratégie dans l'ordre
  S1 à S4 passe, et l'étiquette de confluence signale l'accord des autres. **Limite** : une stratégie qui signale plus tard, alors que le trade
  est déjà ouvert, est bloquée (« doublons » dans l'entonnoir) et l'accord n'est pas ajouté après coup à l'alerte déjà envoyée.
- **S1 et son ancien code S5, S3 et son ancien code S7** : une seule stratégie chacune.
- **Pas de sens opposé** sur un même actif (toutes stratégies, ordres en attente compris).
- **Tendance** : la structure (S2, S5, alertes) vient d'une seule définition, `setups.py`. S2 n'a plus de filtre de biais (le biais H4/H1 est seulement affiché).
- **Setups bloqués par les news / horaires** : refus transitoire, réexaminé au scan suivant ; la clé de la variante structure inclut le déclencheur.
- **Backtest** : trades suivis sur l'unité de temps du signal, comme en direct ; échauffement par défaut de 35 jours.


### Alerte de retournement possible (information ; devient l'ordre de retournement de S3 quand S3 est active)

Les stratégies jouent la continuation de la tendance de fond ; `setups.py` signale en plus, **à titre d'information**, un retournement
possible. Aucun ordre, aucun suivi, aucun filtre sur les stratégies. Une alerte n'est envoyée que si tout se cumule :

1. **Tendance H4 mûre** (4 jambes ou plus) **encore intacte** : on prévient avant que le H4 ne casse (après, il est trop tard).
2. **Sweep H1** : une bougie prend un sommet (creux) récent puis referme de l'autre côté, moins de 6 bougies H1 plus tôt. Un niveau déjà pris par une mèche ou une clôture ne compte pas.
3. **Niveau majeur** : le sommet (creux) pris est sur un sommet / creux H4, une zone H4 ou le plus haut / bas de la veille (`REQUIRE_LEVEL`).
4. **Cassure de structure H1 contre la tendance** : clôture sous le dernier creux (au-dessus du dernier sommet) formé avant le sweep, datant de 2 bougies H1 au plus.
5. **Essoufflement** : au moins `REVERSAL_MIN_SIGNS` signes sur 3 (défaut 2) : divergence RSI H1 (nouvel extrême du prix, RSI plus bas), bougies qui rétrécissent (corps des 3 dernières < 60 % de celui des 10 précédentes), mèche de rejet (>= 2 fois le corps).

Un message par sweep, avec l'invalidation (l'extrême du sweep). Active sur tous les actifs, indices synthétiques compris. Réglages : `REVERSAL_ALERTS=0`
la désactive, `REVERSAL_MIN_SIGNS` (1 à 3), et les constantes de `setups.py` (`AGES`, `SWEEP_BARS`, `FRESH_BARS`, `FADE_RATIO`...).
Attendre la cassure du H4 pour confirmer : un retournement signalé peut n'être qu'un repli.
