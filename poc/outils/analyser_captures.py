"""Captures du mot de réveil faites par l'appli Android (0.53.0) : récupération, liste, nouvelle passe du
détecteur, balayage des seuils et écoute. Base d'un futur réajustement du seuil ou du modèle.

Une capture = `capture-AAAAMMJJ-HHMMSS-mmm.wav` (30 s, 16 kHz, mono, 16 bits) et son `.json` : étiquette
(`manque`, `reveil`, `faux_probable`, `faux_signale`), cause, issue de l'écoute, réglages en vigueur, et par
bloc de 80 ms le score du détecteur, la probabilité de parole de Silero, le niveau en dB et la phase
(R repos, E écoute, T traitement, P réponse, S mode serveur). Le dernier bloc est celui de l'événement.

Les captures sont des données d'usage : le son de tout le logement. Elles ne vont jamais dans un dépôt.
Dossier par défaut : ASSISTANT_VOCAL_CAPTURES, sinon C:/Dev/captures-reveil sous Windows (hors de Documents,
donc hors sauvegarde en ligne), ~/captures-reveil ailleurs.

Usage (depuis la racine du moteur) :
  .venv\\Scripts\\python poc\\outils\\analyser_captures.py recuperer --serie <série adb> [--effacer]
  .venv\\Scripts\\python poc\\outils\\analyser_captures.py lister [--etiquette manque]
  .venv\\Scripts\\python poc\\outils\\analyser_captures.py rejouer [noms...] [--csv scores.csv]
  .venv\\Scripts\\python poc\\outils\\analyser_captures.py seuils [--source rejoue]
  .venv\\Scripts\\python poc\\outils\\analyser_captures.py ecouter <nom>
`recuperer` exige toujours la série adb de l'appareil (jamais d'adb sans -s : plusieurs appareils peuvent
être branchés) et passe par `run-as`, donc une APK de débogage."""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

ICI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ICI))

TAUX = 16000
BLOC = 1280
DOSSIER_APPAREIL = "files/captures-reveil"
MOTIF_NOM = re.compile(r"^capture-\d{8}-\d{6}-\d{3}$")
ETIQUETTES = ("manque", "reveil", "faux_probable", "faux_signale")
#  Règle de confirmation de l'appli (ConfirmationReveil.kt) : deux blocs de suite, parole vue dans les 15 derniers.
BLOCS_SCORE = 2
MEMOIRE_VOIX = 15
SEUIL_VOIX = 0.5
MODELE_REPLI = "hey_jarvis_v0.1.onnx"


def version():
    """Version du serveur (poc/assistant.py), affichée en tête de chaque sortie."""
    m = re.search(r'^VERSION = "([^"]+)"', (ICI / "assistant.py").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def dossier_defaut():
    voulu = os.environ.get("ASSISTANT_VOCAL_CAPTURES", "").strip()
    if voulu:
        return Path(voulu)
    return Path("C:/Dev/captures-reveil") if os.name == "nt" else Path.home() / "captures-reveil"


# ---------------------------------------------------------------- lecture

@dataclass
class Capture:
    nom: str
    meta: dict
    wav: Path

    @property
    def etiquette(self):
        return self.meta.get("etiquette") or "?"

    @property
    def scores(self):
        return self.meta.get("scores") or []

    @property
    def vad(self):
        return self.meta.get("vad") or []

    @property
    def phases(self):
        return self.meta.get("phases") or ""

    @property
    def seuil(self):
        return self.meta.get("seuil")

    def score_max(self):
        valeurs = [s for s in self.scores if s is not None]
        return max(valeurs) if valeurs else None

    def blocs_au_dessus(self, seuil=None):
        s = self.seuil if seuil is None else seuil
        if s is None:
            return None
        return sum(1 for v in self.scores if v is not None and v >= s)

    def son(self):
        import numpy as np
        with wave.open(str(self.wav), "rb") as w:
            if w.getframerate() != TAUX or w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"{self.wav.name} : format inattendu")
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def lire_captures(dossier, noms=None, etiquette=None):
    """Captures complètes (WAV et JSON) du dossier, de la plus ancienne à la plus récente."""
    dossier = Path(dossier)
    if not dossier.is_dir():
        return []
    voulus = set(noms or [])
    sortie = []
    for j in sorted(dossier.glob("capture-*.json")):
        nom = j.stem
        if voulus and nom not in voulus:
            continue
        w = j.with_suffix(".wav")
        if not w.exists():
            continue
        try:
            meta = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"  {j.name} illisible, ignoré", file=sys.stderr)
            continue
        c = Capture(nom, meta, w)
        if etiquette and c.etiquette != etiquette:
            continue
        sortie.append(c)
    return sortie


# ---------------------------------------------------------------- récupération

def chemin_adb():
    explicite = os.environ.get("ADB", "").strip()
    if explicite:
        return explicite
    trouve = shutil.which("adb")
    if trouve:
        return trouve
    sdk = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    return str(sdk) if sdk.exists() else "adb"


def id_application():
    """Identifiant de l'appli Android de la configuration (appareils.android.application_id de maison.json)."""
    import maison
    a = ((maison.CONFIG.get("appareils") or {}).get("android") or {})
    return str(a.get("application_id") or "").strip()


def extraire(archive, destination):
    """Extrait d'une archive tar les seuls fichiers de captures, à plat, sans jamais sortir de [destination].
    Rend la liste des (nom de fichier, taille) écrits."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    ecrits = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            nom = Path(m.name).name
            base, _, ext = nom.rpartition(".")
            if ext not in ("wav", "json") or not MOTIF_NOM.match(base):
                continue
            donnees = t.extractfile(m).read()
            if len(donnees) != m.size:
                raise IOError(f"{nom} tronqué dans l'archive")
            (destination / nom).write_bytes(donnees)
            ecrits.append((nom, m.size))
    return ecrits


def recuperer(serie, appli, destination, effacer=False, adb=None):
    if not serie:
        raise SystemExit("--serie est obligatoire : jamais d'adb sans -s")
    if not appli:
        raise SystemExit("identifiant de l'appli inconnu : --appli, ou appareils.android.application_id dans maison.json")
    adb = adb or chemin_adb()
    base = [adb, "-s", serie]
    r = subprocess.run(base + ["exec-out", "run-as", appli, "tar", "-cf", "-", DOSSIER_APPAREIL],
                       capture_output=True, timeout=600)
    if r.returncode != 0 or not r.stdout:
        message = r.stderr.decode("utf-8", "replace").strip()
        if "No such file" in message or not r.stdout:
            print("Aucune capture sur l'appareil.")
            return []
        raise SystemExit(f"adb a échoué : {message}")
    ecrits = extraire(r.stdout, destination)
    noms = sorted({n.rpartition(".")[0] for n, _ in ecrits})
    # Effacement seulement de ce qui est copié et vérifié : WAV et JSON présents, à la bonne taille.
    verifies = [n for n in noms
                if all((Path(destination) / f"{n}.{e}").exists() for e in ("wav", "json"))
                and all((Path(destination) / f).stat().st_size == t for f, t in ecrits if f.startswith(n))]
    print(f"{len(noms)} captures copiées dans {destination}")
    if effacer and verifies:
        for i in range(0, len(verifies), 40):
            fichiers = [f"{DOSSIER_APPAREIL}/{n}.{e}" for n in verifies[i:i + 40] for e in ("wav", "json")]
            subprocess.run(base + ["shell", "run-as", appli, "rm", "-f"] + fichiers, check=True, timeout=120)
        print(f"{len(verifies)} captures effacées sur l'appareil (le compte affiché par l'appli se met à jour à la"
              f" prochaine capture)")
    return noms


# ---------------------------------------------------------------- nouvelle passe du détecteur

def chemin_modele(capture, explicite=None):
    """Modèle de réveil utilisé par la capture : `--modele`, sinon celui de la configuration, sinon Hey Jarvis."""
    if explicite:
        return str(explicite)
    fichier = ((capture.meta.get("modele") or {}).get("fichier") or "").strip()
    if not fichier or fichier == MODELE_REPLI:
        return "hey_jarvis"
    import maison
    p = maison.DOSSIER / "reveil" / Path(fichier).name
    if not p.exists():
        raise SystemExit(f"modèle {fichier} introuvable dans {p.parent} : le passer par --modele")
    return str(p)


def empreinte(chemin):
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


_modeles = {}


def scores_rejoues(capture, modele=None):
    """Scores recalculés par openWakeWord en Python, un par bloc de 80 ms. Le détecteur repart à neuf : les
    premiers blocs (1,3 s) n'ont pas l'historique qu'avait l'appareil."""
    from openwakeword.model import Model
    chemin = chemin_modele(capture, modele)
    attendu = (capture.meta.get("modele") or {}).get("sha256")
    if attendu and Path(chemin).exists() and empreinte(chemin) != attendu:
        print(f"  {capture.nom} : le modèle {Path(chemin).name} n'est pas celui de la capture (empreinte différente)",
              file=sys.stderr)
    m = _modeles.get(chemin)
    if m is None:
        m = _modeles[chemin] = Model(wakeword_models=[chemin], inference_framework="onnx")
    m.reset()
    pcm = capture.son()
    sortie = []
    for i in range(0, len(pcm) - BLOC + 1, BLOC):
        p = m.predict(pcm[i:i + BLOC])
        sortie.append(float(max(p.values())) if p else 0.0)
    return sortie


def comparer(appareil, rejoue):
    """Écart moyen et maximal entre les scores de l'appareil et ceux de la nouvelle passe, là où les deux existent."""
    paires = [(a, r) for a, r in zip(appareil, rejoue) if a is not None and r is not None]
    if not paires:
        return None, None
    ecarts = [abs(a - r) for a, r in paires]
    return sum(ecarts) / len(ecarts), max(ecarts)


# ---------------------------------------------------------------- règle de confirmation et seuils

def premier_reveil(scores, vad, phases, seuil, blocs_score=BLOCS_SCORE, memoire_voix=MEMOIRE_VOIX, seuil_voix=SEUIL_VOIX):
    """Index du premier bloc où l'appli aurait lancé l'écoute, ou None. Reprise de ConfirmationReveil.kt : il faut
    [blocs_score] blocs de suite au-dessus du seuil, et de la parole vue par Silero dans les [memoire_voix] derniers
    blocs. Sans Silero (vad absent), seule la suite compte. Hors repos (phases E, T, P), le détecteur est remis à
    zéro, comme dans l'appli au retour au repos."""
    jamais = math.inf
    suite, depuis = 0, jamais
    for i, score in enumerate(scores):
        phase = phases[i] if i < len(phases) else "R"
        if phase in "ETP":
            suite, depuis = 0, jamais
            continue
        if score is None:
            continue
        v = vad[i] if i < len(vad) else None
        voix = None if v is None else v >= seuil_voix
        depuis = 0 if voix else (jamais if depuis == jamais else depuis + 1)
        if score < seuil:
            suite = 0
            continue
        suite += 1
        if voix is not None and depuis >= memoire_voix:
            continue
        if suite < blocs_score:
            continue
        return i
    return None


@dataclass
class Bilan:
    seuil: float
    blocs: int
    manques: list = field(default_factory=lambda: [0, 0])
    reveils: list = field(default_factory=lambda: [0, 0])
    faux: list = field(default_factory=lambda: [0, 0])


def balayer(captures, seuils, regles=(1, BLOCS_SCORE), scores_de=None):
    """Pour chaque seuil et chaque nombre de blocs : manqués qui auraient réveillé, réveils gardés, faux évités.
    [scores_de] donne les scores d'une capture (par défaut ceux de l'appareil)."""
    scores_de = scores_de or (lambda c: c.scores)
    cache = {c.nom: scores_de(c) for c in captures}
    sortie = []
    for k in regles:
        for s in seuils:
            b = Bilan(round(s, 3), k)
            for c in captures:
                reveille = premier_reveil(cache[c.nom], c.vad, c.phases, s, blocs_score=k) is not None
                if c.etiquette == "manque":
                    b.manques[1] += 1
                    b.manques[0] += reveille
                elif c.etiquette == "reveil":
                    b.reveils[1] += 1
                    b.reveils[0] += reveille
                elif c.etiquette.startswith("faux"):
                    b.faux[1] += 1
                    b.faux[0] += not reveille
            sortie.append(b)
    return sortie


def plage(de, a, pas):
    n = int(round((a - de) / pas))
    return [round(de + i * pas, 4) for i in range(n + 1)]


# ---------------------------------------------------------------- commandes

def fmt(v, chiffres=2):
    return "-" if v is None else f"{v:.{chiffres}f}".replace(".", ",")


def cmd_lister(a):
    captures = lire_captures(a.dossier, etiquette=a.etiquette)
    print(f"analyser_captures, serveur {version()} : {len(captures)} captures dans {a.dossier}")
    if not captures:
        return
    print(f"{'nom':30} {'étiquette':14} {'issue':19} {'seuil':>5} {'max':>5} {'> seuil':>7}  cause")
    for c in captures:
        print(f"{c.nom:30} {c.etiquette:14} {str(c.meta.get('issue') or '-'):19} {fmt(c.seuil):>5} "
              f"{fmt(c.score_max()):>5} {str(c.blocs_au_dessus() if c.blocs_au_dessus() is not None else '-'):>7}  "
              f"{c.meta.get('cause', '')}")
    compte = {e: sum(1 for c in captures if c.etiquette == e) for e in ETIQUETTES}
    print("  " + ", ".join(f"{e} {n}" for e, n in compte.items()))


def cmd_rejouer(a):
    captures = lire_captures(a.dossier, noms=a.noms, etiquette=a.etiquette)
    print(f"analyser_captures, serveur {version()} : nouvelle passe d'openWakeWord sur {len(captures)} captures")
    lignes = []
    for c in captures:
        r = scores_rejoues(c, a.modele)
        moyen, maxi = comparer(c.scores, r)
        print(f"{c.nom:30} {c.etiquette:14} appareil max {fmt(c.score_max())}, nouvelle passe max {fmt(max(r) if r else None)}, "
              f"écart moyen {fmt(moyen, 3)}, écart max {fmt(maxi, 3)}")
        for i, sr in enumerate(r):
            lignes.append({
                "capture": c.nom, "etiquette": c.etiquette, "bloc": i, "t": round(i * BLOC / TAUX, 2),
                "score_appareil": c.scores[i] if i < len(c.scores) else None, "score_rejoue": round(sr, 4),
                "vad": c.vad[i] if i < len(c.vad) else None, "db": (c.meta.get("db") or [None] * (i + 1))[i]
                if i < len(c.meta.get("db") or []) else None,
                "phase": c.phases[i] if i < len(c.phases) else "", "seuil": c.seuil,
            })
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()) if lignes else ["capture"], delimiter=";")
            w.writeheader()
            w.writerows(lignes)
        print(f"  {len(lignes)} lignes écrites dans {a.csv}")


def cmd_seuils(a):
    captures = lire_captures(a.dossier)
    source = (lambda c: scores_rejoues(c, a.modele)) if a.source == "rejoue" else None
    print(f"analyser_captures, serveur {version()} : {len(captures)} captures, scores {a.source}")
    print("Indicatif : une capture `manque` ne contient pas toujours le mot (l'orbe a pu être touché sans le dire).")
    print(f"{'seuil':>5} {'blocs':>5}  {'manqués rattrapés':>18}  {'réveils gardés':>15}  {'faux évités':>12}")
    for b in balayer(captures, plage(a.de, a.a, a.pas), scores_de=source):
        print(f"{fmt(b.seuil):>5} {b.blocs:>5}  {b.manques[0]:>11} sur {b.manques[1]:<3}  {b.reveils[0]:>8} sur {b.reveils[1]:<3}"
              f"  {b.faux[0]:>5} sur {b.faux[1]:<3}")


def cmd_ecouter(a):
    captures = lire_captures(a.dossier, noms=[a.nom])
    if not captures:
        raise SystemExit(f"capture {a.nom} introuvable dans {a.dossier}")
    c = captures[0]
    print(f"{c.nom} : {c.etiquette}, {c.meta.get('cause', '')}, 30 s jusqu'à l'événement")
    try:
        import sounddevice as sd
        sd.play(c.son(), TAUX)
        sd.wait()
    except ImportError:
        os.startfile(str(c.wav))  # noqa: S606, poste Windows sans sounddevice


def cmd_recuperer(a):
    print(f"analyser_captures, serveur {version()}")
    recuperer(a.serie, a.appli or id_application(), a.dossier, effacer=a.effacer)


def principal(argv=None):
    p = argparse.ArgumentParser(description="Captures du mot de réveil de l'appli Android.")
    p.add_argument("--version", action="version", version=f"analyser_captures, serveur {version()}")
    p.add_argument("--dossier", type=Path, default=dossier_defaut(), help="dossier des captures sur ce poste")
    sous = p.add_subparsers(dest="commande", required=True)

    r = sous.add_parser("recuperer", help="copie les captures de l'appareil (adb, APK de débogage)")
    r.add_argument("--serie", required=True, help="série adb de l'appareil, obligatoire")
    r.add_argument("--appli", help="identifiant de l'appli, sinon celui de maison.json")
    r.add_argument("--effacer", action="store_true", help="efface sur l'appareil ce qui a été copié et vérifié")
    r.set_defaults(f=cmd_recuperer)

    li = sous.add_parser("lister", help="liste les captures")
    li.add_argument("--etiquette", choices=ETIQUETTES)
    li.set_defaults(f=cmd_lister)

    re_ = sous.add_parser("rejouer", help="recalcule les scores avec openWakeWord et les compare")
    re_.add_argument("noms", nargs="*")
    re_.add_argument("--etiquette", choices=ETIQUETTES)
    re_.add_argument("--modele", help="modèle .onnx à utiliser à la place de celui de la capture")
    re_.add_argument("--csv", help="fichier CSV des scores par bloc")
    re_.set_defaults(f=cmd_rejouer)

    s = sous.add_parser("seuils", help="balaye le seuil et la règle de confirmation")
    s.add_argument("--source", choices=("appareil", "rejoue"), default="appareil")
    s.add_argument("--modele")
    s.add_argument("--de", type=float, default=0.2)
    s.add_argument("--a", type=float, default=0.8)
    s.add_argument("--pas", type=float, default=0.05)
    s.set_defaults(f=cmd_seuils)

    e = sous.add_parser("ecouter", help="joue une capture")
    e.add_argument("nom")
    e.set_defaults(f=cmd_ecouter)

    a = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a.f(a)


if __name__ == "__main__":
    principal()
