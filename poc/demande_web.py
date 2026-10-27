"""Demandes du client web (lot S-W3) : ce qu'un navigateur associé a le droit d'envoyer, et en quelle quantité.

Ce module ne parle à personne. Il tient trois choses :
- les quotas par appareil et par rôle (fenêtre glissante), faibles pour l'invité, réglables dans maison.json
  (client_web.quotas) ;
- la validation d'un texte et d'un enregistrement (PCM 16 bits, 16 kHz, mono, 20 secondes au plus) ;
- la liste fermée des causes de refus renvoyées au navigateur.

Ce qu'il ne fait jamais : décider de ce qu'une demande a le droit d'obtenir. Le texte (ou la transcription) suit la
chaîne des autres demandes, Moteur.llm_texte, et toute action passe par acces.controler_service puis
securite.verifier. La personne et le rôle viennent de la session, jamais du message.
"""
import base64
import binascii
import time
from collections import defaultdict, deque

import maison

TEXTE_MAX = 400               # caractères d'une demande écrite
TAUX = 16000                  # échantillons par seconde de l'enregistrement
DUREE_MAX_S = 20
PCM_MAX_OCTETS = 2 * TAUX * DUREE_MAX_S   # int16, mono : 640 000 octets
PCM_MIN_OCTETS = 2 * TAUX // 5            # moins de 0,2 s : rien à transcrire
BASE64_MAX = 4 * ((PCM_MAX_OCTETS + 2) // 3)

GENRES = ("demande_texte", "demande_voix")
ROLES = ("administrateur", "habitant", "invite")
FENETRE_DEFAUT_S = 600
# Demandes permises par fenêtre, par appareil. 0 : ce rôle n'a pas le droit de demander par ce moyen.
QUOTAS_DEFAUT = {
    "demande_texte": {"administrateur": 60, "habitant": 30, "invite": 5},
    "demande_voix": {"administrateur": 30, "habitant": 15, "invite": 3},
}
CLES_QUOTAS = {"demande_texte": "texte", "demande_voix": "voix"}

# Causes renvoyées au navigateur (liste fermée, jamais un texte venu d'ailleurs).
CAUSES = frozenset({"droit", "quota", "texte", "audio", "occupe", "indisponible", "transcription"})


class RefusDemande(Exception):
    """Une demande refusée avant d'avoir été traitée. attente_s : combien de secondes avant de pouvoir réessayer."""

    def __init__(self, cause, attente_s=None):
        assert cause in CAUSES, cause
        super().__init__(cause)
        self.cause = cause
        self.attente_s = attente_s


def fenetre_s():
    return maison.entier(_section(), "fenetre_s", FENETRE_DEFAUT_S)


def _section():
    q = maison.CLIENT_WEB.get("quotas")
    return q if isinstance(q, dict) else {}


def quota(genre, role):
    """Nombre de demandes permises par fenêtre pour ce rôle et ce genre. Un rôle inconnu n'a aucun droit."""
    if role not in ROLES or genre not in CLES_QUOTAS:
        return 0
    section = _section().get(CLES_QUOTAS[genre])
    return maison.entier(section, role, QUOTAS_DEFAUT[genre][role], mini=0)


class Quotas:
    """Fenêtre glissante par (appareil, genre). Les horodatages sont gardés en mémoire seulement : un redémarrage
    remet les compteurs à zéro, ce qui suffit pour un garde-fou de débit."""

    def __init__(self, horloge=time.monotonic):
        self.horloge = horloge
        self._vus = defaultdict(deque)

    def compter(self, appareil, role, genre):
        """Compte une demande. Lève RefusDemande("droit") si le rôle n'a pas ce droit, RefusDemande("quota") avec le
        délai avant la prochaine place si la fenêtre est pleine."""
        limite = quota(genre, role)
        if limite <= 0:
            raise RefusDemande("droit")
        duree = fenetre_s()
        maintenant = self.horloge()
        file = self._vus[(str(appareil), genre)]
        while file and maintenant - file[0] >= duree:
            file.popleft()
        if len(file) >= limite:
            raise RefusDemande("quota", max(1, int(duree - (maintenant - file[0])) + 1))
        file.append(maintenant)

    def oublier(self, appareil):
        for cle in [c for c in self._vus if c[0] == str(appareil)]:
            del self._vus[cle]

    def purger(self):
        """Retire les appareils dont plus aucune demande n'est dans la fenêtre."""
        duree = fenetre_s()
        maintenant = self.horloge()
        for cle in list(self._vus):
            file = self._vus[cle]
            while file and maintenant - file[0] >= duree:
                file.popleft()
            if not file:
                del self._vus[cle]


def texte_valide(texte):
    """Le texte d'une demande écrite, espaces de bord retirés. RefusDemande("texte") s'il n'est pas une chaîne, s'il
    est vide, trop long ou s'il contient un caractère de contrôle (hors saut de ligne et tabulation)."""
    if not isinstance(texte, str):
        raise RefusDemande("texte")
    t = texte.strip()
    if not t or len(t) > TEXTE_MAX:
        raise RefusDemande("texte")
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in t):
        raise RefusDemande("texte")
    return " ".join(t.split())


def pcm_valide(brut):
    """Les octets d'un enregistrement envoyé en base64 : PCM 16 bits petit-boutiste, mono, 16 kHz, de 0,2 à 20
    secondes. RefusDemande("audio") pour tout le reste : pas une chaîne, base64 invalide, nombre d'octets impair,
    trop court, trop long. La taille du texte est bornée avant le décodage."""
    if not isinstance(brut, str) or not brut or len(brut) > BASE64_MAX:
        raise RefusDemande("audio")
    try:
        octets = base64.b64decode(brut, validate=True)
    except (binascii.Error, ValueError):
        raise RefusDemande("audio")
    if len(octets) % 2 or not PCM_MIN_OCTETS <= len(octets) <= PCM_MAX_OCTETS:
        raise RefusDemande("audio")
    return octets


def essai_du_message(msg):
    """L'essai demandé par le navigateur : absent ou illisible vaut vrai (le plus prudent). Le moteur y ajoute celui
    du serveur par un OU : un message ne peut jamais rendre réelle une demande que le serveur garde en essai."""
    v = msg.get("essai", True)
    return v if isinstance(v, bool) else True


class Demande:
    """Une demande acceptée, telle que le moteur la reçoit. appareil, personne et role viennent de la session."""

    __slots__ = ("genre", "texte", "pcm", "essai", "appareil", "personne", "role")

    def __init__(self, genre, texte, pcm, essai, appareil, personne, role):
        self.genre, self.texte, self.pcm, self.essai = genre, texte, pcm, essai
        self.appareil, self.personne, self.role = appareil, personne, role
