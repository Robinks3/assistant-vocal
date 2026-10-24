"""Canary 1B v2 avec le français imposé, sur des commandes courtes synthétisées par Piper."""
import sys, time, numpy as np, onnx_asr
from piper import PiperVoice
sys.stdout.reconfigure(encoding="utf-8")
voix = PiperVoice.load("poc/voix/fr_FR-siwis-medium.onnx")
def audio(t):
    x = np.frombuffer(b"".join(c.audio_int16_bytes for c in voix.synthesize(t)), np.int16).astype(np.float32) / 32768
    n = int(len(x) * 16000 / voix.config.sample_rate)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
phrases = ["Éteins la télé.", "Bonne nuit.", "Lance la musique.", "Aspire la chambre du fond."]
for q in ["int8", None]:
    t = time.perf_counter(); m = onnx_asr.load_model("nemo-canary-1b-v2", quantization=q); print(f"chargement {q} {time.perf_counter()-t:.1f}s")
    m.recognize(audio("test"), language="fr")
    for p in phrases:
        x = audio(p); t = time.perf_counter(); r = m.recognize(x, language="fr"); print(f"  {q} {time.perf_counter()-t:.2f}s  {r}")
