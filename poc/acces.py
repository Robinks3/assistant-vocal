"""Accès des téléphones au serveur assistant (v0.17.0), idées reprises du protocole des satellites de
assistant (auteurs inspiration), réécrites ici.

- Le jeton voyage dans l'en-tête « Authorization: Bearer », plus dans l'adresse (qui finit dans les
  journaux). L'ancienne forme « ?jeton= » reste acceptée sur le port en clair tant que
  JARVIS_ANCIEN_ACCES vaut 1, le temps de mettre à jour tous les téléphones.
- Le serveur ne garde que l'empreinte SHA-256 de chaque jeton (appareils.json dans les données).
- Un nouveau téléphone s'appaire : il se connecte sans jeton sur le port chiffré, affiche un code à
  4 chiffres, et un téléphone déjà connu accepte la demande. Le jeton est créé à ce moment-là et
  n'est envoyé qu'une fois, chiffré.
- Port chiffré (wss) avec un certificat auto-signé créé au premier démarrage. Le téléphone retient
  l'empreinte de sa clé publique à la première connexion et refuse ensuite toute autre clé.
- Passerelle Home Assistant : le mode « Cet appareil » passe par ce serveur, qui a son propre jeton
  HA, au lieu d'embarquer un jeton administrateur dans l'APK. Seuls quelques chemins sont permis, et
  chaque action passe par la sécurité en dur.
"""
import base64, hashlib, hmac, json, re, secrets, time
from datetime import datetime, timedelta, timezone

import securite


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

    def demande(self, nom, ip, futur):
        ident = secrets.token_hex(4)
        code = f"{secrets.randbelow(10000):04d}"
        nom = re.sub(r"[^\w .'-]", "", nom or "")[:40].strip() or "Téléphone"
        self.attente[ident] = {"nom": nom, "code": code, "ip": ip, "futur": futur, "t": time.time()}
        return ident, code, nom

    def accepter(self, ident):
        """Crée le jeton de l'appareil en attente, le remet à sa connexion, et ne garde que l'empreinte."""
        d = self.attente.pop(ident, None)
        if not d or d["futur"].done():
            return None
        jeton = secrets.token_urlsafe(32)
        self.liste.append({"id": ident, "nom": d["nom"], "empreinte": empreinte(jeton),
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

    def vue(self):
        return {"etat": "appareils",
                "attente": [{"id": i, "nom": d["nom"], "code": d["code"], "ip": d["ip"]}
                            for i, d in self.attente.items() if not d["futur"].done()],
                "appareils": [{"id": a["id"], "nom": a["nom"], "cree": a["cree"], "dernier": a["dernier"]}
                              for a in self.liste],
                "jetons_fixes": sorted(set(self.env.values()))}


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
    return securite.verifier(f"{domaine}.{service}", corps if isinstance(corps, dict) else {}, personne=personne)
