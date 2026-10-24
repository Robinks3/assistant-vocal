"""Météo marine du plan d'eau pour la page « Mer » de la tablette (0.22.0, demande du 22/10/2026).

Conditions de navigation du jour et des deux suivants sur le plan d'eau décrit par la section « mer » de
maison.json (nom, fuseau, points, modèles, sources). L'exemple fourni décrit la rade de Marseille.

Les trois points sont lus dans la configuration, tous EN MER (aucune autre position, jamais celle du
logement) : la tablette n'envoie rien. Sources publiques sans clé, aucune donnée personnelle : le
message est servi à toute connexion, chiffrée ou non, dans les deux profils (pc et ha). METEO_MER=0
dans l'environnement (poc/.env) l'éteint, avec le vent mesuré (vent_mesure.py).

Sources, une requête chacune pour les trois points (vagues régionales : une requête par lieu) :
  ARPEGE     Open-Meteo, modèle principal de la configuration (modele_principal) : vent, rafales, air,
              pluie, CAPE, potentiel de foudre, code météo, lever et coucher du soleil (point du soleil).
  AROME      Open-Meteo, modèle second de la configuration (modele_second) : second avis sur le vent,
              visibilité. Environ 60 h, null au-delà.
  MFWAM       Open-Meteo Marine : vagues des trois points (mailles exposées au large) et température
              de l'eau du point d'eau libre.
  régional    WaveWatch III, un lieu par point (rubrique « vagues_regional » de la configuration), pour les
              points où une maille côtière voit l'abri. Heures en UTC (« 20261023Z0800 »), un run par jour.
  station     une station à terre (rubrique « station ») : vent moyen et direction observés, en m/s
              convertis en nœuds. last_timestamp en ISO UTC (« 2026-10-22T18:54:07Z »).

Heures. Open-Meteo applique UN SEUL décalage à toute sa réponse (utc_offset_seconds, celui du moment
de l'appel) : vérifié le 22/10/2026, son « 2026-10-25T03:00 » vaut 01:00 UTC, soit 02:00 en heure locale
après le passage à l'heure d'hiver, et son lever du soleil du 26/10 est écrit une heure trop tard. Tout
est donc ramené à l'instant UTC (libellé moins utc_offset_seconds pour Open-Meteo, heure UTC pour
les vagues régionales), les sources sont appariées sur cet instant, puis chaque heure est écrite en vraie heure
locale du fuseau de la configuration (zoneinfo, tzdata dans requirements, à défaut la règle européenne). Conséquence : la nuit du
25/10, deux heures portent le libellé « 02:00 » (heure d'été puis heure d'hiver), dans l'ordre du temps.

Rafraîchissement, en mémoire seulement : Open-Meteo toutes les heures, vagues régionales toutes les 3 h, station
toutes les 10 min. Une source n'est relue que si la tablette demande et que son cache est périmé (aucun
sondage). Une seule lecture en vol, que les demandes simultanées attendent. Sources lues en parallèle,
chacune avec son délai (Open-Meteo 15 s, vagues régionales 20 s, station 8 s), httpx avec trust_env=False,
réponse lue en flux et plafonnée à 2 Mo. Une source en panne ne bloque pas les autres : son ancien
cache reste servi (sinon ses champs valent null) et son libellé apparaît dans « erreurs ». Panne gardée
60 s avant un nouvel essai. Une erreur n'est renvoyée que si ARPEGE n'a jamais pu être lu. Aucune
exception brute ne sort : seulement des textes écrits ici, avec la classe d'une erreur inattendue.

Une source dont la fiche porte "actif": false (modèle principal ou second, mfwam, vagues_regional et chacun de ses
lieux, station) n'est ni interrogée ni comptée en panne (0.35.0). Une clé absente vaut vrai. Désactiver le
modèle principal éteint tout le module : sans lui rien ne se sert.

Forme de « donnees » (contrat avec l'appli) :
  lu_a      heure de la dernière lecture d'ARPEGE, ISO avec décalage (« 2026-10-23T09:50:12+02:00 »)
  titre     titre de la section mer (0.35.0) : « titre » de la section, sinon son « nom », sinon « Mer »
  points    les 3 points dans l'ordre de POINTS, chacun {id, nom, vagues_source, heures}. vagues_source
            vaut « regional » si la source régionale a fourni au moins une heure du point, sinon « mfwam ».
            heures : toutes les heures d'ARPEGE depuis minuit aujourd'hui (heure locale), chacune
            {t, vent, rafales, dir, vent2, dir2, air, pluie, cape, foudre, code, visi, vagues, periode,
            dir_vagues}. t : « AAAA-MM-JJTHH:MM », heure locale sans décalage. vent, rafales, dir, air,
            pluie, cape, foudre (lightning_potential), code : ARPEGE. vent2, dir2, visi : AROME.
            vagues, periode, dir_vagues : source régionale pour les points qu'il couvre, MFWAM pour les autres et en
            repli à toute heure où la source régionale n'a rien. Vent en nœuds, directions d'où vient le vent ou
            la houle, en degrés entiers de 0 à 359.
  eau       température de l'eau MFWAM du point d'eau libre à l'heure en cours, null sinon
  soleil    [{jour, lever, coucher}] d'ARPEGE (point marqué soleil), heures locales « HH:MM », depuis aujourd'hui
  station   {nom, vent, dir, le} ou null si jamais lue. le : heure de la mesure, ISO avec décalage.
  erreurs   libellés des sources en panne (« AROME indisponible »), liste vide sinon
Arrondis : une décimale pour vent, vent2, rafales, air, pluie, foudre, vagues, periode, eau et le vent de
la station, entiers pour dir, dir2, cape, visi, dir_vagues et code. Absent ou non numérique : null, jamais 0.
"""
import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone

from urllib.parse import quote

import maison

# Plan d'eau, points et sources : section « mer » de la configuration de la maison (maison.json). Sans elle,
# ou avec "actif": false, le module est éteint (depuis_env rend None) et la capacité n'est pas annoncée.
MER = maison.CONFIG.get("mer") or {}
ACTIF = maison.actif(MER)
FUSEAU_MER = str(MER.get("fuseau") or maison.FUSEAU)
try:
    from zoneinfo import ZoneInfo
    LOCAL = ZoneInfo(FUSEAU_MER)
except Exception:  # ni base du système ni paquet tzdata : règle européenne (regle_europeenne)
    LOCAL = None

# Points en mer (identifiant, nom affiché, latitude, longitude), dans l'ordre du message. Les coordonnées
# restent du texte, recopié tel quel dans les adresses d'Open-Meteo.
POINTS = tuple((str(p["id"]), str(p["nom"]), str(p["lat"]), str(p["lon"])) for p in MER.get("points") or [])
# Point dont Open-Meteo donne le lever et le coucher du soleil, point dont MFWAM donne la température de l'eau.
INDICE_SOLEIL = next((i for i, p in enumerate(MER.get("points") or []) if p.get("soleil")), 0)
INDICE_EAU = next((i for i, p in enumerate(MER.get("points") or []) if p.get("eau")), None)
LATITUDES = ",".join(p[2] for p in POINTS)
LONGITUDES = ",".join(p[3] for p in POINTS)
_FUSEAU_URL = quote(FUSEAU_MER, safe="")
_PRINCIPAL = MER.get("modele_principal") or {}
_SECOND = MER.get("modele_second") or {}
NOM_PRINCIPAL = str(_PRINCIPAL.get("nom") or "prévision")
NOM_SECOND = str(_SECOND.get("nom") or "second modèle")
URL_PRINCIPAL = (f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDES}&longitude={LONGITUDES}"
            f"&models={_PRINCIPAL.get('modele', '')}&cell_selection=sea&timezone={_FUSEAU_URL}&wind_speed_unit=kn"
            "&forecast_days=3&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,temperature_2m,"
            "precipitation,cape,lightning_potential,weather_code&daily=sunrise,sunset")
URL_SECOND = (f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDES}&longitude={LONGITUDES}"
                f"&models={_SECOND.get('modele', '')}&cell_selection=sea&timezone={_FUSEAU_URL}&wind_speed_unit=kn"
                "&forecast_days=3&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility")
URL_MFWAM = (f"https://marine-api.open-meteo.com/v1/marine?latitude={LATITUDES}&longitude={LONGITUDES}"
             f"&cell_selection=sea&timezone={_FUSEAU_URL}&forecast_days=3"
             "&hourly=wave_height,wave_direction,wave_period,sea_surface_temperature")
_REGIONAL = MER.get("vagues_regional") or {}
URL_VAGUES_REGIONAL = str(_REGIONAL.get("url") or "")
# Lieux WaveWatch III de la source régionale : (point servi, lieu, nom court, libellé de panne).
def lieux_regional(mer):
    """Lieux WaveWatch III actifs d'une section « mer » : sans lieu, ou section régionale éteinte
    ("actif": false), aucun. Un lieu avec "actif": false n'est pas interrogé (0.35.0)."""
    p = mer.get("vagues_regional") if isinstance(mer.get("vagues_regional"), dict) else {}
    if not maison.source_active(p):
        return ()
    return tuple((str(l["point"]), str(l["lieu"]), str(l["nom"]), str(l["panne"]))
                 for l in p.get("lieux") or [] if maison.source_active(l))


VAGUES_REGIONAL = lieux_regional(MER)
URL_STATION = str((MER.get("station") or {}).get("url") or "")
NOM_STATION = str((MER.get("station") or {}).get("nom") or "la station")


def titre_mer(mer):
    """Titre par défaut de la section mer : « titre » s'il est donné, sinon « nom » (le plan d'eau), sinon
    « Mer » (0.35.0). Le titre propre à un point (« titre » du point) reste prioritaire côté appli."""
    for cle in ("titre", "nom"):
        v = mer.get(cle)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "Mer"


TITRE = titre_mer(MER)

DUREE_OPEN_METEO = 3600      # secondes de cache par source
DUREE_REGIONAL = 3 * 3600
DUREE_STATION = 600
DUREE_PANNE = 60             # secondes, panne d'une source gardée avant un nouvel essai
DELAI_OPEN_METEO = 15        # secondes, lecture et durée totale de l'appel
DELAI_REGIONAL = 20
DELAI_STATION = 8
DELAI_CONNEXION = 4
MARGE = 2                    # au-delà du délai, le thread d'une source n'est plus attendu
ATTENTE_MAX = max(DELAI_OPEN_METEO, DELAI_REGIONAL, DELAI_STATION) + MARGE + 1
TAILLE_MAX = 2_000_000       # octets par réponse
NOEUDS = {"m/s": 1.943844, "km/h": 0.539957, "kn": 1.0, "kt": 1.0, "mph": 0.868976}

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATE_REGIONAL = re.compile(r"(\d{4})(\d{2})(\d{2})Z(\d{2})(\d{2})")


class ErreurMer(Exception):
    """Erreur au texte lisible, écrit ici, à renvoyer telle quelle à la tablette."""


# ---------------------------------------------------------------- valeurs (fonctions pures)
def reel(v):
    """Nombre fini (booléens, textes, NaN et infinis refusés), sinon None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def dixieme(v):
    n = reel(v)
    return None if n is None else round(n, 1)


def entier(v):
    n = reel(v)
    return None if n is None else int(round(n))


def angle(v):
    """Direction en degrés entiers de 0 à 359 (360 devient 0)."""
    n = reel(v)
    return None if n is None else int(round(n)) % 360


def valeur_a(liste, i):
    return liste[i] if isinstance(liste, list) and i < len(liste) else None


# ---------------------------------------------------------------- heures
def regle_europeenne(instant):
    """Fuseau d'Europe centrale sans tzdata : heure d'été (+2) du dernier dimanche de mars au dernier dimanche
    d'octobre, à 01:00 UTC, sinon +1."""
    def dernier_dimanche(mois):
        fin = datetime(instant.year, mois + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        return fin - timedelta(days=(fin.weekday() + 1) % 7)
    ete = dernier_dimanche(3) <= instant < dernier_dimanche(10)
    return timezone(timedelta(hours=2 if ete else 1))


def heure_locale(instant):
    """Heure locale (datetime avec décalage) d'un instant (datetime avec fuseau)."""
    if LOCAL is not None:
        return instant.astimezone(LOCAL)
    return instant.astimezone(regle_europeenne(instant.astimezone(timezone.utc)))


def instant_open_meteo(libelle, decalage):
    """Instant UTC d'un libellé Open-Meteo « AAAA-MM-JJTHH:MM » écrit avec le décalage de sa réponse."""
    if not isinstance(libelle, str):
        return None
    try:
        local = datetime.strptime(libelle, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return local.replace(tzinfo=timezone(timedelta(seconds=decalage))).astimezone(timezone.utc)


def instant_regional(texte):
    """Instant UTC d'une heure de la source régionale « 20261023Z0800 » (2026-10-23 08:00 UTC), sinon None."""
    m = DATE_REGIONAL.fullmatch(texte) if isinstance(texte, str) else None
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    except ValueError:
        return None


def instant_iso(texte):
    """Instant d'un horodatage ISO (« 2026-10-22T18:54:07Z »), supposé UTC sans décalage, sinon None."""
    if not isinstance(texte, str) or not texte.strip():
        return None
    try:
        d = datetime.fromisoformat(texte.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def heure_minute(libelle, decalage):
    instant = instant_open_meteo(libelle, decalage)
    return heure_locale(instant).strftime("%H:%M") if instant else None


# ---------------------------------------------------------------- réduction de chaque source (pure)
CHAMPS_PRINCIPAL = {"wind_speed_10m": ("vent", dixieme), "wind_gusts_10m": ("rafales", dixieme),
               "wind_direction_10m": ("dir", angle), "temperature_2m": ("air", dixieme),
               "precipitation": ("pluie", dixieme), "cape": ("cape", entier),
               "lightning_potential": ("foudre", dixieme), "weather_code": ("code", entier)}
CHAMPS_SECOND = {"wind_speed_10m": ("vent2", dixieme), "wind_direction_10m": ("dir2", angle),
                   "visibility": ("visi", entier)}
CHAMPS_MFWAM = {"wave_height": ("vagues", dixieme), "wave_period": ("periode", dixieme),
                "wave_direction": ("dir_vagues", angle), "sea_surface_temperature": ("eau", dixieme)}


def series_open_meteo(brut, nom, champs):
    """Réponse Open-Meteo à trois points réduite à une série par point, dans l'ordre de POINTS. Une
    série est {instant UTC: {champ de sortie: valeur}}. ErreurMer si la forme est inattendue."""
    if not isinstance(brut, list) or len(brut) != len(POINTS):
        raise ErreurMer(f"réponse inattendue de {nom}")
    series = []
    for p in brut:
        horaire = p.get("hourly") if isinstance(p, dict) else None
        decalage = p.get("utc_offset_seconds") if isinstance(p, dict) else None
        if (not isinstance(horaire, dict) or not isinstance(horaire.get("time"), list)
                or isinstance(decalage, bool) or not isinstance(decalage, int) or abs(decalage) > 18 * 3600):
            raise ErreurMer(f"réponse inattendue de {nom}")
        serie = {}
        for i, libelle in enumerate(horaire["time"]):
            instant = instant_open_meteo(libelle, decalage)
            if instant is not None:
                serie[instant] = {sortie: convertir(valeur_a(horaire.get(champ), i))
                                  for champ, (sortie, convertir) in champs.items()}
        if not serie:
            raise ErreurMer(f"réponse de {nom} sans prévision")
        series.append(serie)
    return series


def soleil_de(p):
    """Lever et coucher du soleil, heure locale, d'après le daily d'un point Open-Meteo."""
    quotidien, decalage = p.get("daily"), p.get("utc_offset_seconds")
    if not isinstance(quotidien, dict) or not isinstance(quotidien.get("time"), list):
        return []
    sortie = []
    for i, jour in enumerate(quotidien["time"][:16]):
        if isinstance(jour, str) and DATE.fullmatch(jour):
            sortie.append({"jour": jour, "lever": heure_minute(valeur_a(quotidien.get("sunrise"), i), decalage),
                           "coucher": heure_minute(valeur_a(quotidien.get("sunset"), i), decalage)})
    return sortie


def reduire_principal(brut, nom):
    series = series_open_meteo(brut, nom, CHAMPS_PRINCIPAL)
    return {"points": series, "soleil": soleil_de(brut[INDICE_SOLEIL])}


def reduire_second(brut, nom):
    return series_open_meteo(brut, nom, CHAMPS_SECOND)


def reduire_mfwam(brut, nom):
    return series_open_meteo(brut, nom, CHAMPS_MFWAM)


def reduire_regional(brut, nom):
    """{instant UTC: {vagues, periode, dir_vagues}}, seulement les heures dont la hauteur est lisible :
    une heure sans hauteur est une heure où la source régionale n'a rien (repli MFWAM)."""
    if not isinstance(brut, dict) or brut.get("result") != "ok" or not isinstance(brut.get("timeseries"), list):
        raise ErreurMer(f"réponse inattendue de {nom}")
    serie = {}
    for e in brut["timeseries"]:
        instant = instant_regional(e.get("dateTime")) if isinstance(e, dict) else None
        if instant is not None and dixieme(e.get("hs")) is not None:
            serie[instant] = {"vagues": dixieme(e.get("hs")), "periode": dixieme(e.get("period")),
                              "dir_vagues": angle(e.get("dir"))}
    if not serie:
        raise ErreurMer(f"réponse de {nom} sans prévision")
    return serie


def reduire_station(brut, nom):
    """{nom, vent (nœuds), dir, le} d'après les cartes du snapshot, ErreurMer s'il n'y a pas de vent."""
    instantane = brut.get("snapshot") if isinstance(brut, dict) else None
    cartes = instantane.get("cards") if isinstance(instantane, dict) else None
    if not isinstance(cartes, list):
        raise ErreurMer(f"réponse inattendue de {nom}")
    par_cle = {c.get("key"): c for c in cartes if isinstance(c, dict) and isinstance(c.get("key"), str)}
    vitesse = par_cle.get("wind_speed", {})
    facteur = NOEUDS.get(str(vitesse.get("unit", "")).strip().lower())
    brute = reel(vitesse.get("value"))
    vent = round(brute * facteur, 1) if brute is not None and facteur is not None else None
    direction = angle(par_cle.get("wind_direction", {}).get("value"))
    if vent is None and direction is None:
        raise ErreurMer(f"réponse de {nom} sans vent")
    le = instant_iso(instantane.get("last_timestamp"))
    return {"nom": NOM_STATION, "vent": vent, "dir": direction,
            "le": heure_locale(le).isoformat(timespec="seconds") if le else None}


# ---------------------------------------------------------------- assemblage (fonction pure)
def assembler(principal, second, mfwam, vagues_regional, station, maintenant, lu_a=None, erreurs=()):
    """Champ « donnees » à partir des réductions de chaque source (None pour une source jamais lue).

    principal : {"points": [série x 3], "soleil": [...]}, obligatoire. second, mfwam : [série x 3] ou None.
    vagues_regional : {id de point: série}. station : dict ou None. maintenant : instant avec fuseau.
    Fonction pure, sans horloge ni réseau."""
    aujourdhui = heure_locale(maintenant).date()
    points = []
    for i, (ident, nom, _, _) in enumerate(POINTS):
        p_principal = principal["points"][i]
        p_second = second[i] if second else {}
        p_mfwam = mfwam[i] if mfwam else {}
        p_regional = (vagues_regional or {}).get(ident) or {}
        heures, par_regional = [], False
        for instant in sorted(p_principal):
            local = heure_locale(instant)
            if local.date() < aujourdhui:
                continue
            ic, ha = p_principal[instant], p_second.get(instant) or {}
            va = p_regional.get(instant)
            if va:
                par_regional = True
            else:
                va = p_mfwam.get(instant) or {}
            heures.append({"t": local.strftime("%Y-%m-%dT%H:%M"),
                           "vent": ic.get("vent"), "rafales": ic.get("rafales"), "dir": ic.get("dir"),
                           "vent2": ha.get("vent2"), "dir2": ha.get("dir2"),
                           "air": ic.get("air"), "pluie": ic.get("pluie"), "cape": ic.get("cape"),
                           "foudre": ic.get("foudre"), "code": ic.get("code"),
                           "visi": ha.get("visi"),
                           "vagues": va.get("vagues"), "periode": va.get("periode"),
                           "dir_vagues": va.get("dir_vagues")})
        points.append({"id": ident, "nom": nom, "vagues_source": "regional" if par_regional else "mfwam",
                       "heures": heures})
    heure = maintenant.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    eau = ((mfwam[INDICE_EAU] if mfwam and INDICE_EAU is not None else {}).get(heure) or {}).get("eau")
    soleil = [dict(s) for s in principal.get("soleil", []) if s["jour"] >= aujourdhui.isoformat()]
    return {"lu_a": lu_a, "titre": TITRE, "points": points, "eau": eau, "soleil": soleil,
            "station": dict(station) if station else None, "erreurs": list(erreurs)}


# ---------------------------------------------------------------- lecture des sources et cache
def lire_json(url, delai, nom, transport=None):
    """Appel bloquant (dans un thread) : JSON de la réponse, ou ErreurMer au texte lisible."""
    import httpx
    debut = time.monotonic()
    corps = bytearray()
    try:
        with httpx.Client(transport=transport, trust_env=False,
                          timeout=httpx.Timeout(delai, connect=DELAI_CONNEXION)) as client:
            with client.stream("GET", url) as r:
                if r.status_code != 200:
                    raise ErreurMer(f"{nom} a répondu {r.status_code}")
                longueur = r.headers.get("content-length", "")
                if longueur.isdigit() and int(longueur) > TAILLE_MAX:
                    raise ErreurMer(f"réponse de {nom} trop grande (plus de 2 Mo)")
                for bloc in r.iter_bytes():
                    corps += bloc
                    if len(corps) > TAILLE_MAX:
                        raise ErreurMer(f"réponse de {nom} trop grande (plus de 2 Mo)")
                    if time.monotonic() - debut > delai:
                        raise ErreurMer(f"{nom} ne répond pas (délai de {delai} s)")
    except httpx.TimeoutException:
        raise ErreurMer(f"{nom} ne répond pas (délai de {delai} s)") from None
    except httpx.HTTPError as e:
        raise ErreurMer(f"{nom} injoignable ({e.__class__.__name__})") from None
    try:
        return json.loads(bytes(corps))
    except (ValueError, RecursionError):
        raise ErreurMer(f"réponse illisible de {nom}") from None


class Source:
    """Une source lue par une requête. État en mémoire seulement : dernière réduction réussie (cache),
    son heure, et la dernière panne."""

    def __init__(self, nom, libelle, url, delai, duree, reduire, point=None):
        self.nom, self.libelle, self.url = nom, libelle, url
        self.delai, self.duree, self.reduire, self.point = delai, duree, reduire, point
        self.cache, self.t, self.lu_a = None, 0.0, None
        self.erreur, self.t_erreur = None, 0.0

    def en_panne_gardee(self, maintenant):
        return self.erreur is not None and maintenant - self.t_erreur < DUREE_PANNE

    def a_relire(self, maintenant):
        """Vrai si le cache manque ou est périmé, et qu'aucune panne de moins de 60 s n'est gardée."""
        if self.en_panne_gardee(maintenant):
            return False
        return self.cache is None or maintenant - self.t >= self.duree

    def lire(self, transport=None):
        return self.reduire(lire_json(self.url, self.delai, self.nom, transport), self.nom)


class MeteoMer:
    """Les six lectures et leur cache : une seule lecture en vol (les demandes simultanées l'attendent),
    sources périmées lues en parallèle, chacune avec son délai."""

    def __init__(self, horloge=time.monotonic, maintenant=None, transport=None, mer=None):
        self._horloge = horloge
        self._maintenant = maintenant or (lambda: datetime.now(timezone.utc))
        self._transport = transport  # httpx.MockTransport dans les tests
        # mer : section « mer » à lire pour les clés « actif » de chaque source (celle de la maison par défaut).
        lieux = VAGUES_REGIONAL if mer is None else lieux_regional(mer)
        mer = MER if mer is None else mer
        self.principal = Source(NOM_PRINCIPAL, f"{NOM_PRINCIPAL} indisponible", URL_PRINCIPAL, DELAI_OPEN_METEO,
                           DUREE_OPEN_METEO, reduire_principal)
        self.second = Source(NOM_SECOND, f"{NOM_SECOND} indisponible", URL_SECOND, DELAI_OPEN_METEO,
                               DUREE_OPEN_METEO, reduire_second)
        self.mfwam = Source("MFWAM", "Vagues MFWAM indisponibles", URL_MFWAM, DELAI_OPEN_METEO,
                            DUREE_OPEN_METEO, reduire_mfwam)
        self.vagues_regional = [Source(nom, libelle, URL_VAGUES_REGIONAL.format(lieu=lieu), DELAI_REGIONAL,
                                  DUREE_REGIONAL, reduire_regional, point=point)
                           for point, lieu, nom, libelle in lieux]
        self.station = Source("station", f"Station de {NOM_STATION} indisponible", URL_STATION, DELAI_STATION,
                              DUREE_STATION, reduire_station)
        # Une source avec "actif": false n'est ni interrogée ni comptée parmi les pannes (0.35.0). Son cache reste
        # vide, ce que l'assemblage sait déjà servir (seule la prévision principale est obligatoire).
        actives = {"principal": maison.source_active(mer.get("modele_principal")),
                   "second": maison.source_active(mer.get("modele_second")),
                   "mfwam": maison.source_active(mer.get("mfwam")),
                   "station": maison.source_active(mer.get("station"))}
        self.inactives = [nom for nom, ok in actives.items() if not ok]
        self.sources = [s for nom, s in (("principal", self.principal), ("second", self.second), ("mfwam", self.mfwam))
                        if actives[nom]] + self.vagues_regional + ([self.station] if actives["station"] else [])
        self._en_vol = None

    async def _lire_source(self, s):
        """Lit une source et range son résultat ou sa panne. Ne lève jamais."""
        try:
            reduit = await asyncio.wait_for(asyncio.to_thread(s.lire, self._transport), s.delai + MARGE)
        except asyncio.TimeoutError:
            erreur = f"{s.nom} ne répond pas (délai de {s.delai} s)"
        except ErreurMer as e:
            erreur = str(e)
        except Exception as e:  # le texte d'une exception n'est pas écrit ici : seulement sa classe
            erreur = f"{s.nom} : erreur inattendue ({e.__class__.__name__})"
        else:
            s.cache, s.t, s.erreur = reduit, self._horloge(), None
            s.lu_a = heure_locale(self._maintenant()).isoformat(timespec="seconds")
            return
        s.erreur, s.t_erreur = erreur, self._horloge()

    async def _lecture(self, sources):
        """Seul chemin vers le réseau : les sources demandées en parallèle, puis la place est libérée."""
        try:
            await asyncio.gather(*(self._lire_source(s) for s in sources))
        finally:
            self._en_vol = None

    async def donnees(self):
        """Champ « donnees » du message, ou ErreurMer si ARPEGE n'a jamais pu être lu. Lance la lecture
        des sources périmées s'il n'y en a pas déjà une en vol, et l'attend ATTENTE_MAX secondes au plus
        (au-delà, ce qui est en cache est servi et la lecture continue)."""
        if self._en_vol is None:
            maintenant = self._horloge()
            if self.principal.cache is None and self.principal.en_panne_gardee(maintenant):
                return self.servir()  # ARPEGE jamais lu et en panne : erreur sans lire les autres
            a_lire = [s for s in self.sources if s.a_relire(maintenant)]
            if a_lire:
                self._en_vol = asyncio.get_running_loop().create_task(self._lecture(a_lire))
                # Résultat lu même si toutes les demandes ont abandonné : pas d'avertissement asyncio.
                self._en_vol.add_done_callback(lambda t: t.cancelled() or t.exception())
        if self._en_vol is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._en_vol), ATTENTE_MAX)
            except asyncio.TimeoutError:
                pass
        return self.servir()

    def servir(self):
        if self.principal.cache is None:
            raison = self.principal.erreur or (f"{NOM_PRINCIPAL} ne répond pas encore" if self.principal in self.sources
                                          else f"{NOM_PRINCIPAL} est désactivé (actif: false)")
            raise ErreurMer(f"prévisions indisponibles : {raison}")
        return assembler(self.principal.cache, self.second.cache, self.mfwam.cache,
                         {s.point: s.cache for s in self.vagues_regional if s.cache is not None},
                         self.station.cache, self._maintenant(), self.principal.lu_a,
                         [s.libelle for s in self.sources if s.erreur is not None])

    def bilan(self):
        """Ligne de journal d'une réponse servie : sources lues, puis sources en panne avec leur raison."""
        servies = [s.nom for s in self.sources if s.cache is not None and s.erreur is None]
        ligne = f"prévisions servies ({', '.join(servies)})"
        en_panne = [s.erreur for s in self.sources if s.erreur is not None]
        return ligne + (f", en panne : {', '.join(en_panne)}" if en_panne else "")


def eteinte_par_env():
    """Vrai si METEO_MER vaut 0 (ou non, false, off) : éteint la mer et, depuis 0.27.2, le vent mesuré."""
    return os.getenv("METEO_MER", "1").strip().lower() in ("0", "non", "false", "off")


def libelle_sources(mer=None):
    """Sources interrogées, pour la ligne du démarrage : les noms des sources actives, dans l'ordre de lecture."""
    cfg = MER if mer is None else mer
    noms = []
    if maison.source_active(cfg.get("modele_principal")):
        noms.append(NOM_PRINCIPAL)
    if maison.source_active(cfg.get("modele_second")):
        noms.append(NOM_SECOND)
    if maison.source_active(cfg.get("mfwam")):
        noms.append("MFWAM")
    if lieux_regional(cfg):
        noms.append(str(cfg["vagues_regional"].get("source") or "vagues régionales"))
    if maison.source_active(cfg.get("station")):
        noms.append("station")
    return noms


def depuis_env():
    """MeteoMer, ou None sans section « mer » active dans maison.json, ou si METEO_MER vaut 0 (ou non, false,
    off), ou si la prévision principale est désactivée ("actif": false : sans elle rien ne se sert). Active par
    défaut dans les deux profils quand la section l'est."""
    if not ACTIF or not POINTS or eteinte_par_env() or not maison.source_active(MER.get("modele_principal")):
        return None
    return MeteoMer()
