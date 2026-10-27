"""Écran Maison du client web (lots S-W4a et S-W4b) : ce qu'un navigateur associé voit de la maison et ce qu'il a le
droit de régler.

Ce module ne parle pas à Home Assistant lui-même. Le serveur lui injecte quatre fournisseurs (lecture des états,
relevé des mesures, appel d'un service, historique de l'air), ce qui le rend testable sans réseau. Il tient cinq choses :
- la liste des pièces, lampes et télévisions que chaque rôle peut voir (maison.json, client_web.maison), jamais en dur ;
- la vue « etats » filtrée par rôle : un appareil ne reçoit que les entités de la liste de son rôle, une pièce
  protégée n'est qu'une ligne, sans entité ni mesure ;
- le message « regler », à schéma strict : une entité de la liste du rôle, une action nommée, une valeur bornée.
  Le service Home Assistant est reconstruit ici, jamais recopié du navigateur, puis contrôlé par
  acces.controler_service (donc par securite.verifier) comme sur toutes les autres voies ;
- le suivi d'un réglage envoyé : « en attente » puis « non appliqué » si la lampe ne suit pas dans le délai fixé
  par client_web.maison.reglage_attente_s ;
- le volet de la télévision (S-W4b) : sources prises dans la liste que Home Assistant renvoie pour cette entité,
  lecture, pause, piste suivante et précédente, coupure du son, volume ;
- le message « air_historique » (S-W4b), réservé aux rôles qui ont les mesures : une pièce visible et non protégée, une
  durée de 1 à 168 heures, au plus 288 points par courbe. Les entités demandées à Home Assistant sont déduites
  de la pièce par historique_air.py, jamais lues dans le message.

Ce qu'il ne fait jamais : lire un identifiant, un service, une zone ou une liste dans le message du navigateur. Le
rôle et la personne viennent de la session. Le texte d'une exception ne part jamais vers le navigateur.
"""
import asyncio
import math
import re
import time

import acces
import demande_web
import historique_air as AH
import maison
import mesures as ME
import securite

GENRE_ETATS = "etats"
GENRE_REGLER = "regler"
GENRE_AIR = "air_historique"
GENRES = (GENRE_ETATS, GENRE_REGLER, GENRE_AIR)
ROLES = ("administrateur", "habitant", "invite")

# Causes renvoyées au navigateur (liste fermée, jamais un texte venu d'ailleurs).
CAUSES = frozenset({"droit", "format", "entite", "action", "valeur", "protegee", "securite", "injoignable",
                    "indisponible", "capteur"})

# Services Home Assistant que l'écran Maison peut déclencher, plus étroits que la liste blanche du LLM.
# Pour la télévision (S-W4b) : source, lecture et pause, piste suivante et précédente, coupure du son. Ni arrêt, ni
# avance rapide, ni lancement de média, ni saisie de texte (note lampes-tele.md, section 4).
SERVICES_WEB = {"light": frozenset({"turn_on", "turn_off"}),
                "media_player": frozenset({"turn_on", "turn_off", "volume_set", "select_source", "media_play_pause",
                                           "media_next_track", "media_previous_track", "volume_mute"})}
ACTIONS = {"light": frozenset({"allumer", "eteindre", "intensite", "blanc", "couleur"}),
           "media_player": frozenset({"allumer", "eteindre", "volume", "source", "lecture", "suivant", "precedent",
                                      "muet"})}
CLES_MESSAGE = frozenset({"type", "entite", "action", "valeur", "essai"})
CLES_AIR = frozenset({"type", "piece", "heures"})
# Commandes de la télévision qui supposent un appareil allumé : action -> (service Home Assistant, bit de
# supported_features, MediaPlayerEntityFeature, qui rend la commande possible).
COMMANDES_TELE = {"source": ("select_source", 2048), "lecture": ("media_play_pause", 1),
                  "suivant": ("media_next_track", 32), "precedent": ("media_previous_track", 16),
                  "muet": ("volume_mute", 8)}
SOURCES_MAX = 30
SOURCE_LONGUEUR_MAX = 80
CACHE_AIR_S = 60.0
CACHE_AIR_MAX = 32

# Quatre blancs nommés et huit couleurs nommées, les mêmes que sur la tablette (ReglageLampe.kt).
BLANCS = (("Bougie", 2200), ("Chaud", 2700), ("Neutre", 4000), ("Froid", 6000))
TEINTES = (("Rouge", 0), ("Orange", 30), ("Jaune", 55), ("Vert", 120), ("Cyan", 180), ("Bleu", 220),
           ("Violet", 275), ("Rose", 330))
KELVIN_MIN_DEFAUT = 2700      # plage supposée d'une lampe qui ne dit pas la sienne
KELVIN_MAX_DEFAUT = 6500
KELVIN_ABSOLU = (1000, 10000)  # au-delà, ce n'est plus un réglage de lampe
TOLERANCE_KELVIN = 100
TOLERANCE_TEINTE = 8           # degrés de teinte, comptés par le plus court chemin (359 est proche de 0)
TOLERANCE_INTENSITE = 6        # points de pourcentage, la luminosité de Home Assistant va de 0 à 255

ATTENTE_DEFAUT_S = 5
ATTENTE_MAX_S = 60
OUBLI_REGLAGE_S = 300          # un réglage non appliqué n'est plus signalé au bout de ce délai
CACHE_ETATS_S = 1.0            # plusieurs navigateurs qui interrogent ne multiplient pas les lectures
CACHE_MESURES_S = 60.0

ID_PIECE = re.compile(r"[a-z0-9_]{1,40}")
ID_LUMIERE = re.compile(r"light\.[a-z0-9_]{1,80}")
ID_TELE = re.compile(r"media_player\.[a-z0-9_]{1,80}")
MODES_COULEUR = frozenset({"hs", "xy", "rgb", "rgbw", "rgbww"})
INJOIGNABLE = frozenset({"unavailable", "unknown", ""})


class RefusMaison(Exception):
    """Un message de la maison refusé avant d'avoir touché à quoi que ce soit."""

    def __init__(self, cause, entite=None):
        assert cause in CAUSES, cause
        super().__init__(cause)
        self.cause = cause
        self.entite = entite


# ------------------------------------------------------------------ configuration
def _section():
    m = maison.CLIENT_WEB.get("maison")
    return m if isinstance(m, dict) else {}


def attente_s():
    """Délai avant de dire qu'un réglage n'a pas été appliqué (client_web.maison.reglage_attente_s)."""
    return min(maison.entier(_section(), "reglage_attente_s", ATTENTE_DEFAUT_S), ATTENTE_MAX_S)


def pieces_configurees(section=None):
    """Pièces de client_web.maison.pieces, dans l'ordre de la configuration : [{id, nom, lumieres, tele, protegee}].
    Une entrée mal formée, un identifiant en double ou une entité d'un autre domaine est ignoré, jamais corrigé."""
    section = _section() if section is None else section
    brutes = section.get("pieces")
    sortie, vus = [], set()
    for p in brutes if isinstance(brutes, list) else []:
        if not isinstance(p, dict):
            continue
        ident, nom = p.get("id"), p.get("nom")
        if not isinstance(ident, str) or not ID_PIECE.fullmatch(ident) or ident in vus:
            continue
        if not isinstance(nom, str) or not nom.strip():
            continue
        lumieres = [e for e in (p.get("lumieres") if isinstance(p.get("lumieres"), list) else [])
                    if isinstance(e, str) and ID_LUMIERE.fullmatch(e)]
        tele = p.get("tele") if isinstance(p.get("tele"), str) and ID_TELE.fullmatch(p.get("tele")) else None
        vus.add(ident)
        sortie.append({"id": ident, "nom": nom.strip()[:60], "lumieres": list(dict.fromkeys(lumieres)),
                       "tele": tele, "protegee": p.get("protegee") is True})
    return sortie


def piece_protegee(piece, corresp=None):
    """Vrai si la configuration marque la pièce protégée, ou si la règle de l'occupant est active et qu'une zone de
    la pièce (correspondance_pieces) est une zone protégée. La liste des zones vient de securite.py."""
    if piece["protegee"]:
        return True
    if not securite.PROTEGER_OCCUPANT:
        return False
    corresp = ME.correspondance(maison.CONFIG) if corresp is None else corresp
    return any(z in securite.ZONES_PROTEGEES for z in corresp.get(piece["id"], []))


def droits(role, section=None):
    """Ce que ce rôle voit : {pieces: ensemble d'identifiants ou None pour toutes, mesures, tele}. Sans section
    roles, un propriétaire et un habitant voient tout, l'invité rien. Un rôle inconnu ne voit rien."""
    section = _section() if section is None else section
    if role not in ROLES:
        return {"pieces": set(), "mesures": False, "tele": False}
    roles = section.get("roles")
    d = roles.get(role) if isinstance(roles, dict) else None
    if not isinstance(d, dict):
        large = role != "invite"
        return {"pieces": None if large else set(), "mesures": large, "tele": large}
    p = d.get("pieces")
    if p == "toutes":
        pieces = None
    elif isinstance(p, list):
        pieces = {x for x in p if isinstance(x, str)}
    else:
        pieces = set()
    return {"pieces": pieces, "mesures": d.get("mesures") is True, "tele": d.get("tele") is True}


def nom_court(entite):
    noms = (maison.CONFIG.get("appareils") or {}).get("noms_courts")
    n = noms.get(entite) if isinstance(noms, dict) else None
    return n.strip()[:60] if isinstance(n, str) and n.strip() else entite.split(".", 1)[1].replace("_", " ").capitalize()


# ------------------------------------------------------------------ calculs sur une lampe
def ecart_teinte(a, b):
    """Écart en degrés entre deux teintes, par le plus court chemin autour du cercle (359 et 0 sont voisines)."""
    d = abs(float(a) - float(b)) % 360
    return min(d, 360 - d)


def mot_chaleur(kelvin):
    if kelvin < 2450:
        return "bougie"
    if kelvin < 3300:
        return "chaud"
    if kelvin < 4800:
        return "neutre"
    return "froid"


def nom_teinte(teinte):
    """Nom de la couleur nommée la plus proche d'une teinte."""
    return min(TEINTES, key=lambda t: ecart_teinte(t[1], teinte))[0].lower()


def _nombre(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fini(v):
    """Le nombre, ou None s'il n'est pas un nombre fini (ni NaN, ni infini)."""
    n = _nombre(v)
    return n if n is not None and math.isfinite(n) else None


def _entier(v):
    n = _fini(v)
    return int(n) if n is not None and n == int(n) else None


def vue_lampe(entite, etat):
    """Ce que le navigateur voit d'une lampe, d'après son état Home Assistant (dict {state, attributes}) ou None."""
    base = {"entite": entite, "nom": nom_court(entite)}
    s = str((etat or {}).get("state") or "").lower() if isinstance(etat, dict) else ""
    attrs = etat.get("attributes") if isinstance(etat, dict) and isinstance(etat.get("attributes"), dict) else {}
    if s in INJOIGNABLE or s not in ("on", "off"):
        return {**base, "statut": "injoignable", "allumee": False, "texte": "Injoignable", "intensite": None,
                "kelvin": None, "teinte": None, "mode": None, "blanc": False, "couleur": False,
                "kmin": KELVIN_MIN_DEFAUT, "kmax": KELVIN_MAX_DEFAUT}
    modes = attrs.get("supported_color_modes")
    modes = {m for m in modes if isinstance(m, str)} if isinstance(modes, list) else set()
    blanc = "color_temp" in modes
    couleur = bool(modes & MODES_COULEUR)
    kmin, kmax = _bornes_kelvin(attrs)
    allumee = s == "on"
    mode_ha = attrs.get("color_mode")
    luminosite = _nombre(attrs.get("brightness"))
    intensite = max(0, min(100, round(luminosite / 2.55))) if allumee and luminosite is not None else None
    kelvin = teinte = mode = None
    if allumee and mode_ha == "color_temp" and _nombre(attrs.get("color_temp_kelvin")) is not None:
        kelvin, mode = int(attrs["color_temp_kelvin"]), "blanc"
    elif allumee and mode_ha in MODES_COULEUR:
        hs = attrs.get("hs_color")
        if isinstance(hs, (list, tuple)) and hs and _nombre(hs[0]) is not None:
            teinte, mode = int(round(hs[0])) % 360, "couleur"
    if not allumee:
        texte = "Éteinte"
    else:
        parties = [f"{intensite} %"] if intensite is not None else ["Allumée"]
        if mode == "blanc":
            parties += [f"{kelvin} K", mot_chaleur(kelvin)]
        elif mode == "couleur":
            parties.append(nom_teinte(teinte))
        texte = ", ".join(parties)
    return {**base, "statut": "ok", "allumee": allumee, "texte": texte, "intensite": intensite, "kelvin": kelvin,
            "teinte": teinte, "mode": mode, "blanc": blanc, "couleur": couleur,
            "reglable": any(m != "onoff" for m in modes), "kmin": kmin, "kmax": kmax}


def _bornes_kelvin(attrs):
    kmin, kmax = _entier(attrs.get("min_color_temp_kelvin")), _entier(attrs.get("max_color_temp_kelvin"))
    if kmin is None or kmax is None or not KELVIN_ABSOLU[0] <= kmin < kmax <= KELVIN_ABSOLU[1]:
        return KELVIN_MIN_DEFAUT, KELVIN_MAX_DEFAUT
    return kmin, kmax


def sources_de_ha(attrs):
    """Les sources que Home Assistant annonce pour cet appareil (source_list), bornées : seule source de vérité de
    select_source. Un texte vide, trop long ou en double est ignoré."""
    liste = attrs.get("source_list")
    vues = []
    for x in liste if isinstance(liste, list) else []:
        if isinstance(x, str) and x.strip() and len(x) <= SOURCE_LONGUEUR_MAX and x not in vues:
            vues.append(x)
    return vues[:SOURCES_MAX]


def sources_proposees(attrs):
    """Tuiles de source du volet : [{nom, source}]. Les noms de reglages.tele.sources (maison.json) ne servent que
    pour les sources que Home Assistant annonce. Sans tuile reconnue, la liste annoncée sert telle quelle."""
    annoncees = sources_de_ha(attrs)
    tele = (maison.CONFIG.get("reglages") or {}).get("tele")
    brutes = tele.get("sources") if isinstance(tele, dict) else None
    tuiles = []
    for t in brutes if isinstance(brutes, list) else []:
        if isinstance(t, dict) and isinstance(t.get("nom"), str) and t["nom"].strip() \
                and t.get("source") in annoncees and all(t["source"] != u["source"] for u in tuiles):
            tuiles.append({"nom": t["nom"].strip()[:30], "source": t["source"]})
    return tuiles or [{"nom": x[:30], "source": x} for x in annoncees]


def _peut(attrs, cle):
    """Vrai si l'appareil sait faire cette commande : le bit de supported_features, ou oui quand il ne le dit pas."""
    bit = COMMANDES_TELE[cle][1]
    f = attrs.get("supported_features")
    return True if isinstance(f, bool) or not isinstance(f, int) else bool(f & bit)


def vue_tele(entite, etat):
    base = {"entite": entite, "nom": nom_court(entite)}
    s = str((etat or {}).get("state") or "").lower() if isinstance(etat, dict) else ""
    attrs = etat.get("attributes") if isinstance(etat, dict) and isinstance(etat.get("attributes"), dict) else {}
    if s in INJOIGNABLE:
        return {**base, "statut": "injoignable", "allumee": False, "texte": "Injoignable", "volume": None,
                "sources": [], "source": None, "lecture": None, "muet": None, "peut": {}}
    allumee = s != "off"
    niveau = _nombre(attrs.get("volume_level"))
    volume = max(0, min(100, round(niveau * 100))) if allumee and niveau is not None else None
    texte = "Éteinte" if not allumee else (f"Allumée, volume {volume} %" if volume is not None else "Allumée")
    source = attrs.get("source")
    muet = attrs.get("is_volume_muted")
    return {**base, "statut": "ok", "allumee": allumee, "texte": texte, "volume": volume,
            "sources": sources_proposees(attrs) if allumee else [],
            "source": source if allumee and isinstance(source, str) and len(source) <= SOURCE_LONGUEUR_MAX else None,
            "lecture": {"playing": "lecture", "paused": "pause"}.get(s) if allumee else None,
            "muet": muet if allumee and isinstance(muet, bool) else None,
            "peut": {c: _peut(attrs, c) for c in COMMANDES_TELE} if allumee else {}}


def conforme(cible, etat):
    """Vrai si l'état de la lampe correspond à ce qui a été demandé. cible : {allumee, intensite?, kelvin?, teinte?}.
    Intensité à 6 points près, kelvins à 100 K près, teinte à 8 degrés près par le plus court chemin. Un blanc
    demandé n'est pas satisfait par une lampe qui reste en couleur, et inversement."""
    if not isinstance(etat, dict):
        return False
    s = str(etat.get("state") or "").lower()
    if not cible.get("allumee"):
        return s == "off"
    if s != "on":
        return False
    attrs = etat.get("attributes") if isinstance(etat.get("attributes"), dict) else {}
    if cible.get("intensite") is not None:
        b = _nombre(attrs.get("brightness"))
        if b is None or abs(b / 2.55 - cible["intensite"]) > TOLERANCE_INTENSITE:
            return False
    if cible.get("kelvin") is not None:
        k = _nombre(attrs.get("color_temp_kelvin"))
        if attrs.get("color_mode") != "color_temp" or k is None or abs(k - cible["kelvin"]) > TOLERANCE_KELVIN:
            return False
    if cible.get("teinte") is not None:
        hs = attrs.get("hs_color")
        if attrs.get("color_mode") not in MODES_COULEUR or not isinstance(hs, (list, tuple)) or not hs \
                or _nombre(hs[0]) is None or ecart_teinte(hs[0], cible["teinte"]) > TOLERANCE_TEINTE:
            return False
    return True


# ------------------------------------------------------------------ le service
class Maison:
    """Vue et réglages de la maison pour le client web.

    etats : coroutine (liste d'entités) rendant {entité: {state, attributes}} (les entités absentes manquent).
    mesures : coroutine sans argument rendant {lu_a, pieces: {id: mesures}} ou None.
    appeler : coroutine (domaine, service, corps, essai) rendant « envoye » ou « essai », qui lève si Home Assistant
      ne répond pas.
    essai_serveur : fonction sans argument, vraie quand le serveur entier est en mode essai.
    historique : coroutine (pièce, heures) rendant la réponse de historique_air.mettre_en_forme, qui lève
      historique_air.ErreurAir pour une pièce sans capteur. Facultatif : sans lui, le graphique est indisponible.
    """

    def __init__(self, etats, mesures, appeler, essai_serveur=lambda: False, horloge=time.monotonic, historique=None):
        self._lire_etats = etats
        self._lire_mesures = mesures
        self._appeler = appeler
        self._lire_air = historique
        self._cache_air = {}   # (pièce, heures) -> (instant, réponse)
        self.essai_serveur = essai_serveur
        self.horloge = horloge
        self._cache_etats = (None, {})
        self._cache_mesures = (None, None)
        self._verrou_lecture = asyncio.Lock()
        self._verrous = {}
        self.attendus = {}   # entité -> {cible, depuis}

    # Lecture
    @staticmethod
    def entites_lues():
        """Les entités lues dans Home Assistant : celles de la configuration, jamais celles d'une pièce protégée."""
        corresp = ME.correspondance(maison.CONFIG)
        entites = []
        for p in pieces_configurees():
            if not piece_protegee(p, corresp):
                entites += p["lumieres"] + ([p["tele"]] if p["tele"] else [])
        return list(dict.fromkeys(entites))

    async def _etats(self):
        t, valeur = self._cache_etats
        if t is not None and self.horloge() - t < CACHE_ETATS_S:
            return valeur
        async with self._verrou_lecture:
            t, valeur = self._cache_etats
            if t is not None and self.horloge() - t < CACHE_ETATS_S:
                return valeur
            try:
                valeur = await self._lire_etats(self.entites_lues())
            except Exception as e:
                print(f"Maison web : lecture des états en échec ({type(e).__name__})")
                valeur = None
            if not isinstance(valeur, dict):
                valeur = {}
            self._cache_etats = (self.horloge(), valeur)
            return valeur

    async def _mesures(self):
        t, valeur = self._cache_mesures
        if t is not None and self.horloge() - t < CACHE_MESURES_S:
            return valeur
        try:
            valeur = await self._lire_mesures()
        except Exception as e:
            print(f"Maison web : lecture des mesures en échec ({type(e).__name__})")
            valeur = None
        self._cache_mesures = (self.horloge(), valeur if isinstance(valeur, dict) else None)
        return self._cache_mesures[1]

    def _pieces_du_role(self, role):
        """Pièces que ce rôle voit, protégées comprises, dans l'ordre de la configuration."""
        d = droits(role)
        corresp = ME.correspondance(maison.CONFIG)
        pieces = []
        for p in pieces_configurees():
            if d["pieces"] is not None and p["id"] not in d["pieces"]:
                continue
            pieces.append({**p, "protegee": piece_protegee(p, corresp)})
        return pieces, d

    async def etats_pour(self, role):
        """Vue « etats » pour un rôle : seulement ses pièces, seulement ses entités, mesures si son rôle y a droit."""
        pieces, d = self._pieces_du_role(role)
        etats = await self._etats() if any(not p["protegee"] for p in pieces) else {}
        lu = await self._mesures() if d["mesures"] and any(not p["protegee"] for p in pieces) else None
        sortie, alertes = [], []
        for p in pieces:
            if p["protegee"]:  # une seule ligne : ni entité, ni mesure, ni nom d'appareil
                sortie.append({"id": p["id"], "nom": p["nom"], "protegee": True, "lumieres": [], "tele": None,
                               "mesures": None})
                continue
            lampes = [self._lampe_avec_suivi(e, etats.get(e)) for e in p["lumieres"]]
            tele = vue_tele(p["tele"], etats.get(p["tele"])) if p["tele"] and d["tele"] else None
            m = self._mesures_de(p, lu) if d["mesures"] else None
            if m and m.get("alerte"):
                alertes.append({"piece": p["id"], "texte": m["alerte"], "couleur": m.get("couleur")})
            sortie.append({"id": p["id"], "nom": p["nom"], "protegee": False, "lumieres": lampes, "tele": tele,
                           "mesures": m})
        return {"type": "etats", "configure": bool(pieces_configurees()), "essai": bool(self.essai_serveur()),
                "attente_s": attente_s(), "mesures_visibles": d["mesures"], "lu_a": (lu or {}).get("lu_a"),
                "alertes": alertes, "pieces": sortie}

    @staticmethod
    def _mesures_de(piece, lu):
        if lu is None:
            return {"statut": "absente", "texte": "mesures indisponibles pour le moment", "alerte": ""}
        m = (lu.get("pieces") or {}).get(piece["id"])
        if not isinstance(m, dict):
            return {"statut": "aucun", "texte": "pas de capteur", "alerte": ""}
        return {k: m.get(k) for k in ("statut", "texte", "couleur", "temperature", "humidite", "co2", "pm25", "air",
                                      "alerte")}

    def _lampe_avec_suivi(self, entite, etat):
        v = vue_lampe(entite, etat)
        a = self.attendus.get(entite)
        v["reglage"] = None
        if a is None:
            return v
        ecoule = self.horloge() - a["depuis"]
        if v["statut"] == "injoignable":
            v["reglage"] = "non_applique" if ecoule >= attente_s() else "en_attente"
        elif conforme(a["cible"], etat):
            del self.attendus[entite]
        elif ecoule >= OUBLI_REGLAGE_S:
            del self.attendus[entite]
        else:
            v["reglage"] = "non_applique" if ecoule >= attente_s() else "en_attente"
        return v

    # Réglage
    def _entite_permise(self, role, entite):
        """(pièce, domaine) de l'entité si ce rôle peut la régler. Lève « protegee » pour une pièce protégée de sa
        liste, « entite » pour tout le reste (y compris les pièces qu'il ne voit pas : rien n'est révélé)."""
        if not isinstance(entite, str):
            raise RefusMaison("entite")
        pieces, d = self._pieces_du_role(role)
        for p in pieces:
            if entite in p["lumieres"] or (entite == p["tele"] and d["tele"]):
                if p["protegee"]:
                    raise RefusMaison("protegee", entite)
                return p, entite.split(".", 1)[0]
        raise RefusMaison("entite", entite)

    def corps_service(self, domaine, action, valeur, etat):
        """(service, corps, cible) reconstruits par le serveur d'après une action nommée et une valeur bornée.
        cible : ce que la lampe doit montrer ensuite (None pour une télévision)."""
        if action not in ACTIONS[domaine]:
            raise RefusMaison("action")
        if action in ("allumer", "eteindre"):
            if valeur is not None:
                raise RefusMaison("valeur")
            if domaine == "light":
                return ("turn_on" if action == "allumer" else "turn_off"), {}, {"allumee": action == "allumer"}
            return ("turn_on" if action == "allumer" else "turn_off"), {}, None
        if action == "volume":
            v = _entier(valeur)
            if v is None or not 0 <= v <= 100:
                raise RefusMaison("valeur")
            return "volume_set", {"volume_level": v / 100}, None
        attrs = etat.get("attributes") if isinstance(etat, dict) and isinstance(etat.get("attributes"), dict) else {}
        if domaine == "media_player":   # source, lecture, suivant, precedent, muet (ACTIONS filtre le reste)
            service = COMMANDES_TELE[action][0]
            if not _peut(attrs, action):
                raise RefusMaison("action")
            if action == "source":
                if not isinstance(valeur, str) or valeur not in sources_de_ha(attrs):
                    raise RefusMaison("valeur")   # seulement une source que Home Assistant annonce pour cette entité
                return service, {"source": valeur}, None
            if action == "muet":
                if not isinstance(valeur, bool):
                    raise RefusMaison("valeur")
                return service, {"is_volume_muted": valeur}, None
            if valeur is not None:
                raise RefusMaison("valeur")
            return service, {}, None
        modes = attrs.get("supported_color_modes")
        modes = {m for m in modes if isinstance(m, str)} if isinstance(modes, list) else set()
        if action == "intensite":
            v = _entier(valeur)
            if v is None or not 0 <= v <= 100:
                raise RefusMaison("valeur")
            if v == 0:
                return "turn_off", {}, {"allumee": False}
            if not any(m != "onoff" for m in modes):
                raise RefusMaison("valeur")
            return "turn_on", {"brightness_pct": v}, {"allumee": True, "intensite": v}
        if action == "blanc":
            k = _entier(valeur)
            kmin, kmax = _bornes_kelvin(attrs)
            if "color_temp" not in modes or k is None or not kmin <= k <= kmax:
                raise RefusMaison("valeur")
            return "turn_on", {"color_temp_kelvin": k}, {"allumee": True, "kelvin": k}
        # couleur : un nom de la liste, ou une teinte de 0 à 360 degrés
        if isinstance(valeur, str):
            noms = {n.lower(): t for n, t in TEINTES}
            teinte = noms.get(valeur.strip().lower())
        else:
            teinte = _entier(valeur)
            if teinte is not None and not 0 <= teinte <= 360:
                teinte = None
        if teinte is None or not modes & MODES_COULEUR:
            raise RefusMaison("valeur")
        teinte %= 360
        return "turn_on", {"hs_color": [teinte, 100]}, {"allumee": True, "teinte": teinte}

    async def regler(self, role, personne, msg):
        """Applique un réglage ou le refuse (RefusMaison). Rend {type: regle, entite, statut: envoye|essai}.
        Comme pour les demandes (S-W3), un message sans « essai » vaut essai : seul « essai: false » agit."""
        if role not in ROLES:
            raise RefusMaison("droit")
        if not isinstance(msg, dict) or not set(msg) <= CLES_MESSAGE:
            raise RefusMaison("format")
        entite = msg.get("entite")
        _, domaine = self._entite_permise(role, entite)
        action = msg.get("action")
        if not isinstance(action, str):
            raise RefusMaison("action", entite)
        etat = (await self._etats()).get(entite)
        if domaine == "light" and action not in ("eteindre",):
            s = str((etat or {}).get("state") or "").lower() if isinstance(etat, dict) else ""
            if s not in ("on", "off"):
                raise RefusMaison("injoignable", entite)
        if domaine == "media_player" and action in COMMANDES_TELE:
            s = str((etat or {}).get("state") or "").lower() if isinstance(etat, dict) else ""
            if s in INJOIGNABLE:
                raise RefusMaison("injoignable", entite)
            if s == "off":
                raise RefusMaison("action", entite)   # une télévision éteinte ne change pas de source
        try:
            service, corps, cible = self.corps_service(domaine, action, msg.get("valeur"), etat)
        except RefusMaison as e:
            e.entite = entite
            raise
        corps["entity_id"] = entite   # la seule cible, posée ici : le navigateur n'en fournit aucune
        refus = acces.controler_service(domaine, service, corps, personne=personne,
                                        services_permis=SERVICES_WEB[domaine])
        if refus:
            raise RefusMaison("securite", entite)
        essai = demande_web.essai_du_message(msg) or bool(self.essai_serveur())
        verrou = self._verrous.setdefault(entite, asyncio.Lock())
        async with verrou:
            try:
                statut = await self._appeler(domaine, service, corps, essai)
            except Exception as e:
                print(f"Maison web : appel {domaine}.{service} en échec ({type(e).__name__})")
                raise RefusMaison("injoignable", entite)
        if statut == "envoye" and cible is not None:
            self.attendus[entite] = {"cible": cible, "depuis": self.horloge()}
        self._cache_etats = (None, self._cache_etats[1])   # la prochaine lecture est fraîche
        return {"type": "regle", "entite": entite, "statut": "essai" if statut == "essai" else "envoye"}

    # Historique de l'air (S-W4b)
    async def air_historique(self, role, msg):
        """Courbes de l'air d'une pièce : {type: air, piece, heures, debut, fin, pas, series}. Réservé aux rôles qui ont
        les mesures. Une pièce que le rôle ne voit pas est « entite » (rien n'est révélé), une pièce protégée est
        « protegee », une pièce sans capteur est « capteur ». La durée est un entier de 1 à 168 heures, absente : 24 h."""
        if role not in ROLES or not droits(role)["mesures"]:
            raise RefusMaison("droit")
        if not isinstance(msg, dict) or not set(msg) <= CLES_AIR:
            raise RefusMaison("format")
        piece = msg.get("piece")
        if not isinstance(piece, str) or not ID_PIECE.fullmatch(piece):
            raise RefusMaison("entite")
        h = msg.get("heures", AH.DUREE_DEFAUT_H)
        if isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= AH.DUREE_MAX_H:
            raise RefusMaison("valeur", piece)
        pieces, _ = self._pieces_du_role(role)
        voulue = next((p for p in pieces if p["id"] == piece), None)
        if voulue is None:
            raise RefusMaison("entite", piece)
        if voulue["protegee"]:
            raise RefusMaison("protegee", piece)
        if self._lire_air is None:
            raise RefusMaison("indisponible", piece)
        t, rep = self._cache_air.get((piece, h), (None, None))
        if t is not None and self.horloge() - t < CACHE_AIR_S:
            return rep
        try:
            brut = await self._lire_air(piece, h)
        except AH.ErreurAir:
            raise RefusMaison("capteur", piece)
        except Exception as e:
            print(f"Maison web : historique de l'air en échec ({type(e).__name__})")
            raise RefusMaison("indisponible", piece)
        rep = self._air_propre(piece, h, brut)
        if rep is None:
            raise RefusMaison("indisponible", piece)
        if len(self._cache_air) >= CACHE_AIR_MAX:
            self._cache_air.clear()
        self._cache_air[(piece, h)] = (self.horloge(), rep)
        return rep

    @staticmethod
    def _air_propre(piece, h, brut):
        """La réponse reconstruite champ par champ : seules les quatre grandeurs connues, au plus POINTS_MAX points
        par courbe, des couples de nombres finis. Rend None si la forme n'est pas celle attendue."""
        if not isinstance(brut, dict) or not isinstance(brut.get("series"), dict):
            return None
        entiers = {}
        for cle in ("debut", "fin", "pas"):
            v = _entier(brut.get(cle))
            if v is None or v < 0:
                return None
            entiers[cle] = v
        series = {}
        for cle in AH.GRANDEURS.values():
            pts = brut["series"].get(cle)
            if not isinstance(pts, list):
                continue
            propres = []
            for pt in pts[:AH.POINTS_MAX]:
                if isinstance(pt, (list, tuple)) and len(pt) == 2 and _fini(pt[0]) is not None \
                        and _fini(pt[1]) is not None and 0 <= pt[0] < 1e11 and abs(pt[1]) < 1e9:
                    propres.append([int(pt[0]), pt[1]])
            series[cle] = propres
        return {"type": "air", "piece": piece, "heures": h, **entiers, "series": series}
