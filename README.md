# Gold Bot : alertes Telegram pour l'or (XAUUSD), le forex, BTC/ETH et les indices Volatility

Bot Python qui scanne **28 actifs** toutes les 5 minutes sur l'API publique de Deriv, applique **5 stratégies** (S1 à S4 et S9) et envoie des **alertes Telegram** avec graphique : type d'ordre, entrée, stop, TP1 à TP3 et ratios. Il **n'exécute aucun ordre** : il suit ensuite chaque signal en R (gain en multiples du risque) et t'indique quand annuler, clôturer ou déplacer ton stop.

> Cette documentation décrit le comportement **du code** (valeurs par défaut, sans variable GitHub). Les seuils sont des points de départ **non validés** par un backtest sur marché réel : aucune stratégie n'a de rendement garanti, et ce document n'est pas un conseil financier.

| Code | Stratégie | Unités de temps (cadre intraday par défaut) |
|---|---|---|
| S1 | **Pullback** : tendance de structure, impulsion, retracement Fibonacci 50-79 %, entrée sur sweep + FVG + bloc d'ordre | H4 > H1 > M15 |
| S2 | **Sweep + CHoCH** (Smart Money) : balayage d'une liquidité sur une zone H1/H4, puis cassure de structure | contexte H4/H1, sweep M15, CHoCH M15 |
| S3 | **Figures & Retournement** : figures chartistes H1/H4 confirmées en M15, plus ordre de retournement contre une tendance H4 mûre | H1/H4 > M15 |
| S4 | **CRT** (Candle Range Theory) : C1/C2 en D1 ou H4, cassure de structure M15 après C2 | D1/H4 > M15 |
| S9 | **Market Profiles** (`profiles.py`) : range, manipulation, expansion ; 5 setups A à E sur des niveaux clés, entrée au retest | M15 (M5 ou H1 au choix), niveaux H1/H4/D1 |

Anciens codes toujours lus : `S5` = S1, `S7` = S3, `S8` = S4 ; la 5e stratégie prend donc le code **S9**, car S5 à S8 sont réservés à ces alias. Les stratégies supprimées (Asian Breakout, Mean Reversion « MR », Trend Pullback « classique ») n'existent plus, mais leurs trades déjà enregistrés restent suivis.

---

## 1. Actifs

| Classe | Actifs (symboles Deriv) |
|---|---|
| Or | `frxXAUUSD` |
| Forex de session | EURUSD, GBPUSD, USDCAD, EURGBP, EURAUD, EURCAD, GBPAUD |
| Forex JPY | USDJPY, EURJPY, GBPJPY, AUDJPY |
| Forex calme | USDCHF, EURCHF, AUDUSD, NZDUSD |
| Cryptos | `cryBTCUSD`, `cryETHUSD` |
| Indices synthétiques | `R_10`, `R_25`, `R_50`, `R_75`, `R_100` et `1HZ10V`, `1HZ25V`, `1HZ50V`, `1HZ75V`, `1HZ100V` |

- **Les classes ne filtrent rien** : elles servent aux récapitulatifs, à l'option `--sym` du backtest et à la colonne « classe » du rapport. Toutes les stratégies actives tournent sur tous les actifs, sauf restriction par `SYMBOL_STRATEGIES` (ex. `frxEURUSD:S1,S2;cryBTCUSD:S2,S3`). Les anciennes variables `CLASS_FILTER`, `CLASS_STRATEGIES` et `TIER_MAX` sont ignorées.
- **Marchés à séance** (or, forex) : fenêtres sans alerte (rollover, week-end), sessions de trading imposées à S1, S2 et S3, fin de séance intraday.
- **Cryptos et indices synthétiques** (24h/24, 7j/7) : S1, S2 et S3 n'ont pas de limite d'horaire (S4 n'en a jamais), aucune fin de séance (sauf `CRYPTO_INTRADAY=1` pour les cryptos), pas de rollover ni de fermeture de week-end.
- **Indices Volatility** : prix généré aléatoirement, insensible aux annonces économiques, aucune liquidité réelle. Rien ne garantit qu'une stratégie y ait un avantage : à traiter comme une expérience, à valider par `--sym synth`. Leur D1 est la bougie daily de Deriv (00h GMT) et non 17h New York.
- **Exposition par devise** : un trade compte long ou short sur chacune de ses deux devises (EURJPY acheté = long EUR, short JPY ; or acheté = short USD). Maximum **2 trades nets dans le même sens** par devise ; BTC et ETH forment un groupe (2 au plus dans le même sens). Aucune limite pour les indices, ni sur le nombre total de trades, ni sur les pertes du jour.
- **Spreads supposés** (en % du prix, retirés de chaque trade en direct et au backtest ; `SPREAD_PCT` ou `SPREAD_TABLE` pour les remplacer) : or 0,015 ; majeures contre USD 0,006 ; croisements EURGBP 0,007, EURJPY 0,008, EURCHF 0,009, AUDJPY 0,009, EURCAD 0,010, EURAUD 0,010, GBPJPY 0,012, GBPAUD 0,014 ; BTC et ETH 0,05 ; indices 0,02. Priorité : `SPREAD_TABLE`, puis `SPREAD_PCT`, puis ces défauts.
- **Décimales d'affichage** : or et cryptos 2, paires en yen 3, autres paires 5, indices : V10 3, V25 3, V50 4, V75 4, V100 2, séries 1s 2.

---

## 2. Fichiers

| Fichier | Rôle |
|---|---|
| `gold.py` | Boucle de scan, client Deriv (WebSocket), messages et commandes Telegram, récapitulatifs, suivi en direct |
| `strategies.py` | S1 (Pullback), S2 (Sweep + CHoCH), unité de prix, primitives SMC, Fibonacci, obstacles H4/H1, sessions, ordres limites |
| `setups.py` | Tendance et âge de tendance (D1/H4/H1), alerte et ordre de retournement, S3 (figures), S4 (CRT) |
| `tracker.py` | Suivi des trades : exécution des ordres limites, TP1 à TP3, break-even, sorties de structure, au temps, de fin de séance |
| `guard.py` | Fenêtres sans alerte (rollover, week-end), doublons et exposition, santé du bot, bilan hebdomadaire |
| `charts.py` | Graphique joint à chaque alerte (matplotlib) |
| `backtest.py` | Rejeu M5 des mêmes fonctions que le bot en direct, deux périodes, grille de réglages |
| `profiles.py` | Détection des setups A à E de Market Profiles (prix pur, retourne des `Setup`) ; branché sur le bot par `setups.scan_profiles` |
| `tests.py` | 275 tests unitaires (`python -m unittest tests -v`), sans réseau |
| `.github/workflows/` | `gold.yml` (scan, déclenché de l'extérieur), `backtest.yml` (manuel), `tests.yml` (à chaque push) |

Dépendances (`requirements.txt`) : `websocket-client`, `requests`, `matplotlib`. Python 3.12 dans les workflows.

---

## 3. Déroulé d'un scan

À chaque passage (environ 5 minutes), `gold.py` :

1. restaure l'état (`trades.json`, `guard.json`, `state.json`) depuis la branche `data` ;
2. lit les commandes et boutons Telegram, puis fait avancer les trades suivis (TP, stop, expirations) et envoie les événements ;
3. envoie le récapitulatif de tendance du matin et le récapitulatif du soir des indices s'ils sont dus ;
4. pour chaque actif : télécharge les bougies (M5, M15, H1 ; H4 et D1 sont reconstruites depuis le H1), ignore l'actif si sa dernière bougie M5 a plus de 15 minutes, évalue les stratégies actives, écarte les signaux déjà envoyés, ajoute tendance D1/H4 et confluence, applique les fenêtres sans alerte (rollover, week-end), puis les contrôles de risque (doublon, sens opposé, exposition) ;
5. envoie l'alerte (graphique + boutons « Pris / Ignoré ») et enregistre le trade ;
6. met à jour la santé du bot, l'entonnoir de filtres et le bilan hebdomadaire, puis sauvegarde l'état.

Données téléchargées : 300 bougies M5, 400 M15, 2 500 H1 (environ 100 jours). D1 et H4 ouvrent à **17h New York** (D1 des indices : 00h GMT). Le client Deriv essaie l'endpoint public, puis l'ancien en secours, avec 0,6 s minimum entre deux requêtes et jusqu'à 6 reprises. Un actif en erreur ne bloque pas les autres.

Un setup bloqué par les contrôles de risque n'est plus réexaminé ; un setup bloqué par une fenêtre sans alerte (horaire) l'est au scan suivant. Les clés de déduplication sont conservées 7 jours.

---

## 4. Installation

1. Crée un dépôt GitHub avec ce dossier (`.github/workflows` inclus).
2. **Settings > Secrets and variables > Actions** : secrets `TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` (facultatif : `HEARTBEAT_URL`, ping de surveillance de type healthchecks.io appelé à la fin de chaque passage réussi).
3. **Settings > Actions > General > Workflow permissions : Read and write** (sauvegarde de l'état sur la branche `data`).
4. `gold.yml` n'a **pas de `schedule`** : déclenche-le toutes les 5 minutes avec un cron externe (`workflow_dispatch`). Un seul scan à la fois (`concurrency`), durée maximale 10 minutes.
5. Lance une fois le workflow avec `test = true` : message de contrôle avec l'entonnoir de filtres et les statistiques.

**État.** `trades.json`, `guard.json` et `state.json` sont sauvegardés à chaque passage sur la branche `data` (une seule révision orpheline, écrasée) : si le dépôt est public, cette branche est lisible par tous (aucun secret dedans). Les bougies sont dans le cache GitHub : sa perte ralentit un scan sans autre conséquence.

### Variables facultatives (Settings > Variables)

Seules les variables **transmises par `gold.yml`** agissent sur le bot en direct (voir la note sous le tableau).

| Variable | Rôle (défaut) |
|---|---|
| `STRATEGIES` | Stratégies actives, ex. `S2,S3` (défaut `S1,S2,S3,S4,S9`). **Si tu as déjà défini cette variable dans GitHub, ajoute `S9`** pour activer la nouvelle stratégie |
| `SYMBOLS` | Actifs suivis (défaut : les 28) |
| `SYMBOL_STRATEGIES` | Stratégies imposées actif par actif ; un actif absent reçoit toutes les stratégies actives |
| `ENTRY_MODE`, `ENTRY_MODES` | `auto` (défaut : ordres limites pour les 5 stratégies), `market` ou `limit` ; par stratégie : `S2:market,S3:market` |
| `INTRADAY` | `0` désactive le cadre intraday ; `INTRADAY_RUNNERS=1` laisse courir le reste après TP1 en fin de séance ; `CRYPTO_INTRADAY=1` soumet les cryptos à la fin de séance |
| `S1_MIN_RR`, `S1_RISK_CAP_H1`, `S1_D1_ALIGN`, `S1_OBST_ENTRY` | Garde-fous de S1 (défauts : 3 ; 2 ; actif ; actif) ; `0` désactive les valeurs numériques |
| `S2_BIAS_FILTER`, `S2_HTF_ZONE`, `S2_FIB_FILTER` | Garde-fous de S2 : biais de structure, sweep sur zone H1/H4, côté Fibonacci (défaut : actifs ; `0` désactive) |
| `S2_MIN_RR`, `S2_RISK_CAP_H1`, `S2_MAX_AGE_MIN`, `S2_SWEEP_MIN_ATR` | Ratio minimal sur TP1 (défaut : celui de S1, soit 3), risque maximal en unités H1 (1,5), âge maximal du déclencheur en minutes (20), dépassement minimal de la mèche en unités M15 (0,1) |
| `S3_FIB_FILTER`, `S3_FIB_CAP_TP3`, `S3_CONTEXT_ALIGN` | Repli Fibonacci des continuations, plafond de TP3 des retournements, contexte H4/D1 des continuations (défaut : actifs) |
| `S3_MAX_AGE_MIN`, `S3_REV_MIN_RR` | Âge du déclencheur (20 min), ratio minimal du retournement sur TP1 (celui de S1) |
| `S6_TOL_ATR`, `S6_RISK_CAP_ATR`, `S6_MIN_RR`, `S6_NOCONF_MIN_RR`, `S6_CONF_RISK_FACTOR` | Figures de S3 : tolérance de touche des lignes (0,5), risque maximal en unités de la figure (5), ratio minimal vers TP3 (1), idem sans confluence (1,5), facteur de risque avec confluence (1,4) |
| `S7_RISK_CAP_ATR`, `S7_ENTRY_MAX_ATR`, `REVERSAL_MIN_SIGNS` | Retournement de S3 : risque maximal en unités H1 (3), retest maximal à 1 unité H1 du prix, signes d'essoufflement exigés sur 2 (2) |
| `S4_MIN_RR`, `S4_MAX_AGE_MIN`, `S4_CONTEXT_ALIGN`, `S4_SWEEP_MIN_ATR` | CRT : ratio minimal sur TP1 (celui de S1), âge du déclencheur (20 min), pas contre une tendance H4/D1 claire (actif), dépassement minimal de C2 en unités de référence (0,1) |
| `S1_CONFIRM_TF`, `S2_CONFIRM_TF`, `S3_CONFIRM_TF`, `S4_CONFIRM_TF` | Timeframe d'entrée/confirmation : `M15` ou `M5` (voir § 6.7) |
| `S9_TF`, `S9_BARS`, `S9_MIN_RR`, `S9_RISK_CAP_H1`, `S9_SL_BUF_ATR`, `S9_MAX_AGE_MIN`, `S9_SESSION_FILTER` | Market Profiles : timeframe d'analyse `M5`, `M15` ou `H1` (M15), bougies clôturées analysées (160), ratio minimal sur TP1 (celui de S1, soit 3), risque maximal en unités H1 (2), marge du stop au-delà du sweep en unités (0,15 ; 0 = sur l'extrême), âge maximal du déclencheur en minutes (20), session obligatoire sur les marchés à séance (actif ; `0` désactive) |
| `UNIT_PCT` | **Unité de prix par actif** (voir § 5) : pourcentage du prix pour une bougie H1, ex. `frxXAUUSD=0.4,cryBTCUSD=0.8` ; remplace les valeurs par défaut de `strategies.py` |
| `STOP_MODE`, `S1_STOP_MODE`, `S2_STOP_MODE`, `S4_STOP_MODE` | Placement du stop de S1, S2 et S4 : `sweep` (défaut : au-delà de l'extrême du sweep) ou `ob` (à l'autre extrémité de la zone d'entrée, voir § 6.10) ; la variable de la stratégie prime sur `STOP_MODE` |
| `ONE_TRADE_PER_SIDE` | `1` (défaut) : un seul trade par actif et par sens, toutes stratégies confondues ; `0` : un par stratégie |
| `CONFLUENCE_MIN` | Fenêtre de confluence en minutes (défaut 60 ; `0` désactive) |
| `SPREAD_PCT`, `SPREAD_TABLE` | Spread supposé : global, ou par actif (`frxXAUUSD=0.02,cryBTCUSD=0.04`, prioritaire) |
| `WEEKEND_EXIT` | `0` désactive la clôture du vendredi (forex et or) |
| `REVERSAL_ALERTS` | `0` supprime le message d'information de retournement |
| `ALERT_FORMAT`, `CHARTS` | Format du texte (voir § 7) ; `CHARTS=0` retire le graphique |
| `ALERT_FUSEAU`, `ALERT_FUSEAU_NOM` | Fuseau affiché (défaut `Africa/Porto-Novo`, « Bénin » ; `none` pour ne plus afficher d'heure) |
| `RECAP_FORMAT`, `RECAP_HEURE`, `RECAP_FUSEAU`, `SYNTH_RECAP_HEURES` | Récapitulatifs de tendance (voir § 8) |
| `DERIV_APP_ID`, `DERIV_WS_URL` | Réglages techniques : application Deriv (défaut 1089), endpoint forcé |

**Note sur `S6_*`.** Le code lit aussi `S6_PIVOT_K`, `S6_MIN_SWING_ATR`, `S6_MIN_H_ATR`, `S6_BUF_ATR`, `S6_MAX_AGE`, `S6_TREND_LB`, `S6_TREND_ATR`, `S6_POLE_LB` et `S6_POLE_ATR` (détection des figures), mais **ni `gold.yml` ni `backtest.yml` ne les transmettent** : les définir dans GitHub reste sans effet tant que tu ne les ajoutes pas à l'étape `env` des deux workflows. À l'inverse, `PULLBACK_VARIANT` est transmise mais plus lue par le code. `backtest.yml` ne transmet que les réglages utiles au rejeu (pas `STRATEGIES`, `SYMBOLS`, ni les variables d'affichage).

---

## 5. Conventions communes

- **Aucun indicateur** : le bot n'utilise ni ATR, ni ADX, ni RSI, ni moyenne mobile. Les entrées reposent sur le prix seul (structure, liquidité, FVG, blocs d'ordre, figures, Fibonacci). Les distances (stops, plafonds de risque, impulsion minimale, tailles de FVG et de sweep, poursuite du prix) s'expriment en **unités de prix** : l'unité d'un actif est un **pourcentage fixe du prix** pour une bougie H1, mis à l'échelle de la durée de la bougie (racine du temps : M5 0,29 ; M15 0,5 ; H1 1 ; H4 2 ; D1 4,9). Elle ne dépend d'aucune donnée de marché récente ; seul le prix courant la fait varier.
- **Unité H1 par défaut, en % du prix** (estimations de départ, **à calibrer** avec `UNIT_PCT`) : or 0,35 ; EURUSD 0,08, GBPUSD 0,10, USDCAD 0,08, EURGBP 0,06, EURAUD 0,10, EURCAD 0,08, GBPAUD 0,12 ; USDJPY 0,09, EURJPY 0,10, GBPJPY 0,13, AUDJPY 0,11 ; USDCHF 0,08, EURCHF 0,06, AUDUSD 0,09, NZDUSD 0,10 ; BTC 0,60, ETH 0,90 ; indices Volatility (valeur théorique selon leur volatilité annuelle de 10, 25, 50, 75 et 100 %) 0,17, 0,43, 0,85, 1,28 et 1,70 ; actif inconnu 0,10. Exemple : l'or à 4 000 a une unité H1 de 14 points, M15 de 7 points.
- **Corps de référence** : 0,4 unité du timeframe ; une cassure ou un FVG doit avoir un déplacement d'au moins 1,2 à 1,5 fois ce corps (soit 0,5 à 0,6 unité).
- **Pas de filtre de volatilité** : sans moyenne de marché, le bot ne peut plus écarter un marché « mort » ou « en pic » ; les stops et plafonds restent des multiples fixes de l'unité.
- **Bougies clôturées uniquement** : la bougie en formation ne sert qu'au prix actuel.
- **Heures** : le bot raisonne en heure de **New York** ; les messages affichent l'heure du Bénin (UTC+1, sans heure d'été), donc le décalage varie d'une heure avec l'heure d'été américaine (2e dimanche de mars au 1er dimanche de novembre).
- **Déclenchement récent** : la bougie de déclenchement doit être l'une des 2 dernières clôturées (`FRESH`) ; S2, S3 et S4 écartent en plus tout signal dont le déclencheur a plus de 20 minutes.
- **Swings** : fractales de 2 bougies de chaque côté (1 seule en D1 pour la tendance).
- **Déplacement** : une bougie de cassure doit avoir un corps d'au moins 1,2 fois le **corps de référence** du timeframe, soit 0,4 unité (valeurs propres à S1 précisées plus bas).
- **Risque minimal** : S2, S3 et S4 élargissent le stop à 0,5 unité du timeframe d'entrée s'il est plus proche.
- **Un signal par sens** : un seul trade par actif et par sens, toutes stratégies confondues ; pas de sens opposé sur un actif tant qu'un trade ou un ordre est en cours.
- **Tendance** (une seule définition, `setups.py`) : dernier sommet et dernier creux plus hauts que les précédents (2 swings suffisent), structure intacte (aucune clôture sous le dernier creux), sommet précédent cassé par une **clôture**. Âge = jambes consécutives : **naissante** 1, **établie** 2-3, **mûre** 4 et plus. Hausse et baisse sont symétriques.
- **Sessions** (heure de New York, marchés à séance seulement) : Asie 20h-02h, Londres 02h-05h, New York 07h-10h, London Close 10h-12h. S1, S2 et S3 exigent que le déclencheur tombe à Londres, New York ou London Close ; S4 n'a aucune limite horaire.
- **Ratio minimal 1:3 sur TP1** (`S1_MIN_RR`, repris par défaut par S2, S4, S9 et le retournement de S3) ; les figures de S3 ont un ratio vers TP3 (1 ; 1,5 sans confluence) car leurs objectifs sont des fractions de la hauteur de la figure.

---

## 6. Stratégies

### 6.1 S1 Pullback (HTF > MTF > LTF)

Cascade par défaut (cadre intraday) : **tendance H4, impulsion H1, entrée M15**. Avec `INTRADAY=0`, trois cascades : D1 > H4 > H1, H4 > H1 > M15, H1 > M15 > M5. Avec `S1_CONFIRM_TF=M5`, le timeframe d'entrée devient M5. Achat et vente symétriques.

**Filtres de contexte**
1. **Tendance HTF** (structure) naissante ou établie ; la tendance mûre est écartée.
2. **Pas contre une tendance D1 claire** (`S1_D1_ALIGN`), sauf si la tendance de la cascade est le D1.

**Impulsion** (timeframe d'impulsion) : cassure de structure avec déplacement (une bougie de la jambe ≥ 1,5 fois le corps de référence), jambe d'au moins **2 unités**, origine non reprise par le prix, extrême vieux de 48 bougies au plus, aucune clôture de retracement au-delà de **79 %** de la jambe.

**Entrée** (timeframe d'entrée, après l'extrême de l'impulsion)
1. La zone **50 %-79 %** de la jambe est touchée (50-61,8 % = « Golden Zone », 61,8-79 % = « OTE »), sans clôture sous l'origine ni au-delà de 79 %.
2. **Sweep** d'un creux formé pendant le repli (mèche sous le creux, clôture au-dessus), sans clôture ultérieure sous la mèche.
3. **Cassure de structure** du dernier sommet (parmi les 2 dernières bougies) avec déplacement (≥ 1,2 fois le corps de référence).
4. **FVG** d'au moins 0,1 unité, dont la bougie centrale est un déplacement (≥ 1,5 fois), puis **bloc d'ordre** qui chevauche la zone 50-79 %. Le candidat au meilleur ratio est retenu.

**Ordre** (par défaut limite)
- **Limite** : milieu du **FVG** en priorité, sinon bord proche du bloc d'ordre ; il doit être dans la zone 50-79 %, pas encore touché, avec un prix ayant fait au plus 50 % du chemin vers TP1 et un ratio ≥ 3.
- Sinon **marché** si le prix est dans le bloc d'ordre, ou entrée **tardive** (le prix vient de le quitter : au plus 2 bougies, moins de 0,5 hauteur de bloc, moins de 25 % du chemin vers TP1).
- **Stop** : sous le creux du sweep moins 0,15 unité du timeframe d'entrée (avec `S1_STOP_MODE=ob` : sous le bas du bloc d'ordre d'entrée, même marge) ; **plafond de risque 2 unités H1** (`S1_RISK_CAP_H1`).
- **Objectifs** : TP1 = extrême de l'impulsion, TP2 = origine + 1,272 jambe, TP3 = origine + 1,618 jambe. Ratio ≥ 3 sur TP1.
- **Session** : déclencheur à Londres, New York ou London Close (marchés à séance).
- **Invalidation** (sortie de structure avant TP1) : bord du bloc d'ordre côté stop.
- Cadre intraday : voir § 6.5.

### 6.2 S2 Sweep + CHoCH

**Idée** : dans le sens de la structure H4/H1, le prix balaie un niveau de liquidité **dans une zone d'intérêt H1/H4**, puis casse sa structure en sens inverse ; on entre contre le balayage.

1. **Niveaux de liquidité** (chacun a une date de naissance) : plus haut/bas de la veille (PDH/PDL, journée 17h-17h New York), extrêmes de la plage asiatique (20h-02h, valables dès 02h00, au moins 20 bougies M15), **equal highs/lows** H1 (deux swings à moins de 0,15 unité H1, parmi les 8 derniers). Un niveau n'est de la liquidité **qu'une fois** : s'il a déjà été dépassé par une mèche M15 depuis sa naissance, il est ignoré.
2. **Sweep M15** parmi les 8 dernières bougies : la mèche dépasse le niveau d'au moins 0,1 unité M15 et n'est pas suivie d'une clôture au-delà.
3. **Biais de structure** (`S2_BIAS_FILTER`, **actif par défaut**) : tendance **H4 exclusivement** (le H1 n'est jamais consulté), selon la définition de § 5. On ne prend que les ventes après un sweep de sommet dans un biais baissier, et les achats dans un biais haussier ; si le H4 n'a pas de tendance claire, pas de biais donc pas de signal. Le filtre s'applique avant le choix du sweep.
4. **CHoCH** en M15 (M5 avec `S2_CONFIRM_TF=M5`) : clôture au-delà du dernier swing formé dans les 12 bougies M15 (36 en M5) avant l'extrême du sweep, avec déplacement (≥ 1,2 fois), parmi les 2 dernières bougies.
5. **Killzone** : déclencheur à Londres, New York ou London Close (marchés à séance).
6. **Zone H4/H1** (`S2_HTF_ZONE`) : l'étendue du sweep recoupe (tolérance 0,25 unité H1) un bloc d'ordre ou un FVG **non retesté** du sens du trade, né d'un déplacement qui casse la structure ; H4 avant H1, bloc d'ordre avant FVG.
7. **Entrée** : ordre limite sur le bloc d'ordre M15 (bord proche) ou le FVG M15 (milieu) du mouvement ; à défaut, marché si le prix n'a pas fui de plus de 0,75 unité depuis la clôture du déclencheur. Une zone à plus de 1,5 unité du prix écarte le signal. **Stop** : au-delà de l'extrême du sweep, plus 0,15 unité M15 ; **risque maximal 1,5 unité H1**. Avec `S2_STOP_MODE=ob`, le stop passe à l'autre extrémité du bloc d'ordre (ou du FVG) d'entrée.
8. **Fibonacci** (`S2_FIB_FILTER`) : l'entrée doit être du bon côté de l'équilibre (50 %) de la jambe H4 (discount pour un achat, premium pour une vente) ; sans effet si la jambe fait moins de 1,5 unité H1.
9. **Objectifs sur la liquidité opposée intacte** entre 1 R et 6 R (placés 0,1 unité M15 avant le niveau) : TP1 = la première ; TP2 = la suivante située à plus de 0,5 R de TP1, sinon TP1 + 1 R ; TP3 de même. Sans liquidité : TP1 au ratio minimal (3 R), puis +1 R et +2 R. Ratio ≥ 3 sur TP1.
10. **Invalidation** : l'extrême du sweep.

### 6.3 S3 Figures & Retournement

Deux sources de signaux dans la même stratégie, **au plus un signal par sens** (la figure de meilleur ratio vers TP3 l'emporte ; le retournement n'ajoute un signal que si aucune figure n'a signalé dans ce sens).

**Figures** (détectées sur bougies H1 et H4 clôturées, 80 bougies minimum, 300 analysées)
- **Toujours retournement** : double et triple sommet/creux, tête et épaules (et inversée).
- **Toujours continuation** : tasse avec anse (et tasse inversée).
- **Famille selon la tendance qui précède** (30 bougies, seuil 1,5 unité ; pas de figure si la tendance est plate) : biseaux montant/descendant, triangles (symétrique, descendant/ascendant), rectangle, canaux haussier/baissier, élargissement. Un canal, un rectangle, un triangle ou un biseau précédé d'un mât d'au moins 3,5 unités (hauteur ≤ 60 % du mât, figure de 40 bougies au plus) devient un **drapeau** ou un **fanion**, mesuré sur la hauteur du mât.
- Détection par zigzag de pivots (4 bougies de chaque côté, swing minimal 0,8 unité), lignes ajustées avec tolérance de 0,5 unité, hauteur minimale 1,5 unité, dernier pivot vieux de 40 bougies au plus. Les figures haussières sont les miroirs des figures baissières (même code).
- **Cassure confirmée en M15** : l'une des 2 dernières bougies M15 clôture au-delà de la ligne (marge 0,1 unité de la figure), la précédente non.
- **Entrée** : ordre limite sur le **bloc d'ordre** (bord proche) ou, à défaut, le milieu du **FVG** du déplacement qui a cassé la ligne ; sans bloc ni FVG, pas de signal. **Stop** à l'autre bout de la zone, plus 0,15 unité M15. Une zone à plus de 1,5 unité M15 du prix écarte le signal ; au marché, le prix ne doit pas avoir fui de plus de 0,75 unité M15.
- **Objectifs** : TP1, TP2, TP3 = ligne cassée plus 0,5 / 1 / 1,5 fois la hauteur de la figure (mât pour drapeau/fanion). Retournement : TP3 plafonné à l'origine de la jambe précédente (100 % Fibonacci) quand elle se situe entre TP2 et TP3 (`S3_FIB_CAP_TP3`).
- **Garde-fous** : risque maximal 5 unités du timeframe de la figure ; ratio vers TP3 d'au moins 1. **Continuation** : pas contre une tendance H4 ou D1 claire (`S3_CONTEXT_ALIGN`), et le repli ne doit pas reprendre plus de 61,8 % de la jambe précédente (`S3_FIB_FILTER`, jambe d'au moins 2 unités). **Retournement** : confluence avec le retournement détecté (ci-dessous) → risque maximal multiplié par 1,4 et mention « Confluence : retournement possible » ; sans confluence, ratio vers TP3 d'au moins 1,5.

**Retournement** (ex-S7, mêmes conditions que l'alerte d'information du § 8)
1. Tendance **H4 mûre** (4 jambes ou plus) encore intacte.
2. **Sweep H1** d'un sommet (creux) récent datant de moins de 6 bougies H1 (niveau non déjà pris), situé sur un **niveau majeur** : sommet/creux H4, zone H4 ou plus haut/bas de la veille.
3. **Cassure de structure H1** contre la tendance : clôture sous le dernier creux (au-dessus du dernier sommet) formé dans les 12 bougies H1 qui précèdent l'extrême atteint après le sweep, la cassure datant de 2 bougies H1 au plus.
4. **Essoufflement** : les 2 signes (`REVERSAL_MIN_SIGNS`, défaut 2 sur 2) : bougies qui rétrécissent (corps moyen des 3 dernières < 60 % du corps de référence, soit 0,4 unité), mèche de rejet (≥ 2 fois le corps).
- **Entrée** au retest du dernier creux (sommet) H1 cassé, **stop** au-delà de l'extrême du sweep plus 0,2 unité H1, risque maximal 3 unités H1, retest à 1 unité H1 du prix au plus. **Objectifs** sur la liquidité opposée intacte (comme S2 : TP1 = première liquidité entre 1 R et 6 R, sinon TP1 = 3 R, +1 R, +2 R), ratio ≥ 3 sur TP1. Alerte toujours marquée **contre la tendance H4** : taille réduite conseillée.

**Garde-fous communs** : sessions (Londres/New York/London Close, marchés à séance), âge du déclencheur ≤ 20 minutes, obstacles H4/H1 du cadre intraday (figures : obstacles H4 et veille seulement ; retournement : H4 et H1).

### 6.4 S4 CRT (Candle Range Theory)

| Étape | Règle |
|---|---|
| C1 | Dernière bougie **D1 ou H4** clôturée avant C2. Taille de son range entre 0,8 et 3,5 unités du timeframe de référence. |
| C2 | Bougie clôturée qui dépasse **un seul** côté de C1 d'au moins 0,1 unité et **clôture dans le range de C1**. Une bougie englobante (les deux côtés) ou une clôture hors range n'est pas un CRT. |
| C3 | Bougie en formation : la livraison se fait pendant C3, la confirmation doit arriver avant sa clôture. |
| Entrée | Première clôture M15 au-delà du dernier swing M15 (CHoCH avec déplacement ≥ 1,2 fois), **après la clôture de C2**, avec ce swing à 16 bougies M15 (48 en M5) au plus avant l'extrême de C2 et une cassure parmi les 2 dernières bougies. Si le prix reprend l'extrême de C2, le sweep est annulé. Ordre limite sur le bloc d'ordre ou le FVG M15 du mouvement (jusqu'à 1,5 unité M15 du prix) ; sinon marché si le prix n'a pas fui de plus de 0,75 unité M15. |
| Stop | Au-delà de l'extrême de C2, plus 0,15 unité M15 (avec `S4_STOP_MODE=ob` : à l'autre extrémité du bloc d'ordre ou du FVG d'entrée, même marge). |
| Objectifs | TP1 milieu de C1, TP2 bord opposé de C1, TP3 bord opposé + 50 % du range. **Ratio ≥ 3 jusqu'au milieu de C1.** |
| Garde-fous | Âge du déclencheur ≤ 20 min, **pas contre une tendance H4 ou D1 claire**, obstacles H4/H1 du cadre intraday. Aucune limite de session. |

Au plus un signal par bougie de référence (D1 et H4). L'invalidation est l'extrême de C2.

### 6.5 Cadre intraday et obstacles (actif par défaut, `INTRADAY=0` pour le désactiver)

- **Obstacles H4/H1** : creux et sommets (60 bougies H4, 120 H1 ; fractale de 2 en H4, 3 en H1), zones d'offre/demande (bloc d'ordre et FVG non invalidés par une clôture), plus haut/bas de la veille.
- **Objectif avant le prochain obstacle** (S1, S2, S3, S4) : si un obstacle opposé est devant TP1 à moins de 1 R de l'entrée (ou à moins de 0,8 R une fois le tampon retiré), le signal est écarté ; sinon les objectifs au-delà sont ramenés à 0,1 unité H1 avant l'obstacle et le ratio minimal est recontrôlé (S1 et S2 sur TP1, retournement de S3 sur TP1, figures de S3 sur TP3, S4 sur TP1).
- **Entrée sur réaction à un niveau** : S1 exige que l'entrée soit à moins de 0,5 unité H1 d'un niveau ou d'une zone H4/H1 du bon côté (`S1_OBST_ENTRY`) ; S2 l'exige seulement si `S2_HTF_ZONE=0` ; S3 et S4 non.
- **Fin de séance** (or et forex) : tout trade est clôturé au plus tard à **16h45 New York** ou **10 heures** après l'alerte, **même après TP1** (sauf `INTRADAY_RUNNERS=1`) ; un ordre en attente n'est jamais conservé au-delà. Cryptos et indices : aucune fin de séance (sauf `CRYPTO_INTRADAY=1` pour les cryptos).
- `INTRADAY=0` restaure l'ancien comportement : cascades S1 à 3 niveaux, confirmation de S2 en M5, pas de fin de séance, pas de filtre d'obstacles.

### 6.6 Ordres limites

Par défaut, chaque alerte est un **ordre limite** posé au retest d'une zone ; si la zone n'est pas exploitable (hors de l'intervalle stop-prix), l'alerte passe au marché. Validité (plafonnée à la fin de séance sur or et forex) :

| Stratégie | Zone d'entrée | Validité maximale |
|---|---|---|
| S1 Pullback | milieu du FVG, sinon bord proche du bloc d'ordre (M15) | 24 h (en pratique : fin de séance) |
| S2 Sweep + CHoCH | bloc d'ordre M15 (sinon FVG) | 1 h |
| S3 figure | bloc d'ordre (sinon FVG) du déplacement de cassure | 3 h |
| S3 retournement | dernier creux (sommet) H1 cassé | 2 h |
| S4 CRT | bloc d'ordre M15 (sinon FVG) | 1 h |
| S9 Market Profiles | niveau de CHoCH ou de cassure à retester | 1 h |

Le bot signale « Ordre limite touché », « Ordre annulé » (TP1 atteint sans fill, bougie clôturée au-delà du stop, week-end) ou « Ordre expiré » pour que tu annules chez ton courtier. `/bilan` affiche le taux de remplissage. **Contrepartie** : meilleur prix et stop plus court, mais certains trades ne sont jamais remplis, et ce sont souvent les meilleurs. Compare avec `--set gold.ENTRY_MODE=market,limit`.

### 6.7 Confirmation en M15 ou en M5

| Stratégie | Variable | Ce qui passe en M5 |
|---|---|---|
| S1 | `S1_CONFIRM_TF` | Entrée de la cascade (`H4 > H1 > M5`) ; seule la valeur `M5` agit |
| S2 | `S2_CONFIRM_TF` | CHoCH, bloc d'ordre, FVG (le sweep reste détecté en M15) ; défaut M15 en intraday, M5 sinon |
| S3 | `S3_CONFIRM_TF` | Confirmation de la cassure des figures, entrée du retournement |
| S4 | `S4_CONFIRM_TF` | Cassure de structure après C2 et zone d'entrée |
| S9 | `S9_TF` | Timeframe d'analyse et d'entrée (`M5`, `M15` ou `H1`) |

Le cadre H4/H1 ne change pas ; les durées en bougies M15 sont converties (x 3). M5 donne une entrée plus précoce et un stop plus serré, mais plus de bruit et un spread plus lourd : compare au backtest avant de t'y fier (`--only S2 --split 0.6 --set strategies.S2_CONFIRM_TF=M15,M5`).

### 6.8 Confluence et cohérence entre stratégies

- **Un seul trade par actif et par sens**, toutes stratégies confondues (`ONE_TRADE_PER_SIDE`) : au même scan, la première stratégie dans l'ordre S1, S2, S3, S4, S9 passe ; les autres sont comptées comme doublons.
- **Confluence** (information, ne filtre rien) : quand une autre stratégie est d'accord sur le même actif et le même sens, trouvée au même scan ou alertée depuis moins de `CONFLUENCE_MIN` minutes (60), l'alerte l'indique. Avec `ONE_TRADE_PER_SIDE`, seule la confluence du même scan sort, car une alerte ultérieure est bloquée comme doublon. L'alerte déjà envoyée n'est jamais modifiée. Chaque trade enregistre `confluence` (ex. `S2+S3`) pour comparer au backtest (`--set gold.CONFLUENCE_MIN=0,30,60,120`).
- **Tendance dans chaque alerte** : tendance D1 et H4 avec âge, ✅ dans le sens du trade, ⚠️ à contre-sens. Ce n'est pas un filtre en soi (seuls S1, S2 pour son biais, S3 pour les continuations et S4 ont leurs propres règles de contexte).

### 6.9 S9 Market Profiles (`profiles.py`)

**Idée** : un marché alterne range, manipulation (sweep d'une borne ou d'un niveau clé) et expansion. La stratégie repère la manipulation, attend la cassure de structure (CHoCH) puis entre au **retest** du niveau cassé. Les 5 setups sont des règles de **prix pur** (pivots, sweeps, clôtures) : aucune unité de mesure ni indicateur dans la détection ; seules les marges du bot (stop, distances) utilisent l'unité de prix.

**Données** : bougies clôturées du timeframe `S9_TF` (M15 par défaut), 160 dernières. **Pivots** : fractales de 3 bougies de chaque côté. **Range** : parmi les 6 derniers pivots, au moins 2 hauts et 2 bas à moins de 25 % de la hauteur des bornes, aucune clôture hors bornes. **Niveaux clés** (prix) : plus haut/bas de la veille, extrêmes de la plage asiatique, equal highs/lows H1, 6 derniers sommets et 6 derniers creux H4 (fractale de 2), fusionnés à moins de 0,1 unité H1.

| Setup | Règle |
|---|---|
| **A Range + Sweep** | Range, puis mèche au-delà d'une borne (une des 10 dernières bougies) avec clôture revenue dedans. CHoCH = clôture au-delà du dernier pivot opposé avant le sweep. Entrée au retest de ce niveau, stop au sweep. |
| **B Break & Retest** | Au moins 8 clôtures d'un même côté d'un niveau (clé ou borne de range), puis clôture de l'autre côté (parmi les 12 dernières bougies) sans reperdre le niveau. Ordre limite sur le niveau tant que le retest n'a pas eu lieu ; au marché s'il a eu lieu. Stop au plus bas (haut) depuis la cassure. |
| **C Reversal sur niveau clé** | Structure baissière (hauts et bas descendants), sweep d'un niveau clé par le bas (6 dernières bougies), CHoCH haussier sur le dernier haut. Contre-tendance. Miroir pour la vente. |
| **D Manipulation sur support** | Expansion d'au moins 1,5 fois la hauteur du range, range **au-dessus** du niveau clé, faux breakdown (mèche sous le niveau, clôture au-dessus), puis CHoCH. Miroir pour la vente. |
| **E Retracement + deep sweep** | Jambe d'expansion, retracement de 25 à 80 %, puis sweep **profond** du niveau clé (la mèche dépasse d'au moins 15 % de la jambe), puis CHoCH. Contre-tendance. |

**Ordre et objectifs tels qu'intégrés au bot**
- **Entrée** : ordre limite au niveau de retest (CHoCH ou cassure) ; au marché pour un break & retest déjà retesté. Retest à plus de 1,5 unité du prix, ou prix déjà repassé du mauvais côté du niveau : signal écarté ; au marché, poursuite de plus de 0,75 unité depuis le déclencheur : écarté.
- **Stop** : extrême du sweep (ou de la cassure) plus une marge de 0,15 unité (`S9_SL_BUF_ATR`), élargi à 0,5 unité du timeframe si plus proche ; plafond de risque 2 unités H1 (`S9_RISK_CAP_H1`).
- **TP1** : première liquidité opposée (pivot) ; sans liquidité, TP1 au ratio minimal (3) du risque réel, marge comprise. **TP2 et TP3** : liquidité suivante à plus de 0,5 R au-delà de l'objectif précédent (et à 6 R au plus de TP1), sinon l'objectif précédent + 1 R. **Ratio ≥ 3 sur TP1** (`S9_MIN_RR`).
- **Garde-fous du bot** : déclencheur de moins de 20 minutes (`S9_MAX_AGE_MIN`) ; session Londres, New York ou London Close sur les marchés à séance (`S9_SESSION_FILTER`) ; obstacles H4/H1 du cadre intraday (§ 6.5, ratio contrôlé sur TP1) ; validité de l'ordre 1 h, plafonnée à la fin de séance. **Aucun filtre de contexte H4/D1** : les setups C et E sont contre-tendance par construction (l'alerte affiche la tendance D1/H4). Invalidation avant TP1 : le stop sans marge.
- **Fichier `profiles.py`** : la détection des setups est celle de ton fichier ; seules des métadonnées ont été ajoutées (index de la bougie de déclenchement, niveaux de range, de sweep et de CHoCH) pour l'âge du signal, la session et le graphique. Résultats identiques à ton fichier d'origine sur 1 500 séries aléatoires (setups B, C et E rencontrés) et sur un scénario A/B fabriqué ; je n'ai pas réussi à déclencher le setup D dans mes essais (il partage le code de confirmation du setup E).

### 6.10 Placement du stop : `sweep` ou `ob`

Par défaut (`sweep`), le stop de S1, S2 et S4 est placé au-delà de l'extrême du sweep. Avec `ob` (`STOP_MODE=ob`, ou `S1_STOP_MODE`, `S2_STOP_MODE`, `S4_STOP_MODE` stratégie par stratégie), il est placé **à l'autre extrémité de la zone d'entrée** : bas du bloc d'ordre pour un achat, haut pour une vente, avec la même marge de 0,15 unité. Sans zone d'entrée (S2 et S4), le stop reste celui du sweep. S3 place déjà son stop de figure de cette façon ; S9 n'utilise pas de bloc d'ordre.

- **Effet** : stop plus court, donc ratio plus élevé et moins de signaux écartés pour « stop trop large » ou « ratio sous 3 » ; mais plus de stops touchés par les mèches, et un spread plus lourd en R. Le plancher de risque de 0,5 unité du timeframe s'applique toujours, et il devient la vraie règle si le bloc d'ordre est plus petit.
- **Souvent identique pour S2 et S4** : quand le bloc d'ordre est la bougie même qui porte l'extrême du sweep, son autre extrémité coïncide avec le stop du sweep.
- **Objectifs et invalidation inchangés** : TP1 de S1 (extrême de l'impulsion) et de S4 (milieu de C1) ne bougent pas ; en S2 sans liquidité repérée, TP1 suit le risque (ratio identique).
- **À comparer en backtest** : `python backtest.py --sym frxXAUUSD --split 0.6 --set strategies.S2_STOP_MODE=sweep,ob`. Ne retiens `ob` que si l'espérance par trade est meilleure sur les deux périodes.

---

## 7. Alertes, heures et commandes

**Format** (`ALERT_FORMAT`, défaut `essentiel`) : cinq formats, `essentiel` (3 lignes), `minimal` (2 à 3 lignes), `compact`, `contexte`, `complet` (détail des conditions, invalidation, règles de gestion). Le graphique est joint à chaque alerte (`CHARTS=0` pour le retirer).

```
🔴 SELL LIMIT · XAUUSD M15 · Sweep + CHoCH · 14h35 Bénin
4012.50 · SL 4018.20 · TP 4001.30 / 3992.40 / 3980.10
Valable jusqu'à 16h30 Bénin · #12
```

L'âge du signal est indiqué (format `essentiel` : à partir de 3 minutes). Événements de suivi envoyés : ordre touché, annulé ou expiré, TP1, TP2, TP3, stop, retour à l'entrée après TP1, stop remonté touché après TP2, structure cassée, sortie au temps, fin de séance, fermeture avant le week-end.

**Commandes Telegram** (seul ton chat est écouté ; réponse au prochain scan, sous 5 minutes) :
- boutons **Pris / Ignoré** sous chaque alerte, ou `/pris N`, `/ignore N` ;
- `/r N X` : ton résultat réel du trade #N en R (ex. `/r 12 -0.8`) ;
- `/bilan` : bilan des 30 derniers jours ;
- `/tendance` : renvoie le récapitulatif de tendance (tous les jours, week-end compris) ;
- toute autre commande renvoie l'aide.

**Horaires clés** (heure de New York → Bénin ; US = heure d'été américaine) :

| Événement | New York | Bénin (été US) | Bénin (hiver US) |
|---|---|---|---|
| Récapitulatif de tendance (lun-ven) | 01h00 | 06h00 | 07h00 |
| Plage asiatique | 20h00-02h00 | 01h00-07h00 | 02h00-08h00 |
| Killzone de Londres | 02h00-05h00 | 07h00-10h00 | 08h00-11h00 |
| Killzone de New York | 07h00-10h00 | 12h00-15h00 | 13h00-16h00 |
| London Close | 10h00-12h00 | 15h00-17h00 | 16h00-18h00 |
| Fin de séance intraday | 16h45 | 21h45 | 22h45 |
| Rollover (plus d'alerte) | 16h55-17h15 | 21h55-22h15 | 22h55-23h15 |
| Ouverture des bougies D1 et H4 | 17h00 | 22h00 | 23h00 |
| Vendredi : plus d'alerte dès / clôture des trades dès | 15h30 / 16h30 | 20h30 / 21h30 | 21h30 / 22h30 |

---

## 8. Récapitulatifs et alerte de retournement

**Récapitulatif de tendance** : chaque jour ouvré à 01h00 New York (`RECAP_HEURE`, `RECAP_FUSEAU`), un message par classe (Or, Forex contre USD, Forex croisements, Cryptos) avec, par actif, la tendance D1, H4, H1 (🟢 haussière, 🔴 baissière, ⚪ pas de tendance claire) et son âge (naissante, établie, mûre ; ⚡ = cassure impulsive). Format `compact` par défaut (une ligne par actif), `RECAP_FORMAT=complet` pour trois lignes avec durée et invalidation. Il peut partir jusqu'à 6 heures après l'heure prévue (retard du cron), puis la journée est sautée ; les actifs sans données de moins de 4 heures sont listés « Marché fermé ». Pas de récapitulatif pour les indices synthétiques.

**Récapitulatif du soir des indices synthétiques** : tous les jours, 4 heures avant la clôture de la bougie daily de Deriv (00h GMT, soit 01h au Bénin ; `SYNTH_RECAP_HEURES`), un message par famille (Volatility, Volatility 1s) avec tendance, biais S2 et extrêmes de la bougie daily en cours.

**Alerte de retournement possible** (information) : si S3 n'est **pas** active (et `REVERSAL_ALERTS` ≠ 0), le même événement que le retournement de S3 est envoyé comme simple message, sans ordre ni suivi, un message par sweep. Quand S3 est active, il arrive uniquement sous forme d'ordre (pas de doublon). Un retournement signalé peut n'être qu'un repli : attendre la cassure du H4 pour confirmer.

---

## 9. Garde-fous d'exploitation

- **Fenêtres sans alerte** (or et forex) : rollover 16h55-17h15 New York ; samedi et dimanche jusqu'à 17h ; **dimanche 17h-18h** (ouverture de semaine) ; vendredi dès 15h30. Les cryptos et les indices ne sont soumis à aucune fenêtre.
- **Aucun filtre d'annonces économiques** : le calendrier (Forex Factory), les décisions FOMC intégrées, la fenêtre NFP et `news.json` ont été supprimés. Le bot peut donc alerter juste avant ou pendant une publication à fort impact ; les spreads et les gaps y sont plus larges (stop exécuté à l'ouverture en cas de gap).
- **Week-end** (forex et or) : trades ouverts clôturés dès le vendredi 16h30 New York, ordres en attente annulés (`WEEKEND_EXIT=0` désactive).
- **Santé du bot** : alerte si le scan reprend après plus de 30 minutes d'interruption, ou après 3 scans de suite sans aucune donnée Deriv ; message de retour quand les données reviennent. Seul `HEARTBEAT_URL` (cron externe supervisé) détecte une panne du cron lui-même.
- **Gaps** : si une bougie ouvre au-delà du stop, la clôture se fait à l'ouverture (perte possible supérieure à 1 R).

---

## 10. Suivi des trades (live et backtest)

Chaque trade est suivi sur les bougies de son timeframe de signal :
- **Ordre limite rempli** si le prix traverse le niveau d'au moins un **demi-spread** ; dans la bougie du fill, aucun objectif n'est compté (le stop, si).
- **Ordre annulé** si TP1 est atteint avant le fill, si une bougie clôture au-delà du stop, ou après sa validité.
- **TP1** : clôture de **50 %**, stop remonté à l'entrée. **TP2** : clôture de **25 %**, stop remonté à TP1. Les **25 %** restants visent TP3. Sans TP3 : 50 % à TP1 et le reste à TP2.
- **Avant TP1** : sortie si une bougie clôture au-delà du niveau d'invalidation (structure cassée) ; sortie au prix si TP1 n'est pas atteint après **150 bougies** du timeframe d'entrée.
- **Fin de séance** et **fermeture de week-end** : voir § 6.5 et § 9.
- Si stop et objectif sont touchés dans la même bougie, le stop est supposé touché en premier ; TP1 puis retour à l'entrée = break-even.

---

## 11. Bilans

- **`/bilan`** (30 jours) : total, par stratégie, par actif, trades pris/ignorés/non renseignés, **RR visé et R obtenu** par stratégie, résultat réel contre simulé (trades renseignés avec `/r`), et statistiques des ordres limites (placés, touchés, annulés, expirés, en attente).
- **RR visé** : ratio gain/risque pondéré par la gestion (50 % TP1, 25 % TP2, 25 % TP3), avec le ratio moyen de chaque objectif ; **R obtenu** : moyenne après spread ; taux d'atteinte de TP1, TP2, TP3 ; **capture** : part du RR visé réellement obtenue. Seul le R obtenu, sur assez de trades et deux périodes, compte.
- **Bilan hebdomadaire** automatique (tous les 7 jours) : total 7 jours (et 30 jours), une ligne par stratégie, par actif, résultats réels, trades actifs et alertes, « Validation : N trades sur ~100 pour juger » tant que le total est inférieur à 100, et les signaux écartés (objectif déjà atteint, horaire, doublons, risque).
- **Entonnoir de filtres** : le message de contrôle (`test = true`), le journal de chaque scan et le rapport du backtest comptent, étape par étape, les passages de scan retenus ou écartés (ce sont des passages, pas des setups distincts).

---

## 12. Backtest

Workflow **Backtest Or** (manuel) ou, en local : `python backtest.py --days 120 --split 0.6`. Il rejoue les **mêmes fonctions** que le bot (`gold.scan`, `guard.risk_check`, `tracker.advance`) sur de l'historique M5 de Deriv, avec toutes les unités de temps reconstruites depuis le M5 **sans regarder le futur**.

- **Sources** : `--source deriv` (défaut), `csv` (`--file`, colonnes `epoch,open,high,low,close`, un seul actif) ou `sim` (marche aléatoire : contrôle de bon sens, l'espérance doit être proche de zéro).
- **Actifs** : `--sym frxXAUUSD,frxEURUSD`, `all` (28 actifs), `forex`, ou une classe (`or`, `forex_session`, `forex_jpy`, `forex_calme`, `crypto`, `synth`). Le workflow accepte aussi `classes` : un job par classe, en parallèle, chacun avec son rapport Telegram, sans qu'un échec arrête les autres.
- **Options** : `--days` (120), `--only S2,S3`, `--spread-pct`, `--warmup-days` (**35** jours, ajoutés à `--days`), `--split 0.6` (entre 0,2 et 0,8), `--sym-strats`, `--no-intraday`, `--telegram`, `--set module.NOM=v1,v2` (répétable, grille de 30 combinaisons au plus ; modules `strategies`, `tracker`, `guard`, `gold`).
- **Réalisme** : spread retiré de chaque trade, stop exécuté à l'ouverture en cas de gap, trades forex/or clôturés le vendredi à 16h30 New York, le rollover appliqué. **Limites** : spread constant, pas de glissement, un fichier CSV = un actif ; comme le bot, le backtest ne filtre plus les annonces.
- **Rapport** : entonnoir, ordres limites, total, **intervalle de confiance à 95 %** de l'espérance par trade (rééchantillonnage de jours entiers) avec verdict prudent, avertissement sur les comparaisons multiples, détail par actif, stratégie, RR visé contre R obtenu, coût du spread, puis par classe, variante, sens, session, liquidité, alignement H4, zone d'entrée, confluence, tendance D1/H4, résultat final et période ; avec `--split`, stabilité entre les deux périodes.
- **Lecture** : sous quelques centaines de trades, un taux de gain n'est que du bruit. Ne retiens une stratégie que si l'espérance est positive sur les **deux périodes**, avec un intervalle de confiance qui exclut zéro, après ton vrai spread, et au moins 30 trades.

---

## 13. Ce qui a été vérifié, et ce qui ne l'a pas été

**Vérifié** : les 275 tests unitaires passent hors réseau (les scénarios de test remplacent l'unité de prix fixe par une unité calculée sur leurs bougies pour tester la logique des filtres ; l'unité de production a ses propres tests) (stratégies, suivi, garde-fous, messages, graphique, backtest) ; le code s'exécute de bout en bout sur des données simulées, et sur une marche aléatoire l'espérance est proche de zéro. Les valeurs de ce document ont été relevées dans le code.

**Non vérifié** : le comportement de S9 sur marché réel (setups A, B, C, D, E : seuls A, B, C et E ont été déclenchés dans des tests, sur données fabriquées ou aléatoires), le calibrage des unités de prix par actif (estimations de départ, à comparer à l'amplitude réelle des bougies de chaque actif), la connexion à l'API Deriv, l'envoi Telegram sur ton compte et surtout **la rentabilité sur marché réel**. Fais d'abord un run avec `test = true`, puis un backtest sur Deriv (deux périodes, spread réaliste), avant de suivre les alertes. Les suivis supposent un remplissage au prix du signal, sans glissement.
