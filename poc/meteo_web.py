"""Écran Météo et mer du client web (lot S-W5) : ce qu'un navigateur associé voit de la météo marine.

Ce module ne lit aucune source lui-même. Le serveur lui injecte deux fournisseurs (les prévisions de meteo_mer.py et
les balises de vent_mesure.py, déjà en cache), ce qui le rend testable sans réseau. Il tient quatre choses :
- le message « meteo », à schéma strict (type, point) : le point est un identifiant de la liste mer.points de
  maison.json, jamais une coordonnée ni une adresse. Sans point, le point par défaut (« defaut »), sinon le premier ;
- le filtrage par rôle (client_web.meteo.roles) : un rôle sans le droit ne reçoit rien, pas même la liste des points ;
- la projection : l'instant présent, les six prochaines heures, trois jours, la mer, le soleil et les balises du point,
  tout dit en mots (force et provenance du vent, état du ciel). Une valeur absente reste absente (null), jamais inventée ;
- l'âge de chaque mesure de balise, en minutes, et son drapeau « ancienne » au-delà du seuil de sa source.

Ce qu'il ne fait jamais : envoyer une coordonnée, lire un identifiant de source dans le message, laisser partir le
texte d'une exception. Le rôle vient de la session. Aucune marée n'est produite par le serveur, l'écran n'en montre donc pas.
"""
import math
import time
from datetime import datetime, timezone

import maison
import meteo_mer as MM

GENRE_METEO = "meteo"
GENRES = (GENRE_METEO,)
ROLES = ("administrateur", "habitant", "invite")
CLES_MESSAGE = frozenset({"type", "point"})

# Symboles du ciel (liste fermée) que le navigateur sait dessiner.
SYMBOLES = frozenset({"soleil", "nuage", "pluie", "orage", "brouillard", "neige"})

# Causes renvoyées au navigateur (liste fermée, jamais un texte venu d'ailleurs).
CAUSES = frozenset({"droit", "format", "entite", "indisponible"})

HEURES_MAX = 6
JOURS_MAX = 3
HEURE_JOUR = "14:00"  # l'heure dont le ciel résume la journée
TEXTE_MAX = 160
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")

# Secteur du vent (d'où il vient), huit pointes, avec la préposition qui convient.
SECTEURS = ("du nord", "du nord-est", "de l'est", "du sud-est", "du sud", "du sud-ouest", "de l'ouest",
            "du nord-ouest")
# Force du vent en nœuds : (borne haute exclue, mot).
FORCES = ((1, "calme"), (4, "très faible"), (11, "faible"), (17, "modéré"), (22, "assez fort"), (28, "fort"),
          (34, "très fort"))
FORCE_MAX = "tempête"

# Code WMO des prévisions : état du ciel en mots.
CIEL = {0: "Ciel dégagé", 1: "Plutôt dégagé", 2: "Partiellement nuageux", 3: "Couvert", 45: "Brouillard",
        48: "Brouillard givrant", 51: "Bruine légère", 53: "Bruine", 55: "Bruine dense", 56: "Bruine verglaçante",
        57: "Bruine verglaçante", 61: "Pluie faible", 63: "Pluie", 65: "Pluie forte", 66: "Pluie verglaçante",
        67: "Pluie verglaçante", 71: "Neige faible", 73: "Neige", 75: "Neige forte", 77: "Grains de neige",
        80: "Averses faibles", 81: "Averses", 82: "Averses violentes", 85: "Averses de neige",
        86: "Averses de neige fortes", 95: "Orage", 96: "Orage avec grêle", 99: "Orage violent avec grêle"}


class RefusMeteo(Exception):
    """Un message météo refusé avant d'avoir touché à quoi que ce soit."""

    def __init__(self, cause, entite=None):
        assert cause in CAUSES, cause
        super().__init__(cause)
        self.cause = cause
        self.entite = entite


# ------------------------------------------------------------------ configuration
def _section():
    m = maison.CLIENT_WEB.get("meteo")
    return m if isinstance(m, dict) else {}


def droits(role, section=None):
    """Vrai si ce rôle voit l'écran. Sans section roles, un propriétaire et un habitant le voient, l'invité non.
    Un rôle inconnu ne voit rien."""
    section = _section() if section is None else section
    if role not in ROLES:
        return False
    roles = section.get("roles")
    if not isinstance(roles, dict):
        return role != "invite"
    return roles.get(role) is True


def _mer():
    m = maison.CONFIG.get("mer")
    return m if isinstance(m, dict) else {}


def points_configures(mer=None):
    """Points de mer.points, dans l'ordre de la configuration : [{id, nom, stations, sans_station, defaut}].
    Une entrée mal formée ou un identifiant en double est ignoré, jamais corrigé. Aucune coordonnée n'est gardée."""
    mer = _mer() if mer is None else mer
    brutes = mer.get("points")
    sortie, vus = [], set()
    for p in brutes if isinstance(brutes, list) else []:
        if not isinstance(p, dict):
            continue
        ident, nom = p.get("id"), p.get("nom")
        if not isinstance(ident, str) or not ident.strip() or ident in vus:
            continue
        if not isinstance(nom, str) or not nom.strip():
            continue
        stations = p.get("stations")
        vus.add(ident)
        sortie.append({"id": ident, "nom": nom.strip()[:60],
                       "stations": [s for s in stations if isinstance(s, str)] if isinstance(stations, list) else None,
                       "sans_station": p.get("sans_station") is True, "defaut": p.get("defaut") is True})
    return sortie


def point_par_defaut(points):
    return next((p for p in points if p["defaut"]), points[0] if points else None)


# ------------------------------------------------------------------ mots
def _nombre(v):
    """Nombre fini ou None (un booléen n'est pas un nombre ici)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return v


def _angle(v):
    v = _nombre(v)
    return None if v is None else v % 360


def secteur(direction):
    d = _angle(direction)
    return None if d is None else SECTEURS[int((d + 22.5) // 45) % 8]


def force(vent):
    v = _nombre(vent)
    if v is None:
        return None
    for borne, mot in FORCES:
        if v < borne:
            return mot
    return FORCE_MAX


def vent_en_mots(vent, direction):
    """« Vent modéré du sud-ouest », « Calme », ou None sans vent. Sans direction, la force seule."""
    f = force(vent)
    if f is None:
        return None
    if f == "calme":
        return "Calme"
    s = secteur(direction)
    return f"Vent {f} {s}" if s else f"Vent {f}"


def _vers(direction):
    """Direction vers laquelle le vent souffle (celle de la flèche), à l'opposé de celle d'où il vient."""
    d = _angle(direction)
    return None if d is None else int(round(d + 180)) % 360


def _texte(v):
    return v.strip()[:TEXTE_MAX] if isinstance(v, str) and v.strip() else None


def ciel(code):
    c = _nombre(code)
    return CIEL.get(int(c)) if c is not None and c == int(c) else None


def symbole(code):
    """Symbole du ciel pour un code WMO : un mot de SYMBOLES, ou None si le code est absent ou inconnu."""
    c = _nombre(code)
    if c is None or c != int(c) or int(c) not in CIEL:
        return None
    c = int(c)
    if c <= 1:
        return "soleil"
    if c <= 3:
        return "nuage"
    if c in (45, 48):
        return "brouillard"
    if c >= 95:
        return "orage"
    if c in (71, 73, 75, 77, 85, 86):
        return "neige"
    return "pluie"


def _arrondi(v):
    v = _nombre(v)
    return None if v is None else (int(v) if v == int(v) else round(v, 1))


# ------------------------------------------------------------------ projection
def _heure(h):
    """Une heure de prévision, champ par champ : rien ne passe tel quel du fournisseur."""
    t = h.get("t") if isinstance(h.get("t"), str) else ""
    vent, rafales, direction = _arrondi(h.get("vent")), _arrondi(h.get("rafales")), _arrondi(h.get("dir"))
    return {"heure": t[11:16] or None, "vent": vent, "rafales": rafales, "dir": direction, "dir_vers": _vers(direction),
            "vent_mot": vent_en_mots(vent, direction), "air": _arrondi(h.get("air")), "pluie": _arrondi(h.get("pluie")),
            "vagues": _arrondi(h.get("vagues")), "periode": _arrondi(h.get("periode")),
            "dir_vagues": _arrondi(h.get("dir_vagues")), "vagues_secteur": secteur(h.get("dir_vagues")),
            "ciel": ciel(h.get("code")), "symbole": symbole(h.get("code"))}


def _extreme(valeurs, fonction):
    v = [x for x in (_nombre(y) for y in valeurs) if x is not None]
    return _arrondi(fonction(v)) if v else None


def _total(valeurs):
    v = [x for x in (_nombre(y) for y in valeurs) if x is not None]
    return _arrondi(sum(v)) if v else None


def _nom_jour(date, aujourdhui):
    ecart = (date - aujourdhui).days
    if ecart == 0:
        return "Aujourd'hui"
    if ecart == 1:
        return "Demain"
    return f"{JOURS[date.weekday()].capitalize()} {date.day} {MOIS[date.month - 1]}"


def _jours(heures, aujourdhui):
    par_jour = {}
    for h in heures:
        t = h.get("t")
        if isinstance(t, str) and len(t) >= 16:
            par_jour.setdefault(t[:10], []).append(h)
    sortie = []
    for cle in sorted(par_jour)[:JOURS_MAX]:
        try:
            date = datetime.strptime(cle, "%Y-%m-%d").date()
        except ValueError:
            continue
        lot = par_jour[cle]
        midi = next((h for h in lot if str(h.get("t"))[11:16] == HEURE_JOUR), lot[len(lot) // 2])
        sortie.append({"date": cle, "jour": _nom_jour(date, aujourdhui),
                       "vent_max": _extreme((h.get("vent") for h in lot), max),
                       "rafales_max": _extreme((h.get("rafales") for h in lot), max),
                       "vagues_max": _extreme((h.get("vagues") for h in lot), max),
                       "air_max": _extreme((h.get("air") for h in lot), max),
                       "air_min": _extreme((h.get("air") for h in lot), min),
                       "pluie_total": _total(h.get("pluie") for h in lot),
                       "ciel": ciel(midi.get("code")), "symbole": symbole(midi.get("code"))})
    return sortie


def _balise(s, maintenant_s):
    """Une balise, sans coordonnée : la dernière mesure, son âge en minutes et son drapeau « ancienne »."""
    mesures = s.get("mesures")
    if not isinstance(mesures, list) or not mesures or not isinstance(mesures[-1], dict):
        return None
    m = mesures[-1]
    t = _nombre(m.get("t"))
    ident, nom = s.get("id"), _texte(s.get("nom"))
    if t is None or not isinstance(ident, str) or nom is None:
        return None
    age = max(0, int((maintenant_s - t) // 60))
    seuil = _nombre(s.get("seuil_min"))
    vent, rafale, direction = _arrondi(m.get("vent")), _arrondi(m.get("rafale")), _arrondi(m.get("dir"))
    return {"id": ident, "nom": nom, "genre": _texte(s.get("genre")), "vent": vent, "rafale": rafale, "dir": direction,
            "dir_vers": _vers(direction), "vent_mot": vent_en_mots(vent, direction), "age_min": age,
            "ancienne": seuil is not None and age > seuil}


def _balises_du_point(donnees, point, maintenant_s):
    if point["sans_station"] or not isinstance(donnees, dict):
        return []
    stations = [s for s in donnees.get("stations") or [] if isinstance(s, dict)]
    if point["stations"] is not None:
        par_id = {s.get("id"): s for s in stations}
        choisies = [par_id[i] for i in point["stations"] if i in par_id]
    else:
        choisies = [s for s in stations if s.get("point") == point["id"]]
    return [b for b in (_balise(s, maintenant_s) for s in choisies) if b]


def _lu_a(donnees, locale):
    """Heure locale « HH:MM » de la lecture la plus ancienne des deux sources, ou None."""
    instants = [MM.instant_iso(d.get("lu_a")) for d in donnees if isinstance(d, dict)]
    instants = [i for i in instants if i]
    return locale(min(instants)).strftime("%H:%M") if instants else None


class Meteo:
    """Message « meteo » : mer et vent sont deux coroutines sans argument qui rendent les `donnees` de meteo_mer et de
    vent_mesure (ou None si la source est éteinte, ou lèvent si elle est en panne). maintenant rend un instant UTC."""

    def __init__(self, mer, vent, maintenant=lambda: datetime.now(timezone.utc), locale=MM.heure_locale):
        self._mer, self._vent = mer, vent
        self._maintenant = maintenant
        self._locale = locale

    async def _lire(self, fournisseur):
        """(données ou None, panne) : une source éteinte n'est pas une panne, le texte d'une exception ne sort pas."""
        if fournisseur is None:
            return None, False
        try:
            d = await fournisseur()
        except Exception as e:
            print(f"Météo web : lecture en échec ({e.__class__.__name__})")
            return None, True
        return (d if isinstance(d, dict) else None), not isinstance(d, dict)

    async def vue(self, role, msg):
        if not droits(role):
            raise RefusMeteo("droit")
        if not isinstance(msg, dict) or not set(msg) <= CLES_MESSAGE:
            raise RefusMeteo("format")
        points = points_configures()
        if not points:
            raise RefusMeteo("indisponible")
        demande = msg.get("point")
        if demande is None:
            point = point_par_defaut(points)
        elif isinstance(demande, str):
            point = next((p for p in points if p["id"] == demande), None)
            if point is None:
                raise RefusMeteo("entite", demande[:40])
        else:
            raise RefusMeteo("format")
        (mer, mer_panne), (vent, vent_panne) = await self._lire(self._mer), await self._lire(self._vent)
        if mer is None and vent is None:
            raise RefusMeteo("indisponible")
        maintenant = self._maintenant()
        local = self._locale(maintenant)
        heure_pleine = local.strftime("%Y-%m-%dT%H:00")
        donnees_point = next((p for p in (mer or {}).get("points") or [] if isinstance(p, dict) and p.get("id") == point["id"]),
                             None)
        heures = [h for h in (donnees_point or {}).get("heures") or [] if isinstance(h, dict)]
        a_venir = [h for h in heures if isinstance(h.get("t"), str) and h["t"] >= heure_pleine]
        panne = []
        if mer_panne:
            panne.append("Prévisions en mer indisponibles")
        if vent_panne:
            panne.append("Balises de vent indisponibles")
        for d in (mer, vent):
            for e in (d or {}).get("erreurs") or []:
                texte = _texte(e)
                if texte and texte not in panne:
                    panne.append(texte)
        soleil = next((s for s in (mer or {}).get("soleil") or [] if isinstance(s, dict)
                       and s.get("jour") == local.date().isoformat()), None)
        eau = _arrondi((mer or {}).get("eau"))
        return {"type": GENRE_METEO,
                "point": {"id": point["id"], "nom": point["nom"]},
                "points": [{"id": p["id"], "nom": p["nom"]} for p in points],
                "titre": _texte((mer or {}).get("titre")),
                "lu_a": _lu_a((mer, vent), self._locale),
                "maintenant": _heure(a_venir[0]) if a_venir else None,
                "heures": [_heure(h) for h in a_venir[:HEURES_MAX]],
                "jours": _jours(heures, local.date()),
                "eau": eau,
                "soleil": ({"lever": _texte(soleil.get("lever")), "coucher": _texte(soleil.get("coucher"))}
                           if soleil else None),
                "vagues_source": _texte((donnees_point or {}).get("vagues_source")),
                "balises": _balises_du_point(vent, point, maintenant.timestamp()),
                "sources_en_panne": panne[:6],
                "attribution": _texte(_mer().get("attribution"))}
