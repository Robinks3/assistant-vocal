"""Historique de l'air d'une pièce (S-L8) : courbes de CO2, de particules fines, de température et d'humidité.

Logique pure, sans réseau. Le serveur (serveur_satellite.repondre_air_historique) fait les deux appels à Home
Assistant, ce module décide quoi demander et met la réponse en forme.

Sécurité de la requête : le client ne donne que l'identifiant d'une pièce et une durée. Les entités demandées à
Home Assistant sont déduites du relevé des capteurs (le même que celui de la carte, mesures.py), pour les seules
zones reliées à la pièce par « correspondance_pieces », jamais un identifiant venu du client. Une pièce protégée
n'a pas d'historique. La durée est plafonnée à 7 jours.

Mise en forme : Home Assistant renvoie les changements d'état de chaque capteur. Un état vaut jusqu'au suivant, sans
dépasser la péremption de la carte (2 h) : au-delà, ou sur unavailable et unknown, la courbe a un trou et jamais un
zéro. La plage est découpée en au plus POINTS_MAX intervalles égaux, chacun porte la moyenne pondérée par le temps
de l'état tenu, puis les capteurs d'une même grandeur sont moyennés (un thermomètre dédié l'emporte, comme sur la
carte). Un intervalle sans mesure n'est pas envoyé.
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote

import mesures as ME

DUREE_DEFAUT_H = 24
DUREE_MAX_H = 168        # 7 jours
POINTS_MAX = 288         # 24 h par pas de 5 minutes
MAX_ENTITES_PAR_GRANDEUR = 8
# Clé de la réponse selon la classe d'appareil de Home Assistant.
GRANDEURS = {"carbon_dioxide": "co2", "pm25": "pm25", "temperature": "temperature", "humidity": "humidite"}
_ENTITE = re.compile(r"^sensor\.[a-z0-9_]+$")


class ErreurAir(Exception):
    """Refus ou impossibilité décrits en français, renvoyés tels quels à la tablette."""


def heures(valeur):
    """Durée demandée en heures, entre 1 et 168 (7 jours). Absente ou illisible : 24 h."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur != valeur:
        return DUREE_DEFAUT_H
    return int(min(max(round(valeur), 1), DUREE_MAX_H))


def bornes(maintenant, h):
    """(début, fin) en secondes Unix : les [h] heures (plafonnées) qui finissent à [maintenant]."""
    h = heures(h)
    fin = float(maintenant)
    return fin - h * 3600.0, fin


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def requete(debut, fin, entites):
    """(chemin, paramètres) de l'historique de Home Assistant pour [entites] : états seuls, sans attributs."""
    chemin = "/api/history/period/" + quote(_iso(debut), safe=":")
    params = {"filter_entity_id": ",".join(entites), "end_time": _iso(fin), "minimal_response": "",
              "no_attributes": ""}
    return chemin, params


def entites_de_piece(releve, corresp, piece, protegees):
    """Entités à demander pour [piece] : {grandeur: [identifiants]} (co2, pm25, temperature, humidite).

    Lève ErreurAir si la pièce est inconnue, protégée ou sans capteur de mesure. Même choix de capteurs que la carte :
    capteurs des zones reliées à la pièce, et pour la température et l'humidité le thermomètre dédié s'il existe."""
    if not isinstance(piece, str) or piece not in corresp:
        raise ErreurAir("pièce inconnue")
    zones = corresp[piece]
    protegees = {str(z).lower() for z in protegees}
    if piece.lower() in protegees or any(z in protegees for z in zones):
        raise ErreurAir("pièce protégée")
    capteurs = [c for c in (releve.get("capteurs") or []) if isinstance(c, dict)]
    ME.marquer_dedies(capteurs)
    sortie = {}
    for classe, cle in GRANDEURS.items():
        ceux = [c for c in capteurs if c.get("classe") == classe and ME._zone_de(c) in zones
                and isinstance(c.get("id"), str) and _ENTITE.match(c["id"])]
        dedies = [c for c in ceux if c.get("dedie")]
        ids = []
        for c in (dedies or ceux):
            if c["id"] not in ids:
                ids.append(c["id"])
        if ids:
            sortie[cle] = ids[:MAX_ENTITES_PAR_GRANDEUR]
    if not sortie:
        raise ErreurAir("aucun capteur de mesure dans cette pièce")
    return sortie


def _horodatage(texte):
    """Secondes Unix d'un horodatage ISO de Home Assistant, ou None."""
    if not isinstance(texte, str):
        return None
    try:
        d = datetime.fromisoformat(texte.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def lire_historique(reponse, autorisees):
    """{entité: [(secondes, valeur ou None)] triés} à partir de la réponse de /api/history/period.

    [autorisees] : les seules entités gardées. Un état qui n'est pas un nombre fini (unavailable, unknown, texte)
    devient None : un trou, jamais un zéro. Les entrées illisibles sont ignorées."""
    sortie = {}
    if not isinstance(reponse, list):
        return sortie
    for liste in reponse:
        if not isinstance(liste, list):
            continue
        ident = next((e.get("entity_id") for e in liste if isinstance(e, dict) and e.get("entity_id")), None)
        if ident not in autorisees:
            continue
        pts = sortie.setdefault(ident, [])
        for e in liste:
            if not isinstance(e, dict):
                continue
            t = _horodatage(e.get("last_changed") or e.get("last_updated"))
            if t is None:
                continue
            pts.append((t, ME._nombre(e.get("state"))))
    for pts in sortie.values():
        pts.sort(key=lambda p: p[0])
    return sortie


def moyennes_par_intervalle(points, debut, fin, nb=POINTS_MAX, tenue=ME.PEREMPTION_S):
    """Moyenne pondérée par le temps de [points] sur [nb] intervalles égaux de [debut, fin] (None sans mesure).

    Un état vaut depuis son horodatage jusqu'au suivant (ou jusqu'à [fin]), sans dépasser [tenue] secondes."""
    pas = (fin - debut) / nb
    somme, poids = [0.0] * nb, [0.0] * nb
    for i, (t, v) in enumerate(points):
        if v is None:
            continue
        suivant = points[i + 1][0] if i + 1 < len(points) else fin
        a, b = max(t, debut), min(suivant, t + tenue, fin)
        if b <= a:
            continue
        for k in range(int((a - debut) / pas), min(nb - 1, int((b - debut) / pas)) + 1):
            bas, haut = max(a, debut + k * pas), min(b, debut + (k + 1) * pas)
            if haut > bas:
                somme[k] += v * (haut - bas)
                poids[k] += haut - bas
    return [somme[k] / poids[k] if poids[k] > 0 else None for k in range(nb)]


def serie(historique, ids, debut, fin, nb=POINTS_MAX, tenue=ME.PEREMPTION_S):
    """Courbe [[secondes du milieu de l'intervalle, valeur]] d'une grandeur : moyenne des capteurs [ids] présents
    dans [historique]. Les intervalles sans mesure sont omis."""
    par_capteur = [moyennes_par_intervalle(historique[i], debut, fin, nb, tenue) for i in ids if i in historique]
    pas = (fin - debut) / nb
    points = []
    for k in range(nb):
        vals = [m[k] for m in par_capteur if m[k] is not None]
        if vals:
            points.append([int(round(debut + (k + 0.5) * pas)), round(sum(vals) / len(vals), 1)])
    return points


def mettre_en_forme(piece, h, debut, fin, entites, historique, nb=POINTS_MAX):
    """Réponse {piece, heures, debut, fin, pas, series} : une courbe par grandeur dont la pièce a un capteur
    (liste vide si Home Assistant n'a rien gardé), aucune clé pour les grandeurs sans capteur."""
    h = heures(h)
    return {"piece": piece, "heures": h, "debut": int(round(debut)), "fin": int(round(fin)),
            "pas": int(round((fin - debut) / nb)),
            "series": {cle: serie(historique, ids, debut, fin, nb) for cle, ids in entites.items()}}
