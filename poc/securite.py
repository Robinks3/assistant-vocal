"""Sécurité écrite en dur, demandée le 13/10/2026. À ne lever qu'à la demande explicite du propriétaire.

Les noms et les listes propres à la maison (occupant protégé, zones, entités, lecteurs de son, fuseau)
viennent de la configuration de la maison (maison.json du dossier de configuration, modèle config-exemple/, voir maison.py).
Ci-dessous, « l'occupant » est la personne nommée par `nom_occupant`.

1. assistant ne touche JAMAIS à ce qui appartient à l'occupant : sa chambre, sa salle de bain, ses
   lumières, ses réveils, ses automatisations, ses scripts, son téléphone. Interdit aussi : viser
   « all », une zone de l'occupant, ou un appareil par son identifiant (on ne sait pas ce qu'il contient).
2. Aucun son dans le salon (séjour, cuisine ouverte, enceintes de l'appartement) entre minuit et
   9 h : seuls éteindre, mettre en pause, arrêter, baisser et couper le son restent permis.

3. Exception décidée le 21/10/2026 : quand la tablette reconnaît l'occupant, seul devant elle,
   assistant peut allumer, éteindre et régler ses lumières à lui (`permis_personne` de la configuration),
   et rien d'autre de ce qui lui appartient (réveil, automatisations, scripts, salle de bain, téléphone).
   Quand c'est quelqu'un d'autre qui parle, ou qu'on ne sait pas qui parle, la règle 1 reste entière.

Levée le 22/10/2026 à la demande explicite du propriétaire : les règles 1 et 2 sont coupées
(PROTEGER_OCCUPANT et HEURE_CALME_ACTIVE à False). assistant peut piloter ce qui appartient à l'occupant et
mettre du son à toute heure. Restent actifs : le refus de viser un appareil par son identifiant brut,
le plafond de volume à 50 % (verifier() le applique sur place, comme Securite.kt) et, dans assistant.py,
la liste blanche des services du LLM.
Remettre une règle : repasser son drapeau à True ici ET dans Securite.kt (les tests communs suivent).

Même règles, mêmes listes, dans l'appli Android (android/app/src/main/java/assistant/vocal/jarvis/Securite.kt).
Assist de Home Assistant agit sans qu'on puisse vérifier sa cible avant : il est sauté tant que
SECURITE_ACTIVE est vrai, une phrase inconnue va directement au LLM dont chaque action passe ici.
"""
from datetime import datetime

import maison

try:  # l'app HA tourne en UTC : l'heure calme se compte toujours à l'heure du fuseau de la maison
    from zoneinfo import ZoneInfo
    FUSEAU = ZoneInfo(maison.FUSEAU)
except Exception:
    FUSEAU = None

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

# Volume le plus fort permis, de 0 à 1 (même valeur que VOLUME_MAX de Securite.kt). Le 12/10, « Mets le
# salon à fond » avait mis la Enceintes au maximum (en essai, rien n'est parti).
VOLUME_MAX = 0.5

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
    """Niveau de volume (0 à 1) borné entre 0 et VOLUME_MAX. Un niveau illisible donne 0."""
    try:
        v = float(niveau)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return min(max(v, 0.0), VOLUME_MAX)


VOLUME_UP_REFUSE = "le volume est plafonné à 50 %, je le règle seulement à une valeur précise (sécurité)"


def plafonner(service, donnees):
    """Plafonne sur place le volume_level d'un media_player.volume_set, et rend les données."""
    if service == "media_player.volume_set" and isinstance(donnees, dict) and "volume_level" in donnees:
        donnees["volume_level"] = plafonner_volume(donnees["volume_level"])
    return donnees


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
    # Monter le son par pas passerait au-dessus de 50 % : seul un volume précis (volume_set plafonné) passe.
    if service == "media_player.volume_up":
        return VOLUME_UP_REFUSE
    if PROTEGER_OCCUPANT and any(e.lower() == "all" for e in entites):
        return f"viser toute la maison est interdit, cela toucherait la chambre de {NOM_OCCUPANT} (sécurité)"
    if PROTEGER_OCCUPANT and any(z.lower() in ZONES_PROTEGEES or protege(z) for z in zones):
        return f"je ne touche jamais aux pièces de {NOM_OCCUPANT} (sécurité)"
    if protege(service) or any(protege(e) and not permis_pour(personne, service, e) for e in entites):
        return f"je ne touche jamais à ce qui appartient à {NOM_OCCUPANT} (sécurité)"
    heure = (maintenant or datetime.now(FUSEAU)).hour
    if HEURE_CALME_ACTIVE and HEURE_CALME_DEBUT <= heure < HEURE_CALME_FIN:
        silencieux = service in SERVICES_SILENCIEUX
        if service == "media_player.volume_mute" and donnees.get("is_volume_muted") is False:
            silencieux = False
        # Un script peut aussi être appelé comme service (« script.lancer_musique »).
        if not silencieux and (service in SON_SALON or any(e in SON_SALON for e in entites)):
            return "pas de son dans le salon entre minuit et 9 h (sécurité)"
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
