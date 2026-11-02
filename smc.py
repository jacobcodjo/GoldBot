"""Primitives SMC communes à S1 (Pullback structure, ex-S5), S3 (Sweep + CHoCH) et aux zones d'entrée (bloc d'ordre, FVG).

Fonctions pures, sans état ni réseau : une bougie est un dict {epoch, open, high, low, close}. Elles ne portent aucune règle de
stratégie (seuils, sessions, filtres) : chaque stratégie garde ses réglages et appelle ces primitives. Un seul endroit définit donc
ce qu'est un déplacement, un sweep de mèche ou une cassure par clôture, au lieu d'une copie par stratégie.
"""


def body(c):
    """Corps d'une bougie."""
    return abs(c["close"] - c["open"])


def mean_body(cs):
    """Corps moyen d'une liste de bougies (sans plafond de longueur) ; 0 si la liste est vide."""
    return sum(body(c) for c in cs) / len(cs) if cs else 0.0


def is_displacement(c, avg, mult):
    """Déplacement : corps >= mult x corps moyen. Si le corps moyen est nul, tout corps passe."""
    return body(c) >= mult * avg


def wick_sweep(c, level, kind):
    """Sweep d'un niveau par la mèche : la bougie dépasse le niveau et clôture de l'autre côté.
    kind 'high' : mèche au-dessus d'un sommet, clôture dessous (vente) ; kind 'low' : mèche sous un creux, clôture dessus (achat)."""
    return (c["high"] > level and c["close"] < level) if kind == "high" else (c["low"] < level and c["close"] > level)


def close_beyond(c, level, up):
    """La bougie clôture au-delà du niveau : au-dessus si `up`, en dessous sinon."""
    return c["close"] > level if up else c["close"] < level


def fresh_break(c, prev, level, up):
    """Cassure par clôture : la bougie clôture au-delà du niveau alors que la précédente clôture ne l'était pas (inclus : sur le niveau)."""
    if up:
        return c["close"] > level and prev["close"] <= level
    return c["close"] < level and prev["close"] >= level


def mirror(cs):
    """Miroir des bougies (prix x -1) : les calculs sont écrits pour un achat, la vente passe par ce miroir."""
    return [{"epoch": c["epoch"], "open": -c["open"], "high": -c["low"], "low": -c["high"], "close": -c["close"]} for c in cs]
