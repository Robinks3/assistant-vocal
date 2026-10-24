"""Chaîne complète sans micro ni haut-parleur : Piper -> Parakeet -> cerveau -> Piper."""
import sys, time, numpy as np
sys.path.insert(0, "poc")
import assistant as A
sys.stdout.reconfigure(encoding="utf-8")
cfg = A.charger_env()
a = A.Assistant(cfg, essai="--reel" not in sys.argv)  # essai par défaut : rien n'est exécuté
sys.argv = [x for x in sys.argv if x != "--reel"]
a.voix.jouer = lambda *x, **k: None  # pas de son
for phrase in sys.argv[1:]:
    brut = a.voix.synthetiser(phrase).astype(np.float32) / 32768
    n = int(len(brut) * 16000 / a.voix.taux)
    x16 = np.interp(np.linspace(0, len(brut) - 1, n), np.arange(len(brut)), brut).astype(np.float32)
    t = time.perf_counter(); texte = a.stt.transcrire(x16); t_stt = time.perf_counter() - t
    print(f"\n> {phrase}\n  STT : {texte}")
    a.traiter(texte, t_stt)
