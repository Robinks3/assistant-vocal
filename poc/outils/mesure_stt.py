"""Mesure la latence STT sur une commande courte synthétisée par Piper."""
import time, numpy as np
from piper import PiperVoice
from faster_whisper import WhisperModel

voix = PiperVoice.load("poc/voix/fr_FR-siwis-medium.onnx")
t = time.perf_counter()
audio = b"".join(c.audio_int16_bytes for c in voix.synthesize("Éteins la lumière du salon et mets la musique sur le Enceintes."))
print(f"TTS {time.perf_counter()-t:.2f}s, sr={voix.config.sample_rate}")
x = np.frombuffer(audio, np.int16).astype(np.float32) / 32768
# rééchantillonnage simple 22050 -> 16000
n = int(len(x) * 16000 / voix.config.sample_rate)
x16 = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
print(f"audio {len(x16)/16000:.1f}s")
for nom in ["small", "medium", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"]:
    m = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=8)
    m.transcribe(x16, language="fr", beam_size=1)  # chauffe
    for _ in range(2):
        t = time.perf_counter()
        segs, _ = m.transcribe(x16, language="fr", beam_size=1, without_timestamps=True, condition_on_previous_text=False)
        txt = "".join(s.text for s in segs)
        print(f"{nom.split('/')[-1]:32s} {time.perf_counter()-t:.2f}s  {txt}")
