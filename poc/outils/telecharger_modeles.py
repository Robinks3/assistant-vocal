"""Télécharge les gros modèles absents du dépôt, vérifie leur empreinte SHA-256 et les range.

Les petits modèles (mot de réveil de l'appli, Silero VAD, YuNet) sont versionnés. Les gros (voix Piper,
SFace) ne le sont pas : ce script les récupère à des versions épinglées, vérifiées par leur empreinte, et
copie SFace dans les assets de l'appli Android avant sa compilation. Depuis la 0.25.1, il fait aussi
télécharger par openWakeWord son modèle « hey_jarvis » et ses modèles de prétraitement, dont le serveur
a besoin pour guetter le mot de réveil (sans vérification d'empreinte, rangés par openWakeWord dans son
propre dossier). Canary (transcription) se télécharge seul au premier lancement par onnx-asr, et sa copie
sur les téléphones se fait par adb.
Usage : python poc/outils/telecharger_modeles.py"""
import hashlib, shutil, sys, urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models"
MODELES = [
    ("poc/voix/fr_FR-siwis-medium.onnx", f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
     "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"),
    ("poc/voix/fr_FR-siwis-medium.onnx.json", f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json",
     "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"),
    ("poc/modeles/vision/sface.onnx", f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
     "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
]
COPIES = [("poc/modeles/vision/sface.onnx", "android/app/src/main/assets/vision/sface.onnx")]


def empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for relatif, url, attendu in MODELES:
        cible = RACINE / relatif
        if cible.exists() and empreinte(cible) == attendu:
            print(f"déjà là : {relatif}")
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        provisoire = cible.with_suffix(cible.suffix + ".part")
        print(f"téléchargement : {relatif}")
        urllib.request.urlretrieve(url, provisoire)
        if empreinte(provisoire) != attendu:
            provisoire.unlink()
            sys.exit(f"empreinte inattendue pour {relatif}, fichier écarté")
        provisoire.replace(cible)
    for source, destination in COPIES:
        d = RACINE / destination
        if not d.exists() or empreinte(d) != empreinte(RACINE / source):
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(RACINE / source, d)
            print(f"copié : {destination}")
    # Mot de réveil par défaut du serveur : rangé par openWakeWord dans son propre dossier.
    try:
        import openwakeword.utils
    except ImportError:
        sys.exit("openwakeword absent : installer d'abord les dépendances (pip install -r poc/requirements.txt)")
    openwakeword.utils.download_models(["hey_jarvis"])
    print("openWakeWord : hey_jarvis prêt")
    print("modèles prêts")


if __name__ == "__main__":
    main()
