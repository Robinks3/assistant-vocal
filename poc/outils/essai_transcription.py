"""Essai de la transcription déportée (0.18.4) : envoie une phrase dite par Piper comme le ferait la
tablette, et affiche le texte rendu par le serveur et le temps mis.

Usage : python poc/outils/essai_transcription.py [hôte] [port chiffré] [moteur] ["phrase"]
Le jeton n'est jamais affiché."""
import asyncio, base64, json, ssl, sys, time
from pathlib import Path

import numpy as np
import websockets
from dotenv import dotenv_values

ICI = Path(__file__).resolve().parents[1]
hote = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
moteur = sys.argv[3] if len(sys.argv) > 3 else ""
phrase = sys.argv[4] if len(sys.argv) > 4 else "Allume la lampe de la télé à quarante pour cent"
JETON = dotenv_values(ICI / ".env").get("SATELLITE_JETON", "")
TLS = ssl.create_default_context()
TLS.check_hostname, TLS.verify_mode = False, ssl.CERT_NONE


def pcm16k(texte):
    from piper import PiperVoice
    voix = PiperVoice.load(str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))
    x = np.frombuffer(b"".join(c.audio_int16_bytes for c in voix.synthesize(texte)), np.int16) / 32768.0
    t = np.linspace(0, len(x) / voix.config.sample_rate, int(len(x) * 16000 / voix.config.sample_rate), endpoint=False)
    y = np.interp(t, np.arange(len(x)) / voix.config.sample_rate, x)
    return (y * 32767).astype(np.int16).tobytes()


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    son = pcm16k(phrase)
    async with websockets.connect(f"wss://{hote}:{port}/", ssl=TLS,
                                  additional_headers={"Authorization": f"Bearer {JETON}"}, max_size=2 ** 22) as ws:
        while True:
            m = json.loads(await ws.recv())
            if m.get("etat") == "capacites":
                print(f"serveur {m['serveur']} v{m['version']}, moteurs {m.get('transcription')}")
                break
        t = time.perf_counter()
        await ws.send(json.dumps({"type": "transcrire", "id": 1, "moteur": moteur,
                                  "pcm": base64.b64encode(son).decode()}))
        while True:
            m = await ws.recv()
            if isinstance(m, str) and json.loads(m).get("etat") == "transcrit":
                r = json.loads(m)
                break
    print(f"dit : {phrase}")
    print(f"rendu par {r.get('moteur')} en {r.get('ms')} ms (aller-retour {1000 * (time.perf_counter() - t):.0f} ms) : "
          f"{r.get('texte') or r.get('erreur')}")


asyncio.run(main())
