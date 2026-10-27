"""Appairage WebAuthn des navigateurs du client web (lot S-W1b).

Ce module est le coeur de l'appairage, sans réseau : il garde les appareils web, l'ouverture d'appairage en cours,
les défis du propriétaire et les tickets. Le serveur (serveur_web.py) le relie aux WebSocket et au cookie.

Parcours, du point de vue du serveur :
1. Le propriétaire (ou la page d'administration de Home Assistant, pour la toute première clé) ouvre un appairage :
   nom, rôle, et un code à 6 chiffres. Seule l'empreinte du code est gardée. Une seule ouverture à la fois.
2. Le nouveau navigateur envoie le code (trois essais, deux minutes). S'il est bon, le serveur renvoie les options
   de création de clé WebAuthn, avec un défi aléatoire à usage unique.
3. Le navigateur crée sa clé (UV exigé, attestation none). Le serveur la vérifie et la garde en attente.
4. Le propriétaire confirme avec sa propre clé d'accès : un défi frais, signé par la clé de son appareil. Depuis
   Home Assistant (administrateur de la maison déjà authentifié), la confirmation n'exige pas de clé.
5. Le serveur enregistre l'appareil et remet au nouveau navigateur un ticket à usage unique (60 s). Le navigateur
   l'échange contre le cookie de session par une requête GET (seule une réponse HTTP peut poser un cookie).

Toute deuxième personne qui présente un code pendant qu'un appairage est en cours (après la saisie du bon code)
détruit l'appairage et alerte le propriétaire : un code vu par un tiers ne sert plus.

Journal : causes courtes d'une liste fermée, jamais un code, un nom d'appareil, un jeton ni un identifiant.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
import unicodedata
from pathlib import Path

import webauthn as WA

ROLES_WEB = ("administrateur", "habitant", "invite")
ROLE_PROPRIETAIRE = "administrateur"
CHIFFRES_CODE = 6
VALIDITE_CODE_S = 120      # le code vaut 2 minutes
VALIDITE_SAISIE_S = 120    # une fois le bon code saisi : 2 minutes de plus pour créer la clé et confirmer
ESSAIS = 3
LIMITE_ECHECS = (10, 600)      # au plus 10 codes refusés par 10 minutes, tous appairages confondus
LIMITE_OUVERTURES = (5, 600)   # au plus 5 ouvertures par 10 minutes
VALIDITE_DEFI_S = 60
VALIDITE_TICKET_S = 60
DEFIS_MAX = 16
LONGUEUR_NOM = 40
MAJ_DERNIER_S = 300            # « dernière connexion » n'est réécrite qu'au plus toutes les 5 minutes
VERSION_FICHIER = 1

_CODE = re.compile(r"^[0-9]{6}$")

CAUSES = frozenset({"role", "nom", "droit", "limite", "etat", "cible", "action", "defi", "preuve", "inconnu"})


class ErreurAppairage(Exception):
    def __init__(self, cause, detail=""):
        assert cause in CAUSES, cause
        super().__init__(f"{cause} {detail}".strip())
        self.cause = cause
        self.detail = detail


def nettoyer_nom(nom):
    """Nom d'appareil : NFKC, espaces simples, 1 à 40 caractères, aucun caractère de contrôle ni invisible."""
    if not isinstance(nom, str):
        raise ErreurAppairage("nom")
    normal = unicodedata.normalize("NFKC", nom)
    if any(unicodedata.category(c).startswith("C") for c in normal):
        raise ErreurAppairage("nom")
    propre = " ".join(normal.split())
    if not 1 <= len(propre) <= LONGUEUR_NOM:
        raise ErreurAppairage("nom")
    return propre


def identite_de(appareil_id):
    return f"web:{appareil_id}"


def _empreinte(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def ecrire_atomique(fichier, octets):
    """Écrit un fichier de données d'un bloc (fichier temporaire puis remplacement), permissions 0600 quand le système
    les connaît. Sert aux appareils web et aux sessions."""
    fichier = Path(fichier)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaire = tempfile.mkstemp(dir=fichier.parent, prefix=fichier.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(octets)
        try:
            os.chmod(temporaire, 0o600)
        except OSError:
            pass
        os.replace(temporaire, fichier)
    except BaseException:
        try:
            os.unlink(temporaire)
        except OSError:
            pass
        raise


class AppareilsWeb:
    """Les appareils web appairés, dans un fichier JSON du dossier de données (comme appareils.json).

    Contient des clés publiques et des compteurs : aucun secret. Écriture atomique (fichier temporaire puis
    remplacement), permissions 0600 quand le système les connaît."""

    def __init__(self, fichier, horloge=time.time):
        self.fichier = Path(fichier)
        self.horloge = horloge
        self._appareils = {}
        self._charger()

    def _charger(self):
        try:
            brut = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(brut, dict) or brut.get("version") != VERSION_FICHIER or not isinstance(brut.get("appareils"), dict):
            return
        for cle, a in brut["appareils"].items():
            cred = a.get("credential") if isinstance(a, dict) else None
            if (isinstance(a, dict) and a.get("id") == cle and a.get("role") in ROLES_WEB and isinstance(a.get("nom"), str)
                    and isinstance(cred, dict) and isinstance(cred.get("id"), str) and isinstance(cred.get("cle"), str)
                    and isinstance(cred.get("compteur"), int)):
                self._appareils[cle] = a

    def _sauver(self):
        ecrire_atomique(self.fichier, json.dumps({"version": VERSION_FICHIER, "appareils": self._appareils},
                                                 ensure_ascii=False, indent=1).encode("utf-8"))

    def tous(self):
        return sorted((dict(a) for a in self._appareils.values()), key=lambda a: (a["cree"], a["id"]))

    def get(self, appareil_id):
        a = self._appareils.get(appareil_id)
        return dict(a) if a else None

    def par_identite(self, identite):
        if isinstance(identite, str) and identite.startswith("web:"):
            return self.get(identite[4:])
        return None

    def par_credential(self, credential_id):
        for a in self._appareils.values():
            if a["credential"]["id"] == credential_id:
                return dict(a)
        return None

    def a_proprietaire(self):
        return any(a["role"] == ROLE_PROPRIETAIRE for a in self._appareils.values())

    def ajouter(self, appareil):
        self._appareils[appareil["id"]] = appareil
        self._sauver()

    def retirer(self, appareil_id):
        if self._appareils.pop(appareil_id, None) is None:
            return False
        self._sauver()
        return True

    def maj(self, appareil_id, **champs):
        a = self._appareils.get(appareil_id)
        if a is None:
            return False
        a.update(champs)
        self._sauver()
        return True


class AppairageWeb:
    """Machine d'états de l'appairage. Tout se passe dans la boucle asyncio du serveur : pas de verrou.

    sur_evenement(cible, message, conn=None) prévient les pages : cible « ouverture » (le nouveau navigateur, par
    son numéro de connexion), « proprietaires » (les propriétaires connectés) ou « ha » (la page d'administration).
    sur_revocation(identite) coupe les sessions et les connexions d'un appareil retiré."""

    def __init__(self, fichier, rp_id, origines, nom="Assistant", invite_jours=7, inactivite_s=30 * 86400,
                 horloge=time.time, sur_evenement=None, sur_revocation=None, journal=None):
        self.appareils = AppareilsWeb(fichier, horloge)
        self._rp_id = rp_id if callable(rp_id) else (lambda: rp_id)
        self._origines = origines if callable(origines) else (lambda: origines)
        self.nom = nom
        self.invite_s = int(invite_jours) * 86400
        self.inactivite_s = int(inactivite_s)
        self.horloge = horloge
        self.sur_evenement = sur_evenement or (lambda cible, message, conn=None: None)
        self.sur_revocation = sur_revocation or (lambda identite: None)
        self.journal = journal or (lambda texte: None)
        self._ouverture = None
        self._defis = {}      # conn -> défi du propriétaire
        self._tickets = {}    # empreinte du ticket -> (appareil, expiration)
        self._echecs = []     # instants des codes refusés
        self._ouvertures = []  # instants des ouvertures

    # Outils internes
    def _rp(self):
        return self._rp_id()

    def _limite(self, liste, regle):
        maintenant = self.horloge()
        liste[:] = [t for t in liste if maintenant - t < regle[1]]
        return len(liste) >= regle[0]

    def _emettre(self, cible, message, conn=None):
        try:
            self.sur_evenement(cible, message, conn)
        except Exception as e:  # une page défaillante ne casse jamais l'appairage
            self.journal(f"appairage : notification impossible ({type(e).__name__})")

    def _vivante(self):
        o = self._ouverture
        if o and self.horloge() >= o["expire"]:
            self._fermer("expiree")
            return None
        return self._ouverture

    def _fermer(self, raison, notifier_conn=True, **en_plus):
        """Détruit l'ouverture en cours et prévient tout le monde. Raisons : expiree, essais, annulee, refusee,
        deconnecte, remplacee, concurrent, creation_refusee. notifier_conn=False quand la réponse directe à la
        connexion du nouveau navigateur porte déjà « interrompu »."""
        o, self._ouverture = self._ouverture, None
        if o is None:
            return
        self.journal(f"appairage : interrompu ({raison})")
        if o["conn"] and notifier_conn:
            self._emettre("ouverture", {"etat": "interrompu"}, o["conn"])
        message = {"evenement": "appairage_ferme", "raison": raison, "nom": o["nom"], "role": o["role"], **en_plus}
        self._emettre("proprietaires", message)
        self._emettre("ha", message)

    # Ouverture par le propriétaire ou par Home Assistant
    def ouvrir(self, nom, role, acteur):
        """Ouvre un appairage. acteur : « ha » ou l'identité web:<id> d'un propriétaire. Renvoie le code, à montrer
        une seule fois à l'acteur."""
        nom = nettoyer_nom(nom)
        if role not in ROLES_WEB:
            raise ErreurAppairage("role")
        if acteur == "ha":
            # Home Assistant amorce la toute première clé et sert de secours : il ne crée un propriétaire que si
            # aucun propriétaire web n'existe (sinon, c'est un propriétaire qui associe les autres).
            if role == ROLE_PROPRIETAIRE and self.appareils.a_proprietaire():
                raise ErreurAppairage("role", "propriétaire existant")
        else:
            a = self.appareils.par_identite(acteur)
            if not a or a["role"] != ROLE_PROPRIETAIRE:
                raise ErreurAppairage("droit")
        if self._limite(self._ouvertures, LIMITE_OUVERTURES):
            raise ErreurAppairage("limite")
        self._ouvertures.append(self.horloge())
        if self._vivante():
            self._fermer("remplacee")
        code = f"{secrets.randbelow(10 ** CHIFFRES_CODE):0{CHIFFRES_CODE}d}"
        maintenant = self.horloge()
        self._ouverture = {
            "id": secrets.token_hex(8), "nom": nom, "role": role, "acteur": acteur, "code": _empreinte(code),
            "cree": maintenant, "expire": maintenant + VALIDITE_CODE_S, "essais": ESSAIS, "etat": "code", "conn": None,
            "challenge": None, "cle": None}
        self.journal(f"appairage : ouvert ({role})")
        return {"code": code, "expire": maintenant + VALIDITE_CODE_S, "duree": VALIDITE_CODE_S, "nom": nom, "role": role,
                "id": self._ouverture["id"]}

    def etat_ouverture(self):
        """Ce que le propriétaire a le droit de savoir de l'ouverture en cours (jamais le code)."""
        o = self._vivante()
        if not o:
            return {"ouverte": False}
        return {"ouverte": True, "etat": o["etat"], "nom": o["nom"], "role": o["role"], "expire": o["expire"],
                "id": o["id"]}

    def annuler(self):
        if self._vivante():
            self._fermer("annulee")
            return True
        return False

    # Le nouveau navigateur
    def tenter_code(self, conn, code):
        """Réponse à un code saisi : {"etat": "creation", "options"} si le code est bon, {"etat": "code_refuse",
        "restant": n}, {"etat": "interrompu"} ou {"etat": "limite"}. Sans ouverture, la réponse imite un premier
        essai raté : le seul indice laissé est l'arrivée du « interrompu » après trois essais."""
        maintenant = self.horloge()
        if self._limite(self._echecs, LIMITE_ECHECS):
            self.journal("appairage : trop d'essais")
            return {"etat": "limite"}
        o = self._vivante()
        if o is None:
            self._echecs.append(maintenant)
            return {"etat": "code_refuse", "restant": ESSAIS - 1}
        if o["etat"] != "code":
            if conn == o["conn"]:
                return {"etat": "erreur"}
            # Un deuxième navigateur pendant la fenêtre : l'appairage est détruit, le propriétaire est alerté.
            self._echecs.append(maintenant)
            self._fermer("concurrent", tentative=maintenant)
            return {"etat": "interrompu"}
        bon = hmac.compare_digest(_empreinte(code if isinstance(code, str) and _CODE.match(code) else "x"), o["code"])
        if not bon:
            self._echecs.append(maintenant)
            o["essais"] -= 1
            if o["essais"] <= 0:
                self._fermer("essais")
                return {"etat": "interrompu"}
            return {"etat": "code_refuse", "restant": o["essais"]}
        o["etat"] = "creation"
        o["conn"] = conn
        o["expire"] = maintenant + VALIDITE_SAISIE_S
        o["challenge"] = os.urandom(32)
        options = WA.options_creation(self._rp(), self.nom, os.urandom(16), o["nom"], o["challenge"],
                                      [a["credential"]["id"] for a in self.appareils.tous()])
        message = {"evenement": "appairage_code_saisi", "nom": o["nom"], "role": o["role"], "expire": o["expire"]}
        self._emettre("proprietaires", message)
        self._emettre("ha", message)
        return {"etat": "creation", "options": options, "expire": o["expire"]}

    def creation(self, conn, reponse):
        """La clé créée par le navigateur. Le défi est à usage unique : il est consommé même si la vérification échoue."""
        o = self._vivante()
        if not o or o["etat"] != "creation" or o["conn"] != conn or o["challenge"] is None:
            return {"etat": "erreur"}
        challenge, o["challenge"] = o["challenge"], None
        try:
            if not isinstance(reponse, dict):
                raise WA.ErreurWebAuthn("format", "réponse")
            res = WA.verifier_creation(WA.deb64u(reponse.get("clientDataJSON"), WA.MAX_CLIENT_DATA),
                                       WA.deb64u(reponse.get("attestationObject"), WA.MAX_ATTESTATION),
                                       challenge, self._origines(), self._rp())
            if reponse.get("id") != res["id"]:
                raise WA.ErreurWebAuthn("identifiant", "différent")
            if self.appareils.par_credential(res["id"]):
                raise WA.ErreurWebAuthn("identifiant", "déjà connu")
        except WA.ErreurWebAuthn as e:
            self.journal(f"appairage : clé refusée ({e.cause})")
            self._fermer("creation_refusee", notifier_conn=False)
            return {"etat": "interrompu"}
        o["cle"] = res
        o["etat"] = "attente"
        message = {"evenement": "appairage_attente", "nom": o["nom"], "role": o["role"], "expire": o["expire"],
                   "id": o["id"], "heure": self.horloge()}
        self._emettre("proprietaires", message)
        self._emettre("ha", message)
        return {"etat": "attente", "expire": o["expire"]}

    def annuler_par_ouvrant(self, conn):
        o = self._ouverture
        if o and o["conn"] == conn and o["etat"] in ("creation", "attente"):
            self._fermer("deconnecte")

    def tick(self, conn):
        """Appelé par le serveur quand une connexion attend : renvoie {"etat": "interrompu"} si l'ouverture a expiré."""
        o = self._ouverture
        if o and o["conn"] == conn and self.horloge() >= o["expire"]:
            self._fermer("expiree", notifier_conn=False)
            return {"etat": "interrompu"}
        return None

    def echeance(self, conn):
        o = self._ouverture
        if o and o["conn"] == conn:
            return max(0.0, o["expire"] - self.horloge())
        return None

    # Défis du propriétaire
    def defi(self, conn, identite, action, cible=None):
        """Options de signature pour une action sensible. Le défi est lié à la connexion, à l'action et à la cible,
        à usage unique, et dure une minute."""
        a = self.appareils.par_identite(identite)
        if not a or a["role"] != ROLE_PROPRIETAIRE:
            raise ErreurAppairage("droit")
        if action == "confirmer":
            o = self._vivante()
            if not o or o["etat"] != "attente":
                raise ErreurAppairage("etat")
            cible = o["id"]
        elif action == "revoquer":
            if not isinstance(cible, str) or cible == a["id"] or self.appareils.get(cible) is None:
                raise ErreurAppairage("cible")
        else:
            raise ErreurAppairage("action")
        maintenant = self.horloge()
        self._defis = {c: d for c, d in self._defis.items() if d["expire"] > maintenant}
        if conn not in self._defis and len(self._defis) >= DEFIS_MAX:
            raise ErreurAppairage("limite")
        challenge = os.urandom(32)
        self._defis[conn] = {"identite": identite, "action": action, "cible": cible, "challenge": challenge,
                             "expire": maintenant + VALIDITE_DEFI_S}
        return WA.options_assertion(self._rp(), challenge, [a["credential"]["id"]])

    def preuve(self, conn, reponse):
        """Vérifie la signature du propriétaire puis exécute l'action du défi. Le défi est consommé dans tous les cas."""
        d = self._defis.pop(conn, None)
        if not d or d["expire"] <= self.horloge():
            raise ErreurAppairage("defi")
        a = self.appareils.par_identite(d["identite"])
        if not a or a["role"] != ROLE_PROPRIETAIRE or not isinstance(reponse, dict):
            raise ErreurAppairage("preuve", "appareil")
        cred = a["credential"]
        try:
            if reponse.get("id") != cred["id"]:
                raise WA.ErreurWebAuthn("identifiant", "inconnu")
            nouveau = WA.verifier_assertion(
                WA.deb64u(reponse.get("clientDataJSON"), WA.MAX_CLIENT_DATA),
                WA.deb64u(reponse.get("authenticatorData"), WA.MAX_AUTH_DATA),
                WA.deb64u(reponse.get("signature"), WA.MAX_SIGNATURE),
                d["challenge"], self._origines(), self._rp(), cred["cle"], cred["compteur"])
        except WA.ErreurWebAuthn as e:
            self.journal(f"appairage : preuve refusée ({e.cause})")
            raise ErreurAppairage("preuve", e.cause) from None
        self.appareils.maj(a["id"], credential={**cred, "compteur": nouveau})
        if d["action"] == "confirmer":
            o = self._vivante()
            if not o or o["id"] != d["cible"] or o["etat"] != "attente":
                raise ErreurAppairage("etat")
            return {"action": "confirmer", "appareil": self.finaliser()}
        self.revoquer(d["cible"])
        return {"action": "revoquer", "cible": d["cible"]}

    # Aboutissement
    def finaliser(self):
        """Enregistre l'appareil en attente et prépare son ticket. Appelé après la preuve du propriétaire, ou
        directement par Home Assistant."""
        o = self._vivante()
        if not o or o["etat"] != "attente" or not o["cle"]:
            raise ErreurAppairage("etat")
        maintenant = self.horloge()
        appareil = {"id": secrets.token_hex(4), "nom": o["nom"], "role": o["role"], "cree": maintenant,
                    "dernier": maintenant, "expire": maintenant + self.invite_s if o["role"] == "invite" else None,
                    "credential": {"id": o["cle"]["id"], "cle": o["cle"]["cle"], "compteur": o["cle"]["compteur"]}}
        while self.appareils.get(appareil["id"]):
            appareil["id"] = secrets.token_hex(4)
        self.appareils.ajouter(appareil)
        ticket = secrets.token_urlsafe(32)
        self._tickets = {e: v for e, v in self._tickets.items() if v[1] > maintenant}
        self._tickets[_empreinte(ticket)] = (appareil["id"], maintenant + VALIDITE_TICKET_S)
        conn, self._ouverture = o["conn"], None
        self.journal(f"appairage : appareil ajouté ({appareil['role']})")
        self._emettre("ouverture", {"etat": "fait", "ticket": ticket}, conn)
        message = {"evenement": "appairage_fait", "nom": appareil["nom"], "role": appareil["role"]}
        self._emettre("proprietaires", message)
        self._emettre("ha", message)
        return self.vue_appareil(appareil)

    def consommer_ticket(self, ticket):
        """Échange un ticket contre l'appareil, une seule fois. None si inconnu, expiré ou déjà utilisé."""
        if not isinstance(ticket, str) or len(ticket) > 100:
            return None
        trouve = self._tickets.pop(_empreinte(ticket), None)
        if not trouve or trouve[1] <= self.horloge():
            return None
        return self.appareils.get(trouve[0])

    # Révocation, oubli, entretien
    def revoquer(self, appareil_id):
        a = self.appareils.get(appareil_id)
        if not a or not self.appareils.retirer(appareil_id):
            raise ErreurAppairage("cible")
        self.journal(f"appairage : appareil révoqué ({a['role']})")
        self.sur_revocation(identite_de(appareil_id))
        return a

    def oublier(self, identite):
        """Un appareil se retire lui-même. Renvoie True s'il était le dernier propriétaire."""
        a = self.appareils.par_identite(identite)
        if not a:
            raise ErreurAppairage("cible")
        dernier = a["role"] == ROLE_PROPRIETAIRE and sum(
            1 for x in self.appareils.tous() if x["role"] == ROLE_PROPRIETAIRE) == 1
        self.revoquer(a["id"])
        return dernier

    def toucher(self, identite):
        a = self.appareils.par_identite(identite)
        if a and self.horloge() - a["dernier"] >= MAJ_DERNIER_S:
            self.appareils.maj(a["id"], dernier=self.horloge())

    def purger(self):
        """Retire les appareils invités arrivés à échéance et ceux restés inactifs trop longtemps."""
        maintenant = self.horloge()
        for a in self.appareils.tous():
            if (a["expire"] is not None and maintenant >= a["expire"]) or maintenant >= a["dernier"] + self.inactivite_s:
                self.appareils.retirer(a["id"])
                self.journal(f"appairage : appareil expiré ({a['role']})")
                self.sur_revocation(identite_de(a["id"]))
        self._defis = {c: d for c, d in self._defis.items() if d["expire"] > maintenant}
        self._tickets = {e: v for e, v in self._tickets.items() if v[1] > maintenant}
        self._vivante()

    def oublier_connexion(self, conn):
        self._defis.pop(conn, None)
        self.annuler_par_ouvrant(conn)

    # Vues
    @staticmethod
    def vue_appareil(a):
        return {"id": a["id"], "nom": a["nom"], "role": a["role"], "cree": a["cree"], "dernier": a["dernier"],
                "expire": a["expire"]}

    def vue(self, identite_courante=None):
        return [{**self.vue_appareil(a), "courant": identite_de(a["id"]) == identite_courante}
                for a in self.appareils.tous()]


def principal(argv=None):
    """python poc/appairage_web.py --reinitialiser : secours quand plus aucun propriétaire n'est joignable."""
    import assistant as A
    parser = argparse.ArgumentParser(description="Appairage des navigateurs du client web.")
    parser.add_argument("--reinitialiser", action="store_true",
                        help="supprime tous les appareils web (il faudra associer de nouveau chaque navigateur)")
    args = parser.parse_args(argv)
    fichier = Path(A.DONNEES) / "appareils_web.json"
    if args.reinitialiser:
        try:
            fichier.unlink()
            print("Appareils web supprimés. Redémarrez le serveur et ouvrez un appairage depuis Home Assistant.")
        except FileNotFoundError:
            print("Aucun appareil web enregistré.")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
