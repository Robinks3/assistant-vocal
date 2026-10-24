"""Vent mesuré sur le plan d'eau de la configuration pour la page « Vent mesuré » de la tablette (0.24.0, demande du 24/10/2026).

Mesures réelles de vent (et non prévisions) sur le plan d'eau et autour : balises, stations
officielles nommées, stations amateurs de la ville, station à terre. Tout ce qui décrit le lieu (balises, stations,
quartiers, cadre de la carte) vient de la section « vent » de maison.json. L'exemple fourni décrit la rade
de Marseille, avec des valeurs fictives.

Tout est public et sans clé, aucune donnée personnelle : le message est servi à toute connexion,
chiffrée ou non, dans les deux profils (pc et ha). VENT_MESURE=0 dans l'environnement (poc/.env)
l'éteint seul, METEO_MER=0 l'éteint avec la météo marine (0.27.2).

Sources (une requête chacune) :
  balises      API JSON à la forme tRPC (url et requête dans la configuration), observations récentes
               de toutes les balises. On ne garde que les ids listés dans la configuration
               (coordonnées lues dans maison.json, aucune dans la réponse). Les autres ids sont des
               doublons des stations officielles. Vitesses et rafales en nœuds, doublons exacts (id, t) retirés,
               rafale 0 = absente. Sans clé, mais avec un User-Agent honnête qui dit qui appelle.
  officielles  Réseau d'observations à la forme DB-All.e (url dans la configuration), un seul appel pour la vitesse (B11002),
               la direction (B11001) et la rafale (B11041) des 3 dernières heures, sur tout le pays
               (environ 1 Mo), réduit au cadre de la carte de la tablette. Valeurs en m/s convertis en
               nœuds, heures en UTC sans fuseau. Instantané : trange 254,0,0. Rafale : maximum sur 15 min
               ou 1 h (2,0,900 ou 2,0,3600), rattachée à la mesure de même heure si elle existe.
  station      Station à terre (rubrique « station »), snapshot avec window=day : les courbes vitesse et
               direction des 24 dernières heures (m/s), dont on garde les 3 dernières heures, plus la
               dernière valeur des cartes si elle est plus récente.

Doublons. Une station officielle à moins de 300 m d'une balise la remplace. Si la source
officielle est en panne, la balise revient. Des stations amateurs de même nom (le quartier)
à moins de 1,5 km sont fusionnées en une seule, celle dont la dernière mesure est la plus récente.

Cadence, en mémoire seulement, rien sur disque : une source n'est relue que si la tablette demande
et que son cache est périmé (balises et station à terre toutes les 2 min, stations officielles toutes les 10 min). Une
lecture en vol par source, que les demandes simultanées partagent. Sources lues en parallèle, chacune
avec son délai (balises 10 s, stations officielles 20 s, station à terre 8 s) et son plafond de taille (2 Mo, 4 Mo, 1 Mo),
httpx avec trust_env=False et réponse lue en flux. Après une erreur, attente croissante avant le
nouvel essai : 1 min, 2, 4, 8, plafond 15 min, remise à 1 min au premier succès. Une source dont la
forme change (clé absente, type inattendu) est « indisponible » proprement, les autres continuent.
Son ancien cache reste servi, ses mesures gardent leur vrai horodatage : la tablette juge la
fraîcheur. Aucune exception brute ne sort : seulement des textes écrits ici, avec la classe d'une
erreur inattendue. Une erreur n'est renvoyée que si aucune source n'a jamais rien donné.

Forme de « donnees » (contrat avec l'appli) :
  lu_a      dernière lecture réussie d'une source, ISO avec décalage, heure locale
  stations  liste de {id, nom, genre, type, source, lat, lon, point, seuil_min, mesures}
            type : mer, abritee, terre ou amateur. source : balises, officielles ou station_terre.
            point : point de prévision le plus proche (un id de la section « mer »). seuil_min : minutes
            sans mesure au-delà desquelles la tablette juge la station périmée (45, 75 ou 30).
            mesures : triées, 3 dernières heures seulement, chacune {t, vent, dir, rafale}. t : secondes
            Unix. vent en nœuds à une décimale, dir entier de 0 à 359 (null si inconnue, ou si le vent
            est nul), rafale en nœuds ou null. Une station sans mesure dans les 3 h n'est pas listée.
            Ordre : mer, abritee, terre, amateur, puis par nom.
  erreurs   libellés lisibles des sources en panne, liste vide sinon
"""
import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import maison
import meteo_mer as MM

# Stations, balises et cadre de la carte : section « vent » de maison.json. Sans elle, ou avec "actif": false,
# le module est éteint (depuis_env rend None). Il suppose aussi la section « mer » (points de rattachement).
VENT = maison.CONFIG.get("vent") or {}
ACTIF = maison.actif(VENT)
FENETRE = 3 * 3600           # secondes de mesures gardées
CADRE = tuple(VENT.get("cadre") or (0.0, 0.0, 0.0, 0.0))   # latitude min et max, longitude min et max : la carte
RAYON_DOUBLON = 300.0        # mètres : station officielle qui remplace une balise
RAYON_FUSION = 1500.0        # mètres : stations amateurs de même nom fusionnées
NOEUDS_PAR_MS = 1.943844
NOEUDS = {"m/s": NOEUDS_PAR_MS, "km/h": 0.539957, "kn": 1.0, "kt": 1.0}

_BAL = VENT.get("balises") or {}
# Adaptateur de forme tRPC : {requete} de l'adresse reçoit l'objet « requete » de la configuration, encodé.
URL_BALISES = str(_BAL.get("url") or "").replace("{requete}", quote(
    json.dumps({"0": {"json": _BAL.get("requete") or {}}}, separators=(",", ":"))))
NOM_BALISES = str(_BAL.get("nom") or "balises")
# Honnête sur l'appelant. ASCII seulement : httpx refuse un accent dans un en-tête.
ENTETES_BALISES = {"User-Agent": str(_BAL.get("user_agent") or "assistant-vocal/1.0 (usage personnel)")}
PANNE_BALISES = str(_BAL.get("panne") or "Balises indisponibles")
_OFF = VENT.get("stations_officielles") or {}
URL_OFFICIELLES = str(_OFF.get("url") or "")
NOM_OFFICIELLES = str(_OFF.get("nom") or "stations officielles")
PANNE_OFFICIELLES = str(_OFF.get("panne") or "Stations officielles indisponibles")
PRODUITS_OFFICIELS = "B11002 or B11001 or B11041"
URL_TERRE = str((VENT.get("station") or {}).get("url") or "")

# Balises gardées : id de la source -> fiche. Positions de la carte, jamais lues dans la réponse.
# Une balise sans point de rattachement ("point": null) est une donnée de contexte hors carte.
BALISES = {int(cle): dict(fiche) for cle, fiche in (_BAL.get("fiches") or {}).items()
                       if maison.source_active(fiche)}   # "actif": false retire la balise (0.35.0)
# Station à terre (même station que la page « Mer ») : sa fiche, sans l'adresse.
STATION_TERRE = {k: v for k, v in (VENT.get("station") or {}).items() if k not in ("url", "actif")}
# Points de prévision de la page « Mer » (meteo_mer.POINTS), pour rattacher chaque station au plus proche.
POINTS_PREVISION = {cle: tuple(v) for cle, v in (VENT.get("points_proches") or {}).items()}
# Stations officielles reconnues par leur nom brut, réseau des stations amateurs (nom = leur code), et quartier
# de chaque station amateur connue.
NOMMEES_OFFICIELLES = {str(n["nom_brut"]).lower(): {k: v for k, v in n.items() if k != "nom_brut"}
                    for n in _OFF.get("nommees") or []}
RESEAU_AMATEUR = str(_OFF.get("reseau_amateur") or "")
QUARTIERS = dict(_OFF.get("quartiers") or {})
NOM_AMATEUR_INCONNU = "Station amateur"
SEUILS_MIN = {"balises": 45, "officielles": 75, "station_terre": 30}   # minutes avant « périmée »
ORDRE_TYPES = {"mer": 0, "abritee": 1, "terre": 2, "amateur": 3}

DUREE_BALISES = 120      # secondes de cache par source
DUREE_OFFICIELLES = 600
DUREE_TERRE = 120
DELAI_BALISES = 10       # secondes, lecture et durée totale de l'appel
DELAI_OFFICIELLES = 20
DELAI_TERRE = 8
DELAI_CONNEXION = 4
TAILLE_BALISES = 2_000_000   # octets par réponse
TAILLE_OFFICIELLES = 4_000_000
TAILLE_TERRE = 1_000_000
ATTENTE_PANNE_MIN = 60       # secondes avant le premier nouvel essai, doublées à chaque échec de suite
ATTENTE_PANNE_MAX = 900
MARGE = 2                    # au-delà du délai, le thread d'une source n'est plus attendu
ATTENTE_MAX = max(DELAI_BALISES, DELAI_OFFICIELLES, DELAI_TERRE) + MARGE + 1


class ErreurVent(Exception):
    """Erreur au texte lisible, écrit ici, à renvoyer telle quelle à la tablette."""


# ---------------------------------------------------------------- valeurs et géographie (fonctions pures)
def distance_m(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux positions (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12_742_000.0 * math.asin(math.sqrt(a))


def dans_le_cadre(lat, lon):
    return CADRE[0] <= lat <= CADRE[1] and CADRE[2] <= lon <= CADRE[3]


def point_proche(lat, lon):
    """Point de prévision (section vent.points_proches) le plus proche d'une position, ou "" sans point
    déclaré (0.27.3) : l'appli prend alors son point par défaut. Avant, min() levait ValueError."""
    if not POINTS_PREVISION:
        return ""
    return min(POINTS_PREVISION, key=lambda p: distance_m(lat, lon, *POINTS_PREVISION[p]))


def mesure(vent, direction, rafale):
    """(vent, dir, rafale) arrondis : nœuds à une décimale, direction entière, rafale nulle = absente.
    Une direction à 0 avec un vent nul n'est pas une direction : null."""
    vent = round(vent, 1)
    direction = MM.angle(direction)
    if vent == 0 and direction == 0:
        direction = None
    rafale = MM.dixieme(rafale)
    return (vent, direction, rafale if rafale is not None and rafale > 0 else None)


def instant(texte):
    """Secondes Unix d'un horodatage ISO (UTC si sans décalage), sinon None."""
    d = MM.instant_iso(texte)
    return int(d.timestamp()) if d else None


# ---------------------------------------------------------------- réduction de chaque source (pure)
def reduire_balises(brut, nom, maintenant=None):
    """{id la source des balises connu: {t: (vent, dir, rafale)}}. ErreurVent si la forme est inattendue, y compris une
    réponse qui n'a plus aucune mesure lisible d'une balise connue (horodatage changé, champ renommé)."""
    try:
        observations = brut[0]["result"]["data"]["json"]["observationData"]
    except (KeyError, IndexError, TypeError):
        raise ErreurVent(f"réponse inattendue de {nom}") from None
    if not isinstance(observations, list):
        raise ErreurVent(f"réponse inattendue de {nom}")
    sortie = {}
    plafond = (maintenant if maintenant is not None else time.time()) + 600
    for o in observations:
        ident = o.get("id") if isinstance(o, dict) else None
        if isinstance(ident, bool) or not isinstance(ident, int) or ident not in BALISES:
            continue
        t, vent = MM.reel(o.get("t")), MM.reel(o.get("tws"))
        if t is None or vent is None or vent < 0:
            continue
        if t > 1e11:  # horodatage passé en millisecondes
            t = t / 1000.0
        if t > plafond:  # mesure dans le futur : horodatage illisible
            continue
        # Un doublon exact (id, t) écrase l'autre : même valeur.
        sortie.setdefault(ident, {})[int(t)] = mesure(vent, o.get("twd"), MM.reel(o.get("gust")))
    if observations and not sortie:
        raise ErreurVent(f"réponse inattendue de {nom}")
    return sortie


def trange_de(valeur):
    """Période d'une mesure la source officielle en tuple d'entiers : « 254,0,0 » ou [254, 0, 0] donnent (254, 0, 0)."""
    if isinstance(valeur, str):
        valeur = valeur.split(",")
    if not isinstance(valeur, (list, tuple)):
        return None
    try:
        return tuple(int(x) for x in valeur)
    except (TypeError, ValueError):
        return None


def identite_officielle(stat):
    """Fiche d'une station officielle (sans position ni mesures), ou None si elle n'a pas de nom."""
    noms = [d.get("val") for d in stat.get("details") or [] if isinstance(d, dict) and d.get("var") == "B01019"]
    brut = next((n.strip() for n in noms if isinstance(n, str) and n.strip()), None)
    if brut is None:
        return None
    if brut.lower() in NOMMEES_OFFICIELLES:
        return dict(NOMMEES_OFFICIELLES[brut.lower()])
    if RESEAU_AMATEUR and stat.get("net") == RESEAU_AMATEUR:
        code = brut.lower()
        return {"id": code, "nom": QUARTIERS.get(code, f"{NOM_AMATEUR_INCONNU} {code}"), "genre": "amateur, en ville",
                "type": "amateur", "point": None}
    ident = re.sub(r"[^a-z0-9]+", "-", brut.lower()).strip("-") or "station"
    return {"id": ident, "nom": brut, "genre": "station météo", "type": "terre", "point": None}


def reduire_officielles(brut, nom):
    """Liste des stations du cadre : fiche, position (lat, lon) et {t: (vent, dir, rafale)} en nœuds.
    ErreurVent si la forme est inattendue."""
    donnees = brut.get("data") if isinstance(brut, dict) else None
    if not isinstance(donnees, list):
        raise ErreurVent(f"réponse inattendue de {nom}")
    stations = []
    for s in donnees:
        stat = s.get("stat") if isinstance(s, dict) else None
        if not isinstance(stat, dict):
            continue
        lat, lon = MM.reel(stat.get("lat")), MM.reel(stat.get("lon"))
        if lat is None or lon is None or not dans_le_cadre(lat, lon):
            continue
        fiche = identite_officielle(stat)
        if fiche is None:
            continue
        vitesses, directions, rafales = {}, {}, {}
        for p in s.get("prod") if isinstance(s.get("prod"), list) else []:
            if not isinstance(p, dict) or not isinstance(p.get("val"), list):
                continue
            periode = trange_de(p.get("trange"))
            if not str(p.get("lev", "")).startswith("103,10000") or periode is None:
                continue  # seulement le vent à 10 m
            cible = None
            if p.get("var") == "B11002" and periode[0] == 254:
                cible = vitesses
            elif p.get("var") == "B11001" and periode[0] == 254:
                cible = directions
            elif p.get("var") == "B11041" and periode[:2] == (2, 0):
                cible = rafales
            if cible is None:
                continue
            for v in p["val"]:
                if not isinstance(v, dict):
                    continue
                t, valeur = instant(v.get("ref")), MM.reel(v.get("val"))
                if t is None or valeur is None or valeur < 0:
                    continue
                # Deux périodes de rafale (15 min et 1 h) à la même heure : la plus forte.
                cible[t] = max(valeur, cible.get(t, 0.0)) if cible is rafales else valeur
        mesures = {t: mesure(ms * NOEUDS_PAR_MS, directions.get(t),
                             rafales[t] * NOEUDS_PAR_MS if t in rafales else None)
                   for t, ms in vitesses.items()}
        stations.append({**fiche, "lat": lat, "lon": lon,
                         "point": fiche["point"] or point_proche(lat, lon), "mesures": mesures})
    return stations


def courbe_terre(series, cle):
    """({t: valeur}, unité) d'une courbe du snapshot, lue dans points {x, y} ou, à défaut, labels et values."""
    serie = next((s for s in series if isinstance(s, dict) and s.get("key") == cle), None)
    if serie is None:
        return {}, None
    if isinstance(serie.get("points"), list):
        couples = [(p.get("x"), p.get("y")) for p in serie["points"] if isinstance(p, dict)]
    elif isinstance(serie.get("labels"), list) and isinstance(serie.get("values"), list):
        couples = list(zip(serie["labels"], serie["values"]))
    else:
        couples = []
    sortie = {}
    for x, y in couples:
        t, valeur = instant(x), MM.reel(y)
        if t is not None and valeur is not None:
            sortie[t] = valeur
    unite = serie.get("unit")
    return sortie, unite.strip().lower() if isinstance(unite, str) else None


def reduire_terre(brut, nom):
    """{t: (vent, dir, None)} en nœuds d'après le snapshot de la station du port : les courbes puis, si
    elle est plus récente, la dernière valeur des cartes. ErreurVent s'il n'y a aucun vent."""
    instantane = brut.get("snapshot") if isinstance(brut, dict) else None
    if not isinstance(instantane, dict):
        raise ErreurVent(f"réponse inattendue de {nom}")
    series = instantane.get("series") if isinstance(instantane.get("series"), list) else []
    cartes = instantane.get("cards") if isinstance(instantane.get("cards"), list) else []
    par_cle = {c.get("key"): c for c in cartes if isinstance(c, dict) and isinstance(c.get("key"), str)}
    vitesses, unite = courbe_terre(series, "wind_speed")
    directions, _ = courbe_terre(series, "wind_direction")
    carte = par_cle.get("wind_speed", {})
    if not vitesses:
        unite = str(carte.get("unit", "")).strip().lower()
    facteur = NOEUDS.get(unite or "m/s")
    if facteur is None:
        raise ErreurVent(f"unité de vent inconnue dans la réponse de {nom}")
    mesures = {t: mesure(v * facteur, directions.get(t), None) for t, v in vitesses.items()}
    t_carte, v_carte = instant(instantane.get("last_timestamp")), MM.reel(carte.get("value"))
    if t_carte is not None and v_carte is not None and v_carte >= 0 and (not mesures or t_carte > max(mesures)):
        facteur_carte = NOEUDS.get(str(carte.get("unit", "")).strip().lower())
        if facteur_carte is not None:
            mesures[t_carte] = mesure(v_carte * facteur_carte, MM.reel(par_cle.get("wind_direction", {}).get("value")), None)
    if not mesures:
        raise ErreurVent(f"réponse de {nom} sans vent")
    return mesures


# ---------------------------------------------------------------- assemblage (fonction pure)
def station_de(fiche, source, mesures, limite):
    """Station au format du message, ou None sans mesure depuis `limite` (secondes Unix)."""
    recentes = [{"t": t, "vent": m[0], "dir": m[1], "rafale": m[2]} for t, m in sorted(mesures.items()) if t > limite]
    if not recentes:
        return None
    return {"id": fiche["id"], "nom": fiche["nom"], "genre": fiche["genre"], "type": fiche["type"], "source": source,
            "lat": fiche["lat"], "lon": fiche["lon"], "point": fiche["point"] or point_proche(fiche["lat"], fiche["lon"]),
            "seuil_min": SEUILS_MIN[source], "mesures": recentes}


def assembler(balises, officielles, station_terre, maintenant, officielles_sain=True, lu_a=None, erreurs=()):
    """Champ « donnees » à partir des réductions de chaque source (None pour une source jamais lue).

    balises : {id: {t: mesure}}. officielles : liste de stations. station_terre : {t: mesure}. maintenant : instant
    avec fuseau. officielles_sain : faux si la source officielle est en panne, la balise remplace alors la
    station officielle voisine au lieu d'être remplacée par elle. Fonction pure, sans horloge ni réseau."""
    limite = int(maintenant.timestamp()) - FENETRE
    pw = [s for ident, mesures in (balises or {}).items()
          if (s := station_de(BALISES[ident], "balises", mesures, limite))]
    mh = [s for f in (officielles or []) if (s := station_de(f, "officielles", f["mesures"], limite))]
    # Un doublon balise / station officielle : la station officielle gagne (rafale horaire, 10 min), sauf si la source
    # officielle est en panne ou si sa station a dépassé son seuil de fraîcheur, alors la balise revient.
    instant = int(maintenant.timestamp())
    for p in pw[:]:
        for m in mh[:]:
            if distance_m(p["lat"], p["lon"], m["lat"], m["lon"]) < RAYON_DOUBLON:
                fraiche = instant - m["mesures"][-1]["t"] <= SEUILS_MIN["officielles"] * 60
                if officielles_sain and fraiche:
                    pw.remove(p)
                    break
                mh.remove(m)
    terre = [s for s in [station_de(STATION_TERRE, "station_terre", station_terre or {}, limite)] if s]
    # Fusion des stations amateurs de même nom proches : on garde la dernière mesure la plus récente.
    gardees = []
    for s in sorted(mh, key=lambda s: (-s["mesures"][-1]["t"], s["id"])):
        if s["type"] == "amateur" and any(
                g["type"] == "amateur" and g["nom"] == s["nom"]
                and distance_m(g["lat"], g["lon"], s["lat"], s["lon"]) < RAYON_FUSION for g in gardees):
            continue
        gardees.append(s)
    # Un même id ne sort qu'une fois (station officielle loin de sa balise) : la plus fraîche reste.
    uniques = {}
    for s in pw + gardees + terre:
        g = uniques.get(s["id"])
        if g is None or s["mesures"][-1]["t"] > g["mesures"][-1]["t"]:
            uniques[s["id"]] = s
    stations = sorted(uniques.values(), key=lambda s: (ORDRE_TYPES.get(s["type"], 9), s["nom"], s["id"]))
    return {"lu_a": lu_a, "stations": stations, "erreurs": list(erreurs)}


# ---------------------------------------------------------------- lecture des sources et cache
def lire_json(url, delai, nom, taille_max, entetes=None, transport=None):
    """Appel bloquant (dans un thread) : JSON de la réponse, ou ErreurVent au texte lisible."""
    import httpx
    debut = time.monotonic()
    corps = bytearray()
    trop = f"réponse de {nom} trop grande (plus de {taille_max // 1_000_000} Mo)"
    try:
        with httpx.Client(transport=transport, trust_env=False, headers=entetes,
                          timeout=httpx.Timeout(delai, connect=DELAI_CONNEXION)) as client:
            with client.stream("GET", url) as r:
                if r.status_code != 200:
                    raise ErreurVent(f"{nom} a répondu {r.status_code}")
                longueur = r.headers.get("content-length", "")
                if longueur.isdigit() and int(longueur) > taille_max:
                    raise ErreurVent(trop)
                for bloc in r.iter_bytes():
                    corps += bloc
                    if len(corps) > taille_max:
                        raise ErreurVent(trop)
                    if time.monotonic() - debut > delai:
                        raise ErreurVent(f"{nom} ne répond pas (délai de {delai} s)")
    except httpx.TimeoutException:
        raise ErreurVent(f"{nom} ne répond pas (délai de {delai} s)") from None
    except httpx.HTTPError as e:
        raise ErreurVent(f"{nom} injoignable ({e.__class__.__name__})") from None
    try:
        return json.loads(bytes(corps))
    except (ValueError, RecursionError):
        raise ErreurVent(f"réponse illisible de {nom}") from None


class Source:
    """Une source lue par une requête. État en mémoire seulement : dernière réduction réussie (cache),
    son heure, la dernière panne, le nombre d'échecs de suite et la lecture en vol."""

    def __init__(self, nom, libelle, url, delai, duree, taille_max, reduire, entetes=None):
        self.nom, self.libelle, self.url = nom, libelle, url   # url : fonction sans argument
        self.delai, self.duree, self.taille_max = delai, duree, taille_max
        self.reduire, self.entetes = reduire, entetes
        self.cache, self.t, self.lu_a = None, 0.0, None
        self.erreur, self.t_erreur, self.echecs = None, 0.0, 0
        self.tache = None

    def attente(self):
        """Secondes à attendre après l'échec en cours : 60, 120, 240, 480, puis 900 au plus."""
        return min(ATTENTE_PANNE_MIN * 2 ** max(self.echecs - 1, 0), ATTENTE_PANNE_MAX)

    def a_relire(self, maintenant):
        """Vrai si le cache manque ou est périmé, et que l'attente après la dernière panne est passée."""
        if self.erreur is not None:
            return maintenant - self.t_erreur >= self.attente()
        return self.cache is None or maintenant - self.t >= self.duree

    def lire(self, transport=None):
        return self.reduire(lire_json(self.url(), self.delai, self.nom, self.taille_max, self.entetes, transport),
                            self.nom)


class VentMesure:
    """Les trois lectures et leur cache : une lecture en vol par source (les demandes simultanées la
    partagent), sources périmées lues en parallèle, chacune avec son délai."""

    def __init__(self, horloge=time.monotonic, maintenant=None, transport=None, vent=None):
        self._horloge = horloge
        self._maintenant = maintenant or (lambda: datetime.now(timezone.utc))
        self._transport = transport  # httpx.MockTransport dans les tests
        vent = VENT if vent is None else vent   # section « vent » lue pour les clés « actif » de chaque source
        self.balises = Source(NOM_BALISES, PANNE_BALISES, lambda: URL_BALISES,
                                  DELAI_BALISES, DUREE_BALISES, TAILLE_BALISES, reduire_balises,
                                  ENTETES_BALISES)
        self.stations_officielles = Source(NOM_OFFICIELLES, PANNE_OFFICIELLES, self._url_officielles,
                               DELAI_OFFICIELLES, DUREE_OFFICIELLES, TAILLE_OFFICIELLES, reduire_officielles)
        self.station_terre = Source("station", f"Station de {STATION_TERRE.get('nom', 'la station')} indisponible", lambda: URL_TERRE,
                          DELAI_TERRE, DUREE_TERRE, TAILLE_TERRE, reduire_terre)
        # Une source avec "actif": false n'est ni interrogée ni comptée en panne (0.35.0), clé absente = vrai.
        actives = {"balises": maison.source_active(vent.get("balises")),
                   "stations_officielles": maison.source_active(vent.get("stations_officielles")),
                   "station_terre": maison.source_active(vent.get("station"))}
        self.inactives = [nom for nom, ok in actives.items() if not ok]
        self.sources = [s for nom, s in (("balises", self.balises), ("stations_officielles", self.stations_officielles),
                                         ("station_terre", self.station_terre)) if actives[nom]]

    def _url_officielles(self):
        """Adresse des stations officielles des 3 dernières heures (UTC), calculée à chaque lecture."""
        fin = self._maintenant().astimezone(timezone.utc)
        debut = fin - timedelta(seconds=FENETRE)
        q = (f"reftime: >={debut:%Y-%m-%d %H:%M},<={fin:%Y-%m-%d %H:%M};product:{PRODUITS_OFFICIELS};"
             "license:CCBY_COMPLIANT")
        return URL_OFFICIELLES.format(q=quote(q))

    async def _lire_source(self, s):
        """Lit une source et range son résultat ou sa panne. Ne lève jamais."""
        try:
            reduit = await asyncio.wait_for(asyncio.to_thread(s.lire, self._transport), s.delai + MARGE)
        except asyncio.TimeoutError:
            erreur = f"{s.nom} ne répond pas (délai de {s.delai} s)"
        except ErreurVent as e:
            erreur = str(e)
        except Exception as e:  # le texte d'une exception n'est pas écrit ici : seulement sa classe
            erreur = f"{s.nom} : erreur inattendue ({e.__class__.__name__})"
        else:
            s.cache, s.t, s.erreur, s.echecs = reduit, self._horloge(), None, 0
            s.lu_a = MM.heure_locale(self._maintenant())
            return
        s.erreur, s.t_erreur, s.echecs = erreur, self._horloge(), s.echecs + 1

    async def _lecture(self, s):
        """Seul chemin vers le réseau : une source, puis sa place en vol est libérée."""
        try:
            await self._lire_source(s)
        finally:
            s.tache = None

    async def donnees(self):
        """Champ « donnees » du message, ou ErreurVent si aucune source n'a jamais rien donné. Lance la
        lecture des sources périmées qui n'en ont pas déjà une en vol. N'attend (ATTENTE_MAX secondes au
        plus) que les lectures qu'elle lance et celles des sources sans cache : une source qui se
        rafraîchit pendant que son ancien cache est servi ne fait attendre personne."""
        maintenant = self._horloge()
        attendre = []
        for s in self.sources:
            if s.tache is None and s.a_relire(maintenant):
                s.tache = asyncio.get_running_loop().create_task(self._lecture(s))
                # Résultat lu même si toutes les demandes ont abandonné : pas d'avertissement asyncio.
                s.tache.add_done_callback(lambda t: t.cancelled() or t.exception())
                attendre.append(s.tache)
            elif s.tache is not None and s.cache is None:
                attendre.append(s.tache)
        if attendre:
            await asyncio.wait(attendre, timeout=ATTENTE_MAX)  # n'annule rien : la lecture continue
        return self.servir()

    def servir(self):
        if all(s.cache is None for s in self.sources):
            raisons = [s.erreur for s in self.sources if s.erreur is not None]
            raise ErreurVent("mesures de vent indisponibles : " + (", ".join(raisons) or "aucune source ne répond encore"))
        lectures = [s.lu_a for s in self.sources if s.lu_a is not None]
        return assembler(self.balises.cache, self.stations_officielles.cache, self.station_terre.cache, self._maintenant(),
                         self.stations_officielles.cache is not None and self.stations_officielles.erreur is None,
                         max(lectures).isoformat(timespec="seconds") if lectures else None,
                         [s.libelle for s in self.sources if s.erreur is not None])

    def bilan(self):
        """Ligne de journal d'une réponse servie : sources lues, puis sources en panne avec leur raison."""
        servies = [s.nom for s in self.sources if s.cache is not None and s.erreur is None]
        ligne = f"mesures servies ({', '.join(servies) or 'anciens caches'})"
        en_panne = [s.erreur for s in self.sources if s.erreur is not None]
        return ligne + (f", en panne : {', '.join(en_panne)}" if en_panne else "")


def libelle_sources(vent=None):
    """Sources interrogées, pour la ligne du démarrage : les noms des sources actives (0.35.0)."""
    cfg = VENT if vent is None else vent
    return [nom for nom, cle in ((NOM_BALISES, "balises"), (NOM_OFFICIELLES, "stations_officielles"), ("station", "station"))
            if maison.source_active(cfg.get(cle))]


def eteint_par_env():
    """Vrai si VENT_MESURE vaut 0 (ou non, false, off), indépendamment de METEO_MER (0.27.3)."""
    return os.getenv("VENT_MESURE", "1").strip().lower() in ("0", "non", "false", "off")


def depuis_env():
    """VentMesure, ou None sans section « vent » active dans maison.json, ou si VENT_MESURE vaut 0 (ou non,
    false, off), ou si METEO_MER éteint la météo marine : la page Vent fait partie du panneau Mer (0.27.2), ou
    si les trois sources sont désactivées ("actif": false, 0.35.0). Active par défaut dans les deux profils quand
    la section l'est."""
    if not ACTIF or not MM.ACTIF or MM.eteinte_par_env() or eteint_par_env() or not libelle_sources():
        return None
    return VentMesure()
