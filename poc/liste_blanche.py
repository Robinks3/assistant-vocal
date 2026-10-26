"""Liste blanche des services Home Assistant, en un seul endroit (0.41.0, S-F5).

Ce module est lu par la voie du LLM (poc/assistant.py : HomeAssistant.service, outil appeler_service, découverte
de GET /api/services) et par la passerelle de l'appli (poc/acces.py : verifier_requete_ha). Les deux passent par
acces.controler_service, qui appelle refus_reglage ci-dessous : une règle écrite ici vaut donc pour les deux voies
et ne peut plus être écrite à l'une sans l'autre.

Il contient :
- SERVICES_PERMIS, la table des services permis par domaine (décision D6), et DOMAINES_HORS_LLM ;
- les listes qui écartent des services un par un (DOMAINES_ADMIN, NOMS_ECARTES, SERVICES_ECARTES) et les deux
  tests de forme du schéma d'un service de HA (_cible_son_domaine, _champ_vers_un_appareil) ;
- les réglages propres à la maison (section reglages de maison.json) : applis de la télé, interrupteurs permis,
  attributs refusés. Rien de la maison n'est écrit ici, tout se lit dans la configuration.

La sécurité en dur (securite.py, Securite.kt) reste la dernière barrière et ne dépend pas de ce module.
"""
import maison
import securite

# Services de Home Assistant permis (décision D6 du 26/10/2026, session S-F1) : tout ce que HA expose pour les
# domaines courants, sauf ce que la sécurité en dur refuse ailleurs : les cibles par device_id, floor_id et
# label_id (securite.verifier), les domaines de acces.DOMAINES_INTERDITS (serrures, alarme, notifications,
# commandes système) et les services qui écrivent un fichier, changent la configuration ou désignent d'autres
# appareils dans leurs données (que securite.verifier ne voit pas), laissés de côté un par un ci-dessous.
# Chaque liste suit la page du domaine sur https://www.home-assistant.io/integrations/<domaine>/.
# Cette table est le socle : HomeAssistant.charger_services() y ajoute ce que HA expose en plus (voir
# services_depuis_ha). Elle part aussi dans dictionnaire.json pour l'appli (CerveauAppareil.kt).
SERVICES_PERMIS = {
    # Éclairage, prises, ventilation, ouvrants, chauffage
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle", "set_percentage", "increase_speed", "decrease_speed", "oscillate",
            "set_direction", "set_preset_mode"},
    "cover": {"open_cover", "close_cover", "stop_cover", "toggle", "set_cover_position", "open_cover_tilt",
              "close_cover_tilt", "stop_cover_tilt", "toggle_cover_tilt", "set_cover_tilt_position"},
    "climate": {"turn_on", "turn_off", "toggle", "set_temperature", "set_hvac_mode", "set_fan_mode",
                "set_preset_mode", "set_swing_mode", "set_swing_horizontal_mode", "set_humidity"},
    "humidifier": {"turn_on", "turn_off", "toggle", "set_humidity", "set_mode"},
    "water_heater": {"turn_on", "turn_off", "set_temperature", "set_operation_mode"},
    "valve": {"open_valve", "close_valve", "stop_valve", "toggle", "set_valve_position"},
    "siren": {"turn_on", "turn_off", "toggle"},
    # Lecteurs. Sans media_player.play_media ni join : la musique passe par jouer_musique (Music Assistant),
    # et group_members désigne d'autres lecteurs dans les données, hors de la vue de securite.verifier.
    "media_player": {"turn_on", "turn_off", "toggle", "media_play", "media_pause", "media_play_pause", "media_stop",
                     "media_next_track", "media_previous_track", "media_seek", "volume_set", "volume_mute",
                     "volume_down", "select_source", "select_sound_mode", "shuffle_set", "repeat_set",
                     "clear_playlist", "unjoin"},
    "music_assistant": {"play_media", "play_announcement"},
    # Robots, tondeuses, caméras. Sans camera.snapshot, record ni play_stream, qui écrivent un fichier ou
    # visent un autre lecteur.
    "vacuum": {"start", "pause", "stop", "return_to_base", "locate", "clean_spot", "set_fan_speed"},
    "lawn_mower": {"start_mowing", "pause", "dock"},
    "camera": {"turn_on", "turn_off", "enable_motion_detection", "disable_motion_detection"},
    # Scènes, scripts, automatisations. Sans scene.apply ni scene.create, qui posent l'état d'entités quelconques,
    # et sans reload.
    "scene": {"turn_on"},
    "script": {"turn_on", "turn_off", "toggle"},
    "automation": {"turn_on", "turn_off", "toggle", "trigger"},
    # Entrées et réglages créés dans HA. Sans input_select.set_options (modifie la liste du choix).
    "input_boolean": {"turn_on", "turn_off", "toggle"},
    "input_number": {"set_value", "increment", "decrement"},
    "input_select": {"select_option", "select_first", "select_last", "select_next", "select_previous"},
    "input_text": {"set_value"},
    "input_datetime": {"set_datetime"},
    "input_button": {"press"},
    "button": {"press"},
    "number": {"set_value"},
    "text": {"set_value"},
    "timer": {"start", "pause", "cancel", "finish", "change"},
    "counter": {"increment", "decrement", "reset", "set_value"},
    # Réglages fins de la télé téléviseur et des lampes (0.30.0) : pour l'appli et la passerelle, jamais pour le LLM
    # (DOMAINES_HORS_LLM : hors enum de l'outil, hors contexte, refusés à l'appel). Sans remote.learn_command ni
    # delete_command, qui écrivent la mémoire de la télécommande.
    "domaine_tele": {"launch_app", "send_text_input", "set_picture_setting"},
    "remote": {"send_command", "turn_on", "turn_off", "toggle"},
    "select": {"select_option", "select_first", "select_last", "select_next", "select_previous"},
}
DOMAINES_HORS_LLM = {"domaine_tele", "remote", "select"}
# Monter le son par pas (volume_up) passerait au-dessus d'un plafond de volume : permis au LLM seulement
# quand la configuration n'en règle aucun (securite.plafond_volume à 100, le défaut).
if not securite.plafond_actif():
    SERVICES_PERMIS["media_player"].add("volume_up")


# Domaines d'administration ou de communication : jamais ajoutés d'après HA.
DOMAINES_ADMIN = {"update", "tts", "stt", "conversation", "assist_satellite", "backup", "cloud", "config", "mqtt",
                  "zha", "zwave_js", "matter", "mobile_app", "ios", "device_tracker", "person", "logbook", "logger",
                  "file", "ffmpeg", "hardware", "websocket_api", "frontend", "browser"}
# Noms de service qui écrivent, créent, suppriment ou installent, quel que soit le domaine.
NOMS_ECARTES = {"install", "skip", "clear_skipped", "snapshot", "record", "learn_command", "delete_command",
                "set_options", "apply", "create", "remove", "delete", "set_usercode", "clear_usercode"}
# Services écartés un par un : la musique a son propre chemin, et join désigne d'autres lecteurs.
SERVICES_ECARTES = {"media_player.play_media", "media_player.join", "camera.play_stream"}


def _cible_son_domaine(domaine, cible):
    """Vrai si la cible du service est « entity » filtrée sur ce domaine ou sur l'intégration de ce nom."""
    if not isinstance(cible, dict):
        return False
    filtres = cible.get("entity")
    if isinstance(filtres, dict):
        filtres = [filtres]
    if not isinstance(filtres, list):
        return False
    for f in filtres:
        if not isinstance(f, dict):
            continue
        domaines = f.get("domain")
        domaines = [domaines] if isinstance(domaines, str) else (domaines if isinstance(domaines, list) else [])
        if domaine in domaines or f.get("integration") == domaine:
            return True
    return False


# Sélecteurs de HA qui désignent un appareil, une pièce, un étage ou une étiquette dans les données d'un service.
SELECTEURS_VERS_UN_APPAREIL = {"entity", "device", "area", "floor", "label", "target", "config_entry"}


def _champ_vers_un_appareil(champs):
    """Vrai si un champ du service (hors entity_id, la cible vérifiée) désigne d'autres appareils."""
    if not isinstance(champs, dict):
        return False
    for nom, champ in champs.items():
        if nom == "entity_id" or not isinstance(champ, dict):
            continue
        selecteur = champ.get("selector")
        if isinstance(selecteur, dict) and SELECTEURS_VERS_UN_APPAREIL & set(selecteur):
            return True
        if "entity_id" in str(nom) or str(nom).endswith(("_entity_id", "_device_id", "_area_id")):
            return True
    return False


# ------------------------------------------------------------ réglages de la maison (section reglages)
# Toutes les clés sont facultatives. Une clé absente ne restreint rien (la table ci-dessus tient seule).
#   applis            noms d'applis que domaine_tele.launch_app peut lancer par le champ « app » (une URL en
#                     https:// reste permise par acces.refus_launch_app)
#   interrupteurs     entités switch.* que switch.turn_on, turn_off et toggle peuvent viser, et elles seules
#   attributs_refuses {"domaine.service": ["clé", ...]} : clés de données refusées pour ce service
# Lue une fois au chargement, comme les autres sections de maison.json.
REGLAGES = maison.CONFIG.get("reglages") if isinstance(maison.CONFIG.get("reglages"), dict) else {}


def _liste_de_textes(valeur):
    """La liste de textes d'une clé de réglage, ou None quand la clé est absente ou mal formée (aucune restriction)."""
    if not isinstance(valeur, list):
        return None
    return [v for v in valeur if isinstance(v, str)]


def _cibles(corps):
    """Entités visées par les données d'un appel (entity_id en texte ou en liste), ou None si aucune entité n'est nommée."""
    cible = corps.get("entity_id") if isinstance(corps, dict) else None
    if isinstance(cible, str):
        return [cible]
    if isinstance(cible, (list, tuple)) and cible and all(isinstance(c, str) for c in cible):
        return list(cible)
    return None


def refus_reglage(domaine, service, corps, reglages=None):
    """Raison du refus d'un appel au regard des réglages de la maison, ou None. Appelée par
    acces.controler_service pour toutes les voies, jamais seule. reglages : pour les tests, sinon REGLAGES."""
    reglages = REGLAGES if reglages is None else reglages
    nom = f"{domaine}.{service}"
    corps = corps if isinstance(corps, dict) else {}
    refuses = reglages.get("attributs_refuses")
    if isinstance(refuses, dict):
        cles = _liste_de_textes(refuses.get(nom)) or []
        for cle in cles:
            if cle in corps:
                return f"{nom} : l'attribut {cle} est refusé par les réglages de la maison"
    applis = _liste_de_textes(reglages.get("applis"))
    if nom == "domaine_tele.launch_app" and applis is not None and "app" in corps:
        app = corps["app"]
        if not isinstance(app, str) or app not in applis:
            return "launch_app : cette appli n'est pas dans les réglages de la maison"
    interrupteurs = _liste_de_textes(reglages.get("interrupteurs"))
    if domaine == "switch" and interrupteurs is not None:
        cibles = _cibles(corps)
        if cibles is None or any(c not in interrupteurs for c in cibles):
            return f"{nom} : cet interrupteur n'est pas dans les réglages de la maison"
    return None
