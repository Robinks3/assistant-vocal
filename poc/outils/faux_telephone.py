"""Faux téléphone : se connecte au serveur satellite et rejoue des phrases synthétisées.

Usage : python poc/outils/faux_telephone.py [--reveil] "phrase 1" "phrase 2"
Sans --reveil, simule le bouton Parler. Avec --reveil, fait précéder la phrase du mot de réveil réglé dans
maison.json (section reveil, voir assistant.prononciation_reveil), « Hey Jarvis » à l'anglaise en repli."""
import asyncio, json, os, sys, time
import numpy as np, websockets
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.stdout.reconfigure(encoding="utf-8")
import assistant as A
from dotenv import load_dotenv
load_dotenv(A.ICI / ".env")
from piper import PiperVoice

voix = PiperVoice.load(str(A.ICI / "voix" / "fr_FR-siwis-medium.onnx"))
MOT_REVEIL, LANGUE_REVEIL = A.prononciation_reveil()  # même source que le serveur : maison.json, section reveil
# Le mot de réveil se dit avec la voix de sa langue : voix française, ou anglaise pour « Hey Jarvis ».
voix_reveil = voix if LANGUE_REVEIL == "fr" else PiperVoice.load(str(A.ICI / "voix" / "en_US-lessac-medium.onnx"))
def pcm16k(texte, v=None):
    v = v or voix
    x = np.frombuffer(b"".join(c.audio_int16_bytes for c in v.synthesize(texte)), np.int16).astype(np.float32)
    n = int(len(x) * 16000 / v.config.sample_rate)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16)

async def envoyer_flux(ws, signal):
    for i in range(0, len(signal), 1280):
        await ws.send(signal[i:i + 1280].tobytes()); await asyncio.sleep(0.08)

async def main():
    reveil = "--reveil" in sys.argv
    phrases = [a for a in sys.argv[1:] if a != "--reveil"]
    url = f"ws://{os.getenv('HOTE_TEST', '127.0.0.1')}:{os.getenv('PORT_TEST', '8765')}/?jeton={os.environ['SATELLITE_JETON']}"
    silence = np.zeros(16000, np.int16)
    async with websockets.connect(url, max_size=2 ** 22) as ws:
        print("connecté :", await ws.recv())
        if os.getenv("MODE_ESSAI"):  # passer le serveur en essai avant de tester
            await ws.send(json.dumps({"type": "mode", "choix": "essai"}))
        for p in phrases:
            t0 = time.perf_counter()
            if reveil:
                await envoyer_flux(ws, np.concatenate([silence, pcm16k(MOT_REVEIL, voix_reveil), silence[:4000]]))
            else:
                await ws.send(json.dumps({"type": "parler"}))
            envoi = asyncio.create_task(envoyer_flux(ws, np.concatenate([pcm16k(p), silence, silence])))
            while True:
                m = await asyncio.wait_for(ws.recv(), 30)
                if isinstance(m, bytes):
                    print(f"  WAV reçu : {len(m)} octets, {time.perf_counter() - t0:.1f} s après le début")
                    await ws.send(json.dumps({"type": "lecture_finie"}))
                    continue
                d = json.loads(m); print("  ", d)
                if d.get("etat") == "repos" and "version" not in d:
                    break
            envoi.cancel()
            await asyncio.sleep(1)

asyncio.run(main())
