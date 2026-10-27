"""IA locale d'un PC puissant, fournisseur optionnel du profil ha (0.53.0), avec repli sur Claude.

Le profil ha (appli Home Assistant, sans carte graphique) n'a que Claude comme cerveau. Si l'option `llm_local_url`
de l'appli est renseignée (LLM_LOCAL_URL, un serveur compatible OpenAI comme LM Studio ou llama-server), le
cerveau « local » devient proposable dans les réglages des téléphones. Option vide : rien ne change, le choix
« local » n'existe pas en profil ha. Sur le PC, ce module n'est pas utilisé.

Le choix par défaut reste Claude. Quand « local » est choisi :
- une sonde courte (GET {url}/models, 2 s au plus) dit si le PC répond, résultat gardé 45 s s'il répond et
  30 s s'il ne répond pas, pour ne pas ralentir chaque phrase quand le PC est éteint ;
- chaque demande va à l'IA locale si la sonde est bonne, sinon à Claude, et si l'IA locale tombe en route
  (connexion coupée, délai dépassé, réponse inutilisable) la demande est refaite sur Claude, SEULEMENT si aucun
  outil n'a encore été exécuté : sinon une action serait faite deux fois, l'erreur est remontée comme pour
  n'importe quel cerveau ;
- les deux cerveaux partagent les mêmes historiques et la même sécurité en dur : l'IA locale passe par la boucle
  d'outils de assistant.Cerveau (liste blanche, garde-fou de volume, securite.verifier avant chaque envoi à HA),
  exactement comme Claude.

Aucune adresse n'est écrite au journal ni dans une erreur : seulement la classe de l'erreur et l'état
(« injoignable », « de nouveau joignable »). Les prompts et l'inventaire de la maison partent vers cette
adresse, qui doit donc être une machine de confiance (Tailscale ou réseau local), jamais un service public."""
import os
import time
from threading import Lock
from urllib.parse import urlsplit

import assistant as A

DELAI_SONDE = 2.0       # secondes, connexion comprise
GARDE_JOIGNABLE = 45.0  # secondes pendant lesquelles un « oui » de la sonde est cru
GARDE_PANNE = 30.0      # secondes pendant lesquelles un « non » est cru
DELAI_REPONSE = 25.0    # une réponse de l'IA locale plus lente est abandonnée et refaite sur Claude
DELAI_CONNEXION = 2.0


def url_valide(brut):
    """Adresse de base du serveur (se terminant par /v1), ou "" si le texte n'est pas utilisable :
    http ou https, un nom d'hôte, ni identifiants, ni paramètres, ni fragment."""
    texte = (brut or "").strip()
    if not texte:
        return ""
    try:
        morceaux = urlsplit(texte)
        hote = morceaux.hostname
        morceaux.port  # lève ValueError si le port est invalide
    except ValueError:
        return ""
    if (morceaux.scheme not in ("http", "https") or not hote or morceaux.username is not None
            or morceaux.password is not None or morceaux.query or morceaux.fragment):
        return ""
    base = texte.rstrip("/")
    return base if base.endswith("/v1") else base + "/v1"


def url_depuis_env(profil, env=None):
    """URL de l'IA locale pour ce profil, ou "" : profil pc (rien ne change), option vide, adresse invalide.
    Une adresse invalide est dite au journal sans être recopiée."""
    if profil != "ha":
        return ""
    brut = (env if env is not None else os.environ).get("LLM_LOCAL_URL", "")
    url = url_valide(brut)
    if brut.strip() and not url:
        print("  ! llm_local_url ignorée : adresse http ou https attendue, sans identifiants ni paramètres")
    return url


class Sonde:
    """Le serveur répond-il ? Cache court, un seul sondage à la fois, jamais d'adresse dans les messages."""

    def __init__(self, url, transport=None, horloge=time.monotonic):
        self.url = url
        self._transport = transport  # httpx.MockTransport dans les tests
        self._horloge = horloge
        self._verrou = Lock()
        self._jusqu_a, self._joignable = 0.0, False
        self.modele = ""  # premier modèle annoncé par /models, pour les serveurs qui en exigent le nom exact

    def verifier(self, force=False):
        with self._verrou:
            maintenant = self._horloge()
            if not force and maintenant < self._jusqu_a:
                return self._joignable
            ok = self._sonder()
            self._joignable = ok
            self._jusqu_a = self._horloge() + (GARDE_JOIGNABLE if ok else GARDE_PANNE)
            return ok

    def signaler_panne(self):
        """Une demande vient d'échouer : ne plus croire le dernier « oui » pendant GARDE_PANNE secondes."""
        with self._verrou:
            self._joignable, self._jusqu_a = False, self._horloge() + GARDE_PANNE

    def _sonder(self):
        import httpx
        debut = time.monotonic()
        try:
            with httpx.Client(transport=self._transport, trust_env=False,
                              timeout=httpx.Timeout(DELAI_SONDE)) as client:
                r = client.get(f"{self.url}/models")
            donnees = r.json()
        except (httpx.HTTPError, ValueError):
            return False
        if r.status_code != 200 or time.monotonic() - debut > DELAI_SONDE or not isinstance(donnees, dict):
            return False
        modeles = donnees.get("data")
        if isinstance(modeles, list) and modeles and isinstance(modeles[0], dict) \
                and isinstance(modeles[0].get("id"), str):
            self.modele = modeles[0]["id"]
        return True


class CerveauLocalSurveille(A.Cerveau):
    """Le cerveau local d'assistant.py, avec un délai court et le compte des outils exécutés pendant la demande
    (le repli sur Claude n'est permis que s'il est à zéro)."""

    def __init__(self, cfg, ha, url, transport=None):
        import httpx
        super().__init__({**cfg, "llm_url": url}, ha)
        self.client = httpx.Client(transport=transport, trust_env=False,
                                   timeout=httpx.Timeout(DELAI_REPONSE, connect=DELAI_CONNEXION))
        self.outils_appeles = 0

    def executer_outil(self, nom, args, texte, noms, actions, musiques):
        self.outils_appeles += 1
        return super().executer_outil(nom, args, texte, noms, actions, musiques)

    def repondre(self, texte, mode="commande"):
        self.outils_appeles = 0
        return super().repondre(texte, mode)


class CerveauAvecRepli:
    """Se présente comme un Cerveau à l'Assistant : IA locale quand elle répond, Claude sinon."""

    NOM_LOCAL = "IA locale du PC"
    NOM_SECOURS = "Claude Haiku (repli)"

    def __init__(self, local, secours, sonde):
        self.local, self.secours, self.sonde = local, secours, sonde
        self.historiques = local.historiques
        secours.historiques = local.historiques  # une conversation, deux cerveaux : « éteins-la » survit au repli
        self._dernier = local
        self._signale = True  # dernier état écrit au journal : vrai = joignable

    # ---- ce que l'Assistant pose ou lit sur un cerveau
    @property
    def rappel_routine(self):
        return self.local.rappel_routine

    @rappel_routine.setter
    def rappel_routine(self, f):
        self.local.rappel_routine = self.secours.rappel_routine = f

    @property
    def rappel_liste(self):
        return self.local.rappel_liste

    @rappel_liste.setter
    def rappel_liste(self, f):
        self.local.rappel_liste = self.secours.rappel_liste = f

    @property
    def dernieres_actions(self):
        return self._dernier.dernieres_actions

    @property
    def dernier_nom(self):
        """Nom du cerveau qui a répondu en dernier, pour le journal et la réponse du serveur."""
        return self.NOM_LOCAL if self._dernier is self.local else self.NOM_SECOURS

    # ---- la demande
    def _noter(self, joignable, cause=None):
        if joignable != self._signale:
            self._signale = joignable
            print("  IA locale : de nouveau joignable" if joignable else
                  "  IA locale : injoignable, repli sur Claude" + (f" ({cause.__class__.__name__})" if cause else ""))

    def repondre(self, texte, mode="commande"):
        cause = None
        if self.sonde.verifier():
            if self.sonde.modele:
                self.local.cfg["llm_modele"] = self.sonde.modele
            try:
                reponse = self.local.repondre(texte, mode)
            except Exception as e:
                # Un outil déjà exécuté, ou pas de clé Claude pour reprendre : l'erreur remonte telle quelle.
                if self.local.outils_appeles or getattr(self.secours, "sans_cle", False):
                    raise
                self.sonde.signaler_panne()
                cause = e
            else:
                self._dernier = self.local
                self._noter(True)
                return reponse
        self._noter(False, cause)
        self._dernier = self.secours
        return self.secours.repondre(texte, mode)
