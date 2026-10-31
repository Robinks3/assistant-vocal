"""Mesure Parakeet TDT v3 (onnx-asr) sur la même commande que mesure_stt.py."""
import time, numpy as np, onnx_asr
from piper import PiperVoice
voix = PiperVoice.load("poc/voix/fr_FR-siwis-medium.onnx")
audio = b"".join(c.audio_int16_bytes for c in voix.synthesize("Éteins la lumière du salon et mets la musique sur l'enceinte."))
x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768
n = int(len(x) * 16000 / voix.config.sample_rate)
x16 = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
for q in ["int8", None]:
    t = time.perf_counter()
    m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization=q)
    print(f"chargement {q}: {time.perf_counter()-t:.1f}s")
    m.recognize(x16)
    for _ in range(3):
        t = time.perf_counter(); txt = m.recognize(x16)
        print(f"parakeet {q}: {time.perf_counter()-t:.2f}s  {txt}")
