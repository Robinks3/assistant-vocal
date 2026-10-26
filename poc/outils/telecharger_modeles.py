"""Télécharge les gros modèles absents du dépôt, vérifie leur empreinte SHA-256 et les range.

Les petits modèles sous licence libre (Silero VAD, YuNet) sont versionnés. Les gros (voix Piper
française et anglaise, SFace) ne le sont pas : ce script les récupère à des versions épinglées, vérifiées
par leur empreinte, et copie SFace dans les assets de l'appli Android avant sa compilation. Depuis la 0.25.1, il fait aussi
télécharger par openWakeWord son modèle « hey_jarvis » et ses modèles de prétraitement, dont le serveur
a besoin pour guetter le mot de réveil (sans vérification d'empreinte, rangés par openWakeWord dans son
propre dossier). Canary (transcription) se télécharge seul au premier lancement par onnx-asr, et sa copie
sur les téléphones se fait par adb.

Modèles sous licence non commerciale (0.34.1, décision D2 du plan) : le mot de réveil « hey_jarvis » et les
deux modèles de prétraitement d'openWakeWord sont sous CC BY-NC-SA 4.0. Le dépôt public ne les redistribue
pas : ce script les télécharge depuis la publication officielle d'openWakeWord (v0.5.1), vérifie leur
empreinte et affiche leur licence avant le téléchargement. Les ranger dans les assets de l'appli Android
est nécessaire à la compilation de l'APK. `message_modeles_manquants` donne le message à afficher quand
l'un d'eux manque (voir `verifier_au_demarrage`).
Usage : python poc/outils/telecharger_modeles.py"""
import hashlib, importlib.util, shutil, sys, urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models"
OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
ASSETS_REVEIL = "android/app/src/main/assets/reveil"
MODELES = [
    ("poc/voix/fr_FR-siwis-medium.onnx", f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
     "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"),
    ("poc/voix/fr_FR-siwis-medium.onnx.json", f"{PIPER}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json",
     "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"),
    # Voix anglaise de poc/outils/faux_telephone.py (mot de réveil dit à l'anglaise), pas du serveur (0.27.3).
    ("poc/voix/en_US-lessac-medium.onnx", f"{PIPER}/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
     "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
    ("poc/voix/en_US-lessac-medium.onnx.json", f"{PIPER}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
     "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
    ("poc/modeles/vision/sface.onnx", f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
     "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
    # Mot de réveil de l'appli Android et ses deux modèles de prétraitement : CC BY-NC-SA 4.0 (voir LICENCES).
    # Les empreintes sont celles des fichiers de la publication v0.5.1, identiques octet pour octet à ceux
    # que livre la roue openwakeword 0.6.0 (même SHA-256).
    (f"{ASSETS_REVEIL}/hey_jarvis_v0.1.onnx", f"{OWW}/hey_jarvis_v0.1.onnx",
     "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"),
    (f"{ASSETS_REVEIL}/embedding_model.onnx", f"{OWW}/embedding_model.onnx",
     "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
    (f"{ASSETS_REVEIL}/melspectrogram.onnx", f"{OWW}/melspectrogram.onnx",
     "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
]
COPIES = [("poc/modeles/vision/sface.onnx", "android/app/src/main/assets/vision/sface.onnx")]

# Modèles dont la licence interdit de les redistribuer dans le dépôt public : chemin relatif -> (licence, page
# de la licence, auteur et dépôt d'origine). Leur licence est citée avant le téléchargement et dans le message
# des modèles manquants.
CC_BY_NC_SA = ("CC BY-NC-SA 4.0 (usage non commercial, partage dans les mêmes conditions)",
               "https://creativecommons.org/licenses/by-nc-sa/4.0/",
               "openWakeWord, David Scripka (github.com/dscripka/openWakeWord)")
LICENCES = {
    f"{ASSETS_REVEIL}/hey_jarvis_v0.1.onnx": CC_BY_NC_SA,
    f"{ASSETS_REVEIL}/embedding_model.onnx": CC_BY_NC_SA,
    f"{ASSETS_REVEIL}/melspectrogram.onnx": CC_BY_NC_SA,
}

# Modèles du serveur, hors dossier du dépôt : openWakeWord les range dans son propre paquet.
OWW_PAQUET = ("hey_jarvis_v0.1.onnx", "embedding_model.onnx", "melspectrogram.onnx")
GROUPES = {
    # Le serveur ne démarre pas sans la voix. Le mot de réveil est vérifié dans le paquet openWakeWord.
    "serveur": ["poc/voix/fr_FR-siwis-medium.onnx", "poc/voix/fr_FR-siwis-medium.onnx.json"],
    # Compilation de l'APK : mot de réveil, prétraitement et SFace dans les assets.
    "android": [f"{ASSETS_REVEIL}/hey_jarvis_v0.1.onnx", f"{ASSETS_REVEIL}/embedding_model.onnx",
                f"{ASSETS_REVEIL}/melspectrogram.onnx", "android/app/src/main/assets/vision/sface.onnx"],
}


def empreinte(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _dossier_openwakeword():
    """Dossier des modèles du paquet openWakeWord, ou None si le paquet n'est pas installé."""
    spec = importlib.util.find_spec("openwakeword")
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).parent / "resources" / "models"


def modeles_manquants(groupe, racine=RACINE):
    """Liste des modèles absents (ou vides) du groupe « serveur » ou « android », en chemins lisibles."""
    if groupe not in GROUPES:
        raise ValueError(f"groupe inconnu : {groupe}")
    absents = []
    for relatif in GROUPES[groupe]:
        chemin = Path(racine) / relatif
        if not chemin.is_file() or chemin.stat().st_size == 0:
            absents.append(relatif)
    if groupe == "serveur":
        dossier = _dossier_openwakeword()
        if dossier is not None:
            for nom in OWW_PAQUET:
                chemin = dossier / nom
                if not chemin.is_file() or chemin.stat().st_size == 0:
                    absents.append(f"openwakeword/resources/models/{nom}")
    return absents


def message_modeles_manquants(groupe, racine=RACINE):
    """Message clair en français pour les modèles manquants du groupe, chaîne vide si tout est là.

    Dit quoi manque, quelle licence s'applique quand elle interdit la redistribution, et la commande qui
    les récupère."""
    absents = modeles_manquants(groupe, racine)
    if not absents:
        return ""
    lignes = [f"Modèles manquants ({len(absents)}) :"]
    licencies = []
    for relatif in absents:
        lignes.append(f"  - {relatif}")
        if relatif in LICENCES:
            licencies.append(relatif)
    if licencies:
        licence, page, origine = CC_BY_NC_SA
        lignes.append(f"Le mot de réveil et son prétraitement ne sont pas redistribués avec le code : ils sont sous "
                      f"licence {licence}, {origine}, {page}. Les télécharger vaut acceptation de cette licence.")
    lignes.append("Les récupérer (adresse officielle, empreinte SHA-256 vérifiée) : "
                  "python poc/outils/telecharger_modeles.py")
    return "\n".join(lignes)


def verifier_au_demarrage(groupe="serveur", racine=RACINE, sortie=None):
    """À appeler au démarrage du serveur : affiche le message des modèles manquants, renvoie True si tout est là."""
    message = message_modeles_manquants(groupe, racine)
    if message:
        print(message, file=sortie or sys.stderr)
    return not message


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for relatif, url, attendu in MODELES:
        cible = RACINE / relatif
        if cible.exists() and empreinte(cible) == attendu:
            print(f"déjà là : {relatif}")
            continue
        if relatif in LICENCES:
            licence, page, origine = LICENCES[relatif]
            print(f"licence de {relatif} : {licence}, {origine}, {page}")
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
