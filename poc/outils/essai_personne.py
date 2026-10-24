"""Essai de « ma chambre » selon la personne (0.18.2) contre un serveur lancé, sans tablette.

Envoie au LLM du serveur, en mode essai (rien n'est exécuté dans la maison), la même phrase au nom de
personnes différentes, comme le ferait la tablette avec son champ « personne », puis deux requêtes de
passerelle qui doivent être refusées quoi qu'il arrive. Le jeton n'est jamais affiché.
Usage : python poc/outils/essai_personne.py [hôte] [port chiffré]"""
import asyncio, json, ssl, sys
from pathlib import Path

import websockets
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maison  # noqa: E402
import securite  # noqa: E402

# Occupant protégé et ses entités (section securite de maison.json) : une lumière qu'il peut piloter
# quand la tablette le reconnaît, une automatisation protégée.
OCCUPANT = securite.NOM_OCCUPANT
LUMIERE_OCCUPANT = min((e for d in securite.PERMIS_PERSONNE.values() for e in d["entites"] if e.startswith("light.")), default="light.inconnue")
AUTOMATISATION_OCCUPANT = min((e for e in securite.ENTITES_PROTEGEES if e.startswith("automation.")), default="automation.inconnue")
UTILISATEUR = maison.NOM_PROPRIETAIRE

hote = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port_tls = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
JETON = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("SATELLITE_JETON", "")
TLS = ssl.create_default_context()
TLS.check_hostname, TLS.verify_mode = False, ssl.CERT_NONE  # épinglage fait par l'appli, pas ici

PHRASES = [
    ("allume ma lampe de chevet", OCCUPANT),
    ("allume ma lampe de chevet", UTILISATEUR),
    ("allume ma lampe de chevet", "inconnu"),
    (f"allume la lumière de la chambre de {OCCUPANT}", UTILISATEUR),
    (f"allume la lumière de la chambre de {OCCUPANT}", OCCUPANT),
    (f"déclenche le réveil de {OCCUPANT}", OCCUPANT),
]


async def attendre(ws, etat, delai=60):
    while True:
        m = await asyncio.wait_for(ws.recv(), delai)
        if isinstance(m, str) and json.loads(m).get("etat") == etat:
            return json.loads(m)


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    async with websockets.connect(f"wss://{hote}:{port_tls}/", ssl=TLS,
                                  additional_headers={"Authorization": f"Bearer {JETON}"}) as ws:
        cap = await attendre(ws, "capacites")
        print(f"serveur {cap['serveur']} v{cap['version']}")
        for texte, personne in PHRASES:
            await ws.send(json.dumps({"type": "llm", "texte": texte, "essai": True, "personne": personne}))
            r = await attendre(ws, "llm")
            print(f"- {personne} : « {texte} »\n    actions {r['actions']}\n    réponse « {r['reponse']} » ({r['ms']} ms)")
        for i, (chemin, corps, personne) in enumerate([
                ("/api/services/light/turn_on", {"entity_id": LUMIERE_OCCUPANT}, UTILISATEUR),
                ("/api/services/automation/trigger", {"entity_id": AUTOMATISATION_OCCUPANT}, OCCUPANT)]):
            await ws.send(json.dumps({"type": "ha", "id": 100 + i, "methode": "POST", "chemin": chemin,
                                      "corps": corps, "personne": personne}))
            r = await attendre(ws, "ha")
            print(f"- passerelle {chemin} {corps['entity_id']} pour {personne} : HTTP {r['code']} ({r['corps'][:70]})")
            assert r["code"] == 403


asyncio.run(main())
