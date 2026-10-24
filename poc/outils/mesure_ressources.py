"""Ressources réelles du POC : RAM et temps processeur de la transcription, RAM du LLM."""
import sys, time, os, psutil, numpy as np
sys.path.insert(0, "poc"); sys.stdout.reconfigure(encoding="utf-8")
import assistant as A
moi = psutil.Process()
r0 = moi.memory_info().rss
voix = A.Voix(str(A.ICI / "voix" / "fr_FR-siwis-medium.onnx"), "")
r1 = moi.memory_info().rss
stt = A.Transcripteur()
r2 = moi.memory_info().rss
print(f"RAM Python de base {r0/1e6:.0f} Mo, Piper +{(r1-r0)/1e6:.0f} Mo, Canary +{(r2-r1)/1e6:.0f} Mo, total {r2/1e9:.2f} Go")
brut = voix.synthetiser("Mets la télé sur la prise HDMI trois et allume la lumière du salon.").astype(np.float32) / 32768
n = int(len(brut) * 16000 / voix.taux)
x = np.interp(np.linspace(0, len(brut) - 1, n), np.arange(len(brut)), brut).astype(np.float32)
stt.transcrire(x)
for _ in range(3):
    c0, t0 = moi.cpu_times(), time.perf_counter()
    stt.transcrire(x)
    c1, t1 = moi.cpu_times(), time.perf_counter()
    cpu = (c1.user - c0.user) + (c1.system - c0.system)
    print(f"transcription de {len(x)/16000:.1f} s d'audio : {t1-t0:.2f} s réelles, {cpu:.2f} s de processeur (~{cpu/(t1-t0):.1f} cœurs occupés)")
c0, t0 = moi.cpu_times(), time.perf_counter(); voix.synthetiser("La télévision du séjour est maintenant allumée."); c1 = moi.cpu_times()
print(f"synthèse Piper : {time.perf_counter()-t0:.2f} s, {(c1.user-c0.user)+(c1.system-c0.system):.2f} s de processeur")
for p in psutil.process_iter(["name", "memory_info", "cpu_times"]):
    if p.info["name"] and "llama-server" in p.info["name"]:
        print(f"llama-server : RAM système {p.info['memory_info'].rss/1e9:.2f} Go")
print(f"RAM totale de la machine {psutil.virtual_memory().total/1e9:.0f} Go, coeurs logiques {psutil.cpu_count()}")
