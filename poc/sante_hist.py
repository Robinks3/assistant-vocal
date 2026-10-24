"""Historique de santé pour quatre onglets de la tablette (0.20.0, demande du 22/10/2026).

Onglets Tendances, Séances, Records et vue Jour. Le serveur du PC ne recalcule rien et ne demande
jamais l'historique complet à sante-api (le résumé sur 4000 jours bloquerait le service une dizaine
de secondes) : il lit le fichier que le tableau de bord HealthStats a déjà calculé sur le SERVEUR
(adresse `reseau.sante_donnees_url` de maison.json (dossier de configuration), chemin /dashboard/HealthStats/dashboard/data-auto.js),
servi par le portail derrière Tailscale Serve, sans jeton, avec ETag (304 sur If-None-Match),
régénéré au plus toutes les 30 min. Contenu : « window.HEALTHSTATS_AUTO = {JSON}; » ou « = null; ».
Code de référence : le service de santé.

Garde-fous de lecture, les mêmes que le relais (sante.py) : le nom est résolu ici, toutes ses
adresses doivent être dans Tailscale (sante.adresse_tailscale), la route doit partir de l'interface
Tailscale du PC (sante.route_tailscale, port 443), puis la connexion vise l'adresse vérifiée avec le
nom en SNI et en Host, certificat vérifié. trust_env=False, délai de 20 s (4 s pour se connecter),
Accept-Encoding: identity pour que le plafond de 16 Mo, lu en flux, porte sur les octets reçus, une
seule lecture en vol, au plus une lecture toutes les 10 min (requête conditionnelle ensuite), panne
gardée 30 s. L'analyse JSON se fait dans un thread et le contenu est réduit tout de suite en
structure compacte (Donnees), le brut est jeté, rien sur disque. Un jour ou une séance de forme
inattendue est écarté seul, sans faire rejeter le fichier. Fichier tronqué ou « null » : l'ancien
cache reste servi, nouvel essai après 30 s, et « perime » devient vrai quand la donnée a plus de
24 h (generatedAt du tableau de bord). Pas de sondage : une lecture seulement quand la tablette
demande, et un préchauffage en tâche de fond après un « sante » réussi si le cache est vide.

Analyse écrite d'un jour (onglet Séances) : GET /api/commentaire?date=AAAA-MM-JJ de sante-api, avec
SANTE_JETON et les mêmes garde-fous que le relais (404 normal s'il n'y en a pas). Cache date vers
analyse, 10 min si présente, 60 s si absente, 64 dates au plus, vidé au changement de jour. Texte
plafonné à 6 000 caractères, jamais dans les journaux. Une panne donne une seule ligne de journal,
« santé : analyse indisponible (<code HTTP ou classe de l'erreur>) », sans date ni texte.

Réglages facultatifs dans poc/.env : SANTE_SEUIL_PAS (6000 par défaut, choix du propriétaire), SANTE_SEUIL_NUIT_MIN (420),
SANTE_FC_MAX (FC max de référence pour les bornes des zones, sinon bornes à null). Même contrôle
d'accès que « sante » (sante.refus avant tout appel), capacité « sante_historique » par connexion.

Dates : tout est en datetime.date, aujourd'hui à l'heure de Paris (sante.date_du_jour), jamais par
soustraction de secondes (le 25/10/2026 dure 25 h). Semaines du lundi par weekday(). Une nuit est
rattachée au jour de son réveil, comme sante-api et le tableau de bord. Aujourd'hui est toujours
inclus et marqué « en_cours » : il est exclu de toutes les moyennes, mais compté dans les totaux de
sport, les nombres de séances et la SpO2 minimale. Le premier jour des données (premier_jour) est
le plus ancien jour renseigné : un jour qui n'a qu'une pesée ne le recule pas.

Valeurs d'un jour (Jour) : « sommeil » est le sommeil réel, somme des stades hors éveil (codes 1,
3 et 7 exclus) de la nuit la plus longue quand sleepStages existe, plafonnée à la durée de la nuit
si des stades se recouvrent. Sans stades, c'est sleepH, qui est le temps au lit (éveils et siestes
compris) : « sommeil_estime » est alors vrai, et ces jours-là sont écartés des records de sommeil.
« au_lit » est la durée de la nuit (dureeMin), sinon sleepH. « profond » est la somme du code 5,
null sans stades. Un jour sans donnée vaut null partout, jamais 0. La distance d'un jour renseigné
sans distance vaut 0 dans les moyennes (le tableau de bord n'écrit dist que si elle est non nulle).

Sports : clé et libellé selon la table SPORTS de ingest-auto.mjs, avec course (course
et course) et course (course et course_tapis) séparés, et les libellés accentués des
autres types de sante-api (TYPES_SEANCE de serveur/agregats.mjs). Ski et snowboard sont exclus de
la charge (TRIMP), comme dans ingest-auto.mjs. Une séance entièrement contenue dans une plus longue
du même jour est écartée partout (doublon d'enregistrement). Le contrôle des pics de FC se fait sur
le sommet de la courbe reçue, avant sa réduction.

Réponses (champ « donnees » de {"etat": <type>, "id", "donnees"} ou {"etat", "id", "erreur"}),
toutes avec aujourdhui, premier_jour, genere_le (generatedAt), lu_a et perime (booléen) :

sante_periode {jours: 7|30|90|365, au: "AAAA-MM-JJ" facultatif (entre premier_jour et aujourd'hui)}
  La période finit le jour « au » (aujourd'hui par défaut) : en_cours est alors faux partout si
  « au » est passé, et la période précédente est celle qui précède cette fenêtre.
  jours, du, au, granularite ("jour" pour 7 et 30, "semaine" pour 90 et 365),
  serie       {dates, en_cours, sommeil_minutes, au_lit_minutes, profond_minutes, pas, fc_moyenne,
               fc_min, sommeil_estime, seance}, une liste par champ, un élément par jour, null sans
               donnée (sommeil_estime null aussi un jour sans sommeil).
  courbes     même forme que serie en granularité jour. En semaine : {dates (lundis), en_cours,
               jours_renseignes, sommeil_minutes, au_lit_minutes, profond_minutes, pas, fc_moyenne,
               fc_min, jours_sommeil_estime, jours_seance}, moyennes des jours renseignés de la
               semaine dans la période.
  bilan       {du (premier jour disponible), au, jours (jours comptés dans les moyennes),
               jours_disponibles (jours de la période à partir de premier_jour, aujourd'hui compris),
               partielle (la période commence avant premier_jour), couverture (jours renseignés),
               jours_sommeil_estime, sommeil_minutes, au_lit_minutes, profond_minutes, pas,
               distance_m, fc_repos (moyenne des fc_min), fc_moyenne, spo2_min, sport}
               sport {minutes, seances, trimp, sans_fc, minutes_par_semaine, seances_par_semaine,
               trimp_par_semaine, par_sport {cle: {nom, minutes, seances, trimp, sans_fc}}}. trimp
               null quand aucune séance n'en a, toujours null pour ski et snowboard, exclus du total.
               Les valeurs par semaine sont rapportées aux jours disponibles : ce sont elles qui se
               comparent quand les deux périodes n'ont pas la même durée.
  avant       même forme que bilan pour la période précédente de même durée, réduite aux jours à
               partir de premier_jour (partielle vrai, du au premier jour réel). null si elle finit
               avant premier_jour, si moins de la moitié de ses jours disponibles sont renseignés,
               ou sous un plancher de jours renseignés (4 pour 7 jours, 7 pour 30, 14 pour 90, 28
               pour 365).
  sport       {granularite ("jour" pour 7, sinon "semaine"), groupes [{debut, jours, en_cours,
               minutes, seances, trimp, sans_fc, par_sport}], par_mois (même forme, 365 jours
               seulement, sinon null)}. debut : le jour, le lundi ou le premier du mois.
  hors_charge ["ski", "snowboard"]
sante_seances {jours: 7|30|90|365 (30 par défaut), sport: "tous" ou une clé de sport,
               au: "AAAA-MM-JJ" facultatif (fin de la fenêtre, aujourd'hui par défaut)}
  jours, sport, du, au, total {seances, minutes, distance_m, trimp, sans_fc},
  par_sport {cle: {nom, seances, minutes, distance_m, trimp, sans_fc}}, tronque (plus de 100
  séances dans la fenêtre). trimp : somme, null si aucune séance n'en a, toujours null pour ski et
  snowboard, exclus du total comme ailleurs.
  seances [100 au plus, de la plus récente à la plus ancienne] de la forme :
    {seance_id, date, debut_local ("AAAA-MM-JJTHH:MM", depuis detail.debut et son décalage, repli
     Europe/Paris), minutes, sport, nom, distance_m, allure_s_par_km (course seulement), fc_moyenne,
     fc_max, trimp, avec_fc}
sante_seance {seance_id}
  la forme d'une séance de la liste, plus fin_local, titre, type, type_code, kcal, fc_min,
  fc_echantillons, vitesse_moyenne_kmh, vitesse_max_kmh, dans_la_charge, zones_minutes {z1..z5} ou
  null, fc_max_reference (SANTE_FC_MAX ou null), zones_bornes {z1..z5: {nom, min_bpm, max_bpm}} ou
  null (z1 part de 0 bpm : comme zoneDe() de agregats.mjs, la zone 1 est tout ce qui est sous le
  seuil de la zone 2, à écrire « moins de N », et z5 n'a pas de max_bpm),
  fc_courbe [[minute, bpm]] (120 points au plus) ou null, analyse {texte, modele, genere} ou
  null. L'analyse du jour n'est gardée que si son seance_id est celui de la séance, ou si la séance
  est la seule du jour et que l'analyse ne désigne pas une autre séance connue.
sante_records {}
  depuis (premier_jour), seuils {pas, nuit_minutes}, records {nom: record ou null}, avec record
  {valeur, unite, puis date, ou du et au, ou lundi, puis seance_id et sport pour une séance,
  battu_le (date si le record date des 7 derniers jours, sinon null)}. Noms : serie_pas,
  journee_la_plus_active, meilleure_semaine_pas, seance_la_plus_longue, course_la_plus_longue,
  semaine_la_plus_sportive, seance_la_plus_chargee, zone5_la_plus_longue, meilleure_allure_5km,
  nuit_la_plus_longue, serie_nuits, sommeil_profond_le_plus_long, fc_la_plus_basse, fc_la_plus_haute.
  Les trois records de sommeil ne retiennent que les nuits avec stades (sommeil_estime faux).
  meilleure_allure_5km porte en plus distance_m (entier), la distance de la séance.
sante_jour {date: "AAAA-MM-JJ"}
  date, en_cours, renseigne, sommeil_minutes, au_lit_minutes, profond_minutes, pas, distance_m,
  kcal, fc_moyenne, fc_min, fc_max, spo2_min, sommeil_estime, seance, nuit {debut_local,
  au_lit_minutes, sommeil_minutes, profond_minutes, stades {nom: minutes}, seq [[décalage_min,
  durée_min, code]]} ou null, codes_stades {code: nom}, seances [forme de la liste, sans courbe].
  nuit.debut_local est à l'heure de Paris : sleepStages ne porte pas le décalage de la mesure.
"""
import asyncio
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import maison
import sante as SA
from sante import ErreurSante

# Fichier du tableau de bord santé (maison.json du dossier de configuration, reseau.sante_donnees_url).
URL_DONNEES = maison.reseau("sante_donnees_url")
PERIODES = (7, 30, 90, 365)
PLANCHERS_AVANT = {7: 4, 30: 7, 90: 14, 365: 28}  # jours renseignés au moins dans la période précédente
DUREE_CACHE = 600            # secondes entre deux lectures de data-auto.js
DUREE_ERREUR = 30            # secondes, panne gardée avant de réessayer
DELAI = 20                   # secondes, durée totale d'une lecture
DELAI_CONNEXION = 4
ATTENTE_MAX = DELAI + 1      # ce qu'attend une demande de la tablette, la lecture continue au-delà
TAILLE_MAX = 16 * 1024 * 1024
PERIME_APRES = 24 * 3600     # secondes depuis generatedAt
COMM_PRESENT = 600           # secondes, analyse trouvée
COMM_ABSENT = 60             # secondes, pas d'analyse ce jour-là
COMM_MAX = 64                # dates gardées
COMM_TEXTE_MAX = 6000        # caractères
COMM_TAILLE_MAX = 256_000    # octets, réponse de sante-api
COMM_DELAI = 10              # secondes, durée totale d'une lecture d'analyse
SEANCES_MAX = 100
POINTS_COURBE = 120
SEGMENTS_MAX = 600           # stades d'une nuit
SEUIL_PAS_DEFAUT = 6000
SEUIL_NUIT_DEFAUT = 420
ECART_PIC_FC = 15            # bpm au-dessus du sommet de la courbe : pic de capteur écarté
ALLURE_DISTANCE_MIN = 5000   # mètres

CODES_EVEIL = frozenset({1, 3, 7})
CODE_PROFOND = 5
# SleepSessionRecord.STAGE_TYPE_*, recopié de serveur/agregats.mjs (sante-api).
STADES = {0: "inconnu", 1: "eveille", 2: "endormi", 3: "hors_du_lit", 4: "leger", 5: "profond",
          6: "paradoxal", 7: "eveille_au_lit"}
# Zones de serveur/agregats.mjs : bornes basses et hautes en pourcentage de la FC max.
ZONES = (("z1", "récupération", 0, 60), ("z2", "endurance", 60, 70), ("z3", "tempo", 70, 80),
         ("z4", "seuil", 80, 90), ("z5", "anaérobie", 90, math.inf))
CLES_ZONES = tuple(z[0] for z in ZONES)
# Type brut de sante-api regroupé en (clé, libellé), d'après la table SPORTS de ingest-auto.mjs.
FAMILLES = {
    "course": ("course", "course"),
    "course": ("course", "course"),
    "patinage": ("course", "course"),
    "course": ("course", "Course à pied"),
    "course_tapis": ("course", "Course à pied"),
    "marche": ("marche", "Marche"),
    "randonnee": ("randonnee", "Randonnée"),
    "velo": ("velo", "Vélo"),
    "velo_appartement": ("velo", "Vélo"),
    "natation_piscine": ("natation", "Natation"),
    "natation_eau_libre": ("natation", "Natation"),
    "renforcement": ("musculation", "Musculation"),
    "halterophilie": ("musculation", "Musculation"),
    "ski": ("ski", "Ski"),
    "snowboard": ("snowboard", "Snowboard"),
}
# Libellés des autres types de TYPES_SEANCE (serveur/agregats.mjs), clé inchangée.
LIBELLES_TYPES = {
    "autre": "Autre", "badminton": "Badminton", "baseball": "Baseball", "basket": "Basket",
    "boot_camp": "Boot camp", "boxe": "Boxe", "gymnastique_suedoise": "Gymnastique suédoise",
    "cricket": "Cricket", "danse": "Danse", "elliptique": "Elliptique", "cours_collectif": "Cours collectif",
    "escrime": "Escrime", "football_americain": "Football américain", "football_australien": "Football australien",
    "frisbee": "Frisbee", "golf": "Golf", "respiration_guidee": "Respiration guidée", "gymnastique": "Gymnastique",
    "handball": "Handball", "hiit": "HIIT", "patinage_sur_glace": "Patinage sur glace",
    "arts_martiaux": "Arts martiaux", "pagaie": "Pagaie", "parapente": "Parapente", "pilates": "Pilates",
    "racquetball": "Racquetball", "escalade": "Escalade", "aviron": "Aviron", "rameur": "Rameur",
    "rugby": "Rugby", "voile": "Voile", "plongee": "Plongée", "raquettes": "Raquettes", "football": "Football",
    "softball": "Softball", "squash": "Squash", "escaliers": "Escaliers", "escaliers_machine": "Escaliers (machine)",
    "etirements": "Étirements", "surf": "Surf", "tennis_de_table": "Tennis de table", "tennis": "Tennis",
    "volleyball": "Volley-ball", "water_polo": "Water-polo", "fauteuil_roulant": "Fauteuil roulant", "yoga": "Yoga",
}
# Libellé du tableau de bord (champ t), seulement quand typeBrut manque.
LIBELLES_TABLEAU = {"course / course": "course", "course": "patinage", "Course à pied": "course",
                    "Marche": "marche", "Randonnée": "randonnee", "Vélo": "velo", "Natation": "natation_piscine",
                    "Musculation": "renforcement", "Ski": "ski"}
HORS_CHARGE = ("ski", "snowboard")
SPORTS_CONNUS = frozenset(c for c, _ in FAMILLES.values()) | frozenset(LIBELLES_TYPES)

JOURNAL = {"sante_periode": "période servie", "sante_seances": "séances servies",
           "sante_seance": "séance servie", "sante_records": "records servis", "sante_jour": "jour servi"}
TYPES = frozenset(JOURNAL)

ENTETE = re.compile(rb"\A\s*window\.HEALTHSTATS_AUTO\s*=\s*")
ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
DECALAGE = re.compile(r"([+-])(\d{2}):?(\d{2})")
ETAG = re.compile(r'(W/)?"[\x21\x23-\x7e]{1,200}"')


class AnalyseIndisponible(ErreurSante):
    """Panne de lecture d'une analyse. raison : code HTTP ou classe de l'erreur, jamais une donnée."""

    def __init__(self, raison):
        super().__init__(f"analyse indisponible ({raison})")
        self.raison = raison


# ---------------------------------------------------------------- structure compacte
@dataclass(slots=True)
class Nuit:
    debut: str | None   # horodatage ISO de sante-api (UTC)
    au_lit: int | None  # minutes, dureeMin
    seq: tuple          # ((décalage_min, durée_min, code), ...)


@dataclass(slots=True)
class Jour:
    renseigne: bool
    pas: int | None
    distance_m: int | None
    kcal: int | None
    sommeil: int | None   # minutes de sommeil réel, ou estimé par sleepH
    sommeil_estime: bool | None  # vrai sans stades (sleepH), null sans sommeil
    au_lit: int | None
    profond: int | None
    fc_moyenne: float | None
    fc_min: float | None
    fc_max: float | None
    spo2_min: float | None
    nuit: Nuit | None
    seances: tuple        # identifiants, dans l'ordre du jour


@dataclass(slots=True)
class Seance:
    id: str
    date: Date
    debut: str | None
    fin: str | None
    decalage: str | None
    t0: float | None
    t1: float | None
    minutes: int | None
    type_brut: str | None
    type_code: int | None
    sport: str
    nom: str
    titre: str | None
    distance_m: int | None
    kcal: int | None
    fc_moyenne: float | None
    fc_min: float | None
    fc_max: float | None
    fc_n: int | None
    trimp: float | None
    zones: dict | None
    vit_moy: float | None
    vit_max: float | None
    courbe: list | None
    fc_sommet: float | None  # plus haut point de la courbe reçue, avant réduction

    @property
    def avec_fc(self):
        return bool(self.courbe) or self.fc_moyenne is not None

    @property
    def dans_la_charge(self):
        return self.sport not in HORS_CHARGE


@dataclass(slots=True)
class Donnees:
    genere: str | None
    genere_ts: float | None
    premier: Date
    jours: dict           # Date vers Jour
    seances: dict         # identifiant vers Seance
    lu_a: str = ""
    lu_ts: float = 0.0


# ---------------------------------------------------------------- réduction (fonctions pures)
def reel(v):
    """Nombre fini tel quel (booléens et textes refusés), sinon None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if math.isfinite(v) else None


def positif(v):
    n = reel(v)
    return n if n is not None and n > 0 else None


def arrondi(x, chiffres=0):
    """Arrondi comme Math.round de JavaScript (0,5 vers le haut), entier quand il tombe juste."""
    if x is None:
        return None
    if chiffres == 0:
        return int(math.floor(x + 0.5))
    p = 10 ** chiffres
    r = math.floor(x * p + 0.5) / p
    return int(r) if r.is_integer() else r


def entier_positif(v):
    n = positif(v)
    return arrondi(n) if n is not None else None


def instant(iso):
    """Horodatage ISO vers secondes depuis l'époque, ou None (sans fuseau : UTC)."""
    if not isinstance(iso, str) or not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    try:
        return t.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def paris():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Paris")
    except Exception:
        return None  # astimezone(None) : heure du PC


def fuseau(decalage):
    """Fuseau du décalage porté par l'enregistrement (« +02:00 »), sinon Europe/Paris."""
    if decalage == "Z":
        return timezone.utc
    m = DECALAGE.fullmatch(decalage or "")
    if m:
        minutes = int(m[2]) * 60 + int(m[3])
        if minutes <= 14 * 60:
            return timezone(timedelta(minutes=-minutes if m[1] == "-" else minutes))
    return paris()


def heure_locale(iso, decalage=None):
    """« AAAA-MM-JJTHH:MM » à l'heure locale de la mesure (Europe/Paris sans décalage), ou None."""
    t = instant(iso)
    if t is None:
        return None
    try:
        return datetime.fromtimestamp(t, timezone.utc).astimezone(fuseau(decalage)).strftime("%Y-%m-%dT%H:%M")
    except (OverflowError, OSError, ValueError):
        return None


def famille(type_brut, libelle):
    """(clé, libellé) du sport d'une séance. libelle : champ t du tableau de bord, de type quelconque."""
    if type_brut in FAMILLES:
        return FAMILLES[type_brut]
    if not type_brut and isinstance(libelle, str) and libelle in LIBELLES_TABLEAU:
        return FAMILLES[LIBELLES_TABLEAU[libelle]]
    if type_brut in LIBELLES_TYPES:
        return type_brut, LIBELLES_TYPES[type_brut]
    if type_brut:  # type inconnu de sante-api (« type_99 ») ou ajouté depuis
        return type_brut, type_brut.replace("_", " ").capitalize()
    return "autre", "Autre"


def nuit_compacte(v):
    if not isinstance(v, dict):
        return None
    seq = []
    brut = v.get("seq")
    for p in brut if isinstance(brut, list) else []:
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            continue
        decalage, duree, code = reel(p[0]), reel(p[1]), reel(p[2])
        if decalage is None or duree is None or code is None or duree < 0 or code != int(code) \
                or int(code) not in STADES:
            continue
        seq.append((arrondi(decalage), arrondi(duree), int(code)))
        if len(seq) >= SEGMENTS_MAX:
            break
    debut = v.get("start") if isinstance(v.get("start"), str) and instant(v.get("start")) is not None else None
    au_lit = entier_positif(v.get("dureeMin"))
    if not seq and au_lit is None:
        return None
    return Nuit(debut[:40] if debut else None, au_lit, tuple(seq))


def jour_compact(j, seances):
    """Jour du tableau de bord réduit. seances : identifiants déjà retenus pour ce jour."""
    j = j if isinstance(j, dict) else {}
    dist = reel(j.get("dist"))
    sommeil_h = positif(j.get("sleepH"))
    nuit = nuit_compacte(j.get("sleepStages"))
    sommeil = au_lit = profond = estime = None
    if nuit is not None:
        au_lit = nuit.au_lit
        dort = sum(du for _, du, code in nuit.seq if code not in CODES_EVEIL)
        if dort > 0:
            sommeil = min(dort, au_lit) if au_lit else dort  # des stades qui se recouvrent
            profond = min(sum(du for _, du, code in nuit.seq if code == CODE_PROFOND), sommeil)
            estime = False
    if sommeil is None and sommeil_h:
        sommeil, estime = arrondi(sommeil_h * 60), True  # temps au lit, éveils et siestes compris
    if au_lit is None and sommeil_h:
        au_lit = arrondi(sommeil_h * 60)
    sortie = Jour(
        renseigne=False,
        pas=entier_positif(j.get("steps")),
        distance_m=arrondi(dist * 1000) if dist is not None and dist >= 0 else None,
        kcal=entier_positif(j.get("kcal")),
        sommeil=sommeil, sommeil_estime=estime, au_lit=au_lit, profond=profond,
        fc_moyenne=arrondi(positif(j.get("hr")), 1), fc_min=arrondi(positif(j.get("hrMin")), 1),
        fc_max=arrondi(positif(j.get("hrMax")), 1), spo2_min=arrondi(positif(j.get("spo2Min")), 1),
        nuit=nuit, seances=tuple(seances))
    sortie.renseigne = bool(seances) or any(
        v is not None for v in (sortie.pas, sortie.distance_m, sortie.kcal, sortie.sommeil, sortie.fc_moyenne,
                                sortie.fc_min, sortie.fc_max, sortie.spo2_min))
    return sortie


def sommet(courbe_brute):
    """Plus haut bpm d'une courbe [[minute, bpm], ...] reçue, avant toute réduction, ou None."""
    if SA.courbe(courbe_brute, maxi=len(courbe_brute) if isinstance(courbe_brute, list) else 1) is None:
        return None
    return max(reel(p[1]) for p in courbe_brute)


def seance_compacte(date, s, rang):
    """Séance du tableau de bord (sessions[] d'un jour) réduite, ou None si ce n'est pas un objet."""
    if not isinstance(s, dict):
        return None
    d = s.get("detail") if isinstance(s.get("detail"), dict) else {}
    ident = d.get("id")
    ident = ident if isinstance(ident, str) and ID.fullmatch(ident) else f"{date.isoformat()}-{rang}"
    type_brut = d.get("typeBrut") if isinstance(d.get("typeBrut"), str) and SA.CLE.fullmatch(d["typeBrut"]) else None
    sport, nom = famille(type_brut, s.get("t"))
    debut, fin = SA.texte(d.get("debut"), 40), SA.texte(d.get("fin"), 40)
    t0, t1 = instant(debut), instant(fin)
    minutes = entier_positif(s.get("min"))
    if minutes is None and t0 is not None and t1 is not None and t1 > t0:
        minutes = arrondi((t1 - t0) / 60)
    km = positif(s.get("km"))
    code = d.get("typeCode")
    decalage = d.get("decalage")
    decalage = decalage if isinstance(decalage, str) and (decalage == "Z" or DECALAGE.fullmatch(decalage)) else None
    zones = {k: v for k, v in SA.minutes_par_cle(d.get("zones"), entier=False, maxi=10).items() if k in CLES_ZONES}
    trimp = reel(d.get("trimp"))
    pointe = sommet(d.get("fcCourbe"))
    return Seance(
        id=ident, date=date, debut=debut, fin=fin, decalage=decalage, t0=t0, t1=t1, minutes=minutes,
        type_brut=type_brut, type_code=code if isinstance(code, int) and not isinstance(code, bool) else None,
        sport=sport, nom=nom, titre=SA.texte(d.get("titre"), 80),
        distance_m=arrondi(km * 1000) if km else None, kcal=entier_positif(s.get("cal")),
        fc_moyenne=arrondi(positif(d.get("fcMoy")) or positif(s.get("hr")), 1),
        fc_min=arrondi(positif(d.get("fcMin")), 1), fc_max=arrondi(positif(d.get("fcMax")), 1),
        fc_n=entier_positif(d.get("fcN")), trimp=arrondi(trimp, 1) if trimp is not None and trimp >= 0 else None,
        zones=zones or None, vit_moy=arrondi(positif(d.get("vitMoy")), 1),
        vit_max=arrondi(positif(d.get("vitMax")), 1), courbe=SA.courbe(d.get("fcCourbe"), maxi=POINTS_COURBE),
        fc_sommet=arrondi(pointe, 1))


def duree_s(s):
    if s.t0 is not None and s.t1 is not None and s.t1 > s.t0:
        return s.t1 - s.t0
    return (s.minutes or 0) * 60


def sans_emboitees(seances):
    """Écarte une séance entièrement contenue dans une plus longue du même jour (ou identique à
    une autre), puis remet le jour dans l'ordre chronologique."""
    gardees = []
    for s in sorted(seances, key=lambda s: -duree_s(s)):  # tri stable : à durée égale, la première reste
        if s.t0 is not None and s.t1 is not None and any(
                g.t0 is not None and g.t1 is not None and g.t0 <= s.t0 and s.t1 <= g.t1 for g in gardees):
            continue
        gardees.append(s)
    rang = {id(s): i for i, s in enumerate(seances)}
    return sorted(gardees, key=lambda s: (s.t0 is None, s.t0 or 0, rang[id(s)]))


def seances_lisibles(date, liste):
    """Séances d'un jour réduites. Une séance de forme inattendue est écartée seule."""
    sortie = []
    for i, s in enumerate(liste if isinstance(liste, list) else []):
        try:
            sc = seance_compacte(date, s, i)
        except Exception:  # forme imprévue : la séance seule est perdue, jamais le fichier
            continue
        if sc is not None:
            sortie.append(sc)
    return sortie


def reduire(brut, lu_a="", lu_ts=0.0):
    """Contenu JSON de data-auto.js réduit en Donnees. Fonction pure, sans horloge ni réseau, qui
    tolère des champs absents ou de forme inattendue. ErreurSante s'il n'y a aucun jour."""
    if not isinstance(brut, dict) or not isinstance(brut.get("days"), dict):
        raise ErreurSante("historique sans jours")
    jours, seances = {}, {}
    for cle, j in brut["days"].items():
        if not isinstance(cle, str) or not SA.DATE.fullmatch(cle) or not isinstance(j, dict):
            continue
        try:
            date = Date.fromisoformat(cle)
            retenues, ids = [], []
            for s in sans_emboitees(seances_lisibles(date, j.get("sessions"))):
                if s.id not in seances and s.id not in ids:  # un identifiant déjà vu est un doublon
                    retenues.append(s)
                    ids.append(s.id)
            jour = jour_compact(j, ids)
        except Exception:  # forme imprévue : le jour seul est écarté, jamais le fichier
            continue
        seances.update((s.id, s) for s in retenues)
        jours[date] = jour
    if not jours:
        raise ErreurSante("historique sans jours")
    renseignes = [x for x, j in jours.items() if j.renseigne]
    premier = min(renseignes) if renseignes else min(jours)  # une pesée seule ne recule pas le début
    genere = SA.texte(brut.get("generatedAt"), 40)
    return Donnees(genere=genere, genere_ts=instant(genere), premier=premier, jours=jours, seances=seances,
                   lu_a=lu_a, lu_ts=lu_ts)


def reduire_fichier(corps, lu_a="", lu_ts=0.0):
    """Octets de data-auto.js (« window.HEALTHSTATS_AUTO = {...}; ») réduits en Donnees."""
    m = ENTETE.match(corps)
    if not m:
        raise ErreurSante("historique illisible (forme inattendue)")
    texte = corps[m.end():].rstrip().rstrip(b";").rstrip()
    if texte == b"null":
        raise ErreurSante("historique vide (tableau de bord sans données)")
    try:
        brut = json.loads(texte)
    except (ValueError, RecursionError):
        raise ErreurSante("historique illisible (fichier tronqué ?)") from None
    return reduire(brut, lu_a, lu_ts)


# ---------------------------------------------------------------- calculs (fonctions pures)
SERIE = ("sommeil_minutes", "au_lit_minutes", "profond_minutes", "pas", "fc_moyenne", "fc_min")
CHAMPS_JOUR = SERIE + ("sommeil_estime", "seance")


def jours_entre(debut, fin):
    return [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]


def lundi(x):
    return x - timedelta(days=x.weekday())


def valeurs(d, x):
    """Champs de série d'une date, tous à null pour un jour sans donnée."""
    j = d.jours.get(x)
    if j is None or not j.renseigne:
        return dict.fromkeys(CHAMPS_JOUR)
    return {"sommeil_minutes": j.sommeil, "au_lit_minutes": j.au_lit, "profond_minutes": j.profond,
            "pas": j.pas, "fc_moyenne": j.fc_moyenne, "fc_min": j.fc_min, "sommeil_estime": j.sommeil_estime,
            "seance": bool(j.seances)}


def serie(d, dates, aujourdhui):
    lignes = [valeurs(d, x) for x in dates]
    return {"dates": [x.isoformat() for x in dates], "en_cours": [x == aujourdhui for x in dates],
            **{k: [v[k] for v in lignes] for k in CHAMPS_JOUR}}


def moyenne(valeurs_, chiffres=0):
    v = [x for x in valeurs_ if x is not None]
    return arrondi(sum(v) / len(v), chiffres) if v else None


def chiffres_de(champ):
    return 1 if champ.startswith("fc") else 0


def groupes(dates, cle):
    sortie = {}
    for x in dates:
        sortie.setdefault(cle(x), []).append(x)
    return sortie


def compte(vus):
    """Nombre de vrais, ou null si aucune valeur n'est connue."""
    return sum(1 for v in vus if v) if any(v is not None for v in vus) else None


def courbes_semaine(d, dates, aujourdhui):
    sortie = {k: [] for k in ("dates", "en_cours", "jours_renseignes") + SERIE
              + ("jours_sommeil_estime", "jours_seance")}
    for l, ds in groupes(dates, lundi).items():
        complets = [valeurs(d, x) for x in ds if x != aujourdhui]
        renseignes = [x for x in ds if x != aujourdhui and d.jours.get(x) and d.jours[x].renseigne]
        sortie["dates"].append(l.isoformat())
        sortie["en_cours"].append(aujourdhui in ds)
        sortie["jours_renseignes"].append(len(renseignes))
        for k in SERIE:
            sortie[k].append(moyenne([v[k] for v in complets], chiffres_de(k)))
        sortie["jours_sommeil_estime"].append(compte([v["sommeil_estime"] for v in complets]))
        sortie["jours_seance"].append(compte([valeurs(d, x)["seance"] for x in ds]))
    return sortie


def seances_de(d, dates):
    return [d.seances[i] for x in dates if x in d.jours for i in d.jours[x].seances]


def par_semaine(total, jours, chiffres=0):
    return arrondi(total * 7 / jours, chiffres) if total is not None and jours else None


def sport_total(seances, jours_disponibles=None):
    """Totaux de sport. Avec jours_disponibles, ajoute les valeurs ramenées à une semaine."""
    par = {}
    for s in seances:
        p = par.setdefault(s.sport, {"nom": s.nom, "minutes": 0, "seances": 0, "trimp": None, "sans_fc": 0})
        p["minutes"] += s.minutes or 0
        p["seances"] += 1
        p["sans_fc"] += 0 if s.avec_fc else 1
        if s.dans_la_charge and s.trimp is not None:
            p["trimp"] = arrondi((p["trimp"] or 0) + s.trimp, 1)
    charge = [s.trimp for s in seances if s.dans_la_charge and s.trimp is not None]
    sortie = {"minutes": sum(s.minutes or 0 for s in seances), "seances": len(seances),
              "trimp": arrondi(sum(charge), 1) if charge else None,
              "sans_fc": sum(1 for s in seances if not s.avec_fc)}
    if jours_disponibles is not None:
        sortie.update({"minutes_par_semaine": par_semaine(sortie["minutes"], jours_disponibles),
                       "seances_par_semaine": par_semaine(sortie["seances"], jours_disponibles, 1),
                       "trimp_par_semaine": par_semaine(sortie["trimp"], jours_disponibles)})
    sortie["par_sport"] = dict(sorted(par.items(), key=lambda kv: -kv[1]["minutes"]))
    return sortie


def sport_groupes(d, dates, aujourdhui, cle):
    return [{"debut": c.isoformat(), "jours": len(ds), "en_cours": aujourdhui in ds,
             **sport_total(seances_de(d, ds))} for c, ds in groupes(dates, cle).items()]


def bilan(d, dates, aujourdhui):
    """Bilan des jours de dates à partir de premier_jour : moyennes sur les jours finis (aujourd'hui
    exclu), totaux de sport et SpO2 minimale sur tous les jours disponibles."""
    dispo = [x for x in dates if x >= d.premier]
    complets = [x for x in dispo if x != aujourdhui]
    rens = [d.jours[x] for x in complets if x in d.jours and d.jours[x].renseigne]
    spo2 = [d.jours[x].spo2_min for x in dispo if x in d.jours and d.jours[x].spo2_min is not None]
    return {"du": (dispo or dates)[0].isoformat(), "au": dates[-1].isoformat(), "jours": len(complets),
            "jours_disponibles": len(dispo), "partielle": len(dispo) < len(dates), "couverture": len(rens),
            "jours_sommeil_estime": sum(1 for j in rens if j.sommeil_estime),
            "sommeil_minutes": moyenne([j.sommeil for j in rens]), "au_lit_minutes": moyenne([j.au_lit for j in rens]),
            "profond_minutes": moyenne([j.profond for j in rens]), "pas": moyenne([j.pas for j in rens]),
            "distance_m": moyenne([j.distance_m or 0 for j in rens]),
            "fc_repos": moyenne([j.fc_min for j in rens], 1), "fc_moyenne": moyenne([j.fc_moyenne for j in rens], 1),
            "spo2_min": min(spo2) if spo2 else None, "sport": sport_total(seances_de(d, dispo), len(dispo))}


def dates_periode(aujourdhui, jours):
    du = aujourdhui - timedelta(days=jours - 1)
    return [du + timedelta(days=i) for i in range(jours)]


def bilan_precedent(d, jours, debut_courant, aujourdhui):
    """Bilan de la période précédente de même durée, réduit aux jours à partir de premier_jour, ou
    None : finie avant premier_jour, moins de la moitié des jours disponibles renseignés, ou sous le
    plancher de PLANCHERS_AVANT."""
    precedentes = dates_periode(debut_courant - timedelta(days=1), jours)
    if precedentes[-1] < d.premier:
        return None
    avant = bilan(d, precedentes, aujourdhui)
    if avant["couverture"] < PLANCHERS_AVANT.get(jours, 1) or avant["couverture"] * 2 < avant["jours_disponibles"]:
        return None
    return avant


def periode(d, jours, aujourdhui, au=None):
    """Période de jours jours qui finit le jour au (aujourd'hui par défaut, déjà validé)."""
    dates = dates_periode(au or aujourdhui, jours)
    granularite = "jour" if jours <= 30 else "semaine"
    courbes = ({"granularite": "jour", **serie(d, dates, aujourdhui)} if granularite == "jour"
               else {"granularite": "semaine", **courbes_semaine(d, dates, aujourdhui)})
    return {
        "jours": jours, "du": dates[0].isoformat(), "au": dates[-1].isoformat(), "granularite": granularite,
        "serie": serie(d, dates, aujourdhui), "courbes": courbes, "bilan": bilan(d, dates, aujourdhui),
        "avant": bilan_precedent(d, jours, dates[0], aujourdhui),
        "sport": {"granularite": "jour" if jours == 7 else "semaine",
                  "groupes": sport_groupes(d, dates, aujourdhui, (lambda x: x) if jours == 7 else lundi),
                  "par_mois": (sport_groupes(d, dates, aujourdhui, lambda x: x.replace(day=1))
                               if jours == 365 else None)},
        "hors_charge": list(HORS_CHARGE),
    }


def allure(s):
    """Secondes par kilomètre d'une course, sur la durée réelle (fin moins début)."""
    if s.sport != "course" or not s.distance_m:
        return None
    duree = duree_s(s)
    return arrondi(duree / (s.distance_m / 1000)) if duree > 0 else None


def ligne_seance(s):
    return {"seance_id": s.id, "date": s.date.isoformat(), "debut_local": heure_locale(s.debut, s.decalage),
            "minutes": s.minutes, "sport": s.sport, "nom": s.nom, "distance_m": s.distance_m,
            "allure_s_par_km": allure(s), "fc_moyenne": s.fc_moyenne, "fc_max": s.fc_max, "trimp": s.trimp,
            "avec_fc": s.avec_fc}


def chronologique(seances, recentes_d_abord=False):
    return sorted(seances, key=lambda s: (s.date, s.t0 is not None, s.t0 or 0), reverse=recentes_d_abord)


def liste_seances(d, jours, sport, aujourdhui, au=None):
    """Séances de la fenêtre de jours jours qui finit le jour au (aujourd'hui par défaut)."""
    dates = dates_periode(au or aujourdhui, jours)
    seances = [s for s in seances_de(d, dates) if sport == "tous" or s.sport == sport]
    seances = chronologique(seances, recentes_d_abord=True)
    par = {}
    for s in seances:
        p = par.setdefault(s.sport, {"nom": s.nom, "seances": 0, "minutes": 0, "distance_m": 0, "trimp": None,
                                     "sans_fc": 0})
        p["seances"] += 1
        p["minutes"] += s.minutes or 0
        p["distance_m"] += s.distance_m or 0
        p["sans_fc"] += 0 if s.avec_fc else 1
        if s.dans_la_charge and s.trimp is not None:  # ski et snowboard hors charge
            p["trimp"] = arrondi((p["trimp"] or 0) + s.trimp, 1)
    charge = [s.trimp for s in seances if s.dans_la_charge and s.trimp is not None]
    return {"jours": jours, "sport": sport, "du": dates[0].isoformat(), "au": dates[-1].isoformat(),
            "total": {"seances": len(seances), "minutes": sum(s.minutes or 0 for s in seances),
                      "distance_m": sum(s.distance_m or 0 for s in seances),
                      "trimp": arrondi(sum(charge), 1) if charge else None,
                      "sans_fc": sum(1 for s in seances if not s.avec_fc)},
            "par_sport": dict(sorted(par.items(), key=lambda kv: -kv[1]["minutes"])),
            "seances": [ligne_seance(s) for s in seances[:SEANCES_MAX]], "tronque": len(seances) > SEANCES_MAX}


def bornes_zones(fc_max):
    """Bornes en bpm de chaque zone, exactement comme zoneDe() de serveur/agregats.mjs (même calcul
    en flottants : pct = bpm / FC max x 100, zone dont min <= pct < max). La zone 1 part de 0 bpm,
    c'est la définition d'agregats.mjs (ZONES_FC, min 0) : tout battement sous le seuil de la zone 2
    y tombe, l'appli l'écrit « moins de N ». La zone 5 n'a pas de borne haute (max_bpm null)."""
    if fc_max is None:
        return None
    vus = {}
    for bpm in range(0, 2 * fc_max + 1):
        pct = (bpm / fc_max) * 100
        cle = next((c for c, _, bas, haut in ZONES if bas <= pct < haut), "z5")
        vus.setdefault(cle, [bpm, bpm])[1] = bpm
    return {c: {"nom": nom, "min_bpm": vus[c][0] if c in vus else None,
                "max_bpm": (vus[c][1] if c in vus else None) if c != "z5" else None} for c, nom, _, _ in ZONES}


def analyse_associee(d, s, commentaire):
    """Analyse du jour gardée seulement si elle désigne cette séance, ou si la séance est la seule du
    jour et que l'analyse ne désigne pas une autre séance connue."""
    if not commentaire:
        return None
    cible = commentaire.get("seance_id")
    if cible == s.id or (len(d.jours[s.date].seances) == 1 and (cible is None or cible not in d.seances)):
        return {"texte": commentaire["texte"], "modele": commentaire.get("modele"), "genere": commentaire.get("genere")}
    return None


def detail_seance(d, s, fc_max_reference, commentaire):
    return {**ligne_seance(s), "fin_local": heure_locale(s.fin, s.decalage), "titre": s.titre, "type": s.type_brut,
            "type_code": s.type_code, "kcal": s.kcal, "fc_min": s.fc_min, "fc_echantillons": s.fc_n,
            "vitesse_moyenne_kmh": s.vit_moy, "vitesse_max_kmh": s.vit_max, "dans_la_charge": s.dans_la_charge,
            "zones_minutes": ({c: s.zones.get(c, 0) for c in CLES_ZONES} if s.zones else None),
            "fc_max_reference": fc_max_reference, "zones_bornes": bornes_zones(fc_max_reference),
            "fc_courbe": [list(p) for p in s.courbe] if s.courbe else None,
            "analyse": analyse_associee(d, s, commentaire)}


def vue_jour(d, x, aujourdhui):
    j = d.jours.get(x)
    base = {"date": x.isoformat(), "en_cours": x == aujourdhui, "renseigne": bool(j and j.renseigne), **valeurs(d, x)}
    codes = {str(k): v for k, v in STADES.items()}
    if j is None or not j.renseigne:
        return {**base, "distance_m": None, "kcal": None, "fc_max": None, "spo2_min": None, "nuit": None,
                "codes_stades": codes, "seances": []}
    nuit = None
    if j.nuit is not None:
        stades = {}
        for _, du, code in j.nuit.seq:
            stades[STADES[code]] = stades.get(STADES[code], 0) + du
        # sleepStages ne porte pas le décalage de la mesure : heure de Paris (ingest-auto.mjs inchangé).
        nuit = {"debut_local": heure_locale(j.nuit.debut), "au_lit_minutes": j.au_lit, "sommeil_minutes": j.sommeil,
                "profond_minutes": j.profond, "stades": stades, "seq": [list(p) for p in j.nuit.seq]}
    return {**base, "distance_m": j.distance_m, "kcal": j.kcal, "fc_max": j.fc_max, "spo2_min": j.spo2_min,
            "nuit": nuit, "codes_stades": codes, "seances": [ligne_seance(d.seances[i]) for i in j.seances]}


# ---------------------------------------------------------------- records
def record_jour(valeur, unite, x):
    return {"valeur": valeur, "unite": unite, "date": x.isoformat()}


def record_seance(valeur, unite, s):
    return {"valeur": valeur, "unite": unite, "date": s.date.isoformat(), "seance_id": s.id, "sport": s.sport}


def meilleur(elements, mesure, plus_grand=True):
    """(élément, valeur) du premier record dans l'ordre chronologique : une égalité ne bat pas."""
    tenant, valeur = None, None
    for e in elements:
        v = mesure(e)
        if v is None:
            continue
        if valeur is None or (v > valeur if plus_grand else v < valeur):
            tenant, valeur = e, v
    return tenant, valeur


def plus_longue_serie(dates, condition, unite):
    meilleure, debut, n = None, None, 0
    for x in dates:
        if condition(x):
            debut, n = (x if n == 0 else debut), n + 1
            if meilleure is None or n > meilleure[0]:
                meilleure = (n, debut, x)
        else:
            n = 0
    if meilleure is None:
        return None
    return {"valeur": meilleure[0], "unite": unite, "du": meilleure[1].isoformat(), "au": meilleure[2].isoformat()}


def seuil_env(nom, defaut):
    try:
        v = int(str(os.getenv(nom, "")).strip())
    except ValueError:
        return defaut
    return v if v > 0 else defaut


def fc_max_env():
    """FC max de référence (SANTE_FC_MAX), entre 100 et 250, sinon None."""
    try:
        v = int(str(os.getenv("SANTE_FC_MAX", "")).strip())
    except ValueError:
        return None
    return v if 100 <= v <= 250 else None


def sommeil_mesure(j):
    """Sommeil réel d'un jour, ou None sans stades : sleepH est un temps au lit, pas un record."""
    return j.sommeil if j is not None and j.sommeil is not None and j.sommeil_estime is False else None


def records(d, aujourdhui, seuil_pas, seuil_nuit):
    dates = jours_entre(d.premier, aujourdhui) if d.premier <= aujourdhui else []
    rens = [(x, d.jours[x]) for x in dates if x in d.jours and d.jours[x].renseigne]
    seances = chronologique(seances_de(d, dates))
    jour_de = d.jours.get
    R = {}

    R["serie_pas"] = plus_longue_serie(
        dates, lambda x: jour_de(x) is not None and jour_de(x).pas is not None and jour_de(x).pas >= seuil_pas, "jours")
    x, v = meilleur(rens, lambda e: e[1].pas)
    R["journee_la_plus_active"] = record_jour(v, "pas", x[0]) if x else None

    semaines, l = [], lundi(d.premier) + timedelta(days=7)  # ni la première semaine
    while dates and l < lundi(aujourdhui):                     # ni la semaine en cours
        pas = [jour_de(l + timedelta(days=i)) for i in range(7)]
        if all(j is not None and j.pas is not None for j in pas):
            semaines.append((l, sum(j.pas for j in pas)))
        l += timedelta(days=7)
    x, v = meilleur(semaines, lambda e: e[1])
    R["meilleure_semaine_pas"] = {"valeur": v, "unite": "pas", "lundi": x[0].isoformat()} if x else None

    s, v = meilleur(seances, lambda s: s.minutes)
    R["seance_la_plus_longue"] = record_seance(v, "min", s) if s else None
    s, v = meilleur(seances, lambda s: s.distance_m if s.sport == "course" else None)
    R["course_la_plus_longue"] = record_seance(arrondi(v / 1000, 2), "km", s) if s else None

    minutes = {}
    for s in seances:
        if s.dans_la_charge and s.minutes:
            minutes[lundi(s.date)] = minutes.get(lundi(s.date), 0) + s.minutes
    x, v = meilleur(sorted(minutes.items()), lambda e: e[1])
    R["semaine_la_plus_sportive"] = {"valeur": v, "unite": "min", "lundi": x[0].isoformat()} if x else None

    s, v = meilleur(seances, lambda s: s.trimp if s.dans_la_charge else None)
    R["seance_la_plus_chargee"] = record_seance(v, "trimp", s) if s else None
    s, v = meilleur(seances, lambda s: (s.zones or {}).get("z5") or None)
    R["zone5_la_plus_longue"] = record_seance(v, "min", s) if s else None
    s, v = meilleur(seances, lambda s: allure(s) if (s.distance_m or 0) >= ALLURE_DISTANCE_MIN else None,
                    plus_grand=False)
    R["meilleure_allure_5km"] = {**record_seance(v, "s/km", s), "distance_m": s.distance_m} if s else None

    x, v = meilleur(rens, lambda e: sommeil_mesure(e[1]))
    R["nuit_la_plus_longue"] = record_jour(v, "min", x[0]) if x else None
    R["serie_nuits"] = plus_longue_serie(
        dates, lambda x: (sommeil_mesure(jour_de(x)) or 0) >= seuil_nuit, "nuits")
    x, v = meilleur(rens, lambda e: (e[1].profond or None) if e[1].sommeil_estime is False else None)
    R["sommeil_profond_le_plus_long"] = record_jour(v, "min", x[0]) if x else None
    x, v = meilleur(rens, lambda e: e[1].fc_min, plus_grand=False)
    R["fc_la_plus_basse"] = record_jour(v, "bpm", x[0]) if x else None

    def pic_verifie(s):
        """FC max de la séance, sauf un pic de capteur plus de 15 bpm au-dessus du sommet de sa
        courbe reçue (avant réduction)."""
        if s.fc_max is None or s.fc_sommet is None:
            return None
        return s.fc_max if s.fc_max <= s.fc_sommet + ECART_PIC_FC else None
    s, v = meilleur(seances, pic_verifie)
    R["fc_la_plus_haute"] = record_seance(v, "bpm", s) if s else None

    recent = aujourdhui - timedelta(days=6)
    for r in R.values():
        if r is None:
            continue
        if "date" in r:
            ref = Date.fromisoformat(r["date"])
        elif "au" in r:
            ref = Date.fromisoformat(r["au"])
        else:
            ref = min(Date.fromisoformat(r["lundi"]) + timedelta(days=6), aujourdhui)
        r["battu_le"] = ref.isoformat() if ref >= recent else None
    return {"depuis": d.premier.isoformat(), "seuils": {"pas": seuil_pas, "nuit_minutes": seuil_nuit}, "records": R}


# ---------------------------------------------------------------- validation des demandes
def valider_jours(msg, defaut):
    v = msg.get("jours", defaut)
    if isinstance(v, bool) or not isinstance(v, int) or v not in PERIODES:
        raise ErreurSante("période non prise en charge (7, 30, 90 ou 365 jours)")
    return v


def valider_date(msg, cle="date"):
    v = msg.get(cle)
    if not isinstance(v, str) or not SA.DATE.fullmatch(v):
        raise ErreurSante("date invalide (AAAA-MM-JJ attendu)")
    try:
        return Date.fromisoformat(v)
    except ValueError:
        raise ErreurSante("date invalide (AAAA-MM-JJ attendu)") from None


# ---------------------------------------------------------------- lecture et caches
class Historique:
    """Lecture de data-auto.js et des analyses du jour, avec leurs caches. Une seule lecture en vol
    (les demandes l'attendent), DUREE_CACHE secondes entre deux lectures, panne gardée DUREE_ERREUR."""

    def __init__(self, url_sante, jeton, url_donnees=URL_DONNEES, horloge=time.monotonic, maintenant=time.time,
                 transport=None, resoudre=SA.resoudre_dns, source=SA.source_vers):
        self.url = (url_donnees or URL_DONNEES).strip()
        self.url_sante = (url_sante or SA.URL_DEFAUT).strip().rstrip("/")
        self._jeton = jeton
        self._horloge, self._maintenant = horloge, maintenant
        self._transport = transport  # httpx.MockTransport dans les tests
        self._resoudre, self._source = resoudre, source
        self._donnees, self._t, self._etag = None, 0.0, None
        self._erreur, self._t_erreur = None, 0.0
        self._en_vol = None
        self._comm, self._comm_vol, self._jour_comm = {}, {}, None

    # ---- data-auto.js
    def lire(self, etag=None):
        """Lecture bloquante (dans un thread) : (Donnees, etag), ou (None, etag) sur un 304."""
        import httpx
        debut = time.monotonic()
        morceaux = urlsplit(self.url)
        if morceaux.scheme != "https" or not morceaux.hostname:
            raise ErreurSante("historique : adresse https attendue")
        hote, port = morceaux.hostname, morceaux.port or 443
        try:
            ip = SA.adresse_tailscale(hote, self._resoudre)
            SA.route_tailscale(ip, port, self._source)
        except ErreurSante as e:
            # Messages du relais, ajustés : ici aucun jeton ne part, c'est la lecture qui est annulée.
            raise ErreurSante(str(e).replace("jeton gardé", "lecture annulée")
                              .replace("sante-api", "le tableau de bord")) from None
        cible = f"https://{f'[{ip}]' if ip.version == 6 else ip}:{port}{morceaux.path or '/'}"
        # identity : le plafond porte sur les octets reçus, pas sur un contenu décompressé.
        entetes = {"Host": hote if port == 443 else f"{hote}:{port}", "Accept-Encoding": "identity"}
        if etag:
            entetes["If-None-Match"] = etag
        corps = bytearray()
        try:
            with httpx.Client(transport=self._transport, trust_env=False,
                              timeout=httpx.Timeout(DELAI, connect=DELAI_CONNEXION)) as client:
                with client.stream("GET", cible, headers=entetes, extensions={"sni_hostname": hote}) as r:
                    if r.status_code == 304 and etag:
                        return None, etag
                    if r.status_code != 200:
                        raise ErreurSante(f"le tableau de bord a répondu {r.status_code}")
                    longueur = r.headers.get("content-length", "")
                    if longueur.isdigit() and int(longueur) > TAILLE_MAX:
                        raise ErreurSante("historique trop grand (plus de 16 Mo)")
                    for bloc in r.iter_bytes():
                        corps += bloc
                        if len(corps) > TAILLE_MAX:
                            raise ErreurSante("historique trop grand (plus de 16 Mo)")
                        if time.monotonic() - debut > DELAI:
                            raise ErreurSante(f"le tableau de bord ne répond pas (délai de {DELAI} s)")
                    nouvel = r.headers.get("etag", "")
        except httpx.TimeoutException:
            raise ErreurSante(f"le tableau de bord ne répond pas (délai de {DELAI} s)") from None
        except httpx.HTTPError as e:
            raise ErreurSante(f"tableau de bord injoignable ({e.__class__.__name__})") from None
        donnees = reduire_fichier(bytes(corps), datetime.now().isoformat(timespec="seconds"), self._maintenant())
        del corps
        return donnees, (nouvel if ETAG.fullmatch(nouvel or "") else None)

    async def _appel(self):
        """Seul chemin vers data-auto.js : range le résultat ou la panne, puis libère la place."""
        etag = self._etag if self._donnees is not None else None
        try:
            nouvelles, etag = await asyncio.to_thread(self.lire, etag)
        except ErreurSante as e:
            self._erreur, self._t_erreur = str(e), self._horloge()
            raise
        except Exception as e:  # le texte d'une exception pourrait citer une valeur : seulement sa classe
            self._erreur, self._t_erreur = f"erreur inattendue ({e.__class__.__name__})", self._horloge()
            raise ErreurSante(self._erreur) from None
        else:
            if nouvelles is None:  # 304 : le cache est encore bon pour 10 min
                self._donnees.lu_a = datetime.now().isoformat(timespec="seconds")
                self._donnees.lu_ts = self._maintenant()
            else:
                self._donnees, self._etag = nouvelles, etag
            self._t, self._erreur = self._horloge(), None
            return self._donnees
        finally:
            self._en_vol = None

    def _lancer(self):
        if self._en_vol is None:
            self._en_vol = asyncio.get_running_loop().create_task(self._appel())
            # Résultat lu même si toutes les demandes ont abandonné : pas d'avertissement asyncio.
            self._en_vol.add_done_callback(lambda t: t.cancelled() or t.exception())
        return self._en_vol

    def prechauffer(self):
        """Lecture en tâche de fond si le cache est vide (après un « sante » réussi). Vrai si lancée."""
        if self._donnees is not None or self._en_vol is not None:
            return False
        if self._erreur is not None and self._horloge() - self._t_erreur < DUREE_ERREUR:
            return False
        self._lancer()
        return True

    async def donnees(self):
        """Cache de moins de 10 min, sinon lecture (conditionnelle s'il y a un cache). En panne,
        l'ancien cache reste servi, sinon la panne est resservie pendant 30 s."""
        maintenant = self._horloge()
        if self._donnees is not None and maintenant - self._t < DUREE_CACHE:
            return self._donnees
        if self._erreur is not None and maintenant - self._t_erreur < DUREE_ERREUR:
            if self._donnees is not None:
                return self._donnees
            raise ErreurSante(self._erreur)
        tache = self._lancer()
        try:
            return await asyncio.wait_for(asyncio.shield(tache), ATTENTE_MAX)
        except asyncio.TimeoutError:
            if self._donnees is not None:
                return self._donnees
            raise ErreurSante(f"le tableau de bord ne répond pas (délai de {DELAI} s)") from None
        except ErreurSante:
            if self._donnees is not None:
                return self._donnees
            raise

    def perime(self, d):
        ref = d.genere_ts if d.genere_ts is not None else d.lu_ts
        return self._maintenant() - ref > PERIME_APRES

    # ---- analyses écrites de sante-api
    def lire_commentaire(self, jour):
        """Appel bloquant : analyse du jour {texte, seance_id, modele, genere}, None si absente (404),
        AnalyseIndisponible en panne. jour est une date déjà validée (datetime.date), jamais un texte
        reçu de la tablette."""
        import httpx
        debut = time.monotonic()
        morceaux = urlsplit(self.url_sante)
        hote, port = morceaux.hostname or "", morceaux.port or (443 if morceaux.scheme == "https" else 80)
        try:
            ip = SA.adresse_tailscale(hote, self._resoudre)
            SA.route_tailscale(ip, port, self._source)
        except ErreurSante:
            raise AnalyseIndisponible("hors Tailscale") from None
        cible = (f"{morceaux.scheme}://{f'[{ip}]' if ip.version == 6 else ip}:{port}"
                 f"{morceaux.path.rstrip('/')}/api/commentaire")
        entetes = {"Authorization": f"Bearer {self._jeton}", "Host": f"{hote}:{port}", "Accept-Encoding": "identity"}
        extensions = {"sni_hostname": hote} if morceaux.scheme == "https" else {}
        corps = bytearray()
        try:
            with httpx.Client(transport=self._transport, trust_env=False,
                              timeout=httpx.Timeout(COMM_DELAI, connect=DELAI_CONNEXION)) as client:
                with client.stream("GET", cible, params={"date": jour.isoformat()}, headers=entetes,
                                   extensions=extensions) as r:
                    if r.status_code == 404:
                        return None
                    if r.status_code != 200:
                        raise AnalyseIndisponible(f"HTTP {r.status_code}")
                    for bloc in r.iter_bytes():
                        corps += bloc
                        if len(corps) > COMM_TAILLE_MAX:
                            raise AnalyseIndisponible("réponse trop grande")
                        if time.monotonic() - debut > COMM_DELAI:
                            raise AnalyseIndisponible("délai dépassé")
        except httpx.HTTPError as e:
            raise AnalyseIndisponible(e.__class__.__name__) from None
        try:
            brut = json.loads(bytes(corps))
        except (ValueError, RecursionError):
            raise AnalyseIndisponible("réponse illisible") from None
        if not isinstance(brut, dict) or brut.get("date") not in (None, jour.isoformat()):
            return None
        texte = brut.get("texte").strip()[:COMM_TEXTE_MAX] if isinstance(brut.get("texte"), str) else ""
        if not texte:
            return None
        seance = brut.get("seance_id")
        return {"texte": texte, "seance_id": seance if isinstance(seance, str) and ID.fullmatch(seance) else None,
                "modele": SA.texte(brut.get("modele"), 80), "genere": SA.texte(brut.get("genere"), 40)}

    def _ranger_commentaire(self, cle, valeur, duree):
        if cle not in self._comm and len(self._comm) >= COMM_MAX:
            self._comm.pop(next(iter(self._comm)))
        self._comm[cle] = (valeur, self._horloge() + duree)

    async def _appel_commentaire(self, jour):
        cle = jour.isoformat()
        try:
            valeur = await asyncio.to_thread(self.lire_commentaire, jour)
        except Exception as e:
            raison = e.raison if isinstance(e, AnalyseIndisponible) else e.__class__.__name__
            print(f"santé : analyse indisponible ({raison})")  # ni date ni texte
            self._ranger_commentaire(cle, None, DUREE_ERREUR)
            raise AnalyseIndisponible(raison) from None
        else:
            self._ranger_commentaire(cle, valeur, COMM_PRESENT if valeur else COMM_ABSENT)
            return valeur
        finally:
            self._comm_vol.pop(cle, None)

    async def commentaire(self, jour):
        """Analyse écrite d'un jour (datetime.date), ou None : pas de jeton, pas d'analyse, panne."""
        if not self._jeton:
            return None
        aujourdhui = SA.date_du_jour()
        if self._jour_comm != aujourdhui:
            self._comm.clear()
            self._jour_comm = aujourdhui
        cle = jour.isoformat()
        garde = self._comm.get(cle)
        if garde is not None and self._horloge() < garde[1]:
            return garde[0]
        tache = self._comm_vol.get(cle)
        if tache is None:
            tache = self._comm_vol[cle] = asyncio.get_running_loop().create_task(self._appel_commentaire(jour))
            tache.add_done_callback(lambda t: t.cancelled() or t.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(tache), COMM_DELAI + 1)
        except (asyncio.TimeoutError, ErreurSante):
            return None

    # ---- réponses aux messages de la tablette
    async def repondre(self, msg):
        """« donnees » d'une demande sante_periode, sante_seances, sante_seance, sante_records ou
        sante_jour. Paramètres validés avant toute lecture, ErreurSante sans donnée dans le texte."""
        genre = msg.get("type")
        au = None
        if genre in ("sante_periode", "sante_seances") and msg.get("au") is not None:
            au = valider_date(msg, "au")  # fin de la fenêtre, comme la date de sante_jour
        if genre == "sante_periode":
            jours = valider_jours(msg, 7)
        elif genre == "sante_seances":
            jours = valider_jours(msg, 30)
            sport = msg.get("sport", "tous")
            if not isinstance(sport, str) or not (sport == "tous" or SA.CLE.fullmatch(sport)):
                raise ErreurSante("sport inconnu")
        elif genre == "sante_seance":
            ident = msg.get("seance_id")
            if not isinstance(ident, str) or not 0 < len(ident) <= 100:
                raise ErreurSante("séance inconnue")
        elif genre == "sante_jour":
            date = valider_date(msg)
        elif genre != "sante_records":
            raise ErreurSante("demande inconnue")

        d = await self.donnees()
        aujourdhui = SA.date_du_jour()
        if au is not None and (au < d.premier or au > aujourdhui):
            raise ErreurSante("date hors de l'historique")
        if genre == "sante_periode":
            resultat = await asyncio.to_thread(periode, d, jours, aujourdhui, au)
        elif genre == "sante_seances":
            if sport != "tous" and sport not in SPORTS_CONNUS and all(s.sport != sport for s in d.seances.values()):
                raise ErreurSante("sport inconnu")
            resultat = await asyncio.to_thread(liste_seances, d, jours, sport, aujourdhui, au)
        elif genre == "sante_seance":
            s = d.seances.get(ident)
            if s is None:
                raise ErreurSante("séance inconnue")
            commentaire = await self.commentaire(s.date)
            resultat = detail_seance(d, s, fc_max_env(), commentaire)
        elif genre == "sante_records":
            resultat = await asyncio.to_thread(records, d, aujourdhui, seuil_env("SANTE_SEUIL_PAS", SEUIL_PAS_DEFAUT),
                                               seuil_env("SANTE_SEUIL_NUIT_MIN", SEUIL_NUIT_DEFAUT))
        else:
            if date < d.premier or date > aujourdhui:
                raise ErreurSante("date hors de l'historique")
            resultat = vue_jour(d, date, aujourdhui)
        resultat.update({"aujourdhui": aujourdhui.isoformat(), "premier_jour": d.premier.isoformat(),
                         "genere_le": d.genere, "lu_a": d.lu_a, "perime": self.perime(d)})
        return resultat


def depuis_env(profil):
    """Historique en profil pc avec SANTE_JETON (comme le relais), sinon None. Le fichier du tableau
    de bord se lit sans jeton, le jeton ne sert qu'aux analyses écrites."""
    if profil != "pc":
        return None
    jeton = os.getenv("SANTE_JETON", "").strip()
    if not jeton:
        return None
    return Historique(os.getenv("SANTE_URL", "").strip() or SA.URL_DEFAUT, jeton)
