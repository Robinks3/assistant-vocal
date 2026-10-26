"""Relais des données de santé pour l'écran de la tablette (0.19.0, demande du 22/10/2026).

Le service sante-api tourne sur un serveur-exemple, joignable seulement par
Tailscale. Le PC est sur le tailnet, l'appli Home Assistant non : le relais n'existe qu'en profil pc.

Configuration dans poc/.env :
  SANTE_JETON      jeton de sante-api. Absent : pas de relais, capacité « sante » fausse.
  SANTE_URL        facultative, par défaut `reseau.sante_url` de maison.json (dossier de configuration) (URL_DEFAUT).
  SANTE_PERSONNES  clés des connexions permises, séparées par des virgules, le propriétaire par défaut
                   (proprietaire.cle de maison.json). Clé d'un jeton fixe : le nom tiré de sa variable (la clé du
                   propriétaire pour SATELLITE_JETON, que portent son téléphone et la tablette du séjour, « camille » pour
                   SATELLITE_JETON_CAMILLE). Clé d'un téléphone appairé : « appareil:<id> », l'id de
                   appareils.json (voir acces.Appareils.identite), jamais son nom, choisi par l'appareil.
Le relais n'est servi que sur la liaison chiffrée (wss, port 8766), jamais sur le port en clair.

Le jeton ne part que vers une adresse Tailscale (100.64.0.0/10 ou fd7a:115c:a1e0::/48) : le nom est
résolu ici, puis la connexion vise l'adresse vérifiée. Un nom MagicDNS ne suffit pas, le DNS public
résout aussi les noms en ts.net (vers des serveurs de Tailscale) quand Tailscale est coupé. Et comme le
DNS public peut aussi rendre l'adresse en 100.x, le relais vérifie en plus que la route vers cette
adresse part de l'interface Tailscale du PC (adresse locale en 100.64.0.0/10), sinon le jeton reste ici.

Rien sur disque, rien dans les journaux : le résumé brut de sante-api (GET /api/resume?jours=8, lu en
flux, 2 Mo au plus) est réduit tout de suite, et seule la version réduite reste 10 minutes en
mémoire. Une panne est gardée 30 s, et il n'y a jamais deux appels à sante-api en même temps. Les
journaux du serveur ne disent que « santé : résumé servi (N jours) » ou l'erreur, jamais une valeur.

Datation, vérifiée dans serveur/agregats.mjs de sante-api : une journée va de minuit à minuit à
l'heure de l'appareil qui a mesuré (à défaut Europe/Paris), et une nuit est rattachée au jour de
son RÉVEIL, comme le fait Samsung Health. La nuit dernière est donc celle du jour d'aujourd'hui
(sante-api y ajoute les siestes du jour). Aujourd'hui se compte à l'heure de Paris, celle du service de santé.

Forme de « donnees » renvoyées à la tablette (tout nombre peut valoir null) :
  date        "AAAA-MM-JJ", aujourd'hui
  lu_a        "AAAA-MM-JJTHH:MM:SS", heure du serveur quand sante-api a été lu (cache de 10 min)
  aujourdhui  {date, renseigne, pas, distance_m, kcal_totales, kcal_actives, fc_repos, fc_min,
              fc_max, fc_moyenne, spo2_moyenne, spo2_min}
  nuit        {date, cette_nuit, minutes, stades: {nom: minutes}} : la nuit terminée aujourd'hui
              (cette_nuit vrai), sinon, avant la synchro du matin, celle d'hier avec sa propre date
              (cette_nuit faux), sinon date et minutes à null.
  jours       7 jours, du plus ancien à aujourd'hui, chacun {date, renseigne, pas, distance_m,
              kcal_totales, kcal_actives, sommeil_minutes, stades, fc_min, fc_max, fc_moyenne,
              fc_repos, spo2_moyenne, spo2_min}.
  seances     séances des 7 jours, de la plus récente à la plus ancienne (30 au plus), chacune
              {date, debut, fin, minutes, type, type_code, titre, kcal, distance_m, fc_moyenne,
              fc_max, fc_min, zones_minutes: {zone: minutes} ou null, trimp, vitesse_moyenne_kmh,
              vitesse_max_kmh, fc_courbe}. fc_courbe ne sert que pour la plus récente : au plus 60
              points [minute, bpm] sous-échantillonnés, null si la courbe manque ou a une forme
              inattendue. null pour toutes les autres.
Règles d'un jour : distance_m est la distance des seules activités suivies (distance_activites_m
de sante-api, Samsung Health n'écrit de distance que pendant une séance), pas la distance marchée
du jour. sante-api met 0 par défaut : pas, kcal_totales, kcal_actives (Samsung n'écrit que le
total) et sommeil_minutes à 0 deviennent null. renseigne est vrai si le jour a au moins une mesure
d'activité (pas, distance, calories, séance), de sommeil ou de cœur (FC ou SpO2), sinon tous ses
champs sont null.
"""
import asyncio
import ipaddress
import json
import math
import os
import re
import socket
import time
from datetime import date as Date, datetime, timedelta
from urllib.parse import urlsplit

import maison

# Nom MagicDNS du relais santé (maison.json du dossier de configuration, reseau.sante_url).
URL_DEFAUT = maison.reseau("sante_url")
# Le propriétaire (proprietaire.cle de maison.json), seul permis par défaut.
PERSONNES_DEFAUT = maison.CLE_PROPRIETAIRE
JOURS_DEMANDES = 8      # une marge d'un jour : la fenêtre de sante-api est glissante (maintenant - 8 x 24 h)
JOURS_SERIE = 7
DUREE_CACHE = 600       # secondes, résumé réduit
DUREE_ERREUR = 30       # secondes, panne gardée avant de réessayer
DELAI = 10              # secondes, lecture et durée totale de l'appel
DELAI_CONNEXION = 4
ATTENTE_MAX = DELAI + 1  # ce qu'attend une demande de la tablette, l'appel en vol continue au-delà
TAILLE_MAX = 2_000_000  # octets, réponse brute de sante-api
POINTS_COURBE = 60
SEANCES_MAX = 30
RESEAUX_TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))

CLE = re.compile(r"[a-z0-9_]{1,30}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CHAMPS_COEUR = ("fc_repos", "fc_min", "fc_max", "fc_moyenne", "spo2_moyenne", "spo2_min")
CHAMPS_SEANCE = ("minutes", "kcal", "distance_m", "fc_moyenne", "fc_max", "fc_min", "trimp",
                 "vitesse_moyenne_kmh", "vitesse_max_kmh")


class ErreurSante(Exception):
    """Erreur à renvoyer telle quelle à la tablette : son texte ne contient jamais de donnée."""


# ---------------------------------------------------------------- réduction (fonction pure)
def nombre(v):
    """Nombre fini (booléens et textes refusés), arrondi au dixième s'il n'est pas entier, sinon None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return int(v) if v.is_integer() else round(v, 1)
    return v


def positif(v):
    """Nombre strictement positif, sinon None : le 0 que sante-api met par défaut n'est pas une mesure."""
    n = nombre(v)
    return n if n is not None and n > 0 else None


def minutes_par_cle(v, entier=True, maxi=12):
    """{nom: minutes} défensif : un dict de nombres, ou une liste de {nom|stade|cle, minutes}."""
    paires = []
    if isinstance(v, dict):
        paires = list(v.items())
    elif isinstance(v, list):
        for e in v:
            if isinstance(e, dict):
                nom = e.get("nom", e.get("stade", e.get("cle")))
                paires.append((nom, e.get("minutes")))
    sortie = {}
    for nom, valeur in paires:
        n = nombre(valeur)
        if not isinstance(nom, str) or not CLE.fullmatch(nom) or n is None or n < 0:
            continue
        sortie[nom] = sortie.get(nom, 0) + n
        if len(sortie) >= maxi:
            break
    return {k: (round(n) if entier else round(n, 1)) for k, n in sortie.items()}


def courbe(v, maxi=POINTS_COURBE):
    """Courbe [[minute, bpm], ...] réduite à maxi points régulièrement espacés (premier et dernier
    gardés), ou None si elle manque ou si un seul point n'a pas la forme attendue."""
    if not isinstance(v, list) or not v:
        return None
    points = []
    for p in v:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return None
        t, bpm = nombre(p[0]), nombre(p[1])
        if t is None or bpm is None:
            return None
        points.append([t, round(bpm)])
    if len(points) > maxi:
        n = len(points)
        points = [points[round(i * (n - 1) / (maxi - 1))] for i in range(maxi)]
    return points


def texte(v, longueur):
    return v.strip()[:longueur] if isinstance(v, str) and v.strip() else None


def instant(iso):
    """Horodatage d'un début de séance pour le tri, 0 s'il est illisible."""
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return 0.0


def jour_reduit(date, j):
    """Champs d'un jour pour la série. j : jour de sante-api, ou None s'il manque."""
    j = j if isinstance(j, dict) else {}
    distance = nombre(j.get("distance_activites_m"))
    distance = distance if distance is not None and distance >= 0 else None
    sortie = {"date": date, "renseigne": False,
              "pas": positif(j.get("pas")), "distance_m": distance,
              "kcal_totales": positif(j.get("kcal_totales")), "kcal_actives": positif(j.get("kcal_actives"))}
    for champ in CHAMPS_COEUR:
        sortie[champ] = nombre(j.get(champ))
    sommeil = positif(j.get("sommeil_minutes"))
    sortie["sommeil_minutes"] = round(sommeil) if sommeil else None
    sortie["stades"] = minutes_par_cle(j.get("stades_minutes"))
    seances = j.get("seances")
    activite = (any(sortie[c] for c in ("pas", "distance_m", "kcal_totales", "kcal_actives"))
                or (isinstance(seances, list) and any(isinstance(s, dict) for s in seances)))
    coeur = any(sortie[c] is not None for c in CHAMPS_COEUR)
    if activite or sommeil or coeur:
        sortie["renseigne"] = True
        return sortie
    return {**{k: None for k in sortie}, "date": date, "renseigne": False, "stades": {}}


def seance_reduite(date, s, avec_courbe):
    sortie = {"date": date, "debut": texte(s.get("debut"), 40), "fin": texte(s.get("fin"), 40),
              "type": texte(s.get("type"), 40), "titre": texte(s.get("titre"), 80)}
    code = s.get("type_code")
    sortie["type_code"] = code if isinstance(code, int) and not isinstance(code, bool) else None
    for champ in CHAMPS_SEANCE:
        sortie[champ] = nombre(s.get(champ))
    zones = minutes_par_cle(s.get("zones_minutes"), entier=False, maxi=10)
    sortie["zones_minutes"] = zones or None
    sortie["fc_courbe"] = courbe(s.get("fc_courbe")) if avec_courbe else None
    return sortie


def nuit_de(serie):
    """La nuit terminée aujourd'hui, sinon celle d'hier (synchro du matin pas encore passée)."""
    for j, cette_nuit in ((serie[-1], True), (serie[-2], False)):
        if j["sommeil_minutes"]:
            return {"date": j["date"], "cette_nuit": cette_nuit, "minutes": j["sommeil_minutes"],
                    "stades": j["stades"]}
    return {"date": None, "cette_nuit": False, "minutes": None, "stades": {}}


def reduire(resume, aujourdhui, jours=JOURS_SERIE):
    """Résumé de sante-api ({"debut", "fin", "jours": [...]}) réduit à ce que l'écran affiche.

    aujourdhui : datetime.date ou "AAAA-MM-JJ". Fonction pure, sans horloge ni réseau, qui tolère
    n'importe quelle entrée (champs absents, nuls ou de forme inattendue)."""
    if isinstance(aujourdhui, str):
        aujourdhui = Date.fromisoformat(aujourdhui)
    dates = [(aujourdhui - timedelta(days=jours - 1 - i)).isoformat() for i in range(jours)]
    brut = resume.get("jours") if isinstance(resume, dict) else None
    par_date = {}
    for j in brut if isinstance(brut, list) else []:
        if isinstance(j, dict) and isinstance(j.get("date"), str) and DATE.fullmatch(j["date"][:10]):
            par_date[j["date"][:10]] = j
    serie = [jour_reduit(d, par_date.get(d)) for d in dates]

    seances = []
    for d in dates:
        liste = par_date.get(d, {}).get("seances")
        for s in liste if isinstance(liste, list) else []:
            if isinstance(s, dict):
                seances.append((d, s))
    seances.sort(key=lambda ds: (ds[0], instant(ds[1].get("debut"))), reverse=True)
    seances = [seance_reduite(d, s, avec_courbe=(i == 0)) for i, (d, s) in enumerate(seances[:SEANCES_MAX])]

    return {
        "date": dates[-1],
        "aujourdhui": {k: v for k, v in serie[-1].items() if k not in ("sommeil_minutes", "stades")},
        "nuit": nuit_de(serie),
        "jours": serie,
        "seances": seances,
    }


def jours_renseignes(donnees):
    return sum(1 for j in donnees.get("jours", []) if j.get("renseigne"))


# ---------------------------------------------------------------- qui peut demander
def personnes_permises():
    """Clés permises (SANTE_PERSONNES de poc/.env, le propriétaire par défaut). Variable vide : personne."""
    brut = os.getenv("SANTE_PERSONNES")
    brut = PERSONNES_DEFAUT if brut is None else brut
    return frozenset(p.strip().lower() for p in brut.split(",") if p.strip())


def refus(relais, chiffre, identite, permises):
    """Raison du refus du relais pour une connexion, ou None. Vérifié avant tout appel à sante-api."""
    if relais is None:
        return "santé non configurée sur ce serveur"
    if not chiffre:
        return "santé réservée à la liaison chiffrée (wss)"
    if not identite or identite.lower() not in permises:
        return "santé non permise pour cet appareil"
    return None


# ---------------------------------------------------------------- appel de sante-api et cache
def date_du_jour():
    """Aujourd'hui à l'heure de Paris (sante-api), ou à l'heure du PC sans tzdata."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris")).date()
    except Exception:
        return datetime.now().date()


def resoudre_dns(hote):
    return list(dict.fromkeys(i[4][0] for i in socket.getaddrinfo(hote, None, type=socket.SOCK_STREAM)))


def adresse_tailscale(hote, resoudre=resoudre_dns):
    """Adresse de hote, à condition que TOUTES ses adresses soient dans Tailscale, sinon ErreurSante."""
    try:
        adresses = [ipaddress.ip_address(a.split("%")[0]) for a in resoudre(hote)]
    except (OSError, ValueError, UnicodeError):
        raise ErreurSante(f"nom {hote} introuvable (Tailscale coupé ?), jeton gardé") from None
    if not adresses or not all(any(a in r for r in RESEAUX_TAILSCALE) for a in adresses):
        raise ErreurSante(f"{hote} ne mène pas dans Tailscale, jeton gardé")
    return min(adresses, key=lambda a: a.version)


def source_vers(ip, port):
    """Adresse locale que le système prendrait pour joindre ip (socket UDP, aucun paquet émis)."""
    famille = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    with socket.socket(famille, socket.SOCK_DGRAM) as s:
        s.connect((str(ip), port))
        return s.getsockname()[0]


def route_tailscale(ip, port, source=source_vers):
    """ErreurSante si la route vers ip ne part pas de l'interface Tailscale : Tailscale coupé, le jeton
    partirait en clair par la route par défaut."""
    try:
        locale = ipaddress.ip_address(str(source(ip, port)).split("%")[0])
    except (OSError, ValueError):
        raise ErreurSante("pas de route vers sante-api (Tailscale coupé ?), jeton gardé") from None
    if not any(locale in r for r in RESEAUX_TAILSCALE):
        raise ErreurSante("la route vers sante-api ne passe pas par Tailscale, jeton gardé")


class Relais:
    """Appels à sante-api : une seule demande en vol (les autres l'attendent), résultat réduit gardé
    DUREE_CACHE secondes en mémoire, panne gardée DUREE_ERREUR secondes."""

    def __init__(self, url, jeton, horloge=time.monotonic, transport=None, resoudre=resoudre_dns, source=source_vers):
        self.url = (url or URL_DEFAUT).strip().rstrip("/")
        self._jeton = jeton
        self._horloge = horloge
        self._transport = transport  # httpx.MockTransport dans les tests
        self._resoudre = resoudre
        self._source = source
        self._cache, self._t = None, 0.0
        self._erreur, self._t_erreur = None, 0.0
        self._en_vol = None

    def lire(self):
        """Appel bloquant (dans un thread) : résumé réduit, ou ErreurSante sans donnée dans le texte."""
        import httpx
        debut = time.monotonic()
        morceaux = urlsplit(self.url)
        hote, port = morceaux.hostname or "", morceaux.port or (443 if morceaux.scheme == "https" else 80)
        ip = adresse_tailscale(hote, self._resoudre)
        route_tailscale(ip, port, self._source)
        cible = (f"{morceaux.scheme}://{f'[{ip}]' if ip.version == 6 else ip}:{port}"
                 f"{morceaux.path.rstrip('/')}/api/resume")
        entetes = {"Authorization": f"Bearer {self._jeton}", "Host": f"{hote}:{port}"}
        corps = bytearray()
        try:
            with httpx.Client(transport=self._transport, trust_env=False,
                              timeout=httpx.Timeout(DELAI, connect=DELAI_CONNEXION)) as client:
                with client.stream("GET", cible, params={"jours": JOURS_DEMANDES}, headers=entetes) as r:
                    if r.status_code in (401, 403):
                        raise ErreurSante(f"jeton refusé par sante-api ({r.status_code})")
                    if r.status_code != 200:
                        raise ErreurSante(f"sante-api a répondu {r.status_code}")
                    longueur = r.headers.get("content-length", "")
                    if longueur.isdigit() and int(longueur) > TAILLE_MAX:
                        raise ErreurSante("réponse de sante-api trop grande (plus de 2 Mo)")
                    for bloc in r.iter_bytes():
                        corps += bloc
                        if len(corps) > TAILLE_MAX:
                            raise ErreurSante("réponse de sante-api trop grande (plus de 2 Mo)")
                        if time.monotonic() - debut > DELAI:
                            raise ErreurSante(f"sante-api ne répond pas (délai de {DELAI} s)")
        except httpx.TimeoutException:
            raise ErreurSante(f"sante-api ne répond pas (délai de {DELAI} s)") from None
        except httpx.HTTPError as e:
            raise ErreurSante(f"sante-api injoignable ({e.__class__.__name__})") from None
        try:
            brut = json.loads(bytes(corps))
        except ValueError:
            raise ErreurSante("réponse illisible de sante-api") from None
        if not isinstance(brut, dict) or not isinstance(brut.get("jours"), list):
            raise ErreurSante("réponse de sante-api sans liste de jours")
        return reduire(brut, date_du_jour())

    async def _appel(self):
        """Seul chemin vers sante-api : range le résultat ou l'erreur, puis libère la place."""
        try:
            donnees = await asyncio.to_thread(self.lire)
        except ErreurSante as e:
            self._erreur, self._t_erreur = str(e), self._horloge()
            raise
        except Exception as e:  # le texte d'une exception pourrait citer une valeur : seulement sa classe
            self._erreur, self._t_erreur = f"erreur inattendue ({e.__class__.__name__})", self._horloge()
            raise ErreurSante(self._erreur) from None
        else:
            donnees["lu_a"] = datetime.now().isoformat(timespec="seconds")
            self._cache, self._t, self._erreur = donnees, self._horloge(), None
            return donnees
        finally:
            self._en_vol = None

    async def resume(self):
        """Données réduites : cache de moins de 10 minutes et du même jour, sinon panne de moins de
        30 s, sinon l'appel en vol (lancé s'il n'y en a pas), attendu ATTENTE_MAX secondes au plus."""
        maintenant = self._horloge()
        if (self._cache is not None and maintenant - self._t < DUREE_CACHE
                and self._cache["date"] == date_du_jour().isoformat()):
            return self._cache
        if self._erreur is not None and maintenant - self._t_erreur < DUREE_ERREUR:
            raise ErreurSante(self._erreur)
        if self._en_vol is None:
            self._en_vol = asyncio.get_running_loop().create_task(self._appel())
            # Résultat lu même si toutes les demandes ont abandonné : pas d'avertissement asyncio.
            self._en_vol.add_done_callback(lambda t: t.cancelled() or t.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(self._en_vol), ATTENTE_MAX)
        except asyncio.TimeoutError:
            raise ErreurSante(f"sante-api ne répond pas (délai de {DELAI} s)") from None


def depuis_env(profil):
    """Relais configuré par SANTE_URL et SANTE_JETON (poc/.env), ou None : profil ha, ou jeton absent."""
    if profil != "pc":
        return None
    jeton = os.getenv("SANTE_JETON", "").strip()
    if not jeton:
        return None
    return Relais(os.getenv("SANTE_URL", "").strip() or URL_DEFAUT, jeton)
