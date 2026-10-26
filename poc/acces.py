"""Accès des téléphones au serveur de l'assistant (v0.17.0), idées reprises du protocole des satellites d'un
projet d'inspiration, réécrites ici.

- Le jeton voyage dans l'en-tête « Authorization: Bearer », plus dans l'adresse (qui finit dans les
  journaux). L'ancienne forme « ?jeton= » reste acceptée sur le port en clair tant que
  JARVIS_ANCIEN_ACCES vaut 1, le temps de mettre à jour tous les téléphones.
- Le serveur ne garde que l'empreinte SHA-256 de chaque jeton (appareils.json dans les données).
- Un nouveau téléphone s'appaire : il se connecte sans jeton sur le port chiffré, affiche un code à
  4 chiffres, et un téléphone déjà connu accepte la demande. Le jeton est créé à ce moment-là et
  n'est envoyé qu'une fois, chiffré.
- Amorçage (0.32.0) : si aucun administrateur n'est connecté, personne ne peut accepter la demande
  (coupure de courant, jeton de l'APK que le serveur ne reconnaît plus). Le serveur écrit alors dans son
  journal un code d'amorçage à 8 chiffres, à usage unique, valable 10 minutes, 5 essais, que le
  téléphone du réseau local saisit pour obtenir son jeton. Voir Amorcage.
- Port chiffré (wss) avec un certificat auto-signé créé au premier démarrage. Le téléphone retient
  l'empreinte de sa clé publique à la première connexion et refuse ensuite toute autre clé.
- Passerelle Home Assistant : le mode « Cet appareil » passe par ce serveur, qui a son propre jeton
  HA, au lieu d'embarquer un jeton administrateur dans l'APK. Seuls quelques chemins sont permis, et
  chaque action passe par la sécurité en dur.
"""
import base64, hashlib, hmac, json, re, secrets, time
from datetime import datetime, timedelta, timezone

import ipaddress
from urllib.parse import urlparse

import maison
import securite

# Réseaux dont une connexion est acceptée par défaut : la maison (adresses privées), le tailnet (Tailscale),
# la machine elle-même (Tailscale Serve et les routines locales arrivent de 127.0.0.1). Un réseau public est refusé.
RESEAUX_PAR_DEFAUT = ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                      "169.254.0.0/16", "100.64.0.0/10", "fe80::/10", "fd00::/8")


def _liste_acces(cle):
    v = maison.ACCES.get(cle)
    return [str(x).strip() for x in v] if isinstance(v, list) else None


def reseaux_autorises():
    """Réseaux acceptés, d'après acces.reseaux_autorises (CIDR) ou RESEAUX_PAR_DEFAUT. Une entrée illisible
    est ignorée. « * » ou 0.0.0.0/0 ouvre à tous (retour à l'ancien comportement)."""
    voulus = _liste_acces("reseaux_autorises") or list(RESEAUX_PAR_DEFAUT)
    reseaux = []
    for v in voulus:
        if v == "*":
            v = "0.0.0.0/0"
        try:
            reseaux.append(ipaddress.ip_network(v, strict=False))
        except ValueError:
            print(f"acces : réseau illisible ignoré : {v}")
    if any(r.prefixlen == 0 for r in reseaux):
        reseaux.append(ipaddress.ip_network("::/0"))
    return reseaux


def adresse_autorisee(ip, reseaux):
    """Vrai si l'adresse de l'homologue est dans un réseau autorisé. Une adresse illisible est refusée."""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return any(a in r for r in reseaux if r.version == a.version)


def adresses_ecoute():
    """Adresses d'écoute des ports (acces.ecoute), « 0.0.0.0 » seul par défaut : le filtre par réseau
    (reseaux_autorises) ne dépend ainsi d'aucune adresse de carte réseau. Y mettre les adresses du PC
    ferme réellement les ports sur les autres interfaces."""
    return [a for a in (_liste_acces("ecoute") or []) if a] or ["0.0.0.0"]


def ancien_acces_permis(env=None):
    """Ancien accès ?jeton= sur le port en clair : JARVIS_ANCIEN_ACCES s'il est réglé, sinon acces.ancien_acces
    de la configuration, sinon permis (inchangé tant que le propriétaire n'a pas décidé de le couper)."""
    if env is not None and str(env).strip() != "":
        return str(env).strip() != "0"
    v = maison.ACCES.get("ancien_acces")
    return v if isinstance(v, bool) else True


# Réseaux où l'amorçage est permis : la maison seulement (ni le tailnet ni un autre réseau autorisé).
RESEAUX_LOCAUX = ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                  "169.254.0.0/16", "fe80::/10", "fd00::/8")


def adresse_locale(ip):
    """Vrai si l'homologue est sur le réseau de la maison (privé ou la machine elle-même)."""
    try:
        if ipaddress.ip_address(str(ip).split("%")[0]) in ipaddress.ip_network("fd7a:115c:a1e0::/48"):
            return False  # le tailnet en IPv6 tombe dans fd00::/8 sans être la maison
    except ValueError:
        return False
    return adresse_autorisee(ip, [ipaddress.ip_network(r) for r in RESEAUX_LOCAUX])


def administrateurs():
    """Identités autorisées à gérer les appareils et les réglages : le propriétaire, plus acces.administrateurs
    (identités telles que renvoyées par Appareils.identite, par exemple « appareil:ab12cd34 »)."""
    return {maison.CLE_PROPRIETAIRE} | {a.lower() for a in (_liste_acces("administrateurs") or [])}


def est_administrateur(identite):
    return bool(identite) and str(identite).lower() in administrateurs()


# Home Assistant Ingress (0.34.0) : le superviseur relaie les requêtes de la page d'administration depuis cette
# adresse et pose lui-même X-Remote-User-Id, -Name et -Display-Name (il retire ceux que le client enverrait).
# https://contributors.home-assistant.io/apps/guides/ingress/
SUPERVISEUR = "172.30.32.2"

# Rôles d'un appareil appairé. Aucun ne change de droit pour l'instant : seul l'administrateur agit, par
# acces.administrateurs. Le rôle prépare la liste blanche des messages par rôle (conception du client web,
# étape 0a). « administrateur » ne s'attribue ni depuis la page d'administration ni par une invitation.
ROLES = ("administrateur", "habitant", "partage", "invite")
ROLES_ATTRIBUABLES = ("habitant", "partage", "invite")
ROLE_PAR_DEFAUT = "habitant"


def role_de(entree):
    """Rôle d'une entrée d'appareils.json. Une entrée sans champ (d'avant 0.34.0) ou au rôle inconnu vaut
    « habitant », sans que le fichier soit réécrit."""
    role = entree.get("role") if isinstance(entree, dict) else None
    return role if role in ROLES else ROLE_PAR_DEFAUT


def utilisateurs_ha():
    """Identifiants Home Assistant (X-Remote-User-Id) admis dans la page d'administration. Liste absente ou
    vide : personne n'entre."""
    v = maison.ADMINISTRATION.get("utilisateurs_ha")
    return {str(x).strip().lower() for x in v if str(x).strip()} if isinstance(v, list) else set()


def url_client():
    """Adresse du client web, pour le QR code d'invitation. Vide tant que le client web n'existe pas."""
    v = maison.ADMINISTRATION.get("url_client")
    return v.strip() if isinstance(v, str) else ""


def controle_ingress(ip, entetes):
    """((identifiant, nom affiché), None) si la requête vient du superviseur et d'un compte de la liste blanche,
    sinon (None, raison du refus). Barrières : adresse du superviseur, identifiant présent, identifiant dans
    administration.utilisateurs_ha (panel_admin: true, dans config.yaml, en est une autre)."""
    if str(ip).split("%")[0] != SUPERVISEUR:
        return None, "adresse source hors superviseur"
    try:
        ident = (entetes.get("X-Remote-User-Id") or "").strip()
        nom = (entetes.get("X-Remote-User-Display-Name") or entetes.get("X-Remote-User-Name") or "").strip()
    except LookupError:
        return None, "en-tête d'identité en double"
    if not ident:
        return None, "utilisateur Home Assistant absent"
    if ident.lower() not in utilisateurs_ha():
        return None, f"utilisateur {ident} hors de administration.utilisateurs_ha"
    return (ident, nom or ident), None


def origine_acceptee(entetes):
    """Vrai si l'en-tête Origin d'une WebSocket est présent et d'un hôte égal à Host (ou X-Forwarded-Host) :
    une page d'un autre site ne peut pas ouvrir la connexion avec les droits de l'utilisateur."""
    try:
        origine = entetes.get("Origin")
        if not origine:
            return False
        hote = urlparse(origine).netloc.lower()
        hotes = {(entetes.get(h) or "").split(",")[0].strip().lower() for h in ("Host", "X-Forwarded-Host")}
    except (ValueError, LookupError):
        return False
    return bool(hote) and hote in hotes


def empreinte(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


class Appareils:
    """Téléphones autorisés. Les jetons de poc/.env (SATELLITE_JETON...) restent valables."""

    def __init__(self, dossier, jetons_env):
        self.fichier = dossier / "appareils.json"
        self.env = {empreinte(j): nom for j, nom in jetons_env.items()}
        try:
            self.liste = json.loads(self.fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.liste = []
        self.attente = {}  # id -> {"nom", "code", "ip", "futur", "t"}
        self.amorcage = Amorcage()
        self.invitation = Invitation()
        self.refus = []  # derniers refus de connexion (cause, adresse, heure), pour le diagnostic

    def enregistrer(self):
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        self.fichier.write_text(json.dumps(self.liste, ensure_ascii=False, indent=1), encoding="utf-8")

    def identifier(self, jeton):
        """Nom de l'appareil qui porte ce jeton, ou None. Comparaison à temps constant."""
        return self.identite(jeton)[0]

    def identite(self, jeton):
        """(nom, clé) de l'appareil qui porte ce jeton, ou (None, None). Comparaison à temps constant.

        La clé est unique et sert aux listes blanches (SANTE_PERSONNES) : pour un jeton fixe de
        poc/.env, le nom tiré de la variable (le propriétaire pour SATELLITE_JETON, « camille » pour
        SATELLITE_JETON_CAMILLE). Pour un téléphone appairé, « appareil:<id> », l'id tiré par le
        serveur à l'appairage : son nom, lui, est choisi par l'appareil, peut se répéter et peut même
        valoir la clé du propriétaire."""
        if not jeton or len(jeton) < 16:
            return None, None
        e = empreinte(jeton)
        for cle, nom in self.env.items():
            if hmac.compare_digest(cle, e):
                return nom, nom
        for a in self.liste:
            if hmac.compare_digest(a["empreinte"], e):
                a["dernier"] = datetime.now().isoformat(timespec="seconds")
                self.enregistrer()
                return a["nom"], f"appareil:{a['id']}"
        return None, None

    def noter_refus(self, cause, ip):
        """Garde les 20 derniers refus de connexion, vus par les administrateurs dans l'écran Appareils."""
        self.refus.append({"cause": cause, "ip": str(ip), "heure": datetime.now().isoformat(timespec="seconds")})
        del self.refus[:-20]

    def demande(self, nom, ip, futur):
        ident = secrets.token_hex(4)
        code = f"{secrets.randbelow(10000):04d}"
        nom = re.sub(r"[^\w .'-]", "", nom or "")[:40].strip() or "Téléphone"
        self.attente[ident] = {"nom": nom, "code": code, "ip": ip, "futur": futur, "t": time.time()}
        return ident, code, nom

    def accepter(self, ident, role=ROLE_PAR_DEFAUT):
        """Crée le jeton de l'appareil en attente, le remet à sa connexion, et ne garde que l'empreinte."""
        d = self.attente.pop(ident, None)
        if not d or d["futur"].done():
            return None
        jeton = secrets.token_urlsafe(32)
        self.liste.append({"id": ident, "nom": d["nom"], "empreinte": empreinte(jeton), "role": role,
                           "cree": datetime.now().isoformat(timespec="seconds"), "dernier": ""})
        self.enregistrer()
        d["futur"].set_result(jeton)
        return d["nom"]

    def refuser(self, ident):
        d = self.attente.pop(ident, None)
        if d and not d["futur"].done():
            d["futur"].set_result(None)
        return bool(d)

    def revoquer(self, ident):
        avant = len(self.liste)
        self.liste = [a for a in self.liste if a["id"] != ident]
        self.enregistrer()
        return len(self.liste) < avant

    def changer_role(self, ident, role):
        """(nom, avant, après), ou None si l'appareil est inconnu ou le rôle non attribuable."""
        if role not in ROLES_ATTRIBUABLES:
            return None
        for a in self.liste:
            if a["id"] == ident:
                avant = role_de(a)
                if avant == "administrateur":
                    return None
                a["role"] = role
                self.enregistrer()
                return a["nom"], avant, role
        return None

    def vue(self, avec_code=False):
        """Liste des appareils. Le code d'appairage n'y figure que sur demande expresse (avec_code), pour
        l'écran d'un administrateur : sans lui, une vue ne permet pas de deviner le code d'une demande."""
        return {"etat": "appareils",
                "attente": [dict({"id": i, "nom": d["nom"], "ip": d["ip"]}, **({"code": d["code"]} if avec_code else {}))
                            for i, d in self.attente.items() if not d["futur"].done()],
                "appareils": [{"id": a["id"], "nom": a["nom"], "role": role_de(a), "cree": a["cree"],
                               "dernier": a["dernier"]} for a in self.liste],
                "invitation": self.invitation.vue(),
                "jetons_fixes": sorted(set(self.env.values())),
                "refus": list(self.refus[-10:]) if avec_code else []}


class Amorcage:
    """Code d'amorçage de l'appairage, pour le cas où aucun administrateur n'est là pour accepter.

    Le code n'est dit qu'au journal du serveur (accès à la machine ou à ses journaux). Il a 8 chiffres, ne sert
    qu'une fois, vit DUREE secondes et meurt après ESSAIS saisies fausses, tous téléphones confondus. Un nouveau
    code ne sort pas plus d'une fois par PAUSE secondes. Comparaison à temps constant."""
    DUREE = 600
    ESSAIS = 5
    PAUSE = 60

    def __init__(self):
        self.code = None
        self.expire = 0.0
        self.essais = 0
        self.dernier = -1e9

    def valide(self, maintenant=None):
        maintenant = time.time() if maintenant is None else maintenant
        return self.code is not None and maintenant < self.expire

    def ouvrir(self, maintenant=None):
        """(code, nouveau) : le code en cours, ou un nouveau. (None, False) si un nouveau est trop proche du dernier."""
        maintenant = time.time() if maintenant is None else maintenant
        if self.valide(maintenant):
            return self.code, False
        if maintenant - self.dernier < self.PAUSE:
            return None, False
        self.code = f"{secrets.randbelow(10 ** 8):08d}"
        self.expire = maintenant + self.DUREE
        self.essais = 0
        self.dernier = maintenant
        return self.code, True

    def fermer(self):
        self.code, self.expire = None, 0.0

    def verifier(self, saisi, maintenant=None):
        """(accepté, essais restants). Un code juste est consommé, la 5e erreur détruit le code."""
        maintenant = time.time() if maintenant is None else maintenant
        if not self.valide(maintenant):
            self.fermer()
            return False, 0
        self.essais += 1
        saisi = re.sub(r"[^0-9]", "", str(saisi or ""))
        if len(saisi) == len(self.code) and hmac.compare_digest(saisi, self.code):
            self.fermer()
            return True, 0
        restant = max(0, self.ESSAIS - self.essais)
        if restant == 0:
            self.fermer()
        return False, restant


class Invitation:
    """Code d'invitation d'un appareil, affiché dans la page d'administration de Home Assistant (0.34.0).

    6 chiffres, DUREE secondes, usage unique, ESSAIS saisies fausses (tous appareils confondus) avant destruction.
    Une seule invitation ouverte à la fois : en créer une annule la précédente. Elle porte le rôle de l'appareil
    qui l'utilisera, jamais administrateur. Le code n'est remis qu'à l'appelant d'ouvrir() : il n'entre ni dans
    le journal, ni dans vue(), ni dans un message diffusé. Comparaison à temps constant."""
    DUREE = 120
    ESSAIS = 3
    LONGUEUR = 6

    def __init__(self):
        self.code = None
        self.role = ROLE_PAR_DEFAUT
        self.expire = 0.0
        self.essais = 0

    def valide(self, maintenant=None):
        maintenant = time.time() if maintenant is None else maintenant
        return self.code is not None and maintenant < self.expire

    def ouvrir(self, role=ROLE_PAR_DEFAUT, maintenant=None):
        """Nouveau code (l'ancien est détruit). ValueError si le rôle n'est pas attribuable."""
        if role not in ROLES_ATTRIBUABLES:
            raise ValueError(f"rôle non attribuable par invitation : {role}")
        maintenant = time.time() if maintenant is None else maintenant
        self.code = f"{secrets.randbelow(10 ** self.LONGUEUR):0{self.LONGUEUR}d}"
        self.role, self.expire, self.essais = role, maintenant + self.DUREE, 0
        return self.code

    def annuler(self):
        """Vrai si une invitation était ouverte."""
        ouverte = self.code is not None
        self.code, self.expire = None, 0.0
        return ouverte

    def restant(self, maintenant=None):
        maintenant = time.time() if maintenant is None else maintenant
        return max(0, int(self.expire - maintenant + 0.999)) if self.valide(maintenant) else 0

    def vue(self, maintenant=None):
        """État sans le code : None sans invitation, sinon secondes restantes et rôle."""
        return {"restant": self.restant(maintenant), "role": self.role} if self.valide(maintenant) else None

    def verifier(self, saisi, maintenant=None):
        """(rôle, essais restants). Rôle None si refus. Un code juste est consommé, la dernière erreur détruit le code."""
        maintenant = time.time() if maintenant is None else maintenant
        if not self.valide(maintenant):
            self.annuler()
            return None, 0
        self.essais += 1
        saisi = re.sub(r"[^0-9]", "", str(saisi or ""))
        if len(saisi) == len(self.code) and hmac.compare_digest(saisi, self.code):
            role = self.role
            self.annuler()
            return role, 0
        restant = max(0, self.ESSAIS - self.essais)
        if restant == 0:
            self.annuler()
        return None, restant


def jeton_de_la_requete(requete, chemin, ancien_acces):
    """Jeton présenté par le téléphone : en-tête Authorization d'abord, puis ?jeton= si permis."""
    entete = requete.headers.get("Authorization", "") if requete is not None else ""
    if entete.lower().startswith("bearer "):
        return entete[7:].strip()
    if ancien_acces:
        from urllib.parse import parse_qs, urlparse
        return parse_qs(urlparse(chemin).query).get("jeton", [""])[0]
    return ""


def certificat(dossier, hote="jarvis"):
    """Certificat auto-signé du port chiffré, créé une fois (10 ans) dans dossier/tls.
    Renvoie (chemin du certificat, chemin de la clé, empreinte SHA-256 de la clé publique en base64)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    tls = dossier / "tls"
    cert_f, cle_f = tls / "cert.pem", tls / "cle.pem"
    if not cert_f.exists() or not cle_f.exists():
        tls.mkdir(parents=True, exist_ok=True)
        cle = ec.generate_private_key(ec.SECP256R1())
        nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hote)])
        maintenant = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom).public_key(cle.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(maintenant - timedelta(days=1))
                .not_valid_after(maintenant + timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(hote)]), critical=False)
                .sign(cle, hashes.SHA256()))
        cle_f.write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        cert_f.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(cert_f.read_bytes())
    spki = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return cert_f, cle_f, base64.b64encode(hashlib.sha256(spki).digest()).decode()


# ------------------------------------------------------------ passerelle Home Assistant
DOMAINES_INTERDITS = {"lock", "alarm_control_panel", "homeassistant", "hassio", "shell_command", "rest_command",
                      "python_script", "notify", "persistent_notification", "recorder", "system_log"}
# Toujours fullmatch (0.19.0) : « $ » accepte un retour à la ligne final, que HA recevrait tel quel.
CHEMINS_LECTURE = re.compile(r"/api/states(/[a-z_]+\.[a-z0-9_]+)?")
CHEMIN_SERVICE = re.compile(r"/api/services/([a-z_]+)/([a-z_]+)")
# Pochettes des lecteurs (0.18.1) : l'image est renvoyée en base64 par la passerelle.
CHEMIN_POCHETTE = re.compile(r"/api/media_player_proxy/media_player\.[a-z0-9_]+(\?[A-Za-z0-9_=&.%-]*)?")
# Prévisions météo de l'écran de la tablette (0.19.0) : seul service à réponse permis, chemin exact.
# Ouvrir « ?return_response » à tous les services exposerait calendar.get_events, todo.get_items...
CHEMIN_PREVISIONS = "/api/services/weather/get_forecasts?return_response"
ENTITE_METEO = re.compile(r"weather\.[a-z0-9_]+")
TYPES_PREVISIONS = ("hourly", "daily", "twice_daily")


def verifier_previsions(corps, personne=None):
    """Corps de weather.get_forecasts : exactement une entité weather.* et un type connu, rien d'autre."""
    if not isinstance(corps, dict) or set(corps) != {"entity_id", "type"}:
        return "prévisions : corps attendu {entity_id, type}, rien d'autre"
    entite, genre = corps["entity_id"], corps["type"]
    if not isinstance(entite, str) or not ENTITE_METEO.fullmatch(entite):
        return "prévisions : une seule entité weather.* permise"
    if not isinstance(genre, str) or genre not in TYPES_PREVISIONS:
        return "prévisions : type hourly, daily ou twice_daily"
    return securite.verifier("weather.get_forecasts", corps, personne=personne)


URL_HTTPS = re.compile(r"https://\S+")
SCHEMA_URL = re.compile(r"\s*[A-Za-z][^\s:/]*:")


def refus_launch_app(service, corps):
    """Raison du refus pour domaine_tele.launch_app (0.30.0), ou None : une URL doit être en https://,
    et aucune autre valeur ne doit commencer par un autre schéma (http:, javascript:, data:...)."""
    if service != "domaine_tele.launch_app":
        return None
    if not isinstance(corps, dict):
        return "launch_app : corps attendu sous forme d'objet (sécurité)"
    for cle, valeur in corps.items():
        if cle == "url":
            if not (isinstance(valeur, str) and valeur.isprintable() and URL_HTTPS.fullmatch(valeur)):
                return "launch_app : l'URL doit commencer par https:// (sécurité)"
        elif cle in ("entity_id", "area_id"):
            continue
        elif isinstance(valeur, (dict, list)):
            return "launch_app : valeur imbriquée refusée (sécurité)"
        elif isinstance(valeur, str) and (SCHEMA_URL.match(valeur) or valeur.startswith("//") or not valeur.isprintable())                 and not URL_HTTPS.fullmatch(valeur):
            return "launch_app : seule une URL en https:// est permise (sécurité)"
    return None


def verifier_requete_ha(methode, chemin, corps, personne=None):
    """Raison du refus, ou None si la passerelle peut transmettre cette requête à Home Assistant."""
    methode = (methode or "GET").upper()
    if methode == "GET" and CHEMINS_LECTURE.fullmatch(chemin or ""):
        return None
    if methode == "GET" and CHEMIN_POCHETTE.fullmatch(chemin or ""):
        return None
    if methode != "POST":
        return "méthode non permise"
    if chemin in ("/api/template", "/api/conversation/process"):
        return None
    if chemin == CHEMIN_PREVISIONS:
        return verifier_previsions(corps, personne)
    m = CHEMIN_SERVICE.fullmatch(chemin or "")
    if not m:
        return "chemin non permis"
    domaine, service = m.groups()
    if domaine in DOMAINES_INTERDITS:
        return f"domaine {domaine} interdit par la passerelle"
    refus = refus_launch_app(f"{domaine}.{service}", corps)
    if refus:
        return refus
    return securite.verifier(f"{domaine}.{service}", corps if isinstance(corps, dict) else {}, personne=personne)
