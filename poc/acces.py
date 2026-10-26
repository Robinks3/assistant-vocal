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
- Rôles (0.38.0) : chaque identité a un rôle effectif (role_effectif), qui borne ses droits. Le « propriétaire » de la
  conception du client web s'appelle « administrateur » dans le code et dans appareils.json (les fichiers
  existants restent valables). Il est réservé à la clé du propriétaire (proprietaire.cle de maison.json) et aux
  clés de acces.administrateurs : ni changer_role, ni une invitation, ni l'appairage ne l'attribuent. Un jeton
  fixe de poc/.env prend le rôle de acces.roles, sinon « habitant ». Un appareil appairé prend le champ « role »
  de son entrée, sinon « invite ». La personne qui parle (champ « personne » d'un message) n'ajoute jamais un
  droit : voir personne_effective.
"""
import base64, hashlib, hmac, json, re, secrets, time
from datetime import datetime, timedelta, timezone

import ipaddress
from urllib.parse import urlparse

import liste_blanche
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


def est_administrateur(identite, appareils=None):
    """Vrai si le rôle effectif de l'identité est « administrateur » (voir role_effectif plus bas)."""
    return role_effectif(identite, appareils) == "administrateur"


# Home Assistant Ingress (0.34.0) : le superviseur relaie les requêtes de la page d'administration depuis cette
# adresse et pose lui-même X-Remote-User-Id, -Name et -Display-Name (il retire ceux que le client enverrait).
# https://contributors.home-assistant.io/apps/guides/ingress/
SUPERVISEUR = "172.30.32.2"

# Rôles (0.38.0). Le rôle effectif d'une identité (role_effectif) borne ses droits : seul l'administrateur gère les
# appareils et les réglages (TYPES_ADMINISTRATION). Depuis 0.39.0, la liste blanche de tous les autres messages
# par rôle est la table TYPES_PAR_ROLE plus bas, consultée par type_permis (conception du client web, étape 0a).
# « administrateur » ne s'attribue ni depuis la page d'administration, ni par une invitation, ni à l'appairage : il
# vient de proprietaire.cle et de acces.administrateurs.
ROLES = ("administrateur", "habitant", "partage", "invite")
ROLES_ATTRIBUABLES = ("habitant", "partage", "invite")
# Rôle d'une acceptation ou d'une invitation sans précision, et d'un jeton fixe absent de acces.roles.
ROLE_PAR_DEFAUT = "habitant"
# Rôle d'une entrée d'appareils.json sans champ « role » (d'avant 0.34.0) ou au rôle inconnu : le moins de droits.
ROLE_SANS_CHAMP = "invite"

# Liste blanche des types de messages du port chiffré (0.39.0), UNE seule table : tout type qui n'y figure pas pour
# le rôle effectif de l'appareil est refusé (serveur_satellite.Satellite.recevoir_texte), même si le serveur sait le
# traiter. Le port en clair (ancien accès ?jeton=) garde son comportement d'avant et ne la consulte pas.
# Administration : gérer les appareils, les rôles, les invitations et les réglages du serveur.
TYPES_ADMINISTRATION = frozenset({"appareils", "appairer", "refuser_appareil", "revoquer", "changer_role",
                                  "changer_personne", "inviter", "annuler_invitation", "transcription", "mode",
                                  "cerveau", "manques"})
# Communs à tous les rôles : parler à l'assistant, piloter la maison par lui, météo, lecture d'une réponse, réglage
# de l'écoute, retours sur une réponse. « historique » est permis à tous mais la réponse est filtrée par rôle
# (entrees_visibles). « transcrire » : la tablette en mode « Cet appareil » transcrit pour un invité aussi.
TYPES_COMMUNS = frozenset({"lecture_finie", "parler", "reveil", "llm", "ha", "meteo_mer", "vent_mesure", "retour",
                           "transcrire", "historique"})
# Santé : réservée aux rôles administrateur et habitant. La barrière fine (SANTE_PERSONNES, serveur_satellite.
# refus_sante) s'ajoute : un habitant n'obtient les données d'une personne que si elle l'y autorise.
TYPES_SANTE = frozenset({"sante", "sante_periode", "sante_seances", "sante_seance", "sante_records", "sante_jour"})
# Reconnaissance des visages (tablette) et signalement de commandes non comprises : pas pour l'invité.
TYPES_FOYER = frozenset({"vision", "manque"})
TYPES_PAR_ROLE = {
    "administrateur": TYPES_COMMUNS | TYPES_SANTE | TYPES_FOYER | TYPES_ADMINISTRATION,
    "habitant": TYPES_COMMUNS | TYPES_SANTE | TYPES_FOYER,
    "partage": TYPES_COMMUNS | TYPES_FOYER,
    "invite": TYPES_COMMUNS,
}


def type_permis(role, genre):
    """Vrai si un message de type [genre] est accepté d'un appareil de rôle effectif [role] sur le port chiffré.
    Seule fonction qui consulte TYPES_PAR_ROLE. Rôle inconnu, type absent ou qui n'est pas une chaîne : refusé."""
    return isinstance(genre, str) and genre in TYPES_PAR_ROLE.get(role, frozenset())


def role_de(entree):
    """Rôle inscrit dans une entrée d'appareils.json. Une entrée sans champ ou au rôle inconnu vaut « invite »,
    sans que le fichier soit réécrit. Ce n'est pas le rôle effectif (voir role_effectif)."""
    role = entree.get("role") if isinstance(entree, dict) else None
    return role if role in ROLES else ROLE_SANS_CHAMP


def roles_configures():
    """acces.roles de maison.json : clé d'identité (minuscules) vers rôle (minuscules). Section absente : vide."""
    v = maison.ACCES.get("roles")
    if not isinstance(v, dict):
        return {}
    return {str(k).strip().lower(): str(r).strip().lower() for k, r in v.items()}


def avertissements_roles():
    """Phrases pour le journal au démarrage : acces.roles qui donne à un administrateur un autre rôle (ignoré),
    « administrateur » à une clé qui ne l'est pas (réservé, le jeton vaut « invite ») ou un rôle inconnu (le jeton
    vaut « invite »)."""
    res = []
    for cle, role in sorted(roles_configures().items()):
        if cle in administrateurs():
            if role != "administrateur":
                res.append(f"acces.roles : « {cle} » est administrateur (proprietaire.cle ou acces.administrateurs), "
                           f"la valeur « {role} » est ignorée")
        elif role == "administrateur":
            res.append(f"acces.roles : « administrateur » est réservé à proprietaire.cle et à acces.administrateurs, "
                       f"« {cle} » vaut « invite »")
        elif role not in ROLES_ATTRIBUABLES:
            res.append(f"acces.roles : rôle inconnu « {role} » pour « {cle} », il vaut « invite »")
    return res


def _entree_appareil(appareils, ident):
    for a in getattr(appareils, "liste", None) or []:
        if isinstance(a, dict) and str(a.get("id", "")).lower() == ident:
            return a
    return None


def role_effectif(identite, appareils=None):
    """Rôle qui borne les droits d'une identité (clé telle que renvoyée par Appareils.identite).

    - le propriétaire et les clés de acces.administrateurs : « administrateur », quoi que disent acces.roles et
      appareils.json ;
    - un jeton fixe de poc/.env (clé sans « : ») : sa valeur dans acces.roles, « habitant » s'il n'y figure pas,
      « invite » si la valeur est inconnue ou vaut « administrateur » (réservé) ;
    - un appareil appairé (« appareil:<id> ») : le champ « role » de son entrée, « invite » si le champ manque, est
      inconnu ou vaut « administrateur » hors de acces.administrateurs, ou si l'entrée n'existe plus
      (appareils : l'objet Appareils, sans lui « invite ») ;
    - tout le reste (aucune identité, « ha:<id> » des pages, forme inconnue) : « invite »."""
    if not identite:
        return "invite"
    cle = str(identite).strip().lower()
    if cle in administrateurs():
        return "administrateur"
    if cle.startswith("appareil:"):
        entree = _entree_appareil(appareils, cle[len("appareil:"):])
        role = role_de(entree) if entree is not None else ROLE_SANS_CHAMP
        return role if role in ROLES_ATTRIBUABLES else "invite"
    if ":" in cle:
        return "invite"
    role = roles_configures().get(cle)
    if role is None:
        return ROLE_PAR_DEFAUT
    return role if role in ROLES_ATTRIBUABLES else "invite"


def cle_habitant(valeur):
    """Clé d'habitant (minuscules sans accent) d'une personne déclarée, ou None si ce n'est pas un habitant connu.

    Habitants connus : le propriétaire (sa clé, son nom, ses variantes de prononciation, toutes ramenées à
    proprietaire.cle), les clés de la liste « habitants » de maison.json et celles de securite.permis_personne."""
    p = securite.personne_normalisee(valeur)
    if not p:
        return None
    proprio = {securite.personne_normalisee(x) for x in
               [maison.CLE_PROPRIETAIRE, maison.NOM_PROPRIETAIRE] + list(maison.PROPRIETAIRE.get("variantes") or [])}
    if p in proprio:
        return maison.CLE_PROPRIETAIRE
    liste = maison.CONFIG.get("habitants")
    autres = {securite.personne_normalisee(x) for x in liste} if isinstance(liste, (list, dict)) else set()
    autres |= set(securite.PERMIS_PERSONNE)
    return p if p in autres else None


def personne_effective(identite, declaree, appareils=None):
    """Personne dont les droits « personnels » valent pour ce message (règle 3 de securite.py, « ma chambre »), ou
    None. Seule fonction qui décide de la personne des messages llm, parler, reveil et ha. Les droits sont bornés
    par le rôle de l'identité, jamais par la personne déclarée :

    - administrateur ou partage : la personne déclarée est acceptée si c'est un habitant connu (cle_habitant), sinon
      aucune. Exception : « inconnu », la tablette qui voit quelqu'un sans le reconnaître, passe telle quelle (elle
      ne donne aucun droit, elle fait seulement refuser « ma chambre »). Transitoire : la tablette du salon porte
      le jeton du propriétaire et sa caméra dit qui parle, jusqu'à ce qu'elle ait son propre jeton « partage » ;
    - habitant ou invite : la personne déclarée est ignorée. Un jeton fixe vaut sa clé (si c'est un habitant connu),
      un appareil appairé le champ « personne » de son entrée, sinon aucune."""
    role = role_effectif(identite, appareils)
    if role in ("administrateur", "partage"):
        from dictionnaire import INCONNU, normaliser
        d = str(declaree or "").strip()
        if d and normaliser(d) == INCONNU:
            return INCONNU
        return cle_habitant(d)
    cle = str(identite or "").strip().lower()
    if cle.startswith("appareil:"):
        entree = _entree_appareil(appareils, cle[len("appareil:"):])
        return cle_habitant(entree.get("personne")) if entree is not None else None
    return cle_habitant(cle) if cle and ":" not in cle else None


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


def origine_acceptee(entetes, ip=None):
    """Vrai si l'en-tête Origin d'une WebSocket est présent et d'un hôte égal à Host : une page d'un autre site ne
    peut pas ouvrir la connexion avec les droits de l'utilisateur.

    Cas Ingress de Home Assistant (0.39.0) : derrière le proxy, Host est celui du superviseur et c'est
    X-Forwarded-Host qui porte l'hôte vu par le navigateur. Cet en-tête ne compte QUE si la requête vient du
    superviseur (SUPERVISEUR). Venant de n'importe quelle autre adresse, ou sans [ip], il est ignoré : un client
    quelconque pourrait sinon l'inventer pour faire passer l'Origin d'une page étrangère."""
    try:
        origine = entetes.get("Origin")
        if not origine:
            return False
        hote = urlparse(origine).netloc.lower()
        noms = ["Host"]
        if ip is not None and str(ip).split("%")[0] == SUPERVISEUR:
            noms.append("X-Forwarded-Host")
        hotes = {(entetes.get(h) or "").split(",")[0].strip().lower() for h in noms}
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
                a["dernier"] = maison.maintenant().strftime(maison.FORMAT_HORODATAGE)
                self.enregistrer()
                return a["nom"], f"appareil:{a['id']}"
        return None, None

    def noter_refus(self, cause, ip):
        """Garde les 20 derniers refus de connexion, vus par les administrateurs dans l'écran Appareils."""
        self.refus.append({"cause": cause, "ip": str(ip), "heure": maison.maintenant().strftime(maison.FORMAT_HORODATAGE)})
        del self.refus[:-20]

    def demande(self, nom, ip, futur):
        ident = secrets.token_hex(4)
        code = f"{secrets.randbelow(10000):04d}"
        nom = re.sub(r"[^\w .'-]", "", nom or "")[:40].strip() or "Téléphone"
        self.attente[ident] = {"nom": nom, "code": code, "ip": ip, "futur": futur, "t": time.time()}
        return ident, code, nom

    def accepter(self, ident, role=ROLE_PAR_DEFAUT, personne=None):
        """Crée le jeton de l'appareil en attente, le remet à sa connexion, et ne garde que l'empreinte.

        None, sans rien consommer, si le rôle n'est pas attribuable (« administrateur » jamais) ou si la personne
        n'est pas un habitant connu (cle_habitant). personne : l'habitant qui porte cet appareil, ou rien."""
        if role not in ROLES_ATTRIBUABLES:
            return None
        cle = cle_habitant(personne) if personne else None
        if personne and not cle:
            return None
        d = self.attente.pop(ident, None)
        if not d or d["futur"].done():
            return None
        jeton = secrets.token_urlsafe(32)
        entree = {"id": ident, "nom": d["nom"], "empreinte": empreinte(jeton), "role": role}
        if cle:
            entree["personne"] = cle
        entree.update({"cree": maison.maintenant().strftime(maison.FORMAT_HORODATAGE), "dernier": ""})
        self.liste.append(entree)
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
        if role not in ROLES_ATTRIBUABLES or role_effectif(f"appareil:{ident}", self) == "administrateur":
            return None  # le rôle d'un administrateur (acces.administrateurs) ne se change pas d'ici
        for a in self.liste:
            if a["id"] == ident:
                avant = role_de(a)
                if avant == "administrateur":
                    return None
                a["role"] = role
                self.enregistrer()
                return a["nom"], avant, role
        return None

    def changer_personne(self, ident, personne):
        """(nom, avant, après), ou None si l'appareil est inconnu ou si la personne n'est pas un habitant connu
        (cle_habitant). Une personne vide retire le champ : l'appareil n'a plus de personne."""
        cle = cle_habitant(personne) if personne else None
        if personne and not cle:
            return None
        for a in self.liste:
            if a["id"] == ident:
                avant = a.get("personne")
                if cle:
                    a["personne"] = cle
                else:
                    a.pop("personne", None)
                self.enregistrer()
                return a["nom"], avant, cle
        return None

    def vue(self, avec_code=False):
        """Liste des appareils. Le code d'appairage n'y figure que sur demande expresse (avec_code), pour
        l'écran d'un administrateur : sans lui, une vue ne permet pas de deviner le code d'une demande."""
        return {"etat": "appareils",
                "attente": [dict({"id": i, "nom": d["nom"], "ip": d["ip"]}, **({"code": d["code"]} if avec_code else {}))
                            for i, d in self.attente.items() if not d["futur"].done()],
                "appareils": [{"id": a["id"], "nom": a["nom"], "role": role_effectif(f"appareil:{a['id']}", self),
                               "personne": a.get("personne") or None, "cree": a["cree"],
                               "dernier": a["dernier"]} for a in self.liste],
                "invitation": self.invitation.vue(),
                "jetons_fixes": sorted(set(self.env.values())),
                # Rôle effectif de chaque jeton fixe (jetons_fixes reste la liste des noms, lue telle quelle par l'appli).
                "roles_jetons_fixes": {n: role_effectif(n, self) for n in sorted(set(self.env.values()))},
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
    le journal, ni dans vue(), ni dans un message diffusé. Comparaison à temps constant.

    Compteur d'essais par adresse (0.39.0). Quand l'appelant donne l'adresse source (verifier(..., ip=...)), les
    erreurs se comptent PAR ADRESSE sur une fenêtre glissante : une adresse qui atteint le plafond est bloquée sans
    même tester le code, et ne détruit plus l'invitation pour les autres (avant, trois erreurs d'un inconnu
    suffisaient à annuler l'invitation d'un habitant). Un filet global (essais_global erreurs toutes adresses
    confondues) détruit encore le code, contre un attaquant qui changerait d'adresse. Sans adresse (ip=None), le
    comportement d'avant est conservé : ESSAIS erreurs globales. Réglages dans la section acces de maison.json :
    invitation_essais_par_ip (défaut ESSAIS), invitation_fenetre_s (défaut DUREE), invitation_essais_global
    (défaut ESSAIS_GLOBAL)."""
    DUREE = 120
    ESSAIS = 3
    ESSAIS_GLOBAL = 30
    LONGUEUR = 6
    # Adresses suivies au plus, pour qu'un balayage d'adresses ne fasse pas grossir la mémoire.
    ADRESSES_MAX = 512

    def __init__(self):
        self.code = None
        self.role = ROLE_PAR_DEFAUT
        self.expire = 0.0
        self.essais = 0
        self.echecs = {}  # adresse -> horodatages (secondes) des essais faux dans la fenêtre

    @staticmethod
    def plafond_par_adresse():
        return maison.entier(maison.ACCES, "invitation_essais_par_ip", Invitation.ESSAIS)

    @staticmethod
    def fenetre():
        return maison.entier(maison.ACCES, "invitation_fenetre_s", Invitation.DUREE)

    @staticmethod
    def plafond_global():
        return maison.entier(maison.ACCES, "invitation_essais_global", Invitation.ESSAIS_GLOBAL)

    @staticmethod
    def adresse(ip):
        """Forme comparable d'une adresse source (sans zone IPv6), None si elle manque."""
        return str(ip).split("%")[0].strip().lower() if ip else None

    def echecs_recents(self, adresse, maintenant):
        """Nombre d'essais faux de [adresse] dans la fenêtre. Purge au passage ce qui en est sorti."""
        depuis = maintenant - self.fenetre()
        recents = [t for t in self.echecs.get(adresse, ()) if t > depuis]
        if recents:
            self.echecs[adresse] = recents
        else:
            self.echecs.pop(adresse, None)
        return len(recents)

    def noter_echec(self, adresse, maintenant):
        if adresse not in self.echecs and len(self.echecs) >= self.ADRESSES_MAX:
            depuis = maintenant - self.fenetre()
            self.echecs = {a: [t for t in ts if t > depuis] for a, ts in self.echecs.items()}
            self.echecs = {a: ts for a, ts in self.echecs.items() if ts}
            if len(self.echecs) >= self.ADRESSES_MAX:
                self.echecs.pop(next(iter(self.echecs)))  # la plus ancienne arrivée
        self.echecs.setdefault(adresse, []).append(maintenant)

    def bloquee(self, ip, maintenant=None):
        """Vrai si cette adresse a atteint son plafond d'essais faux dans la fenêtre."""
        maintenant = time.time() if maintenant is None else maintenant
        adresse = self.adresse(ip)
        return adresse is not None and self.echecs_recents(adresse, maintenant) >= self.plafond_par_adresse()

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
        self.echecs = {}
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

    def verifier(self, saisi, maintenant=None, ip=None):
        """(rôle, essais restants). Rôle None si refus. Un code juste est consommé.

        Sans [ip] : la dernière erreur globale (ESSAIS) détruit le code. Avec [ip] (0.39.0) : les erreurs se
        comptent par adresse dans la fenêtre. Une adresse au plafond reçoit (None, 0) sans que le code soit testé
        ni détruit, et son essai ne compte pas pour les autres. Le filet global détruit le code."""
        maintenant = time.time() if maintenant is None else maintenant
        if not self.valide(maintenant):
            self.annuler()
            return None, 0
        adresse = self.adresse(ip)
        if adresse is not None and self.bloquee(adresse, maintenant):
            return None, 0
        self.essais += 1
        saisi = re.sub(r"[^0-9]", "", str(saisi or ""))
        if len(saisi) == len(self.code) and hmac.compare_digest(saisi, self.code):
            role = self.role
            self.annuler()
            return role, 0
        if adresse is None:
            restant = max(0, self.ESSAIS - self.essais)
        else:
            self.noter_echec(adresse, maintenant)
            restant = max(0, self.plafond_par_adresse() - self.echecs_recents(adresse, maintenant))
            if self.essais >= self.plafond_global():
                restant = 0
                self.annuler()
        if adresse is None and restant == 0:
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


class Refus(str):
    """Raison d'un refus du point de contrôle, avec son genre : « domaine », « service », « donnees » ou « securite »."""
    genre = ""


def _refus(genre, texte):
    r = Refus(texte)
    r.genre = genre
    return r


def refus_schema(corps):
    """Raison du refus si les données d'un appel de service n'ont pas la forme attendue, ou None. Un objet dont
    les clés sont des textes, et des cibles (entity_id, area_id) en texte ou en liste de textes : une cible d'un
    autre type échappe à securite.cibles, qui la lirait de travers, et HA la lirait autrement."""
    if not isinstance(corps, dict):
        return "données : un objet est attendu (sécurité)"
    for cle, valeur in corps.items():
        if not isinstance(cle, str):
            return "données : les clés doivent être du texte (sécurité)"
        if cle in ("entity_id", "area_id") and valeur is not None:
            if not (isinstance(valeur, str) or (isinstance(valeur, (list, tuple)) and all(isinstance(v, str) for v in valeur))):
                return f"données : {cle} doit être un texte ou une liste de textes (sécurité)"
    return None


def controler_service(domaine, service, corps, personne=None, services_permis=None):
    """POINT DE CONTRÔLE UNIQUE (0.40.0, S-F4) de tout appel de service Home Assistant, sur la voie du LLM
    (HomeAssistant.service), celle du dictionnaire (Assistant.executer) et celle de l'appli
    (verifier_requete_ha). Rend un Refus (texte en français, avec son genre), ou None si l'appel peut partir.
    Ordre : domaines interdits, service permis, schéma des données, URL de launch_app, réglages de la maison
    (liste_blanche.refus_reglage, communs à toutes les voies), puis securite.verifier.

    services_permis : l'ensemble des services permis du domaine (liste blanche), ou None quand la voie n'en a pas.
    Le LLM en a une (HomeAssistant.services_permis). Le dictionnaire est écrit par le propriétaire et l'appli
    a besoin de services hors liste (media_player.join pour grouper les enceintes), les deux passent sans, sauf
    la passerelle pour les domaines réservés à l'appli (liste_blanche.DOMAINES_HORS_LLM, table SERVICES_PERMIS).
    personne : qui parle d'après la session, jamais d'après le texte d'un message (règle 3 de securite.py)."""
    if domaine in DOMAINES_INTERDITS:
        return _refus("domaine", f"domaine {domaine} interdit par la passerelle")
    if services_permis is not None and service not in services_permis:
        return _refus("service", f"service {domaine}.{service} inexistant ou interdit")
    # Corps absent (None) : un appel sans données, accepté sauf pour launch_app qui exige son objet.
    refus = None if corps is None else refus_schema(corps)
    if refus:
        return _refus("donnees", refus)
    refus = refus_launch_app(f"{domaine}.{service}", corps)
    if refus:
        return _refus("donnees", refus)
    # Réglages de la maison (liste_blanche.REGLAGES) : les mêmes pour toutes les voies, puisqu'elles passent ici.
    refus = liste_blanche.refus_reglage(domaine, service, corps)
    if refus:
        return _refus("donnees", refus)
    refus = securite.verifier(f"{domaine}.{service}", {} if corps is None else corps, personne=personne)
    return _refus("securite", refus) if refus else None


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
    # Les domaines réservés à l'appli et au dictionnaire (domaine_tele, remote, select) ont leur liste de
    # services dans liste_blanche, la même que celle du serveur. Les autres domaines gardent leur liberté de
    # services côté appli (media_player.join pour grouper les enceintes), le LLM seul a la liste.
    permis = liste_blanche.SERVICES_PERMIS.get(domaine) if domaine in liste_blanche.DOMAINES_HORS_LLM else None
    return controler_service(domaine, service, corps, personne=personne, services_permis=permis) or None
