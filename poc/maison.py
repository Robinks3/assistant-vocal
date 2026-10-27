"""Configuration propre à la maison, rangée dans un seul dossier hors du code.

Le moteur ne contient aucune donnée réelle de la maison. Il lit tout dans le dossier de configuration :
  maison.json      adresses, fuseau, appareils, propriétaire, listes de sécurité, météo marine ;
  commandes.yaml   dictionnaire des commandes vocales (phrases, actions, vue du LLM, personnes) ;
  carte/           plan de l'appartement (pièces, meubles, lampes) ;
  reveil/          modèle facultatif du mot de réveil (section reveil de maison.json) ;
  genere/          fichiers produits ou rangés pour l'appli (dictionnaire, page 3D, trait de côte, aperçu HA).
Le dossier est, dans l'ordre :
1. la variable d'environnement ASSISTANT_VOCAL_CONFIG, ou son ancien nom MAISON_DOSSIER (les tests règlent la
   première sur config-exemple/) ;
2. le dossier config/ à la racine du dépôt, non suivi par git (dépôt privé de configuration cloné là), ou
   l'ancien dossier maison/ tant que config/ n'existe pas.
Sans fichier maison.json lisible, le programme s'arrête : config-exemple/, neutre et suivi, avec des valeurs
fictives, ne sert que de point de départ à copier et aux tests. Les mêmes fichiers servent à l'appli
Android : build.gradle.kts copie maison.json dans BuildConfig.MAISON_JSON et prend le dictionnaire
exporté dans genere/android/. Les phrases apprises, les journaux, les secrets et les visages ne sont pas
de la configuration : ils restent dans le dossier de données de chaque machine (JARVIS_DONNEES, poc/ par
défaut).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
EXEMPLE = RACINE / "config-exemple"


def dossier_config():
    """Dossier de configuration à lire, selon l'ordre décrit en tête de module."""
    voulu = (os.environ.get("ASSISTANT_VOCAL_CONFIG", "").strip() or os.environ.get("MAISON_DOSSIER", "").strip())
    if voulu:
        return Path(voulu)
    if not (RACINE / "config" / "maison.json").exists() and (RACINE / "maison" / "maison.json").exists():
        import sys
        print(f"maison : configuration lue dans l'ancien dossier {RACINE / 'maison'}, à renommer en config/",
              file=sys.stderr)
        return RACINE / "maison"
    return RACINE / "config"


def charger(chemin):
    """Objet JSON lu dans [chemin]. Un fichier absent ou illisible arrête le programme, pour ne jamais
    retomber sans le dire sur des listes de sécurité vides ou fictives."""
    chemin = Path(chemin)
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SystemExit(f"Configuration de la maison absente ({chemin}) : {e}. Copier le dossier "
                         "config-exemple/ en config/ (ou régler ASSISTANT_VOCAL_CONFIG) et y mettre les vraies valeurs de la maison.")
    except ValueError as e:
        # Fichier présent mais abîmé (0.27.3) : recopier l'exemple effacerait la vraie configuration.
        raise SystemExit(f"Configuration de la maison illisible ({chemin}) : {e}. Corriger le fichier, "
                         "à enregistrer en UTF-8 et en JSON valide (virgules, guillemets droits, accolades).")
    except OSError as e:
        raise SystemExit(f"Configuration de la maison illisible ({chemin}) : {e}.")
    if not isinstance(donnees, dict):
        raise SystemExit(f"Configuration de la maison illisible ({chemin}) : un objet JSON est attendu")
    return donnees


DOSSIER = dossier_config()
CONFIG = charger(DOSSIER / "maison.json")
RESEAU = CONFIG.get("reseau") or {}
SECURITE = CONFIG.get("securite") or {}
# Section acces (25/10/2026) : ecoute (adresses où les ports s'ouvrent), reseaux_autorises (réseaux dont une
# connexion est acceptée), ancien_acces (jeton dans l'adresse sur le port en clair), administrateurs (identités
# autorisées à gérer les appareils et les réglages, en plus du propriétaire). Voir acces.py.
ACCES = CONFIG.get("acces") if isinstance(CONFIG.get("acces"), dict) else {}
ADMINISTRATION = CONFIG.get("administration") if isinstance(CONFIG.get("administration"), dict) else {}
# Section client_web (lot S-W1a) : hote (nom de domaine de Tailscale Serve, seul nom accepté en plus de la boucle
# locale par le serveur HTTP du client web), session_jours (durée de vie d'un cookie de session sans usage). Voir
# serveur_web.py.
CLIENT_WEB = CONFIG.get("client_web") if isinstance(CONFIG.get("client_web"), dict) else {}
# Section journal (0.39.0) : conserver_jours (durée de garde de l'historique qui contient les phrases), taille_max_ko
# et fichiers_max (rotation du journal des durées, qui ne contient aucune phrase), phrases_dans_la_console
# (diagnostic : remet les phrases dans la sortie du serveur). Voir assistant.py.
JOURNAL = CONFIG.get("journal") if isinstance(CONFIG.get("journal"), dict) else {}
FUSEAU = CONFIG.get("fuseau") or "UTC"


def entier(section, cle, defaut, mini=1):
    """Entier d'une clé de section de maison.json : le défaut si la clé manque, n'est pas un entier ou est sous mini
    (un booléen n'est pas un entier ici). Une valeur absurde ne doit jamais ouvrir ni bloquer un garde-fou."""
    v = section.get(cle) if isinstance(section, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or int(v) < mini:
        return defaut
    return int(v)


def _zone(nom):
    """Fuseau horaire de la maison. Nom inconnu ou base des fuseaux absente (Windows sans tzdata) : UTC, avec un
    avertissement sauf si UTC était déjà le choix, plutôt que l'heure de la machine."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nom)
    except Exception:
        if nom != "UTC":
            print(f"maison : fuseau « {nom} » inconnu ou base des fuseaux absente (paquet tzdata), repli sur UTC",
                  file=sys.stderr)
        return timezone.utc


ZONE = _zone(FUSEAU)
# Forme des horodatages écrits dans les journaux et les fichiers d'état : heure de la maison, sans décalage.
FORMAT_HORODATAGE = "%Y-%m-%dT%H:%M:%S"


def maintenant():
    """Heure de la maison (datetime avec fuseau), dans le fuseau de maison.json. Seule source d'heure du moteur :
    jamais l'heure de la machine ni de l'appli Home Assistant, qui tourne en UTC (26/10/2026, S-D1)."""
    return datetime.now(ZONE)
# Propriétaire de la maison (section proprietaire) : prénom affiché, clé de son jeton SATELLITE_JETON et de ses
# droits santé, transcriptions erronées de son prénom à corriger.
PROPRIETAIRE = CONFIG.get("proprietaire") or {}
NOM_PROPRIETAIRE = str(PROPRIETAIRE.get("nom") or "Moi").strip() or "Moi"
CLE_PROPRIETAIRE = str(PROPRIETAIRE.get("cle") or NOM_PROPRIETAIRE).strip().lower()
if not PROPRIETAIRE.get("nom"):
    import sys
    print(f"maison : section proprietaire absente de {DOSSIER / 'maison.json'}, propriétaire « {NOM_PROPRIETAIRE} » "
          "(santé, jeton principal et correction du prénom en dépendent)", file=sys.stderr)
# Nom affiché de l'assistant (section assistant) : automatisation du dictionnaire, appli Home Assistant, appli
# Android. Chaîne non vide de assistant.nom, sinon « Assistant ».
_nom = (CONFIG.get("assistant") if isinstance(CONFIG.get("assistant"), dict) else {}).get("nom")
NOM_ASSISTANT = (_nom.strip() if isinstance(_nom, str) else "") or "Assistant"


def chemin(nom):
    """Fichier [nom] du dossier de configuration (commandes.yaml, genere/...)."""
    return DOSSIER / nom


def reseau(cle, defaut=""):
    """Adresse ou nom d'hôte de la section « reseau » (chaîne vide si absent)."""
    valeur = RESEAU.get(cle)
    return str(valeur).strip() if valeur else defaut


def liste(cle):
    """Liste de chaînes de la section « securite » (vide si absente)."""
    return [str(v) for v in (SECURITE.get(cle) or [])]


def actif(section):
    """Champ « actif » d'une section, lu comme l'appli Android (optBoolean) : vrai pour true ou la chaîne
    "true", faux pour tout le reste, "false" et "0" compris (0.27.3, bool("false") valait vrai)."""
    v = (section or {}).get("actif")
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def source_active(source):
    """Champ « actif » d'une source météo ou mer (point, balise, station, modèle). Contrairement à une section,
    une source sans clé « actif » est interrogée : seul `false` (ou la chaîne "false", "0", "non") l'éteint.
    Un élément qui n'est pas un objet reste actif (liste de lieux sous forme de nombres, par exemple)."""
    if not isinstance(source, dict) or "actif" not in source:
        return True
    v = source["actif"]
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "non", "no", "")
    return v is not False and v != 0


def avertissements_meteo(config=None):
    """Incohérences de configuration entre les sections « mer » et « vent », en phrases pour le journal.

    Une source mer sans source de vent est permise (la page météo marine marche seule), mais le vent mesuré
    n'apparaîtra ni sur la carte ni dans les bilans : le dire clairement au démarrage plutôt que de laisser
    l'utilisateur chercher pourquoi. Ne lève jamais d'exception."""
    cfg = CONFIG if config is None else config
    mer = cfg.get("mer") if isinstance(cfg.get("mer"), dict) else {}
    vent = cfg.get("vent") if isinstance(cfg.get("vent"), dict) else {}
    if not actif(mer):
        return []
    vent_utilisable = actif(vent) and bool(
        isinstance(vent.get("balises"), dict) or isinstance(vent.get("stations_officielles"), dict)
        or isinstance(vent.get("station"), dict))
    if vent_utilisable:
        return []
    cause = ("la section « vent » est absente" if not vent
             else "la section « vent » est inactive" if not actif(vent)
             else "la section « vent » ne déclare aucune source (balises, stations_officielles ou station)")
    return [f"maison : la section « mer » est active mais {cause} : la page météo marine fonctionne sans le "
            "vent mesuré (carte du vent, balises et station absentes). Renseigner « vent » pour les obtenir."]


for _phrase in avertissements_meteo():
    print(_phrase, file=sys.stderr)
