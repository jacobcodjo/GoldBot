# Bot or (XAUUSD) + paires forex majeures + BTC/ETH

Bot d'alertes Telegram pour l'or, les paires forex majeures (7 contre USD et 8 croisements majeurs de Deriv), le BTC et l'ETH, avec quatre stratégies (détail précis dans
[STRATEGIES.md](STRATEGIES.md)). Il reprend l'architecture du bot CRT/Impulsion (client Deriv robuste, suivi
des trades, garde-fous, graphique et boutons Telegram, backtest) mais **aucune de ses stratégies**.

| Code (réglages) | Stratégie | Unités de temps |
|---|---|---|
| S1 | Trend Pullback | H4 > H1 > M15 |
| S2 | Asian Breakout | M15 |
| S3 | Sweep + CHoCH (SMC) | H4/H1 > M15 > M5 |
| S4 | Mean Reversion | H1 > M15 |

Le bot **n'exécute aucun ordre** : il envoie des alertes (entrée, stop, TP1 à TP3 avec ratio, lot suggéré,
graphique) et suit leur résultat en R. Aucune stratégie n'est garantie ; les paramètres sont des points de
départ à valider par backtest.

## Actifs suivis

| Actif | Symbole Deriv |
|---|---|
| Or | `frxXAUUSD` |
| Majeures contre USD | `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxUSDCHF`, `frxAUDUSD`, `frxUSDCAD`, `frxNZDUSD` |
| Croisements majeurs Deriv | `frxAUDJPY`, `frxEURAUD`, `frxEURCAD`, `frxEURCHF`, `frxEURGBP`, `frxEURJPY`, `frxGBPAUD`, `frxGBPJPY` |
| Cryptos | `cryBTCUSD`, `cryETHUSD` |

Les quatre stratégies s'appliquent à chaque actif avec les mêmes règles (toutes les distances sont exprimées en ATR,
donc elles s'adaptent à la volatilité de chaque paire). Elles ont été pensées pour l'or : **rien ne dit qu'elles
fonctionnent aussi bien sur les majeures**. Compare actif par actif au backtest et retire ceux qui ne tiennent pas
(variable `SYMBOLS`). La liste forex reprend les 14 paires que Deriv classe en « Forex majeures » (NZDUSD, rangée en
mineures par Deriv, reste suivie). Le suivi de l'exposition est **par devise** : un trade compte comme long ou short
sur chacune de ses deux devises (EURJPY acheté = long EUR, short JPY ; l'or acheté = short USD), et 2 trades au plus
dans le même sens sur une même devise sont ouverts à la fois. BTC et ETH forment un groupe corrélé : 2 trades au plus
dans le même sens.

**Croisements (sans USD)** : lot suggéré converti en USD avec le dernier prix de la paire de conversion (USDJPY, GBPUSD,
AUDUSD, USDCAD, USDCHF), qui doit être dans `SYMBOLS` ; sinon l'alerte indique « lot à calculer » plutôt qu'un lot faux.
Spreads par défaut (estimations, `SPREAD_PCT` pour imposer) : 0,007 à 0,014 % selon la paire, plus larges que les
majeures USD (0,006 %). Les paires en yen s'affichent avec 3 décimales.

**Cryptos (marché 24h/24, 7j/7)** : pas de rollover ni de fermeture hebdomadaire, donc aucune fenêtre sans alerte
liée au week-end (seules les annonces USD à fort impact bloquent les alertes) ; les stratégies Sweep + CHoCH et
Mean Reversion ne sont pas limitées aux heures de session. Lot suggéré : 1 unité de la crypto par lot, à vérifier
sur ta plateforme (`LOT_UNITS_CRYBTCUSD` pour un autre contrat). Spread par défaut du backtest : 0,05 %.

## Fichiers

| Fichier | Rôle |
|---|---|
| `gold.py` | Scan, client Deriv (limites de requêtes, reconnexion), alertes et commandes Telegram, suivi |
| `strategies.py` | Les 4 stratégies, indicateurs (EMA, ATR, ADX, RSI, Bollinger, swings), sessions |
| `trend.py` | Tendance et âge de la tendance (D1, H4, H1) pour le récapitulatif journalier |
| `tracker.py` | Suivi des trades : TP1/TP2/TP3, stop à l'entrée, sorties de structure et au temps, statistiques |
| `guard.py` | Fenêtres sans alerte (news USD, rollover, week-end), limites de risque, lot, santé du bot, bilan |
| `charts.py` | Graphique joint à l'alerte |
| `tests.py` | 53 tests automatisés (`python -m unittest tests -v`, aussi lancés par `.github/workflows/tests.yml`) |
| `backtest.py` | Rejeu M5 des 4 stratégies, par stratégie, avec deux périodes et grille de réglages |
| `STRATEGIES.md` | Règles précises de chaque stratégie |
| `.github/workflows/gold.yml` | Scan (déclenché par un cron externe) + sauvegarde de l'état sur la branche `data` |
| `.github/workflows/tests.yml` | Lance les tests à chaque modification du dépôt |
| `.github/workflows/backtest.yml` | Backtest manuel |

## Installation

1. Crée un dépôt GitHub avec le contenu de ce dossier (le dossier `.github/workflows` inclus).
2. **Settings > Secrets and variables > Actions** : secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID`.
3. Variables facultatives (onglet Variables) :
   - `ACCOUNT_BALANCE` et `RISK_PCT` (ex. 10000 et 1) : affichent le lot suggéré (100 oz par lot ; vérifie sur ta plateforme).
   - `STRATEGIES` : liste à activer, ex. `S2,S3` (défaut : `S1,S2,S3,S4`).
   - `SYMBOL_STRATEGIES` : stratégies par actif, ex. `frxEURUSD:S1,S2;cryBTCUSD:S2,S4` (un actif absent garde toutes les
     stratégies actives). Sert par exemple à couper Sweep + CHoCH sur les cryptos.
   - `ENTRY_MODE` : `auto` (défaut : ordres limites pour les 4 stratégies), `market` ou `limit` pour tout forcer ;
     `ENTRY_MODES` : par stratégie, ex. `S3:market,S4:market`.
   - `SPREAD_PCT` : spread supposé en % du prix, pour tous les actifs (défaut : or 0,015, majeures 0,006, BTC/ETH 0,05).
   - `MAX_AGE_MIN` : âge maximal d'un signal en minutes (défaut 20) ; `WEEKEND_EXIT=0` désactive la clôture du vendredi.
   - `ALERT_FUSEAU` : fuseau d'affichage de l'heure (défaut `Africa/Porto-Novo`, soit l'heure du Bénin ; `none` pour désactiver).
   - `ALERT_FORMAT` : `complet`, `compact`, `contexte` ou `minimal` (voir plus bas).
   - `SYMBOLS` : actifs suivis, ex. `frxXAUUSD,frxEURUSD` (défaut : l'or, les 7 majeures USD, les 8 croisements majeurs, BTC et ETH).
4. Le workflow n'a pas de `schedule` : déclenche-le toutes les 5 minutes avec ton cron externe
   (`workflow_dispatch`), comme pour l'ancien bot. Un scan télécharge M5 et M15 pour chaque actif (18 actifs : une
   trentaine de secondes avec la temporisation anti-limite de requêtes).
5. Lance une fois le workflow avec `test = true` : tu reçois un message de contrôle avec l'entonnoir.

**Sauvegarde de l'état.** Les trades suivis, les garde-fous et les alertes déjà envoyées (`trades.json`, `guard.json`,
`state.json`) sont sauvegardés à chaque scan sur une branche `data` du dépôt (une seule révision, écrasée à chaque fois),
puisque le cache GitHub peut être supprimé sans prévenir. Les bougies (`cache.json`) restent dans le cache GitHub : leur
perte ne fait que ralentir un scan. Il faut **Settings > Actions > General > Workflow permissions : Read and write**.
Si ton dépôt est public, la branche `data` (historique de tes trades simulés, aucun secret) est lisible par tous.
Pour les jours d'annonces non couverts par le calendrier automatique, copie `news.example.json` en `news.json`.

## Récapitulatif de tendance journalier

Chaque matin du lundi au vendredi, à **01h00 New York** (une heure avant l'ouverture de Londres, qui ouvre à 02h00 New
York ; environ 07h00 à Paris), à la première passe après cette heure, le bot envoie un message
avec, pour chaque actif, la tendance en **D1, H4 et H1**, son **âge** et une phrase de synthèse sur l'alignement :

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
sommet (baisse). Les actifs dont le marché est fermé (forex le week-end) sont listés en bas du message.
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
  de résultat). Estimations par défaut ; remplace-les par ceux de ton courtier (`SPREAD_PCT`).
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
- **Écart de prix avec ton courtier** : non mesurable ici. Compare le prix de quelques alertes à celui de ta plateforme
  (spread inclus) et ajuste `SPREAD_PCT` en conséquence.

## Heure locale dans les messages

Chaque alerte, chaque message de suivi et le récapitulatif affichent l'heure du Bénin (« 08h15 Bénin »), et un ordre
limite indique sa fin de validité (« valable jusqu'à 10h15 Bénin »). Variable `ALERT_FUSEAU` pour un autre fuseau
(ex. `Europe/Paris`, avec `ALERT_FUSEAU_NOM=Paris` pour le libellé) ou `none` pour ne plus afficher d'heure.

## Format des alertes (variable `ALERT_FORMAT`)

Le graphique est toujours joint (désactivable avec `CHARTS=0`). Le texte existe en 4 formats, choisis par la variable
GitHub `ALERT_FORMAT` (défaut : `complet` ; une valeur inconnue revient à `complet`) :

| Valeur | Contenu | Longueur |
|---|---|---|
| `complet` | prix actuel, entrée, SL, TP et ratios, analyse détaillée, tendance D1/H4 avec âge, invalidation, lot, règle de gestion | ~24 lignes |
| `compact` | entrée, SL, TP et ratios, résumé du setup, tendance D1/H4 avec âge, lot | ~10 lignes |
| `contexte` | niveaux + risque, résumé du setup, tendance D1/H4 détaillée (jambes), invalidation, lot | ~11 lignes |
| `minimal` | direction, entrée, SL, TP1/2/3, lot | 3 lignes |

Les messages de suivi (TP1 atteint, stop, structure cassée…) gardent leur forme, avec l'heure en plus. La ligne « Lot » n'apparaît que si
`ACCOUNT_BALANCE` est renseigné. Exemple `compact` :

```
🟢 BUY · XAUUSD · M5 · Sweep + CHoCH · Londres

Entrée  2652.40 (marché)
SL  2648.80
TP1 2656.00 (1:1) · TP2 2659.60 (1:2) · TP3 2663.20 (1:3)

✅ PDL pris · CHoCH M5
✅ D1 haussière établie (9 j) · ⚠️ H4 baissière mûre (6 j)

Lot 0.27 · Réf. #15
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

- Rejoue les mêmes fonctions que le bot en direct, sans regarder le futur, avec un spread (défaut : or 0,015 %, majeures 0,006 %, BTC/ETH 0,05 % ; `--spread-pct` pour imposer le tien).
- `--sym frxXAUUSD,frxEURUSD` pour choisir les actifs, `--sym all` pour les 18 actifs.
- Rapport par actif, par stratégie, sens, session, alignement H4, résultat, et stabilité entre deux périodes.
- `--only S2,S3` pour une stratégie ; `--set strategies.S1_ADX_MIN=15,18,22` pour une grille ; `--source csv`
  pour tes propres données (un seul actif) ; `--source sim` pour un contrôle de bon sens sur marche aléatoire.
- Il faut environ 25 jours d'échauffement (EMA 200 du H4) : demande `--days` en plus.

**Ce que le backtest peut et ne peut pas dire** : sous quelques centaines de trades, un taux de gain n'est que
du bruit. Retiens une stratégie seulement si l'espérance est positive sur les deux périodes, avec un intervalle
de confiance qui exclut zéro, et après avoir ajouté ton vrai spread. Une stratégie à quelques dizaines de
trades n'est pas évaluable.

## Ce qui a été vérifié, et ce qui ne l'a pas été

Vérifié (données simulées, sans accès réseau) : le code s'exécute de bout en bout, les 4 stratégies produisent des
signaux, le suivi (TP1/TP2/TP3, stop, doublons), le message, le lot et le graphique fonctionnent, et sur une marche
aléatoire l'espérance est proche de zéro (pas de gain « gratuit » dans le code).

**Non vérifié** : la connexion à l'API Deriv et l'envoi Telegram (pas d'accès réseau pendant la rédaction), et
surtout **la rentabilité sur l'or réel**. Fais d'abord un premier run avec `test = true`, puis un backtest sur
Deriv, avant de suivre les alertes.
