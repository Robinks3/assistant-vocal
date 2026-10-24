"""Envoie les options de l'appli assistant de HA (clé Anthropic, jeton des satellites) depuis poc/.env.

Les secrets passent par l'entrée standard d'une session SSH vers l'API du superviseur : ils ne
s'affichent jamais et n'apparaissent dans aucune ligne de commande. Usage : python ha-app/configurer-options.py [--essai] [--sans-ancien-acces]"""
import json, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "poc"))
import maison

env = dotenv_values(Path(__file__).resolve().parents[1] / "poc" / ".env")
corps = json.dumps({"options": {"anthropic_api_key": env.get("ANTHROPIC_API_KEY", ""),
                                "satellite_jeton": env.get("SATELLITE_JETON", ""),
                                "essai": "--essai" in sys.argv,
                                "ancien_acces": "--sans-ancien-acces" not in sys.argv,
                                "stt_api_cle": env.get("STT_API_CLE", ""),
                                "stt_api_url": env.get("STT_API_URL") or "https://api.mistral.ai/v1/audio/transcriptions",
                                "stt_api_modele": env.get("STT_API_MODELE") or "voxtral-mini-latest",
                                "stt_api_nom": env.get("STT_API_NOM") or "Voxtral"}})
r = subprocess.run(["ssh", "-o", "ConnectTimeout=10", maison.reseau("ssh_ha"),
                    'curl -s -X POST -H "Authorization: Bearer $SUPERVISOR_TOKEN" -H "Content-Type: application/json" '
                    '--data-binary @- http://supervisor/addons/local_jarvis/options'],
                   input=corps.encode(), capture_output=True)
print("réponse du superviseur :", r.stdout.decode(errors="replace")[:200] or r.stderr.decode(errors="replace")[:200])
