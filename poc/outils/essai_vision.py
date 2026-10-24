"""Essai de la vision déportée : envoie une image JPEG au serveur du PC comme le ferait la tablette.

Usage : python poc/outils/essai_vision.py image.jpg [hôte] [port chiffré]
Affiche le temps de traitement et, pour chaque visage, sa boîte, son score et le regard.
Le jeton n'est jamais affiché, l'image n'est gardée nulle part."""
import asyncio, base64, json, ssl, sys, time
from pathlib import Path

import websockets
from dotenv import dotenv_values

image = Path(sys.argv[1])
hote = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
port = int(sys.argv[3]) if len(sys.argv) > 3 else 8766
JETON = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("SATELLITE_JETON", "")
TLS = ssl.create_default_context()
TLS.check_hostname, TLS.verify_mode = False, ssl.CERT_NONE


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    async with websockets.connect(f"wss://{hote}:{port}/", ssl=TLS,
                                  additional_headers={"Authorization": f"Bearer {JETON}"}) as ws:
        while True:
            m = json.loads(await ws.recv())
            if m.get("etat") == "capacites":
                print(f"serveur {m['serveur']} v{m['version']}, vision {m.get('vision')}")
                break
        t = time.perf_counter()
        await ws.send(json.dumps({"type": "vision", "id": 1, "jpeg": base64.b64encode(image.read_bytes()).decode()}))
        while True:
            m = await ws.recv()
            if isinstance(m, str) and json.loads(m).get("etat") == "vision":
                r = json.loads(m)
                break
        print(f"aller-retour {1000 * (time.perf_counter() - t):.0f} ms, traitement {r.get('ms')} ms, {r.get('erreur', '')}")
        for v in r.get("visages", []):
            print(f"  visage {v['boite']} score {v['score']} regard {v['regard']} lacet {v['lacet']}, empreinte {len(v['empreinte'])} nombres")


asyncio.run(main())
