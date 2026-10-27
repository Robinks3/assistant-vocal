"""Serveur HTTP du client web pour téléphone (lot S-W1a).

Brique : la bibliothèque websockets, qui sert déjà l'administration (administration.py). Les requêtes HTTP sont
traitées dans process_request, avant toute poignée de main. Aucun framework, aucune dépendance de plus, et le
WebSocket du client (S-W2) se branchera plus tard sur le même port.

Ce que ce module garantit :
- Il écoute sur 127.0.0.1:8767 par défaut. Tailscale Serve (lot S-W7) est seul à le joindre depuis le tailnet. Sans
  Serve, personne d'autre que la machine ne l'atteint. Le port 8767 est réglable (--port-web, JARVIS_PORT_WEB, 0
  pour le couper), l'adresse aussi (--adresse-web, JARVIS_ADRESSE_WEB).
- Host exact : la boucle locale sur le port d'écoute, ou le nom de domaine de Serve lu dans client_web.hote de
  maison.json. Origin exacte quand elle est présente (jamais « null »). Un navigateur n'envoie pas Origin sur une
  navigation GET du même site, donc son absence passe pour les fichiers de la coquille. Elle est refusée pour une
  ouverture de WebSocket. Tout refus est un 403 sans détail.
- Cookie de session __Host-session (Secure, HttpOnly, SameSite=Strict, Path=/). Le jeton fait 256 bits, le serveur
  n'en garde que l'empreinte SHA-256, comparée à temps constant. Une session expire (glissante, avec un plafond) et
  se révoque. Un cookie absent, forgé, expiré ou révoqué reçoit le même 401.
- Sans cookie valide, seuls répondent l'accueil public de la coquille (page, feuille de style, script, manifeste,
  icônes, polices) et /appairage, qui dit que l'appairage n'est pas encore disponible (S-W1b le livre).
- Les en-têtes de sécurité de la note de conception (section 4.7) sont posés sur toutes les réponses, refus compris.
- Le journal ne reçoit que l'adresse et une cause courte d'une liste fermée : jamais un cookie, un jeton, un
  en-tête complet ni le chemin demandé.

Derrière Tailscale Serve, toutes les connexions arrivent de 127.0.0.1 : il n'y a donc pas de limite de fréquence par
adresse ici. La barrière contre les essais répétés est celle de l'appairage (S-W1b).
"""
import asyncio
import hmac
import html
import json
import re
import secrets
import time
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

import acces
import maison

DOSSIER = Path(__file__).parent / "web"
ADRESSE_DEFAUT = "127.0.0.1"
PORT_DEFAUT = 8767
NOM_COOKIE = "__Host-session"
VERSION_CLIENT = "0.1.0"
SESSION_JOURS_DEFAUT = 30
SESSION_PLAFOND_JOURS = 90

# Table fermée des fichiers de la coquille : chemin demandé -> (fichier du dossier web/, type, Cache-Control).
# Tout autre chemin n'existe pas. Le dossier n'est jamais parcouru, « .. » ne mène donc nulle part.
_NO_CACHE = "no-cache"
_LONG = "public, max-age=604800"
FICHIERS = {
    "/": ("index.html", "text/html; charset=utf-8", _NO_CACHE),
    "/app.css": ("app.css", "text/css; charset=utf-8", _NO_CACHE),
    "/app.js": ("app.js", "text/javascript; charset=utf-8", _NO_CACHE),
    "/icones/icone-192.png": ("icones/icone-192.png", "image/png", _LONG),
    "/icones/icone-512.png": ("icones/icone-512.png", "image/png", _LONG),
    "/icones/icone-masquable-512.png": ("icones/icone-masquable-512.png", "image/png", _LONG),
    "/icones/apple-touch-icon.png": ("icones/apple-touch-icon.png", "image/png", _LONG),
    "/polices/instrument_sans_400.woff2": ("polices/instrument_sans_400.woff2", "font/woff2", _LONG),
    "/polices/instrument_sans_500.woff2": ("polices/instrument_sans_500.woff2", "font/woff2", _LONG),
    "/polices/big_shoulders_display_300.woff2": ("polices/big_shoulders_display_300.woff2", "font/woff2", _LONG),
}

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
                    "cookie inconnu", "cookie expiré", "cookie révoqué", "chemin protégé sans session"})

_JETON = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def journaliser(texte):
    """Une ligne dans la sortie du serveur. Remplaçable par les tests."""
    print(texte)


def refus_journal(ip, cause):
    assert cause in CAUSES
    journaliser(f"serveur web : refus depuis {str(ip).split('%')[0] or 'adresse inconnue'} ({cause})")


class Sessions:
    """Sessions du client web. Seule l'empreinte SHA-256 du jeton est gardée, jamais le jeton.

    La durée est glissante (chaque usage la prolonge) avec un plafond absolu. Une session révoquée reste connue
    jusqu'à son expiration, pour que son rejeu soit refusé avec sa vraie cause. S-W1b y branchera l'appairage et la
    persistance sur disque."""

    def __init__(self, duree_s=SESSION_JOURS_DEFAUT * 86400, plafond_s=SESSION_PLAFOND_JOURS * 86400, horloge=time.time):
        self.duree_s = int(duree_s)
        self.plafond_s = max(int(plafond_s), self.duree_s)
        self.horloge = horloge
        self._sessions = {}  # empreinte -> {identite, cree, expire, plafond, revoquee}

    def creer(self, identite):
        """Jeton de 256 bits à poser dans le cookie. À ne montrer qu'une fois."""
        jeton = secrets.token_urlsafe(32)
        maintenant = self.horloge()
        self._sessions[acces.empreinte(jeton)] = {
            "identite": identite, "cree": maintenant, "expire": maintenant + self.duree_s,
            "plafond": maintenant + self.plafond_s, "revoquee": False}
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
        return n

    def purger(self):
        """Oublie les sessions arrivées au bout de leur durée. Renvoie le nombre de sessions oubliées."""
        maintenant = self.horloge()
        mortes = [e for e, s in self._sessions.items() if maintenant >= s["expire"] or maintenant >= s["plafond"]]
        for e in mortes:
            del self._sessions[e]
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


def entetes_json(corps):
    return {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(corps))}


class ServiceWeb:
    """Le traitement d'une requête, sans réseau : (statut, en-têtes, corps) ou None pour laisser passer."""

    def __init__(self, port, version, date, sessions=None, hote=None, nom=None):
        self.port = port
        self.version = str(version)
        self.date = date
        self.sessions = sessions if sessions is not None else Sessions(duree_session_s())
        self.hote = hote_serve() if hote is None else hote
        self.nom = nom or maison.NOM_ASSISTANT

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

    def page_accueil(self):
        modele = (DOSSIER / "index.html").read_text(encoding="utf-8")
        valeurs = {"nom_assistant": self.nom, "version_client": VERSION_CLIENT, "version_serveur": self.version,
                   "date": self.date}
        for cle, v in valeurs.items():
            modele = modele.replace("{{" + cle + "}}", html.escape(str(v), quote=True))
        return modele.encode("utf-8")

    def fichier(self, chemin):
        if chemin == "/":
            return self.reponse(HTTPStatus.OK, self.page_accueil(), FICHIERS[chemin][1], FICHIERS[chemin][2])
        nom, genre, cache = FICHIERS[chemin]
        return self.reponse(HTTPStatus.OK, (DOSSIER / nom).read_bytes(), genre, cache)

    def traiter(self, ip, chemin, entetes):
        """(statut, en-têtes, corps) pour une requête HTTP, ou None quand la requête peut devenir un WebSocket."""
        cause = self.controle_entree(entetes)
        if cause:
            refus_journal(ip, cause)
            return self.refus(HTTPStatus.FORBIDDEN)
        chemin = chemin.split("?", 1)[0].split("#", 1)[0]
        if "websocket" in (entetes.get("Upgrade") or "").lower():
            # S-W2 branchera le canal du client ici, derrière un cookie valide.
            jeton, cause = lire_cookie(entetes)
            session, cause = self.sessions.verifier(jeton) if jeton else (None, cause)
            if not session:
                refus_journal(ip, cause)
                return self.refus(HTTPStatus.UNAUTHORIZED)
            return self.reponse(HTTPStatus.NOT_IMPLEMENTED, "Pas encore disponible.\n")
        if chemin in FICHIERS:
            try:
                return self.fichier(chemin)
            except OSError:
                return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")
        if chemin == "/manifest.webmanifest":
            return self.reponse(HTTPStatus.OK, self.manifeste(), "application/manifest+json; charset=utf-8",
                                _NO_CACHE)
        if chemin == "/appairage":
            corps = json.dumps({"etat": "indisponible",
                                "message": "L'appairage n'est pas encore disponible sur cette version."},
                               ensure_ascii=False).encode("utf-8")
            return self.reponse(HTTPStatus.NOT_IMPLEMENTED, corps, "application/json; charset=utf-8")
        # Tout le reste exige une session valide, y compris les chemins qui n'existent pas.
        jeton, cause = lire_cookie(entetes)
        session, cause = self.sessions.verifier(jeton) if jeton else (None, cause)
        if not session:
            refus_journal(ip, cause)
            return self.reponse(HTTPStatus.UNAUTHORIZED, "Connexion requise.\n")
        if chemin == "/api/etat":
            corps = json.dumps({"session": True, "serveur": self.version}).encode("utf-8")
            return self.reponse(HTTPStatus.OK, corps, "application/json; charset=utf-8")
        return self.reponse(HTTPStatus.NOT_FOUND, "Introuvable.\n")


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

    async def accueil(ws):
        await ws.close(code=1008, reason="pas encore disponible")

    serveur = await websockets.serve(accueil, adresse, port, process_request=avant, process_response=apres,
                                     max_size=2 ** 16, ping_interval=20)
    service.port = serveur.sockets[0].getsockname()[1]
    serveur.service_web = service
    return serveur
