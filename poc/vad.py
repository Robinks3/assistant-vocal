"""Détection de parole Silero VAD v5 (ONNX, licence MIT, github.com/snakers4/silero-vad v5.1.2).

Remplace le seuil d'énergie pour trouver le début et la fin d'une phrase : la télé, un bip ou
un bruit de fond ne passent plus pour de la parole, et la fin de phrase arrive plus tôt.
Idée reprise d'un projet d'inspiration (auteurs inspiration, perception/vad.py), réécrite ici.

Le modèle travaille par fenêtres de 512 échantillons à 16 kHz (32 ms), précédées des 64
derniers échantillons de la fenêtre d'avant, avec un état récurrent qu'on garde entre deux appels.
Deux seuils : 0,5 pour dire que la parole commence, 0,35 pour dire qu'elle s'est arrêtée."""
import os
from pathlib import Path

import numpy as np

MODELE = Path(os.getenv("VAD_MODELE", str(Path(__file__).resolve().parent / "modeles" / "silero_vad.onnx")))
FENETRE, CONTEXTE, TAUX = 512, 64, 16000
SEUIL_DEBUT, SEUIL_FIN = 0.5, 0.35


_ECHEC = None


def disponible():
    return MODELE.exists() and _ECHEC is None


def creer():
    """Un détecteur prêt, ou None (modèle absent, onnxruntime qui ne charge pas sur ce processeur) :
    l'appelant retombe alors sur le seuil d'énergie au lieu de planter."""
    global _ECHEC
    if not disponible():
        return None
    try:
        return Vad()
    except Exception as e:
        _ECHEC = f"{e.__class__.__name__} : {e}"
        print(f"  Silero VAD indisponible ({_ECHEC}), seuil d'énergie à la place")
        return None


class Vad:
    """Probabilité de parole d'un flux continu, un objet par micro (l'état est propre au flux)."""

    def __init__(self):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(MODELE), options, providers=["CPUExecutionProvider"])
        self.reinitialiser()

    def reinitialiser(self):
        self.etat = np.zeros((2, 1, 128), dtype=np.float32)
        self.contexte = np.zeros(CONTEXTE, dtype=np.float32)
        self.reste = np.zeros(0, dtype=np.float32)
        self.parle = False

    def probabilites(self, signal_f32):
        """Probabilité de chaque fenêtre complète de 32 ms du morceau reçu (le reste attend le suivant)."""
        x = np.concatenate([self.reste, np.asarray(signal_f32, dtype=np.float32)])
        sorties = []
        while len(x) >= FENETRE:
            fenetre, x = x[:FENETRE], x[FENETRE:]
            entree = np.concatenate([self.contexte, fenetre])[None, :]
            sortie, self.etat = self.session.run(None, {"input": entree, "state": self.etat,
                                                       "sr": np.array(TAUX, dtype=np.int64)})
            self.contexte = fenetre[-CONTEXTE:]
            sorties.append(float(sortie[0][0]))
        self.reste = x
        return sorties

    def parole(self, signal_f32):
        """Vrai si on est dans la parole à la fin de ce morceau (hystérésis entre les deux seuils)."""
        for p in self.probabilites(signal_f32):
            if self.parle:
                self.parle = p >= SEUIL_FIN
            else:
                self.parle = p >= SEUIL_DEBUT
        return self.parle
