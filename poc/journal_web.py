"""Journal du client web (S-W2) : qui voit quoi, niveaux de vie privée, lecture par jours, effacement.

Le journal reste celui de assistant.journaliser : un fichier JSONL par jour (journal/assistant-AAAA-MM-JJ.jsonl).
Ce module ne l'écrit pas. Il décide, pour un spectateur donné (un navigateur associé), ce qu'il a le droit d'en
voir, et sous quelle forme. Tout ce qui sort vers un navigateur passe par projeter() : une ligne brute ne part
jamais telle quelle.

Règles (conception du client web, étape 2) :
- une entrée est « à moi » si elle vient de mon appareil ou de ma personne. J'en vois tout le détail, et seul moi
  vois ses étapes ;
- la vie privée de l'auteur borne ce que les autres en voient. Trois niveaux, Discret par défaut :
    tout    : la phrase, ce qui a été fait, la réponse ;
    action  : ce qui a été fait, sans la phrase ni la réponse ;
    discret : rien (un propriétaire voit seulement qu'une demande a eu lieu) ;
- le niveau est figé dans l'entrée au moment de son écriture. Changer de niveau ne change que les demandes à venir ;
- ce qui touche à la santé reste Discret pour les autres, quel que soit le niveau ;
- un invité ne voit que ce qui vient de son appareil. Un rôle inconnu ne voit rien ;
- le journal garde 30 jours, le son n'est jamais conservé.
"""

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

import maison

NIVEAUX = ("tout", "action", "discret")
NIVEAU_DEFAUT = "discret"
CONSERVER_JOURS_DEFAUT = 30
JOURS_PAR_PAGE = 7
ENTREES_MAX = 400

# Un seul verrou pour l'ajout d'une ligne (assistant.journaliser) et pour la réécriture d'un fichier (effacement).
VERROU_FICHIERS = threading.Lock()

# Mots qui rangent une demande dans la santé. Volontairement génériques, aucun identifiant de la maison.
MOTS_SANTE = re.compile(
    r"\b(sant[ée]|m[ée]dicament\w*|m[ée]decin|docteur|ordonnance|tension|glyc[ée]mie|diab[eè]te|poids|pouls|"
    r"rythme cardiaque|sommeil|dormi|r[èe]gles|enceinte|grossesse|douleur\w*|malade|sympt[ôo]me\w*|"
    r"traitement|allergi\w*|th[ée]rapie|psy\w*)\b|sante\.|health", re.I)


class Spectateur(NamedTuple):
    """Qui regarde le journal. role : administrateur, habitant ou invite. identite : celle de la session
    (web:<id>). cle : clé d'auteur, celle qui porte ses niveaux de vie privée et qui désigne ses entrées."""
    role: str
    identite: str
    cle: str


def cle_auteur(personne, appareil):
    """Clé d'auteur d'une demande : la personne si elle est connue, sinon l'appareil, sinon « local » (micro du PC)."""
    p = str(personne or "").strip().lower()
    if p and p != "inconnu":
        return p
    return str(appareil or "").strip().lower() or "local"


def spectateur_de(appareil_web):
    """Spectateur d'un appareil appairé (un dict de appairage_web.AppareilsWeb). Un propriétaire du client web
    est le propriétaire de la maison : ses demandes de partout se retrouvent sous sa clé."""
    identite = "web:" + str(appareil_web["id"])
    role = appareil_web.get("role")
    if role == "administrateur":
        return Spectateur("administrateur", identite, maison.CLE_PROPRIETAIRE)
    return Spectateur(role if role in ("habitant", "invite") else "invite", identite, identite)


def est_a_moi(ligne, spect):
    """Vrai si l'entrée vient de l'appareil ou de la personne du spectateur."""
    appareil = str(ligne.get("appareil") or "").strip().lower()
    if appareil and (appareil == spect.identite or appareil.startswith(spect.identite + "/")):
        return True
    personne = str(ligne.get("personne") or "").strip().lower()
    return bool(personne and personne != "inconnu" and personne == spect.cle)


def nouvel_id():
    return secrets.token_hex(6)


def id_de(ligne):
    """Identifiant d'une entrée. Celles d'avant cette version n'en portent pas : empreinte de l'heure et de la durée,
    jamais du texte."""
    i = ligne.get("id")
    if isinstance(i, str) and re.fullmatch(r"[0-9a-f]{12}", i):
        return i
    brut = f"{ligne.get('horodatage', '')}|{ligne.get('total_s', '')}|{ligne.get('voie', '')}"
    return hashlib.sha1(brut.encode("utf-8")).hexdigest()[:12]


def niveau_de_ligne(ligne):
    n = ligne.get("niveau")
    return n if n in NIVEAUX else NIVEAU_DEFAUT


def est_sante(ligne):
    return bool(MOTS_SANTE.search(" ".join(str(ligne.get(c) or "") for c in ("texte", "actions", "reponse"))))


def statut(ligne):
    """ok, refus, erreur, non compris ou non confirmé."""
    s = ligne.get("statut")
    if isinstance(s, str) and s:
        return s
    v = str(ligne.get("voie") or "")
    if v.startswith("rien compris"):
        return "non compris"
    if " erreur" in v:
        return "erreur"
    if "refus" in v or "(refusé" in str(ligne.get("actions") or ""):
        return "refus"
    if "non confirmé" in v:
        return "non confirmé"
    return "ok"


def motif(ligne):
    """« refusé : sécurité » ou « refusé par HA », tel qu'écrit dans les actions, sinon vide."""
    m = re.search(r"\((refusé[^)]*)\)", str(ligne.get("actions") or ""))
    return m.group(1) if m else ""


def categorie_voie(voie):
    return re.split(r" \(| \[| erreur| refus| non confirmé", str(voie or ""))[0].strip() or "autre"


def _lisibles_defaut(texte):
    return [a.strip() for a in str(texte or "").split(" | ") if a.strip()]


def _nom_defaut(appareil):
    return "Micro du PC" if not appareil else "Appareil de la maison"


def projeter(ligne, spect, lisibles=None, nom_appareil=None):
    """L'entrée telle que ce spectateur a le droit de la voir, ou None s'il ne doit même pas savoir qu'elle existe."""
    lisibles = lisibles or _lisibles_defaut
    nom_appareil = nom_appareil or _nom_defaut
    mien = est_a_moi(ligne, spect)
    niveau = niveau_de_ligne(ligne)
    if mien:
        detail = "complet"
    else:
        if spect.role not in ("administrateur", "habitant"):
            return None
        effectif = "discret" if est_sante(ligne) else niveau
        if effectif == "discret":
            if spect.role != "administrateur":
                return None
            detail = "aucun"
        else:
            detail = "complet" if effectif == "tout" else "action"
    sortie = {"id": id_de(ligne), "horodatage": str(ligne.get("horodatage") or ""), "mien": mien, "detail": detail}
    if detail == "aucun":
        return sortie
    sortie["statut"] = statut(ligne)
    sortie["motif"] = motif(ligne)
    sortie["actions"] = lisibles(ligne.get("actions"))
    if detail == "complet":
        sortie.update({"phrase": str(ligne.get("texte") or ""), "reponse": str(ligne.get("reponse") or ""),
                       "voie": categorie_voie(ligne.get("voie")), "canal": str(ligne.get("canal") or ""),
                       "appareil": nom_appareil(ligne.get("appareil")), "duree_s": str(ligne.get("total_s") or "")})
    if mien:
        etapes = ligne.get("etapes")
        sortie["etapes"] = [{"nom": str(e.get("nom")), "t": str(e.get("t"))} for e in etapes
                            if isinstance(e, dict)] if isinstance(etapes, list) else []
        sortie["niveau"] = niveau
    return sortie


def auteur_visible_en_direct(ligne_en_cours, spect):
    """Les étapes d'une demande en cours ne vont qu'à son auteur : ligne_en_cours = {appareil, personne}."""
    return est_a_moi(ligne_en_cours, spect)


class Niveaux:
    """Niveau de vie privée de chaque auteur, dans un petit fichier JSON écrit de façon atomique."""

    def __init__(self, fichier):
        self.fichier = Path(fichier)
        self._verrou = threading.Lock()

    def _lire(self):
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        niveaux = donnees.get("niveaux") if isinstance(donnees, dict) else None
        if not isinstance(niveaux, dict):
            return {}
        return {str(c): v for c, v in niveaux.items() if isinstance(v, dict) and v.get("niveau") in NIVEAUX}

    def niveau_de(self, cle):
        return self._lire().get(str(cle or "").lower(), {}).get("niveau", NIVEAU_DEFAUT)

    def depuis(self, cle):
        return self._lire().get(str(cle or "").lower(), {}).get("depuis")

    def definir(self, cle, niveau):
        if niveau not in NIVEAUX:
            raise ValueError("niveau inconnu")
        with self._verrou:
            niveaux = self._lire()
            niveaux[str(cle).lower()] = {"niveau": niveau,
                                         "depuis": maison.maintenant().strftime(maison.FORMAT_HORODATAGE)}
            ecrire_atomique(self.fichier, json.dumps({"version": 1, "niveaux": niveaux},
                                                     ensure_ascii=False, indent=1).encode("utf-8"))


def ecrire_atomique(fichier, octets):
    fichier = Path(fichier)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    tmp = fichier.with_name(fichier.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(octets)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, fichier)


def conserver_jours():
    return maison.entier(maison.JOURNAL, "conserver_jours", CONSERVER_JOURS_DEFAUT)


def _fichiers(dossier, reprise=None, retention=None, maintenant=None):
    """Fichiers journaliers dans la rétention, du plus récent au plus ancien, à partir du jour de reprise (inclus)."""
    maintenant = maintenant or maison.maintenant()
    limite = (maintenant - timedelta(days=retention or conserver_jours())).strftime("%Y-%m-%d")
    sortie = []
    for f in Path(dossier).glob("assistant-????-??-??.jsonl"):
        jour = f.stem[len("assistant-"):]
        if jour >= limite and (reprise is None or jour <= reprise):
            sortie.append((jour, f))
    return sorted(sortie, reverse=True)


def _lignes(fichier):
    try:
        brut = fichier.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    sortie = []
    for l in brut:
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if isinstance(e, dict):
            sortie.append(e)
    return sortie


def lire(dossier, spect, lisibles=None, nom_appareil=None, reprise=None, jours=JOURS_PAR_PAGE, retention=None,
         maintenant=None):
    """(entrées, plus) : les entrées visibles par ce spectateur sur les `jours` jours à journal les plus récents
    (à partir du jour de reprise, inclus), la plus récente d'abord. plus est le jour par lequel reprendre pour la
    page suivante, None s'il n'y en a plus."""
    if reprise is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(reprise)):
        reprise = None
    fichiers = _fichiers(dossier, reprise, retention, maintenant)
    sortie = []
    for rang, (jour, f) in enumerate(fichiers[:jours]):
        for ligne in reversed(_lignes(f)):
            p = projeter(ligne, spect, lisibles, nom_appareil)
            if p is not None:
                sortie.append(p)
        if len(sortie) >= ENTREES_MAX and rang + 1 < len(fichiers):  # arrêt entre deux jours, jamais au milieu
            return sortie, fichiers[rang + 1][0]
    plus = fichiers[jours][0] if len(fichiers) > jours else None
    return sortie, plus


def effacer(dossier, spect):
    """Retire du journal toutes les entrées de ce spectateur (réécriture atomique de chaque fichier concerné).
    Renvoie les lignes retirées, pour prévenir les écrans qui les montraient encore. Les entrées des autres, y
    compris celles qui lui ressemblent, ne sont pas touchées."""
    retirees = []
    with VERROU_FICHIERS:
        for f in sorted(Path(dossier).glob("assistant-????-??-??.jsonl")):
            try:
                brut = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            gardees, touche = [], False
            for l in brut:
                try:
                    e = json.loads(l)
                except ValueError:
                    gardees.append(l)
                    continue
                if isinstance(e, dict) and est_a_moi(e, spect):
                    retirees.append(e)
                    touche = True
                else:
                    gardees.append(l)
            if touche:
                if gardees:
                    ecrire_atomique(f, ("\n".join(gardees) + "\n").encode("utf-8"))
                else:
                    f.unlink(missing_ok=True)
    return retirees
