"""Essai hors ligne de Silero VAD et des mots de réveil sur des phrases dites par Piper.

Pour chaque phrase : score maximal de chaque modèle de réveil, et découpage de la parole par Silero
(début, fin, durée trouvée). Ne remplace pas un essai au micro : la voix siwis de Piper a servi à
entraîner le mot de réveil de la configuration, son score ici est donc trop flatteur.
Usage : .venv\\Scripts\\python poc\\outils\\essai_vad_reveil.py"""
import sys
from pathlib import Path

import numpy as np

ICI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ICI))
import maison  # noqa: E402
import vad as V  # noqa: E402

# Mot de réveil de la configuration (section reveil de maison.json, modèle reveil/<mot>.onnx), s'il y en a un.
MOT = str((maison.CONFIG.get("reveil") or {}).get("mot") or "").strip().lower()

PHRASES = ["Assistant", "Hey Jarvis", "Jarvis", "Allume la lumière du salon", "Assistance", "Bonne nuit Assistante"]


def reechantillonner(x, de, vers=16000):
    t = np.linspace(0, len(x) / de, int(len(x) * vers / de), endpoint=False)
    return np.interp(t, np.arange(len(x)) / de, x).astype(np.float32)


def main():
    from piper import PiperVoice
    from openwakeword.model import Model
    sys.stdout.reconfigure(encoding="utf-8")
    voix = PiperVoice.load(str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))
    modeles = {"hey_jarvis": Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")}
    if MOT and (maison.DOSSIER / "reveil" / f"{MOT}.onnx").exists():
        modeles[MOT] = Model(wakeword_models=[str(maison.DOSSIER / "reveil" / f"{MOT}.onnx")], inference_framework="onnx")
    vad = V.Vad()
    silence = np.zeros(8000, dtype=np.float32)
    for phrase in PHRASES:
        brut = b"".join(c.audio_int16_bytes for c in voix.synthesize(phrase))
        x = reechantillonner(np.frombuffer(brut, np.int16) / 32768.0, voix.config.sample_rate)
        signal = np.concatenate([silence, x, silence, silence])
        scores = {}
        for nom, m in modeles.items():
            m.reset()
            pcm = (signal * 32767).astype(np.int16)
            scores[nom] = max(max(m.predict(pcm[i:i + 1280]).values()) for i in range(0, len(pcm) - 1280, 1280))
        vad.reinitialiser()
        etats = [vad.parole(signal[i:i + 512]) for i in range(0, len(signal) - 512, 512)]
        debut = etats.index(True) * 0.032 if True in etats else None
        fin = (len(etats) - etats[::-1].index(True)) * 0.032 if True in etats else None
        print(f"{phrase:<30} réveil " + ", ".join(f"{n} {s:.2f}" for n, s in scores.items())
              + (f" | parole de {debut:.2f} à {fin:.2f} s (vraie : 0,50 à {0.5 + len(x) / 16000:.2f} s)"
                 if debut is not None else " | aucune parole trouvée"))
    vad.reinitialiser()
    bruit = (np.random.default_rng(1).normal(0, 0.02, 16000 * 3)).astype(np.float32)
    print("bruit blanc 3 s : parole trouvée" if any(vad.parole(bruit[i:i + 512]) for i in range(0, len(bruit) - 512, 512))
          else "bruit blanc 3 s : aucune parole, comme attendu")


if __name__ == "__main__":
    main()
