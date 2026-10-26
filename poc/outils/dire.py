"""Fait parler le PC (haut-parleurs) pour tester un satellite à l'oreille.

Usage : python poc/outils/dire.py "phrase en français" [--reveil]
--reveil : prononce d'abord le mot de réveil réglé dans maison.json (section reveil), comme le serveur le guette,
dans sa langue (« Hey Jarvis » à l'anglaise quand le modèle de repli est utilisé)."""
import sys, time, numpy as np, sounddevice as sd
from pathlib import Path
from piper import PiperVoice
ICI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ICI))
fr = PiperVoice.load(str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))
def son(v, t):
    return np.frombuffer(b"".join(c.audio_int16_bytes for c in v.synthesize(t)), np.int16), v.config.sample_rate
if "--reveil" in sys.argv:
    import assistant as A
    from dotenv import load_dotenv
    load_dotenv(ICI / ".env")  # MOT_REVEIL de poc/.env, réglage de secours lu aussi par le serveur
    mot, langue = A.prononciation_reveil()
    voix = fr if langue == "fr" else PiperVoice.load(str(ICI / "voix" / "en_US-lessac-medium.onnx"))
    x, r = son(voix, mot); sd.play(x, r); sd.wait(); time.sleep(1.2)
texte = " ".join(a for a in sys.argv[1:] if a != "--reveil")
if texte:
    x, r = son(fr, texte); sd.play(x, r); sd.wait()
