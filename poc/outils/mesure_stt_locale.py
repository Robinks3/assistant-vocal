"""Compare les moteurs de reconnaissance qui tournent sur le processeur du PC, hors ligne (S-D8).

Aucun serveur, aucun micro, aucun réseau : les phrases sont dites par Piper (voix du dossier `voix`), écrites dans
un dossier temporaire hors du dépôt, puis transcrites par chaque moteur. Pour chaque moteur : temps de chargement,
latence par phrase (médiane de plusieurs passes après une passe de chauffe), taux d'erreur de mots (WER) et nombre
de phrases exactes, sur voix propre puis avec un bruit blanc ajouté (rapport signal sur bruit de 15 dB).

Moteurs : canary_int8 (celui du profil PC, `Transcripteur`), canary_fp32, parakeet_int8, whisper_small,
whisper_medium, whisper_turbo (faster-whisper, int8). Les modèles doivent déjà être dans le cache Hugging Face : le
mode hors ligne est imposé, rien n'est téléchargé.

Limite : une seule voix de synthèse, propre et régulière. Les chiffres de justesse sont donc optimistes par rapport
à une vraie voix dans une pièce. Les écarts entre moteurs, eux, sont comparables.

Usage : python poc/outils/mesure_stt_locale.py [--moteurs canary_int8,parakeet_int8] [--passes 3]
        [--dossier-sortie <dossier hors dépôt>] [--voix <fichier .onnx de Piper>] [--json <fichier>]"""
import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time
import unicodedata
import wave
from pathlib import Path

# Hors ligne avant tout import de huggingface_hub : on mesure ce qui est déjà sur le disque.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

TAUX = 16000
ICI = Path(__file__).resolve().parents[1]

# Phrases du genre de celles que reçoit le serveur : commandes de la maison, questions courtes, nombres.
# Un nombre écrit en chiffres ou en lettres est juste dans les deux cas : VARIANTES donne les écritures acceptées
# en plus de la phrase dite (la comparaison de mots ne juge pas la mise en forme, seulement les mots).
PHRASES = [
    "Éteins la lumière du salon.",
    "Allume la lampe de la télé à quarante pour cent.",
    "Mets la musique sur l'enceinte de la cuisine.",
    "Quel temps fait-il demain matin ?",
    "Baisse le volume de la télé de dix points.",
    "Lance l'aspirateur dans la chambre du fond.",
    "Bonne nuit.",
    "Mets un minuteur de douze minutes.",
    "Il fait combien dans le salon ?",
    "Ouvre le volet roulant de la chambre.",
    "Passe la lampe du bureau en bleu.",
    "Réveille-moi demain à sept heures et demie.",
    "Éteins la télé.",
    "Lance la musique.",
    "Ferme tous les volets du rez-de-chaussée.",
    "Mets le chauffage de la chambre à dix-neuf degrés.",
    "Quelle heure est-il ?",
    "Allume la lumière de la cuisine.",
    "Coupe le son de la télé.",
    "Je pars, éteins tout.",
]

VARIANTES = {
    "Allume la lampe de la télé à quarante pour cent.": ["Allume la lampe de la télé à 40 %."],
    "Baisse le volume de la télé de dix points.": ["Baisse le volume de la télé de 10 points."],
    "Mets un minuteur de douze minutes.": ["Mets un minuteur de 12 minutes."],
    "Mets le chauffage de la chambre à dix-neuf degrés.": ["Mets le chauffage de la chambre à 19 degrés.",
                                                           "Mets le chauffage de la chambre à 19°."],
    "Réveille-moi demain à sept heures et demie.": ["Réveille-moi demain à 7 h 30.", "Réveille-moi demain à 7h30."],
}


def normaliser(texte):
    """Minuscules, sans accents, sans ponctuation : la comparaison de mots ne juge pas la mise en forme."""
    t = unicodedata.normalize("NFD", (texte or "").lower().replace("'", " ").replace("’", " ").replace("%", " pour cent "))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", t).split()


def distance(a, b):
    """Distance d'édition entre deux suites de mots."""
    prec = list(range(len(b) + 1))
    for i, mot_a in enumerate(a, 1):
        cour = [i]
        for j, mot_b in enumerate(b, 1):
            cour.append(min(prec[j] + 1, cour[j - 1] + 1, prec[j - 1] + (mot_a != mot_b)))
        prec = cour
    return prec[-1]


def erreurs_mots(attendu, obtenu):
    """(erreurs, mots attendus) pour une phrase, d'après l'écriture acceptée la plus proche."""
    obtenu = normaliser(obtenu)
    refs = [normaliser(r) for r in [attendu] + VARIANTES.get(attendu, [])]
    return min((distance(r, obtenu), len(r)) for r in refs)


def wer(paires):
    """Taux d'erreur de mots sur une liste de (attendu, obtenu), en pourcentage."""
    erreurs = total = 0
    for attendu, obtenu in paires:
        e, n = erreurs_mots(attendu, obtenu)
        erreurs, total = erreurs + e, total + n
    return 100.0 * erreurs / total if total else 0.0


def ajouter_bruit(signal, rsb_db, graine=0):
    import numpy as np
    rng = np.random.default_rng(graine)
    puissance = float(np.mean(signal ** 2)) or 1e-9
    bruit = rng.normal(0.0, (puissance / (10 ** (rsb_db / 10))) ** 0.5, signal.shape)
    return np.clip(signal + bruit, -1, 1).astype(np.float32)


def synthetiser(phrases, fichier_voix, dossier):
    """Un signal float32 à 16 kHz par phrase. Les WAV vont dans `dossier` (temporaire, hors dépôt)."""
    import numpy as np
    from piper import PiperVoice
    voix = PiperVoice.load(str(fichier_voix))
    signaux = []
    for i, texte in enumerate(phrases):
        x = np.frombuffer(b"".join(c.audio_int16_bytes for c in voix.synthesize(texte)), np.int16).astype(np.float32) / 32768
        n = int(len(x) * TAUX / voix.config.sample_rate)
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        signaux.append(y)
        with wave.open(str(dossier / f"phrase{i:02d}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TAUX)
            w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return signaux


def moteur_onnx(modele, quantification):
    import onnx_asr
    m = onnx_asr.load_model(modele, quantization=quantification)
    # Comme le serveur : Canary a le français imposé, Parakeet devine la langue.
    if modele.startswith("nemo-canary"):
        return lambda x: m.recognize(x, language="fr").strip()
    return lambda x: str(m.recognize(x)).strip()


def moteur_whisper(nom):
    from faster_whisper import WhisperModel
    m = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=8, local_files_only=True)

    def transcrire(x):
        segments, _ = m.transcribe(x, language="fr", beam_size=1, without_timestamps=True,
                                   condition_on_previous_text=False)
        return "".join(s.text for s in segments).strip()
    return transcrire


MOTEURS = {
    "canary_int8": lambda: moteur_onnx("nemo-canary-1b-v2", "int8"),
    "canary_fp32": lambda: moteur_onnx("nemo-canary-1b-v2", None),
    "parakeet_int8": lambda: moteur_onnx("nemo-parakeet-tdt-0.6b-v3", "int8"),
    "whisper_small": lambda: moteur_whisper("small"),
    "whisper_medium": lambda: moteur_whisper("medium"),
    "whisper_turbo": lambda: moteur_whisper("mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
}


def centile(valeurs, p):
    v = sorted(valeurs)
    k = (len(v) - 1) * p / 100
    bas = int(k)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (k - bas)


def mesurer(nom, signaux_par_condition, passes):
    t = time.perf_counter()
    transcrire = MOTEURS[nom]()
    charge = time.perf_counter() - t
    transcrire(signaux_par_condition["propre"][0])  # chauffe
    resultat = {"moteur": nom, "chargement_s": round(charge, 1), "conditions": {}}
    for condition, signaux in signaux_par_condition.items():
        latences, paires, textes = [], [], []
        for attendu, x in zip(PHRASES, signaux):
            temps = []
            for _ in range(passes):
                t = time.perf_counter()
                texte = transcrire(x)
                temps.append(time.perf_counter() - t)
            latences.append(statistics.median(temps))
            paires.append((attendu, texte))
            textes.append(texte)
        resultat["conditions"][condition] = {
            "latence_mediane_s": round(statistics.median(latences), 3),
            "latence_p95_s": round(centile(latences, 95), 3),
            "latence_max_s": round(max(latences), 3),
            "wer_pct": round(wer(paires), 1),
            "phrases_exactes": sum(1 for a, o in paires if erreurs_mots(a, o)[0] == 0),
            "phrases": len(paires),
            "erreurs": [{"attendu": a, "obtenu": o} for a, o in paires if erreurs_mots(a, o)[0]],
        }
    return resultat


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--moteurs", default=",".join(MOTEURS))
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--dossier-sortie", default="")
    p.add_argument("--voix", default=str(ICI / "voix" / "fr_FR-siwis-medium.onnx"))
    p.add_argument("--json", default="")
    a = p.parse_args()
    depot = ICI.parent.resolve()
    dossier = Path(a.dossier_sortie or tempfile.mkdtemp(prefix="mesure_stt_")).resolve()
    if dossier == depot or depot in dossier.parents:
        sys.exit("Le dossier de sortie doit être hors du dépôt (les WAV ne se commitent jamais).")
    dossier.mkdir(parents=True, exist_ok=True)
    print(f"WAV synthétiques dans {dossier}")
    propres = synthetiser(PHRASES, Path(a.voix), dossier)
    signaux = {"propre": propres, "bruit 15 dB": [ajouter_bruit(x, 15, i) for i, x in enumerate(propres)]}
    duree = statistics.mean(len(x) for x in propres) / TAUX
    print(f"{len(PHRASES)} phrases, durée moyenne {duree:.1f} s, {a.passes} passes par phrase")
    sorties = []
    for nom in a.moteurs.split(","):
        r = mesurer(nom.strip(), signaux, a.passes)
        sorties.append(r)
        c = r["conditions"]
        print(f"{nom:16s} chargement {r['chargement_s']:5.1f} s | " + " | ".join(
            f"{k} : med {v['latence_mediane_s']:.2f} s, max {v['latence_max_s']:.2f} s, WER {v['wer_pct']:.1f} %, "
            f"{v['phrases_exactes']}/{v['phrases']} exactes" for k, v in c.items()))
        for k, v in c.items():
            for e in v["erreurs"]:
                print(f"    [{k}] attendu : {e['attendu']} | obtenu : {e['obtenu']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"duree_moyenne_s": round(duree, 2), "moteurs": sorties},
                                           ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
