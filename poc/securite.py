"""Sécurité écrite en dur, demandée le 13/10/2026. À ne lever qu'à la demande explicite du propriétaire.

Les noms et les listes propres à la maison (occupant protégé, zones, entités, lecteurs de son, fuseau)
viennent de la configuration de la maison (maison.json du dossier de configuration, modèle config-exemple/, voir maison.py).
Ci-dessous, « l'occupant » est la personne nommée par `nom_occupant`.

1. L'assistant ne touche JAMAIS à ce qui appartient à l'occupant : sa chambre, sa salle de bain, ses
   lumières, ses réveils, ses automatisations, ses scripts, son téléphone. Interdit aussi : viser
   « all », une zone de l'occupant, ou un appareil par son identifiant (on ne sait pas ce qu'il contient).
2. Aucun son dans le salon (séjour, cuisine ouverte, enceintes de l'appartement) pendant les heures
   calmes (`heures_calmes`, de minuit à 9 h par défaut) : seuls éteindre, mettre en pause, arrêter, baisser et couper le son restent permis.

3. Exception décidée le 21/10/2026 : quand la tablette reconnaît l'occupant, seul devant elle,
   l'assistant peut allumer, éteindre et régler ses lumières à lui (`permis_personne` de la configuration),
   et rien d'autre de ce qui lui appartient (réveil, automatisations, scripts, salle de bain, téléphone).
   Quand c'est quelqu'un d'autre qui parle, ou qu'on ne sait pas qui parle, la règle 1 reste entière.

Levée le 22/10/2026 à la demande explicite du propriétaire : les règles 1 et 2 sont coupées
(PROTEGER_OCCUPANT et HEURE_CALME_ACTIVE à False). L'assistant peut piloter ce qui appartient à l'occupant et
mettre du son à toute heure. Restent actifs : le refus de viser un appareil par son identifiant brut,
le plafond de volume quand la configuration en règle un (securite.plafond_volume, verifier() l'applique sur
place, comme Securite.kt) et, dans assistant.py, la liste blanche des services du LLM.
Levée complète le 27/10/2026, à la demande explicite du propriétaire (l'occupant se sert aussi de l'assistant) :
PROTEGER_OCCUPANT gouverne désormais tout ce qui le concerne, y compris les mesures de ses pièces (zones_protegees) et
les mots qui fermaient le repli Assist. À False, rien n'est caché ni refusé à cause de lui.
Remettre une règle : repasser son drapeau à True ici ET dans Securite.kt (les tests communs suivent).

Même règles, mêmes listes, dans l'appli Android (android/app/src/main/java/assistant/vocal/jarvis/Securite.kt).
Assist de Home Assistant agit sans qu'on puisse vérifier sa cible avant : il est sauté tant que
SECURITE_ACTIVE est vrai, une phrase inconnue va directement au LLM dont chaque action passe ici. Depuis S-D9
(26/10/2026), le réglage securite.assist_repli peut rouvrir Assist comme repli quand le LLM échoue, seulement
pour une phrase que refus_phrase_assist ne refuse pas (en bas de ce fichier), jamais en levant SECURITE_ACTIVE.
"""
import math

import maison

# L'app HA tourne en UTC : l'heure calme se compte toujours à l'heure du fuseau de la maison (maison.maintenant).
FUSEAU = maison.ZONE

SECURITE_ACTIVE = True
# Levées le 22/10/2026 à la demande du propriétaire (voir en tête). À True, chaque règle revient telle quelle.
PROTEGER_OCCUPANT = False
HEURE_CALME_ACTIVE = False

# Nom de l'occupant protégé, tel qu'il s'affiche dans les refus.
NOM_OCCUPANT = str(maison.SECURITE.get("nom_occupant") or "l'occupant")
# Tout identifiant qui contient l'un de ces mots est intouchable.
MOTS_PROTEGES = tuple(m.lower() for m in maison.liste("mots_proteges"))
# Mots d'un nom de pièce qui la rendent protégée (par défaut, les mêmes que MOTS_PROTEGES).
MOTS_PIECES = tuple(m.lower() for m in maison.liste("mots_pieces")) or MOTS_PROTEGES
# Zones de l'occupant dans HA, et entités de ces zones dont l'identifiant ne dit pas son nom
# (par exemple des boutons de sa chambre, l'automatisation de son réveil, « tout éteindre » qui vise
# toutes les lumières, les siennes comprises).
ZONES_PROTEGEES = {z.lower() for z in maison.liste("zones_protegees")}
ENTITES_PROTEGEES = {e.lower() for e in maison.liste("entites_protegees")}

# Son dans le salon : lecteurs du séjour et de l'appartement entier, scripts de musique.
SON_SALON = set(maison.liste("son_salon"))
SERVICES_SILENCIEUX = {"media_player.turn_off", "media_player.media_pause", "media_player.media_stop",
                       "media_player.volume_down", "media_player.volume_mute", "script.turn_off"}
HEURE_CALME_DEBUT = int((maison.SECURITE.get("heures_calmes") or {}).get("debut", 0))
HEURE_CALME_FIN = int((maison.SECURITE.get("heures_calmes") or {}).get("fin", 9))


def en_heure_calme(heure, debut, fin):
    """Vrai si [heure] (0 à 23) tombe dans la plage calme [debut, fin[. Une plage qui passe minuit (début après
    la fin, par exemple 22 h à 7 h) couvre la soirée et le début de matinée. Début égal à la fin : plage vide.
    Même calcul que Securite.enHeureCalme (cas communs « heures_calmes »)."""
    if debut <= fin:
        return debut <= heure < fin
    return heure >= debut or heure < fin


# Plage dite dans le refus, tirée de heures_calmes (0.27.3, « entre minuit et 9 h » était écrit en dur).
PLAGE_CALME = "entre {} et {}".format(*("minuit" if h % 24 == 0 else f"{h} h" for h in (HEURE_CALME_DEBUT, HEURE_CALME_FIN)))

# Plafond du volume, réglé dans la configuration : securite.plafond_volume, en pourcentage, 100 par défaut
# (aucun plafond). Le 12/10, « Mets le salon à fond » avait mis la Enceintes au maximum (en essai, rien n'est
# parti), d'où un plafond fixe le 22/10/2026, rendu réglable le 25/10/2026 à la demande du propriétaire.
# Une valeur illisible garde un plafond prudent (PLAFOND_SI_ILLISIBLE), pour qu'une faute de frappe ne lève
# pas un plafond voulu. Même lecture dans Securite.kt (cas communs « plafonds_configures »).
PLAFOND_SI_ILLISIBLE = 50.0


def plafond_configure(valeur):
    """Plafond du volume en pourcentage (0 à 100) d'après la valeur de securite.plafond_volume.
    Absente (ou null) : 100, aucun plafond. Un nombre est borné entre 0 et 100. Autre chose (texte,
    vrai ou faux, NaN) : PLAFOND_SI_ILLISIBLE."""
    if valeur is None:
        return 100.0
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or valeur != valeur:
        return PLAFOND_SI_ILLISIBLE
    return min(max(float(valeur), 0.0), 100.0)


# Volume le plus fort permis, de 0 à 1 (même calcul que VOLUME_MAX de Securite.kt). 1 : aucun plafond.
VOLUME_MAX = plafond_configure(maison.SECURITE.get("plafond_volume")) / 100


def plafond_actif():
    """Vrai quand la configuration règle un plafond (moins de 100 %)."""
    return VOLUME_MAX < 1.0


def pourcentage(niveau):
    """0.5 donne « 50 », 0.725 donne « 72,5 » : un volume de 0 à 1 dit en pourcentage."""
    # Arrondi au dixième, le demi vers le haut comme Math.round de Securite.kt (round() de Python arrondit au pair).
    p = math.floor(niveau * 1000 + 0.5) / 10
    return str(int(p)) if p == int(p) else str(p).replace(".", ",")

# Exception de la règle 3 : ce que la personne reconnue peut piloter chez elle, et rien de plus.
PERMIS_PERSONNE = {
    cle.lower(): {"entites": set(d.get("entites") or []), "services": set(d.get("services") or [])}
    for cle, d in (maison.SECURITE.get("permis_personne") or {}).items()
}


def personne_normalisee(personne):
    """« Camille », « camille », « Camille  » donnent « camille ». Rien si on ne sait pas qui parle."""
    import unicodedata
    if not personne:
        return ""
    p = unicodedata.normalize("NFKD", str(personne)).encode("ascii", "ignore").decode().strip().lower()
    return p


def permis_pour(personne, service, entite):
    """Vrai si cette personne reconnue a le droit d'agir sur cette entité à elle (règle 3)."""
    droits = PERMIS_PERSONNE.get(personne_normalisee(personne))
    return bool(droits) and service in droits["services"] and entite in droits["entites"]


def entites_permises(personne):
    """Entités de l'occupant que cette personne reconnue peut piloter (règle 3), vide sinon.
    Sert à les montrer au LLM seulement quand c'est elle qui parle."""
    droits = PERMIS_PERSONNE.get(personne_normalisee(personne))
    return set(droits["entites"]) if droits else set()


def cibles(valeur):
    if valeur is None:
        return []
    if isinstance(valeur, str):
        return [v.strip() for v in valeur.split(",") if v.strip()]
    return [str(v).strip() for v in valeur]


def piece_protegee(piece):
    """Vrai pour une pièce (nom lu dans HA) qui appartient à l'occupant, tant que la règle 1 est active."""
    return PROTEGER_OCCUPANT and any(m in str(piece).lower() for m in MOTS_PIECES)


def protege(entite):
    if not PROTEGER_OCCUPANT:
        return False
    e = entite.lower()
    return e in ENTITES_PROTEGEES or any(m in e for m in MOTS_PROTEGES)


def plafonner_volume(niveau):
    """Niveau de volume (0 à 1) borné entre 0 et VOLUME_MAX (1 sans plafond). Un niveau illisible donne 0."""
    try:
        v = float(niveau)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return min(max(v, 0.0), VOLUME_MAX)


def refus_volume_up():
    """Refus d'un volume_up quand un plafond est réglé, avec sa valeur."""
    return f"le volume est plafonné à {pourcentage(VOLUME_MAX)} %, je le règle seulement à une valeur précise (sécurité)"


def plafonner(service, donnees):
    """Plafonne sur place le volume_level d'un media_player.volume_set, et rend les données."""
    if service == "media_player.volume_set" and isinstance(donnees, dict) and "volume_level" in donnees:
        donnees["volume_level"] = plafonner_volume(donnees["volume_level"])
    return donnees


# Domaines que la sécurité en dur refuse en service comme en cible, quel que soit l'appelant (S-F4, comme Securite.kt).
DOMAINES_JAMAIS = frozenset({"lock", "alarm_control_panel"})


def verifier(service, donnees, maintenant=None, personne=None):
    """Raison du refus en français, ou None si l'action est permise.

    service : « domaine.service » ; donnees : corps envoyé à HA (entity_id, area_id, réglages), dont le
    volume est plafonné sur place (plafonner) ; personne : qui parle, d'après la reconnaissance de la
    tablette (règle 3), ou rien."""
    # Le plafond tient quels que soient les drapeaux, comme dans Securite.kt.
    plafonner(service, donnees)
    if not SECURITE_ACTIVE:
        return None
    donnees = donnees or {}
    entites = cibles(donnees.get("entity_id"))
    zones = cibles(donnees.get("area_id"))
    if donnees.get("device_id"):
        return "viser un appareil par son identifiant est interdit (sécurité)"
    # Un étage ou une étiquette désigne un groupe d'entités que la liste blanche par appareil ne voit pas (25/10/2026).
    if "floor_id" in donnees or "label_id" in donnees:
        return "viser un étage ou une étiquette est interdit (sécurité)"
    # Serrures et alarmes : jamais par l'assistant, en service comme en cible d'un autre service (S-F4, 26/10/2026).
    if any(d in DOMAINES_JAMAIS for d in [service.split(".", 1)[0].lower()] + [e.split(".", 1)[0].lower() for e in entites]):
        return "les serrures et les alarmes ne se pilotent pas par l'assistant (sécurité)"
    # Avec un plafond, monter le son par pas passerait au-dessus : seul un volume précis (volume_set plafonné) passe.
    if service == "media_player.volume_up" and plafond_actif():
        return refus_volume_up()
    if PROTEGER_OCCUPANT and any(e.lower() == "all" for e in entites):
        return f"viser toute la maison est interdit, cela toucherait la chambre de {NOM_OCCUPANT} (sécurité)"
    if PROTEGER_OCCUPANT and any(z.lower() in ZONES_PROTEGEES or protege(z) for z in zones):
        return f"je ne touche jamais aux pièces de {NOM_OCCUPANT} (sécurité)"
    if protege(service) or any(protege(e) and not permis_pour(personne, service, e) for e in entites):
        return f"je ne touche jamais à ce qui appartient à {NOM_OCCUPANT} (sécurité)"
    heure = (maintenant or maison.maintenant()).hour
    if HEURE_CALME_ACTIVE and en_heure_calme(heure, HEURE_CALME_DEBUT, HEURE_CALME_FIN):
        silencieux = service in SERVICES_SILENCIEUX
        if service == "media_player.volume_mute" and donnees.get("is_volume_muted") is False:
            silencieux = False
        # Un script peut aussi être appelé comme service (« script.lancer_musique »).
        if not silencieux and (service in SON_SALON or any(e in SON_SALON for e in entites)):
            return f"pas de son dans le salon {PLAGE_CALME} (sécurité)"
    return None


def phrase_protegee(texte, personne=None):
    """Phrase qui parle de l'occupant : refusée avant tout LLM. Banc du 13/10/2026 : à « allume la
    chambre de <occupant> », Gemma allumait d'autres lumières, puisque les siennes lui sont cachées.
    L'occupant reconnu peut parler de ses affaires : chaque action reste vérifiée par verifier()."""
    if not SECURITE_ACTIVE:
        return None
    if not PROTEGER_OCCUPANT or personne_normalisee(personne) in PERMIS_PERSONNE:
        return None
    t = texte.lower()
    if any(m in t for m in MOTS_PROTEGES):
        return f"je ne touche jamais à ce qui appartient à {NOM_OCCUPANT} (sécurité)"
    return None


# --- Repli vers Assist de Home Assistant (S-D9, décision D8 du 26/10/2026) ------------------------------------
# Assist exécute une phrase sans qu'on voie sa cible avant : aucun verifier() ne peut le contrôler. Le repli est
# donc coupé par défaut. Le réglage securite.assist_repli (booléen, absent ou autre que true = coupé) l'ouvre, et
# même ouvert il ne passe que pour une phrase que le filtre ci-dessous ne refuse pas. Le réglage ne touche jamais à
# SECURITE_ACTIVE ni à aucune règle de verifier().
def repli_configure(valeur):
    """Vrai seulement pour le booléen true de securite.assist_repli : absent, false, "true", 1... laissent le repli coupé."""
    return valeur is True


ASSIST_REPLI = repli_configure(maison.SECURITE.get("assist_repli"))


def _mots_de(texte):
    """Mots d'une phrase en minuscules et sans accent, pour comparer sans se faire piéger par l'orthographe."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", t)


# Mots entiers qui font refuser la phrase : cibles qu'Assist ne montre pas ou que la sécurité écarte.
REPLI_MOTS_INTERDITS = frozenset({
    # Ce que verifier() refuse en cible : appareil, étage ou étiquette visés en bloc, et les portes (serrures).
    "porte", "portes", "portail", "portillon", "garage", "appareil", "appareils", "device", "identifiant", "id",
    "etage", "etages", "etiquette", "etiquettes", "label", "rez", "chaussee", "niveau", "niveaux",
    # Visée large ou indéterminée.
    "all", "tout", "toute", "toutes", "tous", "partout", "maison", "appartement",
    # Ce qui peut chauffer, brûler ou geler.
    "four", "fours", "plaque", "plaques", "fer", "micro", "onde", "ondes", "lave", "seche", "frigo", "frigos",
    "congelateur", "refrigerateur", "poele", "cheminee", "convecteur", "soufflant", "bouilloire", "cafetiere",
    "prise", "prises", "multiprise", "degre", "degres",
    # Ce qui déclenche autre chose que ce qui est dit.
    "script", "scripts", "automatisation", "automatisations", "scene", "scenes", "routine", "routines",
})
# Radicaux qui font refuser la phrase quand ils sont contenus dans un mot (serrure, verrouille, chauffage...).
REPLI_RADICAUX_INTERDITS = ("serrur", "verrou", "cadenas", "alarm", "sirene", "chauff", "radiateur", "thermostat",
                            "temperature", "chaudiere", "cuisiniere", "clim", "repasser", "arrosage", "vanne",
                            "debloqu", "coffre")
# Quand un plafond de volume est réglé, monter le son par un autre chemin que volume_set le contournerait.
REPLI_MOTS_VOLUME = frozenset({"son", "sonore", "fort", "forte", "monte", "monter", "augmente", "augmenter",
                               "decibel", "decibels", "bruit"})


def refus_phrase_assist(texte, personne=None):
    """Raison du refus en français, ou None si la phrase peut aller jusqu'à Assist. Écarte tout ce que la sécurité en
    dur refuse ou ne sait pas contrôler d'avance : serrures, alarmes, cuisson, chauffage, visée en bloc, volume
    quand un plafond est réglé, et tout mot de l'occupant protégé tant que la règle 1 est active."""
    refus = phrase_protegee(texte, personne)
    if refus:
        return refus
    mots = _mots_de(texte)
    if not mots:
        return "phrase vide (sécurité)"
    # Mots de l'occupant gardés tant que la règle 1 est active (levée complète le 27/10/2026, il se sert aussi de l'assistant).
    gardes = {m for p in (*MOTS_PROTEGES, *MOTS_PIECES, NOM_OCCUPANT) for m in _mots_de(p)} if PROTEGER_OCCUPANT else set()
    for m in mots:
        if m in REPLI_MOTS_INTERDITS or any(r in m for r in REPLI_RADICAUX_INTERDITS):
            return f"le mot « {m} » vise une cible que je ne peux pas contrôler d'avance (sécurité)"
        if any(m == g or (len(g) >= 4 and m.startswith(g)) for g in gardes):
            return f"le mot « {m} » touche à ce qui appartient à {NOM_OCCUPANT} (sécurité)"
        if plafond_actif() and (m in REPLI_MOTS_VOLUME or "volume" in m):
            return "le volume est plafonné, Assist ne le règle pas (sécurité)"
    return None


def repli_assist(texte, personne=None):
    """Décision du repli Assist pour une phrase : (permis, motif en français pour le journal).

    SECURITE_ACTIVE faux : l'ancien comportement (Assist toujours permis), la sécurité entière étant levée.
    Sinon : coupé tant que securite.assist_repli n'est pas true, et même ouvert, refusé pour une phrase que
    refus_phrase_assist écarte."""
    if not SECURITE_ACTIVE:
        return True, "repli tenté (sécurité levée)"
    if not ASSIST_REPLI:
        return False, "repli coupé par le réglage securite.assist_repli"
    refus = refus_phrase_assist(texte, personne)
    if refus:
        return False, f"repli refusé par la sécurité : {refus}"
    return True, "repli tenté"
