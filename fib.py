"""Fibonacci : jambe de référence, profondeur d'un prix dans la jambe, zone nommée (voir STRATEGIES.md, « Fibonacci »).

Module autonome : aucune entrée/sortie réseau, aucune dépendance aux stratégies. Chaque stratégie s'en sert là où cela a un sens :
S1 a sa propre implémentation (retracement 50-79 % d'une impulsion), S2 l'utilise comme filtre de position (premium / discount),
S3 comme filtre de profondeur (continuation) et plafond d'objectif (retournement).
"""

GOLDEN_FROM = 0.5      # 50 % -> 61,8 % : « Golden Zone »
OTE_FROM = 0.618       # 61,8 % -> 79 % : « OTE »
ZONE_MAX = 0.79        # au-delà : extrême de la jambe


def swing_idx(cs, kind, n):
    """Index des swings confirmés (fractales) : plus haut/bas strict sur n bougies de chaque côté. `cs` : bougies clôturées."""
    out = []
    for i in range(n, len(cs) - n):
        v = cs[i][kind]
        around = [cs[j][kind] for j in range(i - n, i + n + 1) if j != i]
        if (kind == "high" and v > max(around)) or (kind == "low" and v < min(around)):
            out.append(i)
    return out


def dealing_range(cs, n=3, lookback=120):
    """(bas, haut) de la jambe de référence : plus bas des creux et plus haut des sommets CONFIRMÉS (fractales de n bougies)
    parmi les `lookback` dernières bougies clôturées. None si un côté manque ou si la jambe est nulle."""
    seg = cs[-lookback:]
    hs, ls = swing_idx(seg, "high", n), swing_idx(seg, "low", n)
    if not hs or not ls:
        return None
    hi = max(seg[i]["high"] for i in hs)
    lo = min(seg[i]["low"] for i in ls)
    return (lo, hi) if hi > lo else None


def retrace(d, price, lo, hi):
    """Profondeur de `price` dans la jambe [lo, hi], vue du sens d : 0 au bord haut pour un achat (bas pour une vente), 0,5 à
    l'équilibre, 1 au bord opposé. Au-delà de 0,5 on est du bon côté : discount pour un achat, premium pour une vente.
    Peut sortir de [0, 1] si le prix dépasse la jambe."""
    if hi <= lo:
        return None
    return (hi - price) / (hi - lo) if d == "BUY" else (price - lo) / (hi - lo)


def zone_name(r):
    """Nom de la zone de profondeur r (voir retrace) : « mauvais côté » sous 50 %, « Golden Zone », « OTE », « extrême »."""
    if r is None or r < GOLDEN_FROM:
        return "mauvais côté"
    if r < OTE_FROM:
        return "Golden Zone"
    if r <= ZONE_MAX:
        return "OTE"
    return "extrême"


def side_word(d):
    """« discount » pour un achat, « premium » pour une vente."""
    return "discount" if d == "BUY" else "premium"


def pullback_depth(origin, end, extreme):
    """Profondeur d'un repli, en espace miroir « baissier » : jambe qui descend de `origin` (haut) à `end` (bas), repli qui remonte
    jusqu'à `extreme`. 0 = pas de repli, 0,5 = la moitié de la jambe, 1 = jambe entièrement reprise. None si la jambe est nulle."""
    if origin <= end:
        return None
    return (extreme - end) / (origin - end)
