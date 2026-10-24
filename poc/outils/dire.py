"""Fait parler le PC (haut-parleurs) pour tester un satellite à l'oreille.

Usage : python poc/outils/dire.py "phrase en français" [--reveil]   (--reveil : « Hey Jarvis » à l'anglaise avant)"""
import sys, time, numpy as np, sounddevice as sd
from pathlib import Path
from piper import PiperVoice
ICI = Path(__file__).resolve().parents[1]
fr = PiperVoice.load(str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))
def son(v, t):
    return np.frombuffer(b"".join(c.audio_int16_bytes for c in v.synthesize(t)), np.int16), v.config.sample_rate
if "--reveil" in sys.argv:
    en = PiperVoice.load(str(ICI / "voix" / "en_US-lessac-medium.onnx"))
    x, r = son(en, "Hey Jarvis!"); sd.play(x, r); sd.wait(); time.sleep(1.2)
texte = " ".join(a for a in sys.argv[1:] if a != "--reveil")
if texte:
    x, r = son(fr, texte); sd.play(x, r); sd.wait()
