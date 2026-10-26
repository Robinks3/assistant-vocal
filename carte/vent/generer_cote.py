"""Génère le trait de côte et la terre de la carte du vent mesuré, depuis des données ouvertes en GeoJSON.

Le fichier source est fourni par l'utilisateur et n'est jamais téléchargé ici. Il contient des lignes (LineString,
MultiLineString) ou des contours (Polygon, MultiPolygon) en longitude/latitude WGS84. Un export OpenStreetMap
(natural=coastline, par exemple via Overpass turbo puis « exporter en GeoJSON »), un découpage IGN ou Natural Earth
convient. Les lignes dont les extrémités se touchent sont jointes. Les contours fermés deviennent des îles.

Les deux fichiers produits sont des chemins SVG en absolu (M x,y L x,y ... Z) dans le repère de la carte,
lus par CheminSvg.kt :
- le trait de côte (clé vent.carte.cote) : les lignes de côte, plus les îles ;
- la terre (clé vent.carte.terre) : la terre refermée le long du cadre, plus les îles.

Le cadre (vent.cadre, [lat_min, lat_max, lon_min, lon_max]) et la taille de la carte (vent.carte.largeur et
hauteur) sont lus dans maison.json, sauf si on les passe en argument. Les chemins de sortie sont ceux de
vent.carte.cote et vent.carte.terre, sous genere/android/ du dossier de configuration (ASSISTANT_VOCAL_CONFIG,
sinon config/ à la racine du dépôt).

Les données sont tracées jusqu'à une marge hors cadre (60 pixels par défaut), pour que la côte ne s'arrête pas au
bord de la carte. Le résultat ne dépend que de l'entrée et des paramètres : deux exécutions donnent les mêmes octets.

Usage :
    python carte/vent/generer_cote.py cote.geojson
    python carte/vent/generer_cote.py cote.geojson --cadre 43.2 43.32 5.22 5.47 --taille 640 423 --sortie /tmp/carte
Voir docs/CONFIGURER.md, section « Régénérer la côte et le plan 3D ».
"""
import argparse
import json
import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
MARGE_DEFAUT = 60


class ErreurCote(Exception):
    """Données ou paramètres inutilisables, dit en une phrase à l'utilisateur."""


# ------------------------------------------------------------ lecture du GeoJSON
def _coords_valides(pts):
    out = []
    for p in pts:
        if (not isinstance(p, (list, tuple)) or len(p) < 2 or isinstance(p[0], bool) or isinstance(p[1], bool)
                or not isinstance(p[0], (int, float)) or not isinstance(p[1], (int, float))):
            raise ErreurCote(f"point GeoJSON illisible : {p!r} (attendu [longitude, latitude])")
        out.append((float(p[0]), float(p[1])))
    return out


def _geometries(objet):
    """Géométries (dict) d'un objet GeoJSON : collection d'éléments, élément ou géométrie seule."""
    if not isinstance(objet, dict):
        raise ErreurCote("le fichier n'est pas un objet GeoJSON")
    kind = objet.get("type")
    if kind == "FeatureCollection":
        for f in objet.get("features") or []:
            yield from _geometries(f)
    elif kind == "Feature":
        if objet.get("geometry"):
            yield from _geometries(objet["geometry"])
    elif kind == "GeometryCollection":
        for g in objet.get("geometries") or []:
            yield from _geometries(g)
    elif kind in ("LineString", "MultiLineString", "Polygon", "MultiPolygon"):
        yield objet


def lire_geojson(objet):
    """(lignes, anneaux) en longitude/latitude : lignes ouvertes ou fermées à joindre, anneaux extérieurs des
    polygones. Les trous des polygones sont ignorés."""
    lignes, anneaux = [], []
    for g in _geometries(objet):
        kind, c = g["type"], g.get("coordinates") or []
        if kind == "LineString":
            lignes.append(_coords_valides(c))
        elif kind == "MultiLineString":
            lignes.extend(_coords_valides(ligne) for ligne in c)
        elif kind == "Polygon":
            if c:
                anneaux.append(_coords_valides(c[0]))
        else:
            anneaux.extend(_coords_valides(poly[0]) for poly in c if poly)
    if not lignes and not anneaux:
        raise ErreurCote("aucune ligne ni aucun contour dans le fichier GeoJSON")
    return lignes, anneaux


def joindre(lignes):
    """Joint les lignes qui se touchent par une extrémité (mêmes longitude et latitude), dans l'ordre d'entrée.
    Renvoie (lignes_ouvertes, anneaux_fermes)."""
    restantes = [list(ligne) for ligne in lignes if len(ligne) >= 2]
    ouvertes, fermes = [], []
    while restantes:
        cour = restantes.pop(0)
        etendu = True
        while etendu and cour[0] != cour[-1]:
            etendu = False
            for i, autre in enumerate(restantes):
                if autre[0] == cour[-1]:
                    cour = cour + autre[1:]
                elif autre[-1] == cour[-1]:
                    cour = cour + autre[::-1][1:]
                elif autre[-1] == cour[0]:
                    cour = autre + cour[1:]
                elif autre[0] == cour[0]:
                    cour = autre[::-1] + cour[1:]
                else:
                    continue
                restantes.pop(i)
                etendu = True
                break
        (fermes if len(cour) >= 4 and cour[0] == cour[-1] else ouvertes).append(cour)
    return ouvertes, fermes


# ------------------------------------------------------------ projection et découpe
def projeteur(cadre, taille):
    """Fonction (lon, lat) vers (x, y) en pixels : la même projection linéaire que l'appli (y vers le bas)."""
    lat_min, lat_max, lon_min, lon_max = cadre
    largeur, hauteur = taille
    if not (lat_max > lat_min and lon_max > lon_min and largeur > 0 and hauteur > 0):
        raise ErreurCote("cadre ou taille de carte incohérent (lat_max > lat_min, lon_max > lon_min, taille > 0)")
    return lambda lon, lat: ((lon - lon_min) / (lon_max - lon_min) * largeur,
                             (lat_max - lat) / (lat_max - lat_min) * hauteur)


def _clipper(p, q, boite):
    """Segment p-q découpé dans la boîte (x0, y0, x1, y1), ou None. Les coordonnées coupées sont posées
    exactement sur le bord."""
    x0, y0, x1, y1 = boite
    (px, py), (qx, qy) = p, q
    dx, dy = qx - px, qy - py
    t0, t1 = 0.0, 1.0
    cote_entree = cote_sortie = None
    for pente, dist, cote in ((-dx, px - x0, "x0"), (dx, x1 - px, "x1"), (-dy, py - y0, "y0"), (dy, y1 - py, "y1")):
        if pente == 0:
            if dist < 0:
                return None
            continue
        t = dist / pente
        if pente < 0:
            if t > t1:
                return None
            if t > t0:
                t0, cote_entree = t, cote
        else:
            if t < t0:
                return None
            if t < t1:
                t1, cote_sortie = t, cote

    def point(t, cote):
        x, y = px + t * dx, py + t * dy
        if cote == "x0":
            x = x0
        elif cote == "x1":
            x = x1
        elif cote == "y0":
            y = y0
        elif cote == "y1":
            y = y1
        return (x, y)

    a = point(t0, cote_entree) if cote_entree else p
    b = point(t1, cote_sortie) if cote_sortie else q
    return a, b


def decouper_ligne(pts, boite):
    """Morceaux de la polyligne [pts] (x, y) qui sont dans la boîte, chacun d'au moins deux points."""
    morceaux, cour = [], None
    for p, q in zip(pts, pts[1:]):
        seg = _clipper(p, q, boite)
        if seg is None:
            if cour is not None and len(cour) >= 2:
                morceaux.append(cour)
            cour = None
            continue
        a, b = seg
        if cour is None or cour[-1] != a:
            if cour is not None and len(cour) >= 2:
                morceaux.append(cour)
            cour = [a]
        cour.append(b)
        if b != q:
            morceaux.append(cour)
            cour = None
    if cour is not None and len(cour) >= 2:
        morceaux.append(cour)
    return morceaux


def decouper_anneau(pts, boite):
    """Contour fermé découpé dans la boîte (Sutherland-Hodgman). Liste vide si rien n'est dans la boîte."""
    x0, y0, x1, y1 = boite
    sortie = pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else list(pts)
    for dedans, coupe in (
            (lambda p: p[0] >= x0, lambda p, q: (x0, p[1] + (q[1] - p[1]) * (x0 - p[0]) / (q[0] - p[0]))),
            (lambda p: p[0] <= x1, lambda p, q: (x1, p[1] + (q[1] - p[1]) * (x1 - p[0]) / (q[0] - p[0]))),
            (lambda p: p[1] >= y0, lambda p, q: (p[0] + (q[0] - p[0]) * (y0 - p[1]) / (q[1] - p[1]), y0)),
            (lambda p: p[1] <= y1, lambda p, q: (p[0] + (q[0] - p[0]) * (y1 - p[1]) / (q[1] - p[1]), y1))):
        entree, sortie = sortie, []
        for i, p in enumerate(entree):
            q = entree[i - 1]
            if dedans(p):
                if not dedans(q):
                    sortie.append(coupe(q, p))
                sortie.append(p)
            elif dedans(q):
                sortie.append(coupe(q, p))
        if not sortie:
            return []
    return sortie if len(sortie) >= 3 else []


# ------------------------------------------------------------ fermeture de la terre le long du bord
def _abscisse(p, boite):
    """Position du point [p] du bord, dans le sens des aiguilles d'une montre à l'écran (y vers le bas), ou None
    s'il n'est pas sur le bord."""
    x0, y0, x1, y1 = boite
    larg, haut = x1 - x0, y1 - y0
    x, y = p
    if y == y0 and x0 <= x <= x1:
        return x - x0
    if x == x1 and y0 <= y <= y1:
        return larg + (y - y0)
    if y == y1 and x0 <= x <= x1:
        return larg + haut + (x1 - x)
    if x == x0 and y0 <= y <= y1:
        return 2 * larg + haut + (y1 - y)
    return None


def _coins(boite):
    x0, y0, x1, y1 = boite
    larg, haut = x1 - x0, y1 - y0
    return [(0.0, (x0, y0)), (larg, (x1, y0)), (larg + haut, (x1, y1)), (2 * larg + haut, (x0, y1))]


def fermer_terre(morceaux, boite, terre_a_gauche=True):
    """Polygones de terre formés par les morceaux de côte et le bord de la boîte. La terre est à gauche du sens
    de parcours (convention OpenStreetMap : l'eau est à droite), ou à droite si [terre_a_gauche] est faux.
    Un morceau qui ne touche pas le bord par ses deux extrémités n'enferme rien et est ignoré ici."""
    perimetre = 2 * ((boite[2] - boite[0]) + (boite[3] - boite[1]))
    fermables = [m for m in morceaux
                 if _abscisse(m[0], boite) is not None and _abscisse(m[-1], boite) is not None]
    sens = -1 if terre_a_gauche else 1            # marche le long du bord : sens trigonométrique pour la gauche
    coins = _coins(boite)
    utilises, polygones = set(), []
    for i0 in range(len(fermables)):
        if i0 in utilises:
            continue
        poly, courant = [], i0
        while True:
            utilises.add(courant)
            m = fermables[courant]
            poly.extend(m)
            t_fin = _abscisse(m[-1], boite)
            # prochain début de morceau rencontré en marchant sur le bord depuis la fin
            meilleur = None
            for j, autre in enumerate(fermables):
                if j in utilises and j != i0:
                    continue
                dist = ((t_fin - _abscisse(autre[0], boite)) if sens < 0
                        else (_abscisse(autre[0], boite) - t_fin)) % perimetre
                if meilleur is None or dist < meilleur[0]:
                    meilleur = (dist, j)
            dist, j = meilleur
            passes = sorted(((((t_fin - tc) if sens < 0 else (tc - t_fin)) % perimetre), pc)
                            for tc, pc in coins)
            poly.extend(pc for d, pc in passes if 0 < d < dist)
            if j == i0:
                break
            courant = j
        polygones.append(poly)
    return polygones


# ------------------------------------------------------------ sortie
def simplifier(pts, tolerance):
    """Douglas-Peucker itératif, extrémités gardées. Sans effet quand [tolerance] vaut 0."""
    if tolerance <= 0 or len(pts) < 3:
        return list(pts)
    garde = [False] * len(pts)
    garde[0] = garde[-1] = True
    pile = [(0, len(pts) - 1)]
    while pile:
        a, b = pile.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        long = math.hypot(bx - ax, by - ay)
        pire, imax = -1.0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            d = (math.hypot(px - ax, py - ay) if long == 0
                 else abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / long)
            if d > pire:
                pire, imax = d, i
        if pire > tolerance and imax is not None:
            garde[imax] = True
            pile += [(a, imax), (imax, b)]
    return [p for p, g in zip(pts, garde) if g]


def _entier(v):
    return int(math.floor(v + 0.5))


def chemin_svg(sous_chemins):
    """Chemin SVG absolu (M x,y L x,y ... [Z]) en pixels entiers. [sous_chemins] : liste de (points, ferme).
    Les points entiers consécutifs identiques sont fusionnés, un sous-chemin sans surface ou sans longueur saute."""
    morceaux = []
    for pts, ferme in sous_chemins:
        ent = []
        for x, y in pts:
            p = (_entier(x), _entier(y))
            if not ent or ent[-1] != p:
                ent.append(p)
        if ferme and len(ent) > 1 and ent[0] == ent[-1]:
            ent.pop()
        if len(ent) < (3 if ferme else 2):
            continue
        morceaux.append(f"M{ent[0][0]},{ent[0][1]} " + " ".join(f"L{x},{y}" for x, y in ent[1:])
                        + (" Z" if ferme else ""))
    return " ".join(morceaux)


def generer(geojson, cadre, taille, marge=MARGE_DEFAUT, tolerance=0.0, terre_a_gauche=True):
    """(texte_cote, texte_terre, bilan) à partir d'un objet GeoJSON. Fonction pure, sans fichier."""
    lignes, anneaux = lire_geojson(geojson)
    ouvertes, fermees = joindre(lignes)
    anneaux = anneaux + fermees
    proj = projeteur(cadre, taille)
    boite = (-float(marge), -float(marge), taille[0] + float(marge), taille[1] + float(marge))

    morceaux = []
    for ligne in ouvertes:
        pts = [proj(lon, lat) for lon, lat in ligne]
        morceaux.extend(simplifier(m, tolerance) for m in decouper_ligne(pts, boite))
    iles = []
    for anneau in anneaux:
        pts = decouper_anneau([proj(lon, lat) for lon, lat in anneau], boite)
        if pts:
            iles.append(simplifier(pts, tolerance))

    polygones = fermer_terre(morceaux, boite, terre_a_gauche)
    cote = chemin_svg([(m, False) for m in morceaux] + [(i, True) for i in iles])
    terre = chemin_svg([(p, True) for p in polygones] + [(i, True) for i in iles])
    if not cote:
        raise ErreurCote("aucune côte dans le cadre : vérifier le cadre (lat_min, lat_max, lon_min, lon_max) "
                         "et que le fichier est en longitude/latitude")
    bilan = {"lignes": len(morceaux), "terres": len(polygones), "iles": len(iles),
             "ouvertes_non_fermees": len(morceaux) - sum(
                 1 for m in morceaux if _abscisse(m[0], boite) is not None and _abscisse(m[-1], boite) is not None)}
    return cote, terre, bilan


# ------------------------------------------------------------ ligne de commande
def _parametres_config():
    """(cadre, taille, cote, terre, dossier) de la configuration de la maison, valeurs None si absentes."""
    sys.path.insert(0, str(RACINE / "poc"))
    try:
        import maison
    except SystemExit:                 # pas de configuration : tout doit alors venir des arguments
        return None, None, None, None, None
    vent = maison.CONFIG.get("vent") if isinstance(maison.CONFIG.get("vent"), dict) else {}
    carte = vent.get("carte") if isinstance(vent.get("carte"), dict) else {}
    cadre = vent.get("cadre")
    taille = (carte.get("largeur"), carte.get("hauteur"))
    return (cadre if isinstance(cadre, list) and len(cadre) == 4 else None,
            taille if all(isinstance(v, (int, float)) for v in taille) else None,
            carte.get("cote"), carte.get("terre"), maison.chemin("genere") / "android")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trait de côte et terre de la carte du vent, depuis un GeoJSON.")
    ap.add_argument("entree", help="fichier GeoJSON (lignes ou contours de côte en longitude/latitude)")
    ap.add_argument("--cadre", nargs=4, type=float, metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
                    help="emprise de la carte, sinon vent.cadre de maison.json")
    ap.add_argument("--taille", nargs=2, type=float, metavar=("LARGEUR", "HAUTEUR"),
                    help="taille de la carte en pixels, sinon vent.carte.largeur et hauteur")
    ap.add_argument("--sortie", metavar="DOSSIER",
                    help="dossier des deux fichiers, sinon genere/android/ de la configuration")
    ap.add_argument("--cote", metavar="CHEMIN", help="chemin du trait de côte sous le dossier de sortie, sinon "
                    "vent.carte.cote")
    ap.add_argument("--terre", metavar="CHEMIN", help="chemin de la terre sous le dossier de sortie, sinon "
                    "vent.carte.terre")
    ap.add_argument("--marge", type=float, default=MARGE_DEFAUT, help="marge hors cadre en pixels (60)")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="simplification en pixels (0, aucune). Quelques dizaines de points suffisent à 640 px")
    ap.add_argument("--terre-a-droite", action="store_true",
                    help="la terre est à droite du sens des lignes (par défaut à gauche, comme OpenStreetMap)")
    a = ap.parse_args(argv)

    try:
        try:
            geojson = json.loads(Path(a.entree).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ErreurCote(f"fichier GeoJSON illisible ({a.entree}) : {e}")
        cadre, taille, cote_cfg, terre_cfg, dossier = a.cadre, a.taille, a.cote, a.terre, a.sortie
        if None in (cadre, taille, cote_cfg, terre_cfg, dossier):
            c_cadre, c_taille, c_cote, c_terre, c_dossier = _parametres_config()
            cadre = cadre or c_cadre
            taille = taille or c_taille
            cote_cfg = cote_cfg or c_cote or "carte/cote.txt"
            terre_cfg = terre_cfg or c_terre or "carte/terre.txt"
            dossier = dossier or c_dossier or "."
        if cadre is None or taille is None:
            raise ErreurCote("cadre ou taille de carte inconnus : les passer par --cadre et --taille, ou renseigner "
                             "vent.cadre et vent.carte.largeur et hauteur dans maison.json")
        dossier = Path(dossier)
        cote, terre, bilan = generer(geojson, cadre, taille, a.marge, a.tolerance, not a.terre_a_droite)
    except ErreurCote as e:
        print(f"generer_cote : {e}", file=sys.stderr)
        return 1

    for relatif, texte in ((cote_cfg, cote), (terre_cfg, terre)):
        cible = dossier / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes((texte + "\n").encode("utf-8"))
        print(f"{cible} ({len(texte)} caractères)")
    print(f"{bilan['lignes']} ligne(s) de côte, {bilan['terres']} terre(s), {bilan['iles']} île(s).")
    if bilan["ouvertes_non_fermees"]:
        print(f"generer_cote : {bilan['ouvertes_non_fermees']} ligne(s) de côte ne rejoignent pas le bord du cadre, "
              "sans terre refermée pour elles. Élargir le cadre ou la marge, ou fournir une côte complète.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
