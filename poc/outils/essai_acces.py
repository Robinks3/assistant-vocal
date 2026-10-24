"""Essai du protocole d'accès 0.17.0 contre un serveur lancé (mode essai conseillé), sans téléphone.

1. Connexion chiffrée avec SATELLITE_JETON en en-tête, lecture des capacités et de l'empreinte TLS.
2. Appairage d'un faux téléphone, accepté par la première connexion, puis reconnexion avec son jeton.
3. Passerelle HA : une lecture permise, une action sur une lumière de l'occupant protégé (doit être refusée).
4. L'ancienne forme ?jeton= sur le port en clair, et un jeton faux (doit être refusé).
Rien n'est exécuté dans la maison. Le jeton n'est jamais affiché.
Usage : python poc/outils/essai_acces.py [hôte] [port en clair] [port chiffré]"""
import asyncio, json, os, ssl, sys
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
port, port_tls = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (8765, 8766)
JETON = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("SATELLITE_JETON", "")
TLS = ssl.create_default_context()
TLS.check_hostname, TLS.verify_mode = False, ssl.CERT_NONE  # épinglage fait par l'appli, pas ici


async def attendre(ws, etat, delai=15):
    while True:
        m = await asyncio.wait_for(ws.recv(), delai)
        if isinstance(m, str) and json.loads(m).get("etat") == etat:
            return json.loads(m)


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    entete = {"Authorization": f"Bearer {JETON}"}
    async with websockets.connect(f"wss://{hote}:{port_tls}/", ssl=TLS, additional_headers=entete) as proprio:
        cap = await attendre(proprio, "capacites")
        print(f"1. connecté en chiffré, serveur {cap['serveur']} v{cap['version']}, vad {cap.get('vad')}, "
              f"mot {cap.get('mot_reveil')}, empreinte {cap.get('empreinte', '')[:12]}...")
        async with websockets.connect(f"wss://{hote}:{port_tls}/appairage?nom=Faux%20t%C3%A9l%C3%A9phone", ssl=TLS) as neuf:
            dem = await attendre(neuf, "appairage")
            vu = await attendre(proprio, "appairage_demande")
            assert vu["code"] == dem["code"]
            await proprio.send(json.dumps({"type": "appairer", "id": vu["id"]}))
            jeton = (await attendre(neuf, "appaire"))["jeton"]
            print(f"2. appairage : code {dem['code']} vu par le téléphone connu, accepté, jeton reçu ({len(jeton)} caractères)")
        async with websockets.connect(f"wss://{hote}:{port_tls}/", ssl=TLS,
                                      additional_headers={"Authorization": f"Bearer {jeton}"}) as faux:
            await attendre(faux, "capacites")
            await faux.send(json.dumps({"type": "ha", "id": 1, "methode": "GET", "chemin": "/api/states/sun.sun"}))
            r1 = await attendre(faux, "ha")
            await faux.send(json.dumps({"type": "ha", "id": 2, "methode": "POST", "chemin": "/api/services/light/turn_on",
                                        "corps": {"entity_id": LUMIERE_OCCUPANT}}))
            r2 = await attendre(faux, "ha")
            print(f"3. passerelle : lecture HTTP {r1['code']}, lumière de {OCCUPANT} HTTP {r2['code']} ({r2['corps'][:60]})")
            assert r2["code"] == 403
            await faux.send(json.dumps({"type": "appareils"}))
            vue = await attendre(faux, "appareils")
            for a in vue["appareils"]:
                if a["nom"] == "Faux téléphone":
                    await faux.send(json.dumps({"type": "revoquer", "id": a["id"]}))
            await attendre(faux, "appareils")
        try:
            async with websockets.connect(f"wss://{hote}:{port_tls}/", ssl=TLS,
                                          additional_headers={"Authorization": f"Bearer {jeton}"}) as revoque:
                await revoque.recv()
                await revoque.recv()
            print("   ! jeton révoqué encore accepté")
        except websockets.ConnectionClosed as e:
            print(f"   jeton révoqué refusé ({e.rcvd.code if e.rcvd else '?'})")
    async with websockets.connect(f"ws://{hote}:{port}/?jeton={JETON}") as ancien:
        await attendre(ancien, "capacites")
        print("4. ancienne forme ?jeton= acceptée sur le port en clair")
    try:
        async with websockets.connect(f"ws://{hote}:{port}/", additional_headers={"Authorization": "Bearer faux-jeton-de-test-123"}) as mauvais:
            await mauvais.recv()
            await mauvais.recv()
        print("   ! faux jeton accepté")
    except websockets.ConnectionClosed as e:
        print(f"   faux jeton refusé ({e.rcvd.code if e.rcvd else '?'})")


asyncio.run(main())
