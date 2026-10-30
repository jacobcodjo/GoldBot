# Bot or (XAUUSD) + paires forex majeures + BTC/ETH

Bot d'alertes Telegram pour l'or, les paires forex majeures (7 contre USD et 8 croisements majeurs de Deriv), le BTC, l'ETH et les 10 indices Volatility de Deriv, avec cinq stratégies (détail précis dans
[STRATEGIES.md](STRATEGIES.md)). Il reprend l'architecture du bot CRT/Impulsion (client Deriv robuste, suivi
des trades, garde-fous, graphique et boutons Telegram, backtest) mais **aucune de ses stratégies d'origine**, sauf la S5, portée depuis son module Impulsion.

| Code (réglages) | Stratégie | Unités de temps |
|---|---|---|
| S1 | Trend Pullback | H4 > H1 > M15 |
| S2 | Asian Breakout | M15 |
| S3 | Sweep + CHoCH (SMC) | H4/H1 > M15 > M5 |
| S4 | Mean Reversion | H1 > M15 |
| S5 | Impulsion + Fibonacci (portée du crt-bot) | D1 > H4 > H1, H4 > H1 > M15 ou H1 > M15 > M5 |

Le bot **n'exécute aucun ordre** : il envoie des alertes (entrée, stop, TP1 à TP3 avec ratio,
graphique) et suit leur résultat en R. Aucune stratégie n'est garantie ; les paramètres sont des points de
départ à valider par backtest.

## Actifs suivis

| Actif | Symbole Deriv |
|---|---|
| Or | `frxXAUUSD` |
| Majeures contre USD | `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxUSDCHF`, `frxAUDUSD`, `frxUSDCAD`, `frxNZDUSD` |
| Croisements majeurs Deriv | `frxAUDJPY`, `frxEURAUD`, `frxEURCAD`, `frxEURCHF`, `frxEURGBP`, `frxEURJPY`, `frxGBPAUD`, `frxGBPJPY` |
| Cryptos | `cryBTCUSD`, `cryETHUSD` |
| Indices Volatility | `R_10`, `R_25`, `R_50`, `R_75`, `R_100` (V10 à V100) et `1HZ10V`, `1HZ25V`, `1HZ50V`, `1HZ75V`, `1HZ100V` (variantes 1s) |

Par défaut, **toutes les stratégies actives tournent sur chaque actif**. Avec `CLASS_FILTER=1`, chaque actif est restreint aux stratégies de sa **classe** (voir « Classes d'actifs et niveaux » plus bas).
Les règles de chaque stratégie sont les mêmes pour tous les actifs (toutes les distances sont exprimées en ATR,
donc elles s'adaptent à la volatilité de chaque paire). Elles ont été pensées pour l'or : **rien ne dit qu'elles
fonctionnent aussi bien sur les majeures**. Compare actif par actif au backtest et retire ceux qui ne tiennent pas
(variable `SYMBOLS`). La liste forex reprend les 14 paires que Deriv classe en « Forex majeures » (NZDUSD, rangée en
mineures par Deriv, reste suivie). Le suivi de l'exposition est **par devise** : un trade compte comme long ou short
sur chacune de ses deux devises (EURJPY acheté = long EUR, short JPY ; l'or acheté = short USD), et 2 trades au plus
dans le même sens sur une même devise sont ouverts à la fois. BTC et ETH forment un groupe corrélé : 2 trades au plus
dans le même sens.

## Classes d'actifs et niveaux de stratégie

**Ce tableau ne s'applique que si `CLASS_FILTER=1`** (variable GitHub ; par défaut, toutes les stratégies tournent sur tous les actifs et les alertes n'affichent ni niveau ni 🧪). Chaque actif est rangé dans une classe. Pour chaque classe : une stratégie **principale** (niveau 1), des **secondaires** (niveau 2) et des
stratégies **à tester** (niveau 3). Ce sont des hypothèses de départ tirées de la logique de chaque stratégie, **pas des résultats de backtest**.

| Classe | Actifs | Principale | Secondaires | À tester |
|---|---|---|---|---|
| Or | `frxXAUUSD` | S3 | S1, S5 | |
| Forex de session | EURUSD, GBPUSD, USDCAD, EURGBP, EURAUD, EURCAD, GBPAUD | S3 | S2 | S1, S5 |
| Forex JPY | USDJPY, EURJPY, GBPJPY, AUDJPY | S1 | S5 | |
| Forex calme | USDCHF, EURCHF, AUDUSD, NZDUSD | S4 | S3 | |
| Cryptos | BTC, ETH | S1 | S3, S5 | |
| Indices synthétiques | les 10 Volatility | S3 | S5 | |

Avec `CLASS_FILTER=1`, une stratégie absente de la ligne d'une classe n'y tourne pas (par exemple S2 et S4 sur l'or). L'alerte indique alors la classe et le niveau
(« 🏷️ Or · stratégie principale ») ; une stratégie à tester est marquée « 🧪 À tester ». Le backtest ajoute les lignes `classe` et `tier` à son rapport (le niveau vaut « toutes » quand `CLASS_FILTER` est vide).

Réglages (onglet Variables) :
- `CLASS_FILTER` : `1` pour restreindre chaque actif aux stratégies de sa classe (défaut : vide = toutes les stratégies sur chaque actif).
  Le backtest accepte `--class-filter` et lit aussi les variables `CLASS_FILTER`, `CLASS_STRATEGIES`, `SYMBOL_STRATEGIES` et `TIER_MAX`.
- `TIER_MAX` (avec `CLASS_FILTER=1`) : niveau maximal actif, `1` (principales seules), `2` (+ secondaires) ou `3` (+ à tester, défaut).
- `CLASS_STRATEGIES` (avec `CLASS_FILTER=1`) : change une classe, au format `classe:principales/secondaires/à tester`, ex. `or:S3/S1,S5/S2;forex_jpy:S1/S5/`
  (classes : `or`, `forex_session`, `forex_jpy`, `forex_calme`, `crypto`, `synthetique`).
- `SYMBOL_STRATEGIES` reste **prioritaire** sur tout, actif par actif (alertes alors étiquetées « manuelle »). Attention : un actif absent de cette
  variable reçoit toutes les stratégies actives (ou celles de sa classe avec `CLASS_FILTER=1`).
- Backtest par classe : `python backtest.py --sym forex_jpy --split 0.6 --class-filter`, avec `--tier-max 1` pour la principale seule, ou
  `--set gold.TIER_MAX=1,2,3` pour comparer les niveaux. Classes acceptées par `--sym` : `or`, `forex`, `forex_session`, `forex_jpy`, `forex_calme`, `crypto`, `synth`.

**Indices Volatility** : prix produit par un générateur aléatoire, marché 24h/24 et 7j/7, insensible aux news. Par défaut ils reçoivent toutes les
stratégies actives (avec `CLASS_FILTER=1` : S3 principale et S5 secondaire, sa version d'origine étant faite pour ces indices ; `TIER_MAX=1` la coupe), sans killzone, sans filtre de week-end ni de news, sans
récapitulatif de tendance du matin ni limite d'exposition. **Rien ne garantit qu'une stratégie ait un avantage sur un prix aléatoire** : valide d'abord
au backtest sur des mois de données réelles Deriv (`python backtest.py --sym synth --days 120 --split 0.6`) avant de te fier aux
alertes. Spread par défaut 0,02 % (estimation, `SPREAD_TABLE` ou `SPREAD_PCT`) et décimales d'affichage à vérifier sur Deriv.

**Récapitulatif du soir des indices** : chaque jour, week-end compris, **4 heures avant la clôture de la bougie daily de Deriv** (00h GMT, soit 20h
GMT = 21h au Bénin), le bot envoie un message **séparé par classe** : « Volatility Indices »
(V10 à V100) puis « Volatility (1s) Indices ». Pour chaque indice : tendance D1/H4/H1 avec âge et invalidation, biais utilisé par S3
(les signaux S3 n'iront que dans ce sens) et plus haut / plus bas de la bougie daily en cours. Un seul envoi par bougie ; si le cron
est trop en retard et que la bougie est déjà close, la journée est sautée. Variable `SYNTH_RECAP_HEURES` (défaut 4) pour changer le délai.
Pour ces indices, **D1 (tendance, PDH/PDL de S3) est la bougie daily de Deriv, ouverte à 00h GMT** ; leur H4 reste ancré à 17h New York
comme celui des autres actifs. Le backtest applique la même règle (`--sym synth`).

**Croisements (sans USD)** : spreads par défaut (estimations, `SPREAD_TABLE` ou `SPREAD_PCT` pour imposer) : 0,007 à 0,014 % selon la paire, plus larges que les
majeures USD (0,006 %). Les paires en yen s'affichent avec 3 décimales.

**Cryptos (marché 24h/24, 7j/7)** : pas de rollover ni de fermeture hebdomadaire, donc aucune fenêtre sans alerte
liée au week-end (seules les annonces USD à fort impact bloquent les alertes) ; les stratégies Sweep + CHoCH et
Mean Reversion ne sont pas limitées aux heures de session. Spread par défaut du backtest : 0,05 %.

## Fichiers

| Fichier | Rôle |
|---|---|
| `gold.py` | Scan, client Deriv (limites de requêtes, reconnexion), alertes et commandes Telegram, suivi |
| `strategies.py` | Les 5 stratégies, indicateurs (EMA, ATR, ADX, RSI, Bollinger, swings), sessions |
| `trend.py` | Tendance et âge de la tendance (D1, H4, H1) pour le récapitulatif journalier |
| `tracker.py` | Suivi des trades : TP1/TP2/TP3, stop à l'entrée, sorties de structure et au temps, statistiques |
| `guard.py` | Fenêtres sans alerte (news USD, rollover, week-end), limite d'exposition, santé du bot, bilan |
| `charts.py` | Graphique joint à l'alerte |
| `tests.py` | 137 tests automatisés (`python -m unittest tests -v`, aussi lancés par `.github/workflows/tests.yml`) |
| `backtest.py` | Rejeu M5 des 5 stratégies, par stratégie, avec deux périodes et grille de réglages |
| `STRATEGIES.md` | Règles précises de chaque stratégie |
| `.github/workflows/gold.yml` | Scan (déclenché par un cron externe) + sauvegarde de l'état sur la branche `data` |
| `.github/workflows/tests.yml` | Lance les tests à chaque modification du dépôt |
| `.github/workflows/backtest.yml` | Backtest manuel |

## Installation

1. Crée un dépôt GitHub avec le contenu de ce dossier (le dossier `.github/workflows` inclus).
2. **Settings > Secrets and variables > Actions** : secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID`.
3. Variables facultatives (onglet Variables) :
   - `SYNTH_RECAP_HEURES` (défaut 4) : délai avant la clôture de la bougie daily pour le récapitulatif des indices synthétiques.
   - `STRATEGIES` : liste à activer, ex. `S2,S3` (défaut : `S1,S2,S3,S4,S5`).
   - `SYMBOL_STRATEGIES` : stratégies par actif, ex. `frxEURUSD:S1,S2;cryBTCUSD:S2,S4` (prioritaire sur tout ; un actif
     absent reçoit toutes les stratégies actives, ou celles de sa classe avec `CLASS_FILTER=1`). Sert par exemple à couper Sweep + CHoCH sur les cryptos.
   - `HEARTBEAT_URL` (secret, pas variable) : URL de ping de surveillance (par exemple une vérification healthchecks.io). Le bot l'appelle à la fin de chaque passage réussi ; si les pings cessent, le service t'alerte, ce qui signale que le cron externe est tombé.
   - `DERIV_APP_ID`, `DERIV_WS_URL`, `CALENDAR_URL` : réglages techniques facultatifs (identifiant d'application Deriv, point d'accès forcé, source du calendrier économique).
   - `INTRADAY` : `0` pour désactiver le cadre intraday (défaut : actif, voir « Cadre intraday »). `INTRADAY_RUNNERS` : `0` pour clôturer aussi, en fin de séance, les restes de trades dont TP1 est atteint.
   - `CLASS_FILTER` : `1` pour restreindre chaque actif aux stratégies de sa classe (défaut : vide, toutes les stratégies sur chaque actif).
   - `TIER_MAX` et `CLASS_STRATEGIES` : niveaux et stratégies par classe d'actifs, utiles seulement avec `CLASS_FILTER=1` (voir « Classes d'actifs et niveaux »).
   - `CONFLUENCE_MIN` : fenêtre de confluence en minutes (défaut 60, `0` pour désactiver) : voir STRATEGIES.md.
   - `ENTRY_MODE` : `auto` (défaut : ordres limites pour les 5 stratégies), `market` ou `limit` pour tout forcer ;
     `ENTRY_MODES` : par stratégie, ex. `S3:market,S4:market`.
   - `SPREAD_PCT` : spread supposé en % du prix, pour tous les actifs (défaut : or 0,015, majeures 0,006, BTC/ETH 0,05).
   - `SPREAD_TABLE` : spreads par actif, en % du prix, ex. `frxXAUUSD=0.02,frxEURUSD=0.008,cryBTCUSD=0.04` (prioritaire sur `SPREAD_PCT` ;
     sert à saisir les spreads de ton courtier, par exemple Exness Standard, actif par actif).
   - `MAX_AGE_MIN` : âge maximal d'un signal en minutes (défaut 20) ; `WEEKEND_EXIT=0` désactive la clôture du vendredi.
   - `ALERT_FUSEAU` : fuseau d'affichage de l'heure (défaut `Africa/Porto-Novo`, soit l'heure du Bénin ; `none` pour désactiver).
   - `ALERT_FORMAT` : `essentiel` (défaut), `complet`, `compact`, `contexte` ou `minimal` (voir plus bas).
   - `SYMBOLS` : actifs suivis, ex. `frxXAUUSD,frxEURUSD` (défaut : l'or, les 7 majeures USD, les 8 croisements majeurs, BTC, ETH et les 10 indices Volatility).
4. Le workflow n'a pas de `schedule` : déclenche-le toutes les 5 minutes avec ton cron externe
   (`workflow_dispatch`), comme pour l'ancien bot. Un scan télécharge M5 et M15 pour chaque actif (28 actifs : une
   cinquantaine de secondes avec la temporisation anti-limite de requêtes).
5. Lance une fois le workflow avec `test = true` : tu reçois un message de contrôle avec l'entonnoir.

**Sauvegarde de l'état.** Les trades suivis, les garde-fous et les alertes déjà envoyées (`trades.json`, `guard.json`,
`state.json`) sont sauvegardés à chaque scan sur une branche `data` du dépôt (une seule révision, écrasée à chaque fois),
puisque le cache GitHub peut être supprimé sans prévenir. Les bougies (`cache.json`) restent dans le cache GitHub : leur
perte ne fait que ralentir un scan. Il faut **Settings > Actions > General > Workflow permissions : Read and write**.
Si ton dépôt est public, la branche `data` (historique de tes trades simulés, aucun secret) est lisible par tous.
Pour les jours d'annonces non couverts par le calendrier automatique, copie `news.example.json` en `news.json`.

## Récapitulatif de tendance journalier

Chaque matin du lundi au vendredi, à **01h00 New York** (une heure avant l'ouverture de Londres, qui ouvre à 02h00 New
York ; environ 07h00 à Paris), à la première passe après cette heure, le bot envoie **un message par classe d'actif** (Or,
Forex · paires contre USD, Forex · croisements majeurs, Cryptos ; la légende figure seulement dans le premier) avec, pour chaque actif, la tendance en **D1, H4 et H1**, son **âge** et une phrase de synthèse sur l'alignement :

```
XAUUSD
  D1  🟢 Haussière · établie (2 jambes, 9 j) ⚡ · invalidation 2641.20
  H4  🟢 Haussière · mûre (4 jambes, 6 j) · invalidation 2655.80
  H1  🔴 Baissière · naissante (1 jambe, 14 h) · invalidation 2668.90
  → D1 et H4 alignés (haussiers), H1 à contre-sens (baissiers)
```

Âge = nombre de jambes consécutives (sommet **et** creux plus hauts pour une hausse, plus bas pour une baisse) :
naissante 1 · établie 2-3 · mûre 4 et plus. Deux swings suffisent pour reconnaître une tendance (pas trois, qui arrive
trop tard), avec des fractales de 2 bougies (1 seule en D1, pour confirmer un swing après 1 jour au lieu de 2 ;
réglage `SWING_N_BY_TF` de `trend.py`, à comparer avec les colonnes `tend_d1` du backtest). La structure doit être intacte (aucune clôture au-delà du dernier creux/sommet), le sommet précédent doit
être cassé par une **clôture**, et ⚡ signale une cassure impulsive. L'invalidation est le dernier creux (hausse) ou
sommet (baisse). Les actifs dont le marché est fermé (forex le week-end) sont listés dans le message de leur classe, ou dans un dernier message si toute la classe est fermée.
L'heure se règle avec les variables `RECAP_HEURE` (ex. `07:00`) et `RECAP_FUSEAU` (ex. `Europe/Paris` ; défaut :
`America/New_York`). Si le workflow n'a pas pu tourner dans les 6 heures suivant l'heure prévue, la journée est sautée.
La commande `/tendance` renvoie le récapitulatif à la demande (au prochain scan, sous 5 minutes). Réglages dans
`trend.py` (`AGE_ESTABLISHED`, `AGE_MATURE`, `BOS_BY_CLOSE`). Le récapitulatif informe : aucune alerte de trade n'en dépend.

## Tendance et âge dans chaque alerte

Chaque alerte ajoute deux lignes d'information : la tendance **D1** et **H4** de l'actif avec son âge (même lecture que
le récapitulatif), marquées ✅ si elle va dans le sens du trade et ⚠️ si elle est à contre-sens :

```
✅ Tendance D1 haussière · établie (2 jambes, 9 j)
⚠️ Tendance H4 baissière · mûre (4 jambes, 6 j) : contre le trade
```

Ce n'est **pas un filtre** : l'alerte part quelle que soit la tendance (seule exception : Sweep + CHoCH, qui ne trade que dans le sens du biais de structure H4/H1, voir `STRATEGIES.md`). Le backtest enregistre ces deux informations
(colonnes `tend_d1` et `tend_h4` du rapport, ex. « mûre avec », « naissante contre ») pour que tu compares la
performance selon l'âge de la tendance avant d'en faire éventuellement un filtre.

## Ordres limites

Par défaut, chaque alerte est un **ordre limite** posé au retest d'une zone, au lieu d'une entrée au marché. Pour les
blocs d'ordre, l'entrée est à leur **extrémité proche** ; pour les **FVG**, à leur **milieu** (bloc d'ordre d'abord, FVG
si aucun bloc d'ordre) :

| Stratégie | Zone d'entrée | Validité |
|---|---|---|
| Trend Pullback | bord proche du bloc d'ordre M15 (sinon milieu du FVG M15) | 2 h |
| Asian Breakout | bord de plage cassé (retest) | 3 h |
| Sweep + CHoCH | bord proche du bloc d'ordre M5 (sinon milieu du FVG M5) | 1 h |
| Mean Reversion | bande de Bollinger rejetée | 1 h 30 |

Exemple (`compact`) :

```
🟢 BUY · XAUUSD · M15 · Trend Pullback · New York

Entrée  BUY LIMIT 2650.10 (prix 2652.40)
SL  2646.10
TP1 2654.10 (1:1) · TP2 2658.10 (1:2) · TP3 2662.10 (1:3)
```

Le bot t'envoie ensuite : « Ordre limite touché » quand le prix atteint la zone, ou « Ordre annulé » (TP1 atteint sans
fill, stop franchi, week-end) ou « Ordre expiré », pour que tu annules l'ordre chez ton courtier. `/bilan` affiche le taux de
remplissage. Si la zone est du mauvais côté du prix ou sous le stop, ou si aucun bloc d'ordre n'existe, l'alerte reste au
marché. Une zone à plus de 1,5 x ATR du prix écarte le signal.

**Contrepartie** : on obtient un meilleur prix et un stop plus court, mais certains trades ne sont jamais remplis (souvent
ceux qui partent sans retour, donc les meilleurs). Compare avec le backtest :
`--sym all --split 0.6 --set gold.ENTRY_MODE=market,limit` (le rapport affiche le taux de remplissage et la
performance par type de zone : colonne `poi`). Pour comparer l'extrémité et le milieu des blocs d'ordre :
`--set strategies.LIMIT_OB_FRACTION=0,0.5`. Choisis par
stratégie avec `ENTRY_MODES` (ex. `S3:market`) ou repasse tout au marché avec `ENTRY_MODE=market`.

## Réalisme des résultats et fiabilité

- **Spread** : le suivi en direct et le backtest retirent le spread de chaque trade (« spread inclus » dans le message
  de résultat). Estimations par défaut ; remplace-les par ceux de ton courtier (`SPREAD_TABLE`, actif par actif, ou `SPREAD_PCT`).
- **Gaps** : si une bougie ouvre au-delà du stop, le trade est clôturé à l'ouverture (perte supérieure à 1 R possible).
- **Week-end** : les trades or et forex encore ouverts le vendredi à 16h30 New York sont clôturés (message « Fermeture
  avant le week-end ») et les ordres limites en attente annulés, et aucune alerte ne part le week-end pour ces actifs. Les cryptos ne sont pas concernées.
- **Retard** : chaque alerte indique son âge (« signal il y a 3 min »). Un signal de plus de 20 minutes (`MAX_AGE_MIN`),
  ou dont le prix a déjà trop fui, est écarté.
- **Volatilité** : les signaux sont écartés quand l'ATR H1 tombe sous la moitié de sa médiane récente (marché mort où le
  spread domine ; `VOL_MIN_RATIO` dans `strategies.py`).
- **Calendrier économique** : si le flux reste indisponible plus de 6 h, tu reçois un message (les annonces ne bloquent
  alors plus les alertes) ; un autre message prévient du retour.
- **Bilan** (`/bilan`) : par stratégie, par actif, et réel vs simulé par stratégie pour les trades renseignés avec `/r`.
- **Bilan hebdomadaire** (envoyé automatiquement, sans l'entonnoir détaillé) : total sur 7 jours, ligne « 30 j : identique » si le résultat est le même,
  une ligne par stratégie (meilleure d'abord), les actifs s'il y en a plusieurs, le nombre de trades actifs et d'alertes, et les signaux écartés
  (tardifs, volatilité faible, news/horaire, doublons, risque), puis « Validation : N trades clôturés sur ~100 pour juger » tant que l'échantillon est trop petit.
  L'entonnoir détaillé reste dans les journaux du workflow.
- **Écart de prix avec ton courtier** : non mesurable ici. Compare le prix de quelques alertes à celui de ta plateforme
  (spread inclus) et ajuste `SPREAD_TABLE` en conséquence.

## Heure locale dans les messages

Chaque alerte, chaque message de suivi et le récapitulatif affichent l'heure du Bénin (« 08h15 Bénin »), et un ordre
limite indique sa fin de validité (« valable jusqu'à 10h15 Bénin »). Variable `ALERT_FUSEAU` pour un autre fuseau
(ex. `Europe/Paris`, avec `ALERT_FUSEAU_NOM=Paris` pour le libellé) ou `none` pour ne plus afficher d'heure.

## Cadre intraday (par défaut, `INTRADAY=0` pour le désactiver)

Toutes les stratégies suivent le même cadre : contexte et obstacles majeurs en H4 / H1, confirmation en M15, trade de la journée.

- **Confirmation en M15** : S5 ne garde que la cascade H4>H1>M15 (plus de D1>H4>H1 ni de H1>M15>M5). S3 confirme (CHoCH, bloc d'ordre, FVG) en M15 au lieu de M5.
- **Entrée sur réaction à un niveau** (S1, S3, S5) : l'entrée doit être à moins de 0,5 ATR H1 d'un niveau ou dans une zone H4/H1 du bon côté (creux ou sommet H1/H4, plus haut ou bas de la veille, bloc d'ordre ou FVG non invalidé par une clôture). Sinon le signal est écarté (« hors niveau H4/H1 »). S2 (cassure de plage) et S4 (range H1) en sont exemptées.
- **Objectif avant le prochain obstacle** (toutes les stratégies) : TP1 ne dépasse jamais le prochain obstacle opposé (sommet ou creux H1/H4, plus haut ou bas de la veille, zone d'offre ou de demande). S'il est à moins de 1 R de l'entrée, le signal est écarté (« obstacle devant l'objectif ») ; sinon TP1 est ramené 0,1 ATR H1 avant lui. TP2 et TP3 ne sont pas modifiés : après TP1, le stop est à l'entrée.
- **Fin de séance** : un trade dont TP1 n'est pas atteint est clôturé au plus tard à 16h45 (New York) ou 10 heures après son ouverture, le plus proche des deux ; un ordre en attente est annulé au même moment. Le message de suivi s'appelle « Fin de séance » et le résultat `eod`. **Après TP1** (stop à l'entrée), le reste continue jusqu'à TP2 ou TP3 même après la fin de séance ; seule la fermeture avant le week-end l'arrête. `INTRADAY_RUNNERS=0` clôture aussi ces restes en fin de séance.
- Les seuils (0,5 ATR, 1 R, 0,1 ATR, 16h45, 10 h) sont des choix de départ, pas des résultats de backtest. Pour comparer : lance le backtest avec la variable `INTRADAY` vide, puis à `0` (ou `--no-intraday` en ligne de commande).

## Hypothèses du suivi et du backtest

- Un ordre limite n'est rempli que si le prix traverse le niveau d'au moins un **demi-spread** (le spread de l'actif, voir `SPREAD_TABLE`) : un simple effleurement ne compte pas.
- Dans la bougie où un ordre est rempli, aucun objectif n'est compté (l'ordre des extrêmes de la bougie est inconnu). Le stop, lui, reste évalué.
- Si une bougie atteint TP1 puis revient à l'entrée, le trade ferme à break-even (idem pour le stop remonté à TP1 après TP2).
- Le rapport du backtest donne le coût moyen du spread par stratégie, avec le résultat avant et après coût.
- Ces hypothèses sont prudentes : elles rendent le backtest plus pessimiste, donc plus proche du réel.

## Format des alertes (variable `ALERT_FORMAT`)

Le graphique est toujours joint (désactivable avec `CHARTS=0`). Le texte existe en 5 formats, choisis par la variable
GitHub `ALERT_FORMAT` (défaut : `essentiel` ; une valeur inconnue revient à `essentiel`) :

| Valeur | Contenu | Longueur |
|---|---|---|
| `complet` | prix actuel, entrée, SL, TP et ratios, analyse détaillée, tendance D1/H4 avec âge, invalidation, règle de gestion | ~24 lignes |
| `compact` | entrée, SL, TP et ratios, résumé du setup, tendance D1/H4 avec âge | ~10 lignes |
| `contexte` | niveaux + risque, résumé du setup, tendance D1/H4 détaillée (jambes), invalidation | ~11 lignes |
| `minimal` | direction, entrée, SL, TP1/2/3 | 3 lignes |
| `essentiel` (défaut) | type d'ordre, actif, stratégie (⚡ si confluence), heure, entrée, SL, TP1/2/3, validité, numéro ; « signal il y a N min » si l'alerte a 3 minutes ou plus | 3 lignes |

Exemple `essentiel` (ordre limite avec confluence) :

```
🔴 SELL LIMIT · XAUUSD M15 · ⚡ Sweep + CHoCH + Asian Breakout · 14:35
4012.50 · SL 4018.20 · TP 4001.30 / 3992.40 / 3980.10
Valable jusqu'à 16:30 · #12
```

Les messages de suivi (TP1 atteint, stop, structure cassée…) gardent leur forme, avec l'heure en plus. Exemple `compact` :

```
🟢 BUY · XAUUSD · M5 · Sweep + CHoCH · Londres

Entrée  2652.40 (marché)
SL  2648.80
TP1 2656.00 (1:1) · TP2 2659.60 (1:2) · TP3 2663.20 (1:3)

✅ PDL pris · CHoCH M5
✅ D1 haussière établie (9 j) · ⚠️ H4 baissière mûre (6 j)

Réf. #15
```

## Horaires en heure du Bénin (UTC+1, sans heure d'été)

Le bot raisonne en heure de New York, qui change avec l'heure d'été américaine (du 2e dimanche de mars au 1er dimanche de
novembre). Au Bénin, l'heure ne change pas : les horaires glissent donc d'une heure d'une saison à l'autre.

| Événement | New York | Bénin (heure d'été US) | Bénin (heure d'hiver US) |
|---|---|---|---|
| **Récapitulatif de tendance** | 01h00 | **06h00** | **07h00** |
| Début de la plage asiatique | 20h00 | 01h00 | 02h00 |
| Ouverture de la killzone de Londres | 02h00 | 07h00 | 08h00 |
| Fin de la killzone de Londres | 05h00 | 10h00 | 11h00 |
| Killzone de New York | 07h00-10h00 | 12h00-15h00 | 13h00-16h00 |
| London Close | 10h00-12h00 | 15h00-17h00 | 16h00-18h00 |
| Rollover (plus d'alerte dès) | 16h55 | 21h55 | 22h55 |
| Ouverture des bougies D1 et H4 | 17h00 | 22h00 | 23h00 |
| Vendredi : plus d'alerte dès / trades clôturés dès | 15h30 / 16h30 | 20h30 / 21h30 | 21h30 / 22h30 |

Avec le réglage par défaut (01h00 New York), le récapitulatif arrive donc **toujours une heure avant Londres** : à 06h00
au Bénin jusqu'au 1er novembre 2026, puis à 07h00. Pour le recevoir à heure fixe au Bénin, définis `RECAP_HEURE=06:00` et
`RECAP_FUSEAU=Africa/Porto-Novo` (mais il sera alors à 1 h ou 2 h de Londres selon la saison).

## Commandes Telegram

Boutons **Pris / Ignoré** sous chaque alerte, et : `/pris N`, `/ignore N`, `/r N X` (ton résultat réel du
trade #N en R, ex. `/r 12 -0.8`), `/bilan` (30 derniers jours, par stratégie), `/tendance` (récapitulatif de tendance). Les commandes sont lues à chaque
scan (réponse sous 5 minutes).

## Backtest

Workflow **Backtest Or** (ou en local : `python backtest.py --days 120 --split 0.6`).

- Rejoue les mêmes fonctions que le bot en direct, sans regarder le futur, avec un spread (défaut : or 0,015 %, majeures 0,006 %, BTC/ETH 0,05 % ; `--spread-pct` pour imposer le tien, ou la variable `SPREAD_TABLE` actif par actif).
- `--sym frxXAUUSD,frxEURUSD` pour choisir les actifs, `--sym all` pour les 28 actifs, `--sym synth` pour les 10 indices Volatility.
- Rapport par actif, par stratégie, sens, session, alignement H4, résultat, coût du spread par stratégie, et stabilité entre deux périodes. L'intervalle de confiance rééchantillonne des jours entiers, et un avertissement signale le nombre de combinaisons actif x stratégie testées.
- `--class-filter` restreint chaque actif aux stratégies de sa classe (par défaut, toutes les stratégies tournent sur chaque actif).
- `--only S2,S3` pour une stratégie ; `--set strategies.S1_ADX_MIN=15,18,22` pour une grille ; `--source csv`
  pour tes propres données (un seul actif) ; `--source sim` pour un contrôle de bon sens sur marche aléatoire.
- Il faut environ 25 jours d'échauffement (EMA 200 du H4) : demande `--days` en plus.

**Ce que le backtest peut et ne peut pas dire** : sous quelques centaines de trades, un taux de gain n'est que
du bruit. Retiens une stratégie seulement si l'espérance est positive sur les deux périodes, avec un intervalle
de confiance qui exclut zéro, et après avoir ajouté ton vrai spread. Une stratégie à quelques dizaines de
trades n'est pas évaluable.

## Ce qui a été vérifié, et ce qui ne l'a pas été

Vérifié (données simulées, sans accès réseau) : le code s'exécute de bout en bout, les 5 stratégies produisent des
signaux, le suivi (TP1/TP2/TP3, stop, doublons), le message et le graphique fonctionnent, et sur une marche
aléatoire l'espérance est proche de zéro (pas de gain « gratuit » dans le code).

**Non vérifié** : la connexion à l'API Deriv et l'envoi Telegram (pas d'accès réseau pendant la rédaction), et
surtout **la rentabilité sur l'or réel**. Fais d'abord un premier run avec `test = true`, puis un backtest sur
Deriv, avant de suivre les alertes.
