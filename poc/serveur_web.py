"""Serveur HTTP du client web pour téléphone (lots S-W1a et S-W1b).

Brique : la bibliothèque websockets, qui sert déjà l'administration (administration.py). Les requêtes HTTP sont
traitées dans process_request, avant toute poignée de main. Aucun framework, aucune dépendance de plus, et le
WebSocket du client (S-W2) se branche sur le même port.

Ce que ce module garantit :
- Il écoute sur 127.0.0.1:8767 par défaut. Tailscale Serve (lot S-W7) est seul à le joindre depuis le tailnet. Sans
  Serve, personne d'autre que la machine ne l'atteint. Le port 8767 est réglable (--port-web, JARVIS_PORT_WEB, 0
  pour le couper), l'adresse aussi (--adresse-web, JARVIS_ADRESSE_WEB).
- Host exact : la boucle locale sur le port d'écoute, ou le nom de domaine de Serve lu dans client_web.hote de
  maison.json. Origin exacte quand elle est présente (jamais « null »). Un navigateur n'envoie pas Origin sur une
  navigation GET du même site, donc son absence passe pour les fichiers de la coquille. Elle est refusée pour une
  ouverture de WebSocket. Tout refus est un 403 sans détail.
- Cookie de session __Host-session (Secure, HttpOnly, SameSite=Strict, Path=/). Le jeton fait 256 bits, le serveur
  n'en garde que l'empreinte SHA-256, comparée à temps constant. Une session expire (glissante, avec un plafond), se
  révoque et survit à un redémarrage (sessions_web.json ne contient que des empreintes). Un cookie absent, forgé,
  expiré ou révoqué reçoit le même 401.
- Sans cookie valide, seuls répondent l'accueil public de la coquille (page, feuille de style, scripts, manifeste,
  icônes, polices), la page /appairage et ses deux routes : le WebSocket /ws/appairage (le code à 6 chiffres) et
  /appairage/fin (le ticket à usage unique contre le cookie). Le reste exige une session.
- Appairage (S-W1b) : les échanges WebAuthn passent par un WebSocket du même site, car process_request ne voit que
  les en-têtes, jamais un corps POST. Seule une réponse HTTP peut poser un cookie : le ticket de fin d'appairage est
  donc échangé par un GET avec l'en-tête X-Ticket (un site tiers ne peut pas l'ajouter sans préambule CORS, et aucun
  préambule n'est servi). Le coeur de l'appairage est dans appairage_web.py, le module WebAuthn dans webauthn.py.
- Les en-têtes de sécurité de la note de conception (section 4.7) sont posés sur toutes les réponses, refus compris.
- Le journal ne reçoit que l'adresse et une cause courte d'une liste fermée : jamais un cookie, un jeton, un
  en-tête complet ni le chemin demandé.

Derrière Tailscale Serve, toutes les connexions arrivent de 127.0.0.1 : il n'y a donc pas de limite de fréquence par
adresse ici. Les barrières contre les essais répétés sont celles de l'appairage (appairage_web.py), par ouverture, et
une limite de messages par connexion pour les propriétaires connectés.
"""
import asyncio
import hmac
import html
import itertools
import json
import re
import secrets
import time
from collections import deque
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

import acces
import appairage_web as AW
import maison

DOSSIER = Path(__file__).parent / "web"
ADRESSE_DEFAUT = "127.0.0.1"
PORT_DEFAUT = 8767
NOM_COOKIE = "__Host-session"
VERSION_CLIENT = "0.3.0"
SESSION_JOURS_DEFAUT = 30
SESSION_PLAFOND_JOURS = 90
INVITE_JOURS_DEFAUT = 7

# Table fermée des fichiers de la coquille : chemin demandé -> (fichier du dossier web/, type, Cache-Control).
# Tout autre chemin n'existe pas. Le dossier n'est jamais parcouru, « .. » ne mène donc nulle part.
_NO_CACHE = "no-cache"
_LONG = "public, max-age=604800"
_JS = "text/javascript; charset=utf-8"
_HTML = "text/html; charset=utf-8"
FICHIERS = {
    "/": ("index.html", _HTML, _NO_CACHE),
    "/app.css": ("app.css", "text/css; charset=utf-8", _NO_CACHE),
    "/app.js": ("app.js", _JS, _NO_CACHE),
    "/client.js": ("client.js", _JS, _NO_CACHE),
    "/appairage": ("appairage.html", _HTML, _NO_CACHE),
    "/appairage.js": ("appairage.js", _JS, _NO_CACHE),
    "/icones/icone-192.png": ("icones/icone-192.png", "image/png", _LONG),
    "/icones/icone-512.png": ("icones/icone-512.png", "image/png", _LONG),
    "/icones/icone-masquable-512.png": ("icones/icone-masquable-512.png", "image/png", _LONG),
    "/icones/apple-touch-icon.png": ("icones/apple-touch-icon.png", "image/png", _LONG),
    "/polices/instrument_sans_400.woff2": ("polices/instrument_sans_400.woff2", "font/woff2", _LONG),
    "/polices/instrument_sans_500.woff2": ("polices/instrument_sans_500.woff2", "font/woff2", _LONG),
    "/polices/big_shoulders_display_300.woff2": ("polices/big_shoulders_display_300.woff2", "font/woff2", _LONG),
}

# Pages qui exigent une session (sinon 303 vers /appairage) : chemin -> (fichier, scripts liés, propriétaire exigé).
# Leurs scripts sont servis comme les autres, mais seulement avec une session.
PAGES_PROTEGEES = {
    "/associer": ("associer.html", True),
    "/reglages": ("reglages.html", False),
}
SCRIPTS_PROTEGES = {
    "/associer.js": ("associer.js", True),
    "/reglages.js": ("reglages.js", False),
}
MAX_APPAIRAGES_WS = 8        # navigateurs en train de saisir un code, en même temps
INACTIF_APPAIRAGE_S = 130    # un navigateur qui ne dit rien est lâché après un peu plus de 2 minutes
LIMITE_MESSAGES = (30, 10)   # messages d'un propriétaire connecté : 30 par 10 secondes
SAUVEGARDE_SESSIONS_S = 600  # l'expiration glissante n'est réécrite qu'au plus toutes les 10 minutes
ENTRETIEN_S = 60
FERMETURE_REVOQUE = 4001     # code de fermeture d'un WebSocket dont l'appareil vient d'être retiré

# Politique de contenu de la note 4.7, avec frame-ancestors 'none' (aucune page ne s'encadre dans un autre site).
CSP = ("default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
       "object-src 'none'; worker-src 'self'; manifest-src 'self'; media-src 'self' blob:; frame-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; require-trusted-types-for 'script'")

# En-têtes de toutes les réponses. Permissions-Policy est fermée : le lot S-W3 ouvrira microphone=(self).
ENTETES_SECURITE = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
                          "microphone=(), payment=(), usb=()",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}

# Causes de refus consignées au journal : liste fermée, pour ne jamais y écrire une donnée venue du client.
CAUSES = frozenset({"hôte refusé", "origine refusée", "origine absente", "cookie absent", "cookie illisible",
                    "cookie inconnu", "cookie expiré", "cookie révoqué", "chemin protégé sans session",
                    "ticket refusé", "trop de connexions", "appareil inconnu", "confirmation absente",
                    "droit insuffisant", "chemin inconnu"})

_JETON = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")


def journaliser(texte):
    """Une ligne dans la sortie du serveur. Remplaçable par les tests."""
    print(texte)


def refus_journal(ip, cause):
    assert cause in CAUSES
    journaliser(f"serveur web : refus depuis {str(ip).split('%')[0] or 'adresse inconnue'} ({cause})")


class Sessions:
    """Sessions du client web. Seule l'empreinte SHA-256 du jeton est gardée, jamais le jeton.

    La durée est glissante (chaque usage la prolonge) avec un plafond absolu. Une session révoquée reste connue
    jusqu'à son expiration, pour que son rejeu soit refusé avec sa vraie cause. Avec un fichier, les sessions
    survivent à un redémarrage : création, révocation et purge sont écrites tout de suite, la prolongation glissante
    au plus toutes les 10 minutes."""

    def __init__(self, duree_s=SESSION_JOURS_DEFAUT * 86400, plafond_s=SESSION_PLAFOND_JOURS * 86400, horloge=time.time,
                 fichier=None):
        self.duree_s = int(duree_s)
        self.plafond_s = max(int(plafond_s), self.duree_s)
        self.horloge = horloge
        self.fichier = Path(fichier) if fichier else None
        self._sessions = {}  # empreinte -> {identite, cree, expire, plafond, revoquee}
        self._derniere_ecriture = horloge()
        self._charger()

    def _charger(self):
        if not self.fichier:
            return
        try:
            brut = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(brut, dict) or not isinstance(brut.get("sessions"), dict):
            return
        maintenant = self.horloge()
        for empreinte, s in brut["sessions"].items():
            if not (isinstance(empreinte, str) and _EMPREINTE.match(empreinte) and isinstance(s, dict)
                    and isinstance(s.get("identite"), str) and isinstance(s.get("revoquee"), bool)
                    and all(isinstance(s.get(c), (int, float)) and not isinstance(s.get(c), bool)
                            for c in ("cree", "expire", "plafond"))):
                continue
            if maintenant >= s["expire"] or maintenant >= s["plafond"]:
                continue
            self._sessions[empreinte] = {c: s[c] for c in ("identite", "cree", "expire", "plafond", "revoquee")}

    def _sauver(self, force=True):
        if not self.fichier:
            return
        maintenant = self.horloge()
        if not force and maintenant - self._derniere_ecriture < SAUVEGARDE_SESSIONS_S:
            return
        try:
            AW.ecrire_atomique(self.fichier, json.dumps({"version": 1, "sessions": self._sessions},
                                                        ensure_ascii=False).encode("utf-8"))
            self._derniere_ecriture = maintenant
        except OSError:
            journaliser("serveur web : sessions non enregistrées (écriture impossible)")

    def creer(self, identite):
        """Jeton de 256 bits à poser dans le cookie. À ne montrer qu'une fois."""
        jeton = secrets.token_urlsafe(32)
        maintenant = self.horloge()
        self._sessions[acces.empreinte(jeton)] = {
            "identite": identite, "cree": maintenant, "expire": maintenant + self.duree_s,
            "plafond": maintenant + self.plafond_s, "revoquee": False}
        self._sauver()
        return jeton

    def verifier(self, jeton):
        """(session, None) si le jeton est valable, sinon (None, cause). La comparaison des empreintes se fait à temps
        constant, sur toutes les sessions, sans sortie anticipée."""
        presentee = acces.empreinte(jeton)
        trouvee = None
        for connue, session in list(self._sessions.items()):
            if hmac.compare_digest(connue, presentee):
                trouvee = session
        if trouvee is None:
            return None, "cookie inconnu"
        maintenant = self.horloge()
        if trouvee["revoquee"]:
            return None, "cookie révoqué"
        if maintenant >= trouvee["expire"] or maintenant >= trouvee["plafond"]:
            return None, "cookie expiré"
        trouvee["expire"] = min(maintenant + self.duree_s, trouvee["plafond"])
        self._sauver(force=False)
        return trouvee, None

    def revoquer(self, jeton=None, identite=None):
        """Révoque la session de ce jeton, ou toutes celles d'une identité. Renvoie le nombre de sessions touchées."""
        n = 0
        empreinte = acces.empreinte(jeton) if jeton else None
        for connue, session in self._sessions.items():
            if (empreinte and hmac.compare_digest(connue, empreinte)) or (identite and session["identite"] == identite):
                if not session["revoquee"]:
                    session["revoquee"] = True
                    n += 1
        if n:
            self._sauver()
        return n

    def purger(self):
        """Oublie les sessions arrivées au bout de leur durée. Renvoie le nombre de sessions oubliées."""
        maintenant = self.horloge()
        mortes = [e for e, s in self._sessions.items() if maintenant >= s["expire"] or maintenant >= s["plafond"]]
        for e in mortes:
            del self._sessions[e]
        if mortes:
            self._sauver()
        return len(mortes)


def en_tete_cookie(jeton, duree_s=SESSION_JOURS_DEFAUT * 86400):
    """Valeur de Set-Cookie pour une session. __Host- exige Secure, Path=/ et aucun Domain."""
    return f"{NOM_COOKIE}={jeton}; Max-Age={int(duree_s)}; Path=/; Secure; HttpOnly; SameSite=Strict"


def en_tete_cookie_efface():
    return f"{NOM_COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict"


def lire_cookie(entetes):
    """(jeton, None) ou (None, cause). Le jeton doit avoir la forme d'un jeton émis par ce serveur."""
    for brut in entetes.get_all("Cookie") if hasattr(entetes, "get_all") else [entetes.get("Cookie")]:
        for morceau in (brut or "").split(";"):
            nom, _, valeur = morceau.strip().partition("=")
            if nom == NOM_COOKIE:
                valeur = valeur.strip()
                return (valeur, None) if _JETON.match(valeur) else (None, "cookie illisible")
    return None, "cookie absent"


def hote_serve():
    """Nom de domaine de Tailscale Serve (client_web.hote), en minuscules, ou "" s'il n'est pas réglé ou illisible."""
    v = maison.CLIENT_WEB.get("hote")
    if not isinstance(v, str):
        return ""
    v = v.strip().lower().rstrip(".")
    return v if re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", v) else ""


def duree_session_s():
    return maison.entier(maison.CLIENT_WEB, "session_jours", SESSION_JOURS_DEFAUT) * 86400


def invite_jours():
    return maison.entier(maison.CLIENT_WEB, "invite_jours", INVITE_JOURS_DEFAUT)


def entetes_json(corps):
    return {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(corps))}


class Connexion:
    """Un WebSocket ouvert. Tous les envois passent par une chaîne de tâches : l'ordre est gardé même quand l'envoi
    est déclenché depuis du code synchrone (les événements de l'appairage)."""

    def __init__(self, ident, ws, genre, identite=None):
        self.id = ident
        self.ws = ws
        self.genre = genre          # « appairage » ou « client »
        self.identite = identite
        self._dernier = None

    def envoyer(self, message, fermer=None):
        """Met le message en file. fermer : None, True (fermeture normale) ou un code de fermeture."""
        precedent = self._dernier
        self._dernier = asyncio.ensure_future(self._envoyer(precedent, message, fermer))

    async def _envoyer(self, precedent, message, fermer):
        if precedent is not None:
            await asyncio.gather(precedent, return_exceptions=True)
        try:
            if message is not None:
                await self.ws.send(json.dumps(message, separators=(",", ":"), ensure_ascii=False))
            if fermer:
                await self.ws.close(1000 if fermer is True else fermer)
        except websockets.ConnectionClosed:
            pass

    async def vider(self):
        if self._dernier is not None:
            await asyncio.gather(self._dernier, return_exceptions=True)


class ServiceWeb:
    """Le traitement d'une requête, sans réseau : (statut, en-têtes, corps) ou None pour laisser passer."""

    def __init__(self, port, version, date, sessions=None, hote=None, nom=None):
        self.port = port
        self.version = str(version)
        self.date = date
        self.sessions = sessions if sessions is not None else Sessions(duree_session_s())
        self.hote = hote_serve() if hote is None else hote
        self.nom = nom or maison.NOM_ASSISTANT
        self.appairage = None
        self.connexions = {}
        self.sur_ha = lambda message: None
        self._ids = itertools.count(1)
        self._dernier_entretien = time.monotonic()

    # Appairage
    @property
    def rp_id(self):
        return self.hote or "localhost"

    def brancher_appairage(self, fichier, invite_jours=INVITE_JOURS_DEFAUT, horloge=time.time):
        """Crée l'appairage des navigateurs. Le journal est lié tard : les tests peuvent remplacer journaliser."""
        self.appairage = AW.AppairageWeb(
            fichier, lambda: self.rp_id, self.origines_permises, nom=self.nom, invite_jours=invite_jours,
            inactivite_s=self.sessions.duree_s, horloge=horloge, sur_evenement=self.evenement,
            sur_revocation=self.retirer_acces, journal=lambda t: journaliser(t))
        return self.appairage

    def evenement(self, cible, message, conn=None):
        """Aiguille un événement de l'appairage : le nouveau navigateur, les propriétaires connectés ou Home Assistant."""
        if cible == "ouverture":
            c = self.connexions.get(conn)
            if c:
                c.envoyer(message, fermer=message.get("etat") in ("interrompu", "fait") or None)
        elif cible == "proprietaires":
            for c in list(self.connexions.values()):
                if c.genre == "client" and self._est_proprietaire(c.identite):
                    c.envoyer({"type": "evenement", **message})
        elif cible == "ha":
            self.sur_ha(message)

    def retirer_acces(self, identite):
        """Un appareil est retiré : ses sessions sont révoquées, ses connexions coupées, les listes se rafraîchissent."""
        self.sessions.revoquer(identite=identite)
        for c in list(self.connexions.values()):
            if c.identite == identite:
                c.envoyer(None, fermer=FERMETURE_REVOQUE)
        message = {"evenement": "appareils_change"}
        self.evenement("proprietaires", message)
        self.evenement("ha", message)

    def _appareil(self, identite):
        return self.appairage.appareils.par_identite(identite) if self.appairage else None

    def _est_proprietaire(self, identite):
        a = self._appareil(identite)
        return bool(a and a["role"] == AW.ROLE_PROPRIETAIRE)

    def _entretien(self):
        maintenant = time.monotonic()
        if maintenant - self._dernier_entretien < ENTRETIEN_S:
            return
        self._dernier_entretien = maintenant
        if self.appairage:
            self.appairage.purger()
        self.sessions.purger()

    # Barrières d'entrée
    def hotes_permis(self):
        locaux = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}
        return locaux | ({self.hote} if self.hote else set())

    def origines_permises(self):
        locales = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}", f"http://[::1]:{self.port}"}
        return locales | ({f"https://{self.hote}"} if self.hote else set())

    def controle_entree(self, entetes):
        """None si Host et Origin conviennent, sinon la cause du refus."""
        if (entetes.get("Host") or "").strip().lower() not in self.hotes_permis():
            return "hôte refusé"
        origine = entetes.get("Origin")
        ouverture_ws = "websocket" in (entetes.get("Upgrade") or "").lower()
        if origine is None:
            return "origine absente" if ouverture_ws else None
        if origine.strip().lower() not in self.origines_permises():
            return "origine refusée"
        return None

    def session_de(self, entetes):
        """(session, None) pour un cookie valide d'un appareil connu, sinon (None, cause). Quand l'appairage est
        branché, une session dont l'appareil a été retiré est refusée même si son cookie vit encore."""
        jeton, cause = lire_cookie(entetes)
        if not jeton:
            return None, cause
        session, cause = self.sessions.verifier(jeton)
        if not session:
            return None, cause
        if self.appairage:
            if self._appareil(session["identite"]) is None:
                return None, "appareil inconnu"
            self.appairage.toucher(session["identite"])
        return session, None

    # Réponses
    @staticmethod
    def reponse(statut, corps, genre="text/plain; charset=utf-8", cache=None, en_plus=None):
        donnees = corps if isinstance(corps, bytes) else corps.encode("utf-8")
        entetes = dict(ENTETES_SECURITE)
        if cache:
            entetes["Cache-Control"] = cache
        entetes["Content-Type"] = genre
        entetes["Content-Length"] = str(len(donnees))
        entetes.update(en_plus or {})
        return statut, entetes, donnees

    def refus(self, statut):
        return self.reponse(statut, "Accès refusé.\n")

    def json(self, statut, valeur, en_plus=None):
        return self.reponse(statut, json.dumps(valeur, ensure_ascii=False), "application/json; charset=utf-8",
                            en_plus=en_plus)

    def manifeste(self):
        icones = [
            {"src": "/icones/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icones/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icones/icone-masquable-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ]
        corps = {"name": self.nom, "short_name": self.nom[:12], "description": f"Le client web de {self.nom}.",
                 "lang": "fr", "dir": "ltr", "start_url": "/", "scope": "/", "id": "/", "display": "standalone",
                 "orientation": "portrait", "background_color": "#F3EFE7", "theme_color": "#E8E2D6",
                 "icons": icones}
        return json.dumps(corps, ensure_ascii=False).encode("utf-8")

    def page(self, nom_fichier):
        """Une page HTML dont les modèles {{...}} sont remplis (valeurs échappées)."""
        modele = (DOSSIER / nom_fichier).read_text(encoding="utf-8")
        valeurs = {"nom_assistant": self.nom, "version_client": VERSION_CLIENT, "version_serveur": self.version,
                   "date": self.date}
        for cle, v in valeurs.items():
            modele = modele.replace("{{" + cle + "}}", html.escape(str(v), quote=True))
        return modele.encode("utf-8")

    def fichier(self, chemin):
        nom, genre, cache = FICHIERS[chemin]
        corps = self.page(nom) if genre == _HTML else (DOSSIER / nom).read_bytes()
        return self.reponse(HTTPStatus.OK, corps, genre, cache)

    def _fichier_protege(self, nom, genre, cache=_NO_CACHE):
        try:
            corps = self.page(nom) if genre == _HTML else (DOSSIER / nom).read_bytes()
        except OSError:
            return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")
        return self.reponse(HTTPStatus.OK, corps, genre, cache)

    # Parcours HTTP
    def _ouverture_websocket(self, ip, chemin, entetes):
        if chemin == "/ws/appairage" and self.appairage:
            if sum(1 for c in self.connexions.values() if c.genre == "appairage") >= MAX_APPAIRAGES_WS:
                refus_journal(ip, "trop de connexions")
                return self.refus(HTTPStatus.SERVICE_UNAVAILABLE)
            return None
        if chemin == "/ws" and self.appairage:
            session, cause = self.session_de(entetes)
            if not session:
                refus_journal(ip, cause)
                return self.refus(HTTPStatus.UNAUTHORIZED)
            return None
        # Un chemin inconnu n'apprend rien : même refus qu'une session absente quand il n'y en a pas.
        session, cause = self.session_de(entetes)
        if not session:
            refus_journal(ip, cause)
            return self.refus(HTTPStatus.UNAUTHORIZED)
        refus_journal(ip, "chemin inconnu")
        return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")

    def _fin_appairage(self, ip, entetes):
        """Échange le ticket de fin d'appairage contre le cookie de session. Aucun détail sur la cause du refus."""
        appareil = self.appairage.consommer_ticket(entetes.get("X-Ticket")) if self.appairage else None
        if not appareil:
            refus_journal(ip, "ticket refusé")
            return self.reponse(HTTPStatus.UNAUTHORIZED, "Ticket refusé.\n")
        jeton = self.sessions.creer(AW.identite_de(appareil["id"]))
        return self.json(HTTPStatus.OK, {"ok": True, "role": appareil["role"], "nom": appareil["nom"]},
                         {"Set-Cookie": en_tete_cookie(jeton, self.sessions.duree_s)})

    def _oublier(self, ip, session, entetes):
        if (entetes.get("X-Confirme") or "") != "oui":
            refus_journal(ip, "confirmation absente")
            return self.reponse(HTTPStatus.BAD_REQUEST, "Confirmation absente.\n")
        try:
            dernier = self.appairage.oublier(session["identite"])
        except AW.ErreurAppairage:
            refus_journal(ip, "appareil inconnu")
            return self.reponse(HTTPStatus.UNAUTHORIZED, "Connexion requise.\n")
        return self.json(HTTPStatus.OK, {"ok": True, "dernier": bool(dernier)}, {
            "Set-Cookie": en_tete_cookie_efface(), "Clear-Site-Data": '"cache", "cookies", "storage"'})

    def traiter(self, ip, chemin, entetes):
        """(statut, en-têtes, corps) pour une requête HTTP, ou None quand la requête peut devenir un WebSocket."""
        cause = self.controle_entree(entetes)
        if cause:
            refus_journal(ip, cause)
            return self.refus(HTTPStatus.FORBIDDEN)
        self._entretien()
        chemin = chemin.split("?", 1)[0].split("#", 1)[0]
        if "websocket" in (entetes.get("Upgrade") or "").lower():
            return self._ouverture_websocket(ip, chemin, entetes)
        if chemin in FICHIERS:
            try:
                return self.fichier(chemin)
            except OSError:
                return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")
        if chemin == "/manifest.webmanifest":
            return self.reponse(HTTPStatus.OK, self.manifeste(), "application/manifest+json; charset=utf-8",
                                _NO_CACHE)
        if chemin == "/appairage/fin":
            return self._fin_appairage(ip, entetes)
        # Tout le reste exige une session valide, y compris les chemins qui n'existent pas.
        session, cause = self.session_de(entetes)
        if chemin in PAGES_PROTEGEES:
            nom, proprietaire = PAGES_PROTEGEES[chemin]
            if not session:
                refus_journal(ip, "chemin protégé sans session")
                return self.reponse(HTTPStatus.SEE_OTHER, "", en_plus={"Location": "/appairage"})
            if proprietaire and not self._est_proprietaire(session["identite"]):
                refus_journal(ip, "droit insuffisant")
                return self.reponse(HTTPStatus.SEE_OTHER, "", en_plus={"Location": "/reglages"})
            return self._fichier_protege(nom, _HTML)
        if not session:
            refus_journal(ip, cause)
            return self.reponse(HTTPStatus.UNAUTHORIZED, "Connexion requise.\n")
        if chemin in SCRIPTS_PROTEGES:
            nom, proprietaire = SCRIPTS_PROTEGES[chemin]
            if proprietaire and not self._est_proprietaire(session["identite"]):
                refus_journal(ip, "droit insuffisant")
                return self.reponse(HTTPStatus.FORBIDDEN, "Accès refusé.\n")
            return self._fichier_protege(nom, _JS)
        if chemin == "/api/etat":
            return self.json(HTTPStatus.OK, {"session": True, "serveur": self.version})
        if chemin == "/oublier" and self.appairage:
            return self._oublier(ip, session, entetes)
        return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")

    # Boucles WebSocket
    @staticmethod
    def _lire(brut):
        """Un message du client : un objet JSON, sinon None. Les messages binaires sont refusés."""
        if not isinstance(brut, str):
            return None
        try:
            msg = json.loads(brut)
        except ValueError:
            return None
        return msg if isinstance(msg, dict) else None

    async def boucle_appairage(self, ws):
        """Le nouveau navigateur : saisie du code, création de la clé, attente de la confirmation du propriétaire."""
        conn = Connexion(next(self._ids), ws, "appairage")
        self.connexions[conn.id] = conn
        try:
            while True:
                delai = self.appairage.echeance(conn.id)
                try:
                    brut = await asyncio.wait_for(ws.recv(), INACTIF_APPAIRAGE_S if delai is None else delai + 0.05)
                except asyncio.TimeoutError:
                    rep = self.appairage.tick(conn.id) if delai is not None else None
                    conn.envoyer(rep, fermer=True)
                    break
                except websockets.ConnectionClosed:
                    break
                msg = self._lire(brut)
                genre = msg.get("type") if msg else None
                if genre == "code":
                    rep = self.appairage.tenter_code(conn.id, msg.get("code"))
                elif genre == "creation":
                    rep = self.appairage.creation(conn.id, msg)
                else:  # « annuler », type inconnu ou message illisible : la connexion se ferme
                    break
                final = rep.get("etat") in ("interrompu", "limite")
                conn.envoyer(rep, fermer=final or None)
                if final:
                    break
        finally:
            self.appairage.oublier_connexion(conn.id)
            self.connexions.pop(conn.id, None)
            if ws.state.name != "CLOSED":
                conn.envoyer(None, fermer=True)
            await conn.vider()

    async def boucle_client(self, ws, identite):
        """Un navigateur associé : liste des appareils, association, révocation, oubli."""
        conn = Connexion(next(self._ids), ws, "client", identite)
        self.connexions[conn.id] = conn
        recents = deque()
        try:
            while True:
                try:
                    brut = await ws.recv()
                except websockets.ConnectionClosed:
                    break
                maintenant = time.monotonic()
                while recents and maintenant - recents[0] > LIMITE_MESSAGES[1]:
                    recents.popleft()
                recents.append(maintenant)
                if len(recents) > LIMITE_MESSAGES[0]:
                    conn.envoyer(None, fermer=1008)
                    break
                self._entretien()
                msg = self._lire(brut)
                if msg is None:
                    conn.envoyer(None, fermer=1008)
                    break
                try:
                    rep = self._client(conn, msg)
                except AW.ErreurAppairage as e:
                    rep = {"type": "erreur", "cause": e.cause}
                if rep is not None:
                    conn.envoyer(rep)
        finally:
            if self.appairage:
                self.appairage.oublier_connexion(conn.id)
            self.connexions.pop(conn.id, None)
            await conn.vider()

    def _client(self, conn, msg):
        """Réponse à un message d'un navigateur associé. Un rôle autre que propriétaire ne peut que se décrire."""
        a = self._appareil(conn.identite)
        if a is None:
            raise AW.ErreurAppairage("droit")
        proprietaire = a["role"] == AW.ROLE_PROPRIETAIRE
        genre = msg.get("type")
        if genre == "moi":
            dernier = proprietaire and sum(1 for x in self.appairage.appareils.tous()
                                           if x["role"] == AW.ROLE_PROPRIETAIRE) == 1
            return {"type": "moi", "appareil": self.appairage.vue_appareil(a), "proprietaire": proprietaire,
                    "dernier_proprietaire": dernier, "nom": self.nom,
                    "serveur": {"version": self.version, "date": self.date, "client": VERSION_CLIENT}}
        if not proprietaire:
            raise AW.ErreurAppairage("droit")
        if genre == "appareils":
            return {"type": "appareils", "appareils": self.liste_appareils(conn.identite),
                    "ouverture": self.appairage.etat_ouverture()}
        if genre == "ouvrir":
            o = self.appairage.ouvrir(msg.get("nom"), msg.get("role"), conn.identite)
            return {"type": "ouverture", **o, "qr": self.qr_appairage(o["code"])}
        if genre == "annuler":
            self.appairage.annuler()
            return {"type": "annule"}
        if genre == "defi":
            options = self.appairage.defi(conn.id, conn.identite, msg.get("action"), msg.get("cible"))
            return {"type": "defi", "options": options}
        if genre == "preuve":
            res = self.appairage.preuve(conn.id, msg.get("reponse"))
            if res["action"] == "confirmer":
                return {"type": "confirme", "appareil": res["appareil"]}
            return {"type": "revoque", "cible": res["cible"]}
        raise AW.ErreurAppairage("action")

    def liste_appareils(self, identite_courante=None):
        """Les appareils associés (sans clé), avec « en_ligne » pour ceux dont un navigateur est connecté."""
        en_ligne = {c.identite for c in self.connexions.values() if c.genre == "client"}
        return [{**v, "en_ligne": AW.identite_de(v["id"]) in en_ligne} for v in self.appairage.vue(identite_courante)]

    def qr_appairage(self, code):
        """QR code (data URI SVG) de l'adresse d'appairage, le code dans le fragment qui ne part jamais au serveur."""
        if not self.hote:
            return None
        import administration
        return administration._qr(f"https://{self.hote}/appairage#code={code}")

    async def traiter_websocket(self, ws):
        """Aiguille un WebSocket accepté : l'appairage d'un nouveau navigateur, ou le client d'un navigateur associé."""
        chemin = ws.request.path.split("?", 1)[0]
        if chemin == "/ws/appairage" and self.appairage:
            await self.boucle_appairage(ws)
            return
        if chemin == "/ws" and self.appairage:
            session, _ = self.session_de(ws.request.headers)
            if session:
                await self.boucle_client(ws, session["identite"])
                return
        await ws.close(code=1008, reason="refusé")


async def demarrer(adresse, port, version, sessions=None, service=None):
    """Démarre le serveur HTTP du client web sur adresse:port (port 0 : un port libre, pour les tests). Renvoie le
    serveur websockets, comme administration.demarrer."""
    service = service or ServiceWeb(port, version, maison.maintenant().strftime("%d/%m/%Y"), sessions)

    def avant(connexion, requete):
        ip = connexion.remote_address[0] if connexion.remote_address else ""
        rep = service.traiter(ip, requete.path, requete.headers)
        if rep is None:
            return None
        statut, entetes, corps = rep
        return Response(statut.value, statut.phrase, Headers(entetes), corps)

    def apres(connexion, requete, reponse):
        for cle, valeur in ENTETES_SECURITE.items():
            if cle not in reponse.headers:
                reponse.headers[cle] = valeur
        return reponse

    serveur = await websockets.serve(service.traiter_websocket, adresse, port, process_request=avant,
                                     process_response=apres, max_size=2 ** 16, ping_interval=20)
    service.port = serveur.sockets[0].getsockname()[1]
    serveur.service_web = service
    return serveur
