# Stratégies du bot (or, paires majeures, BTC et ETH)

Quatre stratégies indépendantes, évaluées à chaque scan (toutes les 5 minutes). Chacune a son nom dans les
alertes Telegram (le code S1 à S4 sert seulement aux réglages : variable `STRATEGIES`, option `--only`), son propre suivi et ses propres statistiques. Les noms entre parenthèses sont les
paramètres de `strategies.py` (modifiables, et testables avec `backtest.py --set`).

> **Important.** Aucune stratégie n'a un taux de réussite élevé garanti. Les valeurs ci-dessous sont des
> points de départ classiques, **pas des valeurs optimisées ni validées** sur l'or. Lance le backtest
> (`backtest.yml`) sur plusieurs mois avant de t'y fier, et vérifie sur deux périodes (`--split 0.6`).
> Ce document n'est pas un conseil financier.

## Actifs

L'or (`frxXAUUSD`), les 7 majeures (EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD) et deux cryptos
(`cryBTCUSD`, `cryETHUSD`). Les règles sont
identiques pour tous : seuils en ATR, heures de New York, D1/H4 à 17h. Les stratégies ont été conçues pour l'or ;
leur comportement sur chaque paire est à vérifier au backtest (`--sym all`), actif par actif. Les cryptos ont une volatilité et des spreads très différents de l'or : ne
les juge pas sur les résultats des autres actifs. Exposition : l'or
compte comme une position sur l'USD (acheter l'or = vendre l'USD), 2 trades au plus dans le même sens USD ;
BTC et ETH forment un groupe : 2 trades au plus dans le même sens.

**Cryptos** : marché 24h/24, 7j/7. Les heures de session (killzones de Sweep + CHoCH, heures favorables de
Mean Reversion) ne s'appliquent pas à elles, et les fenêtres de rollover, vendredi soir, dimanche et NFP non plus.
La plage asiatique (Asian Breakout) et les niveaux PDH/PDL gardent leur définition en heure de New York.

## Conventions communes

- **Heures** : heure de New York. **D1 et H4 ouvrent à 17h New York** (reconstruits depuis le H1).
- **Bougies clôturées** : toutes les conditions utilisent des bougies clôturées ; la bougie en formation ne
  sert qu'à connaître le prix actuel.
- **Déclenchement récent** : la bougie de déclenchement doit être l'une des 2 dernières clôturées (`FRESH`).
- **Tendance dans l'alerte** : chaque alerte indique la tendance D1 et H4 avec son âge (règles de `trend.py`,
  voir plus bas), ✅ dans le sens du trade, ⚠️ à contre-sens. Information seulement, jamais un filtre.
- **Zones d'entrée de Trend Pullback et Sweep + CHoCH** : 1) le **bloc d'ordre** (dernière bougie de sens opposé entre
  l'extrême du repli ou du sweep et la bougie de cassure) avec entrée à son **bord proche** (le haut pour un achat, le
  bas pour une vente ; `LIMIT_OB_FRACTION = 0`, 1 = bord lointain) ; 2) à défaut, le **FVG** non comblé créé par le
  déplacement (3 bougies, la bougie du milieu doit être un déplacement : corps >= 1,2 x le corps moyen) avec entrée
  à son **milieu** (`LIMIT_FVG_FRACTION = 0.5`) ; 3) à défaut, l'ordre reste au marché. Le type de zone (OB, FVG ou
  marché) est enregistré (`poi` dans le rapport du backtest).
- **Ordres limites** (défaut, `ENTRY_MODE=auto`) : l'entrée est un ordre limite au retest d'une zone propre à chaque
  stratégie, à condition que la zone soit entre le stop et le prix actuel, sinon l'ordre est au marché.
  L'ordre est **annulé** si TP1 est atteint avant l'entrée, si une bougie clôture au-delà du stop, si le marché ferme pour
  le week-end, ou après sa durée de validité (S1 2 h, S2 3 h, S3 1 h, S4 1 h 30 : `LIMIT_TTL`). Une zone à plus de
  1,5 x ATR du prix écarte le signal (`LIMIT_MAX_ATR`). Les ordres limites améliorent le prix d'entrée mais manquent
  les mouvements qui ne reviennent pas : compare les rendements **totaux** au backtest, pas seulement par trade.
  Le suivi ne considère l'ordre posé qu'à partir de la bougie suivant l'alerte.
- **Ordre au marché** (`ENTRY_MODE=market`, ou stratégie listée dans `ENTRY_MODES`) : au prix du scan. Si le prix a déjà fui de plus de 0,75 x ATR de la clôture
  de déclenchement (`CHASE_ATR`), le signal est écarté (« entrée tardive »).
- **Stop** : au-delà de l'extrême de la structure, plus une marge de 0,15 x ATR (`BUF_ATR`). Risque minimal
  0,5 x ATR du timeframe d'entrée (`MIN_RISK_ATR`) : si le stop est plus proche, il est éloigné jusque-là.
  Risque maximal : un plafond en ATR H1 propre à chaque stratégie, sinon le signal est rejeté.
- **Objectifs** (S1, S2, S3) : TP1 = 1 R, TP2 = 2 R, TP3 = 3 R (R = distance entrée-stop).
- **Gestion** (`tracker.py`) : 50 % clôturés à TP1 et stop à l'entrée ; 25 % à TP2 et stop à TP1 ; 25 % vers
  TP3. Sortie avant TP1 si une bougie clôture au-delà du niveau d'invalidation, ou après 150 bougies sans TP1.
  Si stop et cible sont touchés dans la même bougie, le stop est supposé touché en premier.
- **Signal tardif** : écarté si la clôture de la bougie de déclenchement date de plus de 20 minutes (`MAX_AGE_MIN`).
- **Volatilité** : signal écarté si l'ATR H1 est sous 0,5 x sa médiane des ~240 dernières bougies H1 (`VOL_MIN_RATIO`).
- **Week-end** (or et forex) : trades encore ouverts clôturés le vendredi à 16h30 New York ; pas d'alerte le week-end.
- **Gap** : si une bougie ouvre au-delà du stop, la sortie se fait à l'ouverture (perte possible supérieure à 1 R).
- **Spread** : retiré du résultat de chaque trade (en R), en direct comme au backtest.
- **Fenêtres sans alerte** : rollover 16h55-17h15, vendredi dès 15h30, ouverture de dimanche 17h-18h, NFP,
  FOMC, annonces à fort impact de la devise de l'actif (USD pour l'or ; les deux devises pour une paire),
  15 min avant et 45 min après (90 min après une décision de taux).
- **Risque** : 6 trades ouverts au plus, exposition USD nette de 2 trades au plus dans le même sens, une seule
  position par actif, stratégie et sens, plus d'alertes après -3 R sur la journée (17h NY à 17h NY).

---

## Trend Pullback (code S1) · H4 > H1 > M15

**Idée** : trader dans le sens de la tendance H4, en entrant à la fin d'un repli de 50 à 85 % de la dernière
jambe impulsive H1, quand le M15 confirme la reprise.

**1. Tendance H4** (bougies H4 clôturées)
- Achat : EMA 50 > EMA 200 (`S1_EMA_FAST/SLOW`), dernière clôture > EMA 200, ADX(14) ≥ 18 (`S1_ADX_MIN`),
  et le dernier creux H4 est **plus haut** que le précédent (fractale de 2 bougies, `S1_SWING_H4`).
- Vente : l'inverse (EMA 50 < EMA 200, clôture < EMA 200, ADX ≥ 18, dernier sommet plus bas).
- Un seul creux (sommet) plus haut (bas) suffit, volontairement : exiger trois swings consécutifs détecte la
  tendance trop tard.

**2. Jambe impulsive H1**
- Sommet de référence (achat) : dernier plus haut H1 confirmé (fractale de 3 bougies, `S1_SWING_H1`), vieux de
  48 bougies H1 au plus et **pas dépassé** depuis (sinon on attend la confirmation du nouveau sommet).
- Base de la jambe : plus bas des 24 H1 qui précèdent le sommet (`S1_LEG_BARS`).
- Taille de la jambe : entre 1,5 et 5 x ATR H1 (`S1_LEG_MIN_ATR`, `S1_LEG_MAX_ATR`).

**3. Repli**
- Extrême du repli : plus bas M15 depuis la clôture de la bougie H1 du sommet.
- Le repli doit atteindre **50 %** de la jambe et ne pas dépasser **85 %** (`S1_FIB_MIN/MAX`). La zone
  50-79 % est dessinée sur le graphique.

**4. Déclencheur M15**
- Niveau : dernier sommet M15 (fractale de 2) formé pendant le repli, avant son extrême.
- Une bougie M15 **clôture au-dessus** de ce niveau (sous le dernier creux pour une vente), avec un corps
  d'au moins 1,2 x le corps moyen (`DISP_MULT`).

**Entrée** : ordre **limite** sur la zone du déplacement (bloc d'ordre M15 en priorité, sinon FVG M15 ; règles de
zone plus bas). **Stop** : sous l'extrême du repli (+ marge). **Plafond de risque** : 1,5 x ATR H1.
**Invalidation** : clôture M15 sous l'extrême du repli.

---

## Asian Breakout (code S2) · M15

**Idée** : l'or sort souvent de la plage calme de l'Asie à l'ouverture de Londres. On trade la **première**
cassure propre, dans le sens de l'EMA 50 du H4.

**1. Plage asiatique** : de 20h00 à 02h00 New York, sur les bougies M15 (au moins 20 bougies présentes).
- Taille valable : entre 0,4 et 2 x ATR H1 (`S2_RANGE_MIN_ATR`, `S2_RANGE_MAX_ATR`).

**2. Fenêtre** : de 02h00 à 07h00 New York (`S2_WINDOW`).

**3. Cassure** : la **première** bougie M15 après 02h00 qui clôture hors de la plage.
- Elle doit être récente (2 dernières bougies clôturées).
- Corps d'au moins 1,2 x le corps moyen, et clôture dans les 30 % extrêmes de son amplitude (`S2_CLOSE_STRENGTH`).
- Filtre : achat seulement si le dernier H4 clôturé est au-dessus de son EMA 50, vente s'il est dessous
  (`S2_H4_FILTER`).

**Entrée** : ordre **limite** sur le bord de plage cassé (retest). **Stop** : de l'autre côté de la plage (+ marge).
**Plafond de risque** : 2 x ATR H1.
Comme le stop est de l'autre côté de la plage, 1 R = la hauteur de la plage : TP1 projette 1 fois la plage,
TP2 deux fois, TP3 trois fois. Pas de niveau d'invalidation séparé (le stop fait office).

---

## Sweep + CHoCH (code S3) · M15 > M5

**Idée** : le prix balaie un niveau où s'accumulent des stops, puis casse sa structure en sens inverse. On
entre contre le balayage.

**1. Niveaux de liquidité**
- PDH / PDL : plus haut / plus bas de la veille (journée 17h-17h New York).
- Asie H / Asie B : extrêmes de la plage asiatique (dès 02h00).
- EQH / EQL : deux swings H1 (fractale de 2) à moins de 0,15 x ATR H1 l'un de l'autre, parmi les 8 derniers
  (`S3_EQ_TOL_ATR`).

**2. Sweep M15** (dans les 8 dernières bougies M15, `S3_SWEEP_BARS`)
- Une bougie dont la mèche dépasse le niveau mais qui **clôture de l'autre côté** (au-dessus du niveau pour un
  balayage de plus bas, donc achat). Si une bougie M15 ultérieure clôture au-delà du niveau, c'est une vraie
  cassure : le setup est annulé.

**3. CHoCH M5**
- Extrême du sweep : plus haut (vente) ou plus bas (achat) atteint en M5 depuis la bougie de sweep.
- Pivot : dernier creux (sommet) M5 (fractale de 2) formé juste avant cet extrême, à 36 bougies M5 au plus.
- Une bougie M5 **clôture sous** le pivot (au-dessus pour un achat), avec un corps d'au moins 1,2 x le corps
  moyen, et c'est l'une des 2 dernières clôturées.

**4. Killzone** de la bougie de cassure : Londres 02h-05h, New York 07h-10h ou London Close 10h-12h
(`S3_SESSIONS`). Hors de ces heures, pas de signal.

**Entrée** : ordre **limite** sur la zone du CHoCH (bloc d'ordre M5 en priorité, sinon FVG M5 ; règles de zone plus bas). **Stop** : au-delà de l'extrême du sweep (+ marge, calculée sur l'ATR M15).
**Plafond de risque** : 1,5 x ATR H1. **Invalidation** : clôture M5 au-delà de l'extrême du sweep.
**Information affichée** : la liquidité opposée la plus proche à au moins 1 R, et si le trade est aligné ou
contre l'EMA 50 du H4. Ce second point n'est pas un filtre : il est enregistré pour que le backtest compare
les deux cas (`h4 aligné` / `h4 contre`).

---

## Mean Reversion (code S4) · H1 > M15

**Idée** : quand l'or oscille sans direction, un rejet net des bandes de Bollinger ramène le prix vers la
moyenne. C'est la stratégie la plus risquée si une tendance démarre : le régime est donc filtré strictement.

**1. Régime H1 (marché sans tendance)**
- ADX(14) du H1 < 20 (`S4_ADX_MAX`).
- EMA 50 du H1 quasi plate : variation sur 12 bougies < 0,6 x ATR H1 (`S4_FLAT_ATR`).

**2. Heures** : 20h-02h ou 11h-15h New York (`S4_HOURS`). Pas d'entrée aux ouvertures de Londres et de New York.

**3. Bougie de rejet M15** (l'une des 2 dernières clôturées)
- Achat : la mèche passe sous la bande de Bollinger basse (20, 2), la bougie **clôture dans les bandes**, elle
  est haussière, et le RSI(14) a été ≤ 30 sur cette bougie ou la précédente.
- Vente : l'inverse (bande haute, bougie baissière, RSI ≥ 70).

**Entrée** : ordre **limite** sur la bande de Bollinger rejetée. **Stop** : au-delà de la mèche de rejet + 0,3 x ATR M15
(`S4_BUF_ATR`).
**Objectifs** : TP1 = moyenne mobile 20 de Bollinger, TP2 = bande opposée, **pas de TP3** (50 % à TP1, le reste
à TP2). **Rejet du signal** si le ratio vers TP1 est < 0,8 ou vers TP2 < 1,5, ou si le risque dépasse 1 x ATR H1.
**Invalidation** : clôture M15 au-delà de la mèche de rejet.

---

## Récapitulatif de tendance (information, hors stratégies)

Message quotidien (lundi au vendredi, 01h00 New York par défaut, réglable) : tendance D1 / H4 / H1 de chaque actif, avec son âge (naissante 1 jambe,
établie 2-3, mûre 4 et plus). Règles de `trend.py` (fractales de 2 bougies, 1 en D1) : dernier sommet et dernier creux plus hauts (plus bas pour une
baisse), structure intacte, sommet précédent cassé par une clôture. Il est indépendant des filtres de tendance de
Trend Pullback (EMA 50/200 du H4) : les deux lectures peuvent différer.

## Ce que le bot ne fait pas

- Il ne passe aucun ordre : il envoie des alertes et suit leur résultat théorique en R.
- Il ne prédit rien : chaque signal est un scénario, pas une certitude.
- Le suivi suppose un remplissage au prix du signal, sans glissement. Le backtest applique un spread constant.
