"""Analyse d'image déportée sur le PC pour la tablette (v0.18.0) : visages, regard, empreinte.

Idée reprise d'un projet d'inspiration, réécrite ici. Mêmes modèles
publiés par OpenCV : YuNet pour trouver les visages (licence MIT) et SFace pour en tirer une
empreinte de 128 nombres (Apache 2.0), dans poc/modeles/vision/.

Le serveur ne garde rien : ni image, ni empreinte. Il rend les visages trouvés, et la tablette
compare elle-même les empreintes aux profils qu'elle a enregistrés. Ainsi les profils ne vivent
qu'à un seul endroit, que la vision tourne sur la tablette ou sur le PC.
"""
import base64, sys, time
from pathlib import Path

import numpy as np

DOSSIER = Path(__file__).resolve().parent / "modeles" / "vision"
SEUIL_VISAGE = 0.7
TAILLE_MAX = 4_000_000  # octets de JPEG en base64 acceptés par image


def disponible():
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return (DOSSIER / "yunet.onnx").exists() and (DOSSIER / "sface.onnx").exists()


def regard(points):
    """Vrai si la personne regarde l'appareil : le nez reste entre les yeux (visage de face).
    points : œil droit, œil gauche, nez, coin droit et coin gauche de la bouche (YuNet)."""
    (xd, yd), (xg, yg), (xn, yn) = points[0], points[1], points[2]
    ecart = max(abs(xg - xd), 1e-6)
    lacet = (xn - (xd + xg) / 2) / ecart          # 0 de face, vers ±0,5 de profil
    hauteur = (yn - (yd + yg) / 2) / ecart        # le nez sous les yeux, environ 0,5 à 0,9 de face
    return abs(lacet) < 0.22 and 0.25 < hauteur < 1.2, round(float(lacet), 2)


class Vision:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.detecteur = cv2.FaceDetectorYN.create(str(DOSSIER / "yunet.onnx"), "", (320, 240), SEUIL_VISAGE, 0.3, 20)
        self.reconnaisseur = cv2.FaceRecognizerSF.create(str(DOSSIER / "sface.onnx"), "")

    def analyser(self, jpeg):
        cv2 = self.cv2
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("image illisible")
        h, w = image.shape[:2]
        self.detecteur.setInputSize((w, h))
        _, visages = self.detecteur.detect(image)
        sortie = []
        for v in (visages if visages is not None else []):
            points = v[4:14].reshape(5, 2)
            de_face, lacet = regard(points)
            empreinte = self.reconnaisseur.feature(self.reconnaisseur.alignCrop(image, v)).flatten()
            empreinte = empreinte / max(float(np.linalg.norm(empreinte)), 1e-9)
            sortie.append({"boite": [round(float(x), 1) for x in v[0:4]], "score": round(float(v[14]), 3),
                           "points": [[round(float(x), 1), round(float(y), 1)] for x, y in points],
                           "regard": bool(de_face), "lacet": lacet,
                           "empreinte": [round(float(x), 5) for x in empreinte]})
        return w, h, sortie


def traiter_message(vision, msg):
    """Réponse au message {"type":"vision","id","jpeg"} d'une tablette."""
    ident = msg.get("id")
    if vision is None:
        return {"etat": "vision", "id": ident, "erreur": "vision indisponible sur ce serveur"}
    brut = str(msg.get("jpeg", ""))
    if not brut or len(brut) > TAILLE_MAX:
        return {"etat": "vision", "id": ident, "erreur": "image absente ou trop grande"}
    t = time.perf_counter()
    try:
        w, h, visages = vision.analyser(base64.b64decode(brut))
    except Exception as e:
        # Le détail reste dans le journal du serveur, la tablette ne reçoit que le type d'erreur (0.27.3).
        print(f"vision : {e.__class__.__name__} : {e}", file=sys.stderr)
        return {"etat": "vision", "id": ident, "erreur": f"analyse impossible ({e.__class__.__name__})"}
    return {"etat": "vision", "id": ident, "ms": round((time.perf_counter() - t) * 1000),
            "largeur": w, "hauteur": h, "visages": visages}
