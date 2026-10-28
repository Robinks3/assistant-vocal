"""Administration de l'assistant dans Home Assistant (v0.34.0) : page servie par Ingress, réservée aux
administrateurs de HA de la liste blanche administration.utilisateurs_ha.

- Service HTTP et WebSocket dédié, actif seulement si JARVIS_ADMIN_PORT est posée (appli HA). Pas de framework :
  une table de chemins fermée vers poc/admin/ et un WebSocket (/ws) qui parle comme un satellite administrateur.
- Barrières : adresse source du superviseur, X-Remote-User-Id dans la liste blanche (acces.controle_ingress),
  en-tête Origin de la WebSocket égal à l'hôte (acces.origine_acceptee). Aucun jeton dans l'adresse, aucun stockage.
- Le canal de la page n'accepte que TYPES_PAGE. Le traitement des appareils (gerer_appareils) est commun avec
  les satellites administrateurs : un seul point de contrôle.
https://contributors.home-assistant.io/apps/guides/ingress/
"""
import asyncio, json
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

import acces
import maison

DOSSIER_PAGE = Path(__file__).parent / "admin"

# Table fermée : tout autre chemin (dont « .. ») répond 404.
FICHIERS = {"/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
            "/admin.css": ("admin.css", "text/css; charset=utf-8")}

ENTETES_SECURITE = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# Seuls messages acceptés de la page.
TYPES_PAGE = frozenset({"appareils", "appairer", "refuser_appareil", "revoquer", "changer_role", "changer_personne",
                        "inviter", "annuler_invitation"})
# Messages de gestion des appareils, communs à la page et aux satellites administrateurs.
TYPES_APPAREILS = TYPES_PAGE
# Invitation : le code n'est montré que dans la page.
TYPES_PAGE_SEULE = frozenset({"inviter", "annuler_invitation"})
# Client web (S-W1b) : la page d'administration amorce la première clé du propriétaire et sert de secours. Ces
# messages ne passent jamais par un satellite, ni par le client web lui-même.
TYPES_WEB = frozenset({"web_etat", "web_ouvrir", "web_confirmer", "web_annuler", "web_revoquer"})
CAUSES_WEB = {"role": "rôle non permis (un propriétaire web existe déjà, ou rôle inconnu)", "nom": "nom invalide",
              "droit": "droit insuffisant", "limite": "trop d'ouvertures, réessayer dans quelques minutes",
              "etat": "aucun navigateur n'attend de confirmation", "cible": "appareil inconnu"}


class Page:
    """Une page d'administration connectée. Identité « ha:<id> », administrateur le temps de la connexion."""

    def __init__(self, ws, ident, nom):
        self.ws, self.identite, self.nom = ws, f"ha:{ident}", nom
        self.personne = nom

    async def envoyer(self, **message):
        await self.ws.send(json.dumps(message, ensure_ascii=False))


def _qr(url):
    """QR code en image SVG (data URI) générée ici, sans service externe. None si segno manque."""
    try:
        import segno
        return segno.make(url, error="m").svg_data_uri(scale=6, border=2, dark="#000000", light="#ffffff")
    except Exception as e:
        print(f"administration : QR code impossible ({type(e).__name__})")
        return None


def message_invitation(code, role, restant):
    """Réponse à « inviter » : code en grand, à saisir dans l'appli Android. Pas de QR code : ce code n'est vérifié
    que par l'appairage des appareils, le client web ne le connaît pas (son QR vient de « web_ouvrir »)."""
    return {"etat": "invitation", "code": code, "role": role, "expire": restant}


async def gerer_appareils(moteur, msg, acteur, courant=None, page=False):
    """Traite un message de gestion des appareils. Renvoie les messages à répondre à l'appelant.

    acteur : nom pour le journal. courant : canal de l'appelant (jamais coupé par une révocation, pas notifié).
    page : vrai pour la page d'administration, seule à voir un code d'invitation."""
    app = moteur.appareils
    genre = msg.get("type")
    ident = str(msg.get("id", ""))
    if ident.startswith("appareil:"):
        ident = ident[len("appareil:"):]
    reponses, change = [], True
    if (courant is not None and not page and genre in TYPES_APPAREILS
            and not acces.est_administrateur(getattr(courant, "identite", None), app)):
        # Seconde barrière : serveur_satellite.recevoir_texte refuse déjà ces messages hors administrateur.
        print(f"[{acteur}] message « {genre} » refusé : réservé à un administrateur")
        return [{"etat": "refuse", "type": genre, "message": "réservé à un administrateur"}]
    if genre == "appairer":
        role = msg.get("role") or acces.ROLE_PAR_DEFAUT
        personne = msg.get("personne") or None
        if role not in acces.ROLES_ATTRIBUABLES:  # « administrateur » ne s'attribue pas, rien ne retombe sur « habitant »
            reponses.append({"etat": "refuse", "type": genre, "message": "rôle non attribuable"})
            change = False
        elif personne and not acces.cle_habitant(personne):
            reponses.append({"etat": "refuse", "type": genre, "message": "personne inconnue (pas un habitant)"})
            change = False
        else:
            nom = app.accepter(ident, role, personne)
            print(f"[{acteur}] appairage accepté : {nom}" if nom else f"[{acteur}] appairage introuvable : {ident}")
    elif genre == "refuser_appareil":
        app.refuser(ident)
    elif genre == "revoquer":
        nom = next((a["nom"] for a in app.liste if a["id"] == ident), None)
        print(f"[{acteur}] appareil révoqué : {ident} ({app.revoquer(ident)})")
        for sat in list(moteur.satellites):  # coupé tout de suite, par identité et non par nom
            if getattr(sat, "identite", None) == f"appareil:{ident}" and sat is not courant:
                asyncio.create_task(sat.ws.close(code=4001, reason="appareil révoqué"))
    elif genre == "changer_role":
        r = app.changer_role(ident, msg.get("role"))
        if r:
            print(f"[{acteur}] rôle de « {r[0]} » (appareil:{ident}) changé de {r[1]} à {r[2]}")
        else:
            reponses.append({"etat": "refuse", "type": genre, "message": "appareil ou rôle inconnu"})
    elif genre == "changer_personne":
        personne = msg.get("personne") or None
        r = app.changer_personne(ident, personne)
        if r:
            print(f"[{acteur}] personne de « {r[0]} » (appareil:{ident}) changée de {r[1] or 'aucune'} "
                  f"à {r[2] or 'aucune'}")
        else:
            reponses.append({"etat": "refuse", "type": genre, "message": "appareil ou personne inconnue"})
    elif genre == "inviter" and page:
        try:
            code = app.invitation.ouvrir(msg.get("role") or acces.ROLE_PAR_DEFAUT)
        except ValueError:
            reponses.append({"etat": "refuse", "type": genre, "message": "rôle non attribuable"})
        else:
            print(f"[{acteur}] invitation ouverte pour le rôle {app.invitation.role} "
                  f"({acces.Invitation.DUREE} s, une seule fois)")  # jamais le code
            reponses.append(message_invitation(code, app.invitation.role, app.invitation.restant()))
    elif genre == "annuler_invitation" and page:
        if app.invitation.annuler():
            print(f"[{acteur}] invitation annulée")
    elif genre in TYPES_PAGE_SEULE:
        reponses.append({"etat": "refuse", "type": genre, "message": "invitation réservée à la page d'administration"})
        change = False
    else:
        change = genre != "appareils"
    reponses.append(app.vue(avec_code=True))
    if change:
        await notifier_pages(moteur, sauf=courant)
    return reponses


def vue_web(moteur):
    """État du client web pour la page : appareils (sans clé), ouverture en cours (jamais le code)."""
    service = getattr(moteur, "service_web", None)
    if service is None or service.appairage is None:
        return {"etat": "web", "disponible": False}
    ap = service.appairage
    ouverture = ap.etat_ouverture()
    if ouverture.get("ouverte"):  # durée restante plutôt qu'une date : l'horloge du navigateur peut différer
        ouverture["restant"] = max(0, int(ouverture["expire"] - ap.horloge()))
    return {"etat": "web", "disponible": True, "hote": service.hote, "appareils": service.liste_appareils(),
            "ouverture": ouverture, "proprietaire": ap.appareils.a_proprietaire()}


async def gerer_web(moteur, msg, acteur):
    """Traite un message TYPES_WEB de la page d'administration. Renvoie les messages à répondre à la page.

    Home Assistant n'ouvre un appairage de propriétaire que s'il n'en existe aucun (appairage_web.ouvrir). La page
    confirme sans clé d'accès : l'administrateur de HA (liste blanche, Ingress) est l'autorité de dépannage."""
    import appairage_web as AW
    service = getattr(moteur, "service_web", None)
    genre = msg.get("type")
    if service is None or service.appairage is None:
        return [{"etat": "refuse", "type": genre, "message": "client web non démarré"}, vue_web(moteur)]
    ap = service.appairage
    reponses = []
    try:
        if genre == "web_ouvrir":
            o = ap.ouvrir(msg.get("nom"), msg.get("role"), "ha")
            print(f"[{acteur}] appairage web ouvert pour le rôle {o['role']}")  # jamais le code
            reponses.append({"etat": "web_ouverture", "code": o["code"], "expire": o["expire"], "duree": o["duree"],
                             "nom": o["nom"], "role": o["role"], "qr": service.qr_appairage(o["code"])})
        elif genre == "web_confirmer":
            appareil = ap.finaliser()
            print(f"[{acteur}] appairage web confirmé ({appareil['role']})")
            reponses.append({"etat": "web_confirme", "nom": appareil["nom"], "role": appareil["role"]})
        elif genre == "web_annuler":
            if ap.annuler():
                print(f"[{acteur}] appairage web annulé")
        elif genre == "web_revoquer":
            a = ap.revoquer(str(msg.get("id", ""))[:32])
            print(f"[{acteur}] appareil web révoqué ({a['role']})")
    except AW.ErreurAppairage as e:
        reponses.append({"etat": "refuse", "type": genre, "message": CAUSES_WEB.get(e.cause, "refusé")})
    reponses.append(vue_web(moteur))
    return reponses


async def notifier_web(moteur, evenement=None):
    """Prévient les pages d'un changement côté client web (appairage fait, fermé, appareil retiré)."""
    for p in list(moteur.pages_admin):
        try:
            if evenement:
                await p.envoyer(etat="web_evenement", **evenement)
            await p.envoyer(**vue_web(moteur))
        except Exception:
            pass


async def notifier_pages(moteur, sauf=None):
    """Envoie la liste à jour aux pages ouvertes (invitation utilisée, appareil créé ou retiré)."""
    for p in list(moteur.pages_admin):
        if p is not sauf:
            try:
                await p.envoyer(**moteur.appareils.vue(avec_code=True))
            except Exception:
                pass


def reponse_http(statut, corps, genre="text/plain; charset=utf-8"):
    """(statut, en-têtes, corps) d'une réponse HTTP, avec les en-têtes de sécurité."""
    donnees = corps if isinstance(corps, bytes) else corps.encode("utf-8")
    entetes = dict(ENTETES_SECURITE)
    entetes["Content-Type"] = genre
    entetes["Content-Length"] = str(len(donnees))
    return statut, entetes, donnees


def refus_texte(ip, entetes, raison):
    """403 expliqué : montre à l'utilisateur de HA son identifiant, à mettre dans administration.utilisateurs_ha,
    seulement quand la requête vient bien du superviseur."""
    texte = "Accès refusé à l'administration de l'assistant.\n"
    ident = (entetes.get("X-Remote-User-Id") or "").strip()
    if str(ip).split("%")[0] == acces.SUPERVISEUR and ident:
        texte += ("\nPour autoriser ce compte Home Assistant, ajoute son identifiant à la clé "
                  "administration.utilisateurs_ha de maison.json, puis redéploie l'appli :\n"
                  f"  {ident}\n")
    return reponse_http(HTTPStatus.FORBIDDEN, texte)


def traiter_requete(ip, chemin, entetes):
    """(statut, en-têtes, corps) pour une requête HTTP, ou None pour laisser passer l'ouverture de /ws.
    Les barrières d'entrée jouent avant tout, y compris pour les chemins inconnus."""
    utilisateur, raison = acces.controle_ingress(ip, entetes)
    if not utilisateur:
        print(f"administration : accès refusé depuis {ip} ({raison})")
        return refus_texte(ip, entetes, raison)
    chemin = chemin.split("?", 1)[0].split("#", 1)[0]
    if chemin == "/ws":
        return None
    fichier = FICHIERS.get(chemin)
    if not fichier:
        return reponse_http(HTTPStatus.NOT_FOUND, "Introuvable.\n")
    try:
        return reponse_http(HTTPStatus.OK, (DOSSIER_PAGE / fichier[0]).read_bytes(), fichier[1])
    except OSError:
        return reponse_http(HTTPStatus.NOT_FOUND, "Introuvable.\n")


async def session_page(moteur, ws, version):
    """Une connexion WebSocket de la page. Fermée en 4003 si l'origine ne correspond pas à l'hôte."""
    entetes = ws.request.headers
    ip = ws.remote_address[0]
    utilisateur, raison = acces.controle_ingress(ip, entetes)
    if not utilisateur or not acces.origine_acceptee(entetes, ip):
        print(f"administration : WebSocket refusée depuis {ip} ({raison or 'origine absente ou étrangère'}, "
              f"Origin={entetes.get('Origin')!r}, Host={entetes.get('Host')!r}, "
              f"X-Forwarded-Host={entetes.get('X-Forwarded-Host')!r})")
        await ws.close(code=4003, reason="accès refusé")
        return
    page = Page(ws, *utilisateur)
    moteur.pages_admin.add(page)
    print(f"[{page.nom}] page d'administration ouverte")
    try:
        await page.envoyer(etat="session", assistant=maison.NOM_ASSISTANT, version=version,
                           utilisateur=utilisateur[1])
        await page.envoyer(**moteur.appareils.vue(avec_code=True))
        await page.envoyer(**vue_web(moteur))
        async for brut in ws:
            try:
                msg = json.loads(brut)
            except (ValueError, RecursionError):
                continue
            genre = msg.get("type") if isinstance(msg, dict) else None
            if isinstance(genre, str) and genre in TYPES_WEB:
                for rep in await gerer_web(moteur, msg, page.nom):
                    await page.envoyer(**rep)
                continue
            if not isinstance(genre, str) or genre not in TYPES_PAGE:
                await page.envoyer(etat="refuse", type=str(genre)[:40], message="message non permis")
                continue
            for rep in await gerer_appareils(moteur, msg, page.nom, courant=page, page=True):
                await page.envoyer(**rep)
    except websockets.ConnectionClosed:
        pass
    finally:
        moteur.pages_admin.discard(page)
        print(f"[{page.nom}] page d'administration fermée")


async def demarrer(moteur, port, version):
    """Démarre le service d'administration sur 0.0.0.0:port (le conteneur : le port n'est pas publié)."""
    def avant(connexion, requete):
        rep = traiter_requete(connexion.remote_address[0] if connexion.remote_address else "", requete.path,
                              requete.headers)
        if rep is None:
            return None
        statut, entetes, corps = rep
        return Response(statut.value, statut.phrase, Headers(entetes), corps)

    def apres(connexion, requete, reponse):
        for cle, valeur in ENTETES_SECURITE.items():
            reponse.headers[cle] = valeur
        return reponse

    async def accueil(ws):
        await session_page(moteur, ws, version)

    return await websockets.serve(accueil, "0.0.0.0", port, process_request=avant, process_response=apres,
                                  max_size=2 ** 16, ping_interval=20)

