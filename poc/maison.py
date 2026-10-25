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
FUSEAU = CONFIG.get("fuseau") or "UTC"
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
