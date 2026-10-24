"""Démarrage de l'appli Home Assistant « assistant » : options de l'appli vers variables, puis serveur.

Les options (clé Anthropic, jeton des satellites, essai) sont réglées dans l'appli assistant de HA.
La configuration de la maison (maison.json, dictionnaire) est dans /app/config, remplacée à chaque
déploiement. Les phrases apprises vivent dans /data, qui survit aux mises à jour."""
import json, os, shutil, sys
from pathlib import Path

options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
os.environ.update({
    "JARVIS_PROFIL": "ha",
    "JARVIS_DONNEES": "/data",
    # Configuration de la maison (maison.json, commandes.yaml), copiée par deployer.sh à chaque déploiement.
    "ASSISTANT_VOCAL_CONFIG": "/app/config",
    "HA_URL": "http://supervisor/core",
    "HA_TOKEN": os.environ.get("SUPERVISOR_TOKEN", ""),
    "LLM_FOURNISSEUR": "claude",
    "ANTHROPIC_API_KEY": options.get("anthropic_api_key", ""),
    "SATELLITE_JETON": options.get("satellite_jeton", ""),
    # 0.17.0 : ?jeton= dans l'adresse, sur le port en clair, permis tant que l'option est cochée.
    "JARVIS_ANCIEN_ACCES": "1" if options.get("ancien_acces", True) else "0",
    "VAD_MODELE": "/app/modeles/silero_vad.onnx",
    # Transcription en ligne (repli de Speech-to-Phrase), service compatible API OpenAI.
    "STT_API_CLE": options.get("stt_api_cle", ""),
    "STT_API_URL": options.get("stt_api_url", ""),
    "STT_API_MODELE": options.get("stt_api_modele", ""),
    "STT_API_NOM": options.get("stt_api_nom", "API"),
})
for k in ("STT_API_URL", "STT_API_MODELE"):  # une option vide garde la valeur par défaut du serveur
    if not os.environ.get(k):
        os.environ.pop(k, None)
# commandes.yaml est lu dans /app/config, la configuration déployée (plus de copie dans /data depuis la
# 0.23.1). Les phrases apprises restent propres à ce serveur : copiées seulement au premier démarrage.
if not os.path.exists("/data/commandes_apprises.yaml") and os.path.exists("/app/commandes_apprises.yaml"):
    shutil.copy("/app/commandes_apprises.yaml", "/data/commandes_apprises.yaml")
print(f"assistant : clé Anthropic {'présente' if options.get('anthropic_api_key') else 'ABSENTE'}, "
      f"jeton satellites {'présent' if len(options.get('satellite_jeton', '')) >= 16 else 'ABSENT'}, "
      f"transcription en ligne {'configurée' if len(options.get('stt_api_cle', '')) > 10 else 'non configurée'}", flush=True)
arguments = [sys.executable, "/app/serveur_satellite.py"] + (["--essai"] if options.get("essai") else [])
os.execv(sys.executable, arguments)
