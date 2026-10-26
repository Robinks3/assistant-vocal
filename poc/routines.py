"""Moteur de routines (0.42.0, S-R1) : une phrase dite, une suite d'actions faites.

Conception : docs/plan/conception/routines.md. Ce module ne sait rien de l'assistant ni du réseau. Il porte :
- le fichier routines.json (format, chargement, écriture atomique, fichier illisible mis de côté) ;
- la validation d'une routine proposée par le LLM (phrases, étapes, limites) et sa reformulation ;
- le brouillon en attente de confirmation et l'absorption du « oui » qui suit ;
- les droits (propriétaire, habitant, invité, personne non reconnue) ;
- l'exécution d'une routine : partie immédiate, puis suite (musique et pauses) rendue sous forme de fonction.

Règle de fer : une routine ne permet jamais ce qu'une commande directe refuse. Chaque étape qui appelle un service
de Home Assistant passe par acces.controler_service (domaines interdits, liste blanche, réglages de la maison,
sécurité en dur), à la création, à la revérification du chargement et à chaque lancement. Les cibles doivent être
nommées une à une et figurer dans l'inventaire de la personne qui lance.

Le contexte (Contexte) est fabriqué par l'assistant, qui y met ce que seul lui connaît : inventaire, enceintes de
musique, dictionnaire, mot de réveil, garde-fou du volume. Rien de la maison n'est écrit ici.
"""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import acces
import liste_blanche
import maison
import securite
from dictionnaire import SEUIL_FLOU, epurer, mots_compatibles, normaliser

ICI = Path(__file__).resolve().parent
DONNEES = Path(os.getenv("JARVIS_DONNEES", str(ICI)))
FICHIER = DONNEES / "routines.json"
JOURNAL = DONNEES / "journal" / "routines.jsonl"
FORMAT = 1

DEFAUTS = {"active": True, "delai_confirmation_s": 30, "absorption_s": 120, "nombre_max": 30, "etapes_max": 8,
           "variantes_max": 5, "lettres_min": 6, "pause_max_s": 600, "duree_max_s": 1800, "intervalle_min_s": 10,
           "question_delai_s": 10, "phrases_interdites": []}


def reglage(cle):
    """Réglage de la section routines de maison.json, relu à chaque appel, avec son défaut."""
    section = maison.CONFIG.get("routines")
    valeur = section.get(cle) if isinstance(section, dict) else None
    defaut = DEFAUTS[cle]
    if isinstance(defaut, list):
        return [v for v in valeur if isinstance(v, str)] if isinstance(valeur, list) else defaut
    if isinstance(defaut, bool):
        return valeur if isinstance(valeur, bool) else defaut
    return valeur if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) else defaut


# ------------------------------------------------------------------------------------------ formules fixes
def _formes(*phrases):
    return {normaliser(p) for p in phrases}


CONFIRMER = _formes("oui", "d'accord", "vas-y", "c'est bon", "enregistre", "confirme")
ABANDONNER = _formes("non", "annule", "laisse tomber")
INTERDITES = _formes("oui", "non", "ok", "d'accord", "merci", "stop", "arrête", "annule", "pause", "encore",
                     "suivant", "plus fort", "moins fort", "aide", "vas-y", "c'est bon", "enregistre", "confirme",
                     "laisse tomber")
MSG_INCONNU = "Je ne sais pas qui parle, je ne crée pas de routine. Mets-toi devant la tablette."
MSG_INVITE = "Les invités ne peuvent pas créer de routine."
MSG_EXPIRE = "La proposition a expiré, redis-moi la routine."
MSG_RESTE = "Le reste, je le garde ?"
CHAMPS_PROPOSITION = {"nom", "phrases", "variantes", "reponse", "etapes", "remplace"}
INTERDITS_CIBLE = {"area_id", "device_id", "floor_id", "label_id"}
TYPES_MUSIQUE = ("track", "artist", "album", "playlist")


# ------------------------------------------------------------------------------------------------- journal
def journal(evenement, **champs):
    """Une ligne de journal/routines.jsonl. Ne fait jamais échouer l'appelant."""
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        entree = {"le": maison.maintenant().strftime(maison.FORMAT_HORODATAGE), "evenement": evenement, **champs}
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"routines : journal illisible ({e})")


# ------------------------------------------------------------------------------------------------ contexte
class Contexte:
    """Ce que le moteur doit savoir de la requête en cours et de la maison (fabriqué par l'assistant).

    entites   jeu des entity_id de l'inventaire de la personne (None : inventaire non chargé, rien ne passe)
    statique  vrai pour la revérification du chargement : pas d'inventaire, on ne juge que la liste blanche
    """

    def __init__(self, personne="", role="", appareil="", essai=False, entites=None, noms=None, enceintes=None,
                 dico=None, services_permis=None, mots_reserves=(), motifs_reserves=(), garde_volume=None,
                 phrase_creation="", statique=False):
        p = securite.personne_normalisee(personne)
        self.personne = "" if p == "inconnu" else p
        self.role = role or ""
        self.appareil = appareil or ""
        self.essai = bool(essai)
        self.entites = None if entites is None else set(entites)
        self.noms = dict(noms or {})
        self.enceintes = dict(enceintes or {})
        self.dico = dico
        self.services_permis = services_permis or (lambda d: liste_blanche.SERVICES_PERMIS.get(d, set()))
        self.mots_reserves = {normaliser(m) for m in mots_reserves if m}
        self.motifs_reserves = list(motifs_reserves)
        self.garde_volume = garde_volume
        self.phrase_creation = phrase_creation or ""
        self.statique = statique
        self.declencheurs = set()  # formes qu'une annonce ou une question ne doit pas contenir
        self.echecs = []  # étapes sautées ou refusées au dernier lancement (renseigné par lancer)


def qui_est(ctx):
    """proprietaire, habitant, invite ou inconnu (6.2)."""
    if ctx.role == "invite":
        return "invite"
    if not ctx.personne:
        return "inconnu"
    return "proprietaire" if ctx.personne == maison.CLE_PROPRIETAIRE else "habitant"


def peut_creer(ctx):
    return qui_est(ctx) in ("proprietaire", "habitant")


def peut_lancer(routine, ctx):
    """Une routine « tous » se lance par n'importe qui, une routine « auteur » par son auteur seulement."""
    return routine.get("pour") == "tous" or (bool(ctx.personne) and routine.get("auteur") == ctx.personne)


def peut_gerer(routine, ctx):
    """Le propriétaire gère tout, un habitant ses routines, les autres rien."""
    q = qui_est(ctx)
    return q == "proprietaire" or (q == "habitant" and routine.get("auteur") == ctx.personne)


def droits(ctx):
    q = qui_est(ctx)
    return {"qui": q, "creer": peut_creer(ctx), "tout_gerer": q == "proprietaire", "exporter": q == "proprietaire"}


# ---------------------------------------------------------------------------------------------- phrases
def forme(phrase):
    return normaliser(epurer(str(phrase)))


def _formes_routine(routine):
    return {f for d in routine.get("declencheurs", []) for f in d.get("formes", [])}


def refus_phrase(phrase, ctx, registre, ignorer=None):
    """Raison pour laquelle la phrase ne peut pas déclencher une routine, ou None. Renvoie (genre, message, id)
    avec genre « phrase », « commande », « apprise » ou « routine » (id : la routine en conflit)."""
    f = forme(phrase)
    txt = str(phrase).strip()
    lettres = sum(1 for c in f if c.isalpha())
    mots = f.split()
    interdites = INTERDITES | {normaliser(p) for p in reglage("phrases_interdites")}
    if lettres < reglage("lettres_min") or not any(len(m) >= 4 for m in mots) or f in interdites:
        return "phrase", f"« {txt} » est trop court ou réservé, choisis une phrase plus longue.", None
    if any(m.search(txt) or m.search(f) for m in ctx.motifs_reserves):
        return "phrase", f"« {txt} » ressemble à une formule de gestion, choisis une autre phrase.", None
    if ctx.mots_reserves & set(mots) or "routine" in mots:
        return "phrase", f"« {txt} » contient un mot réservé, choisis une autre phrase.", None
    trouve = ctx.dico.chercher(txt) if ctx.dico is not None else None
    if trouve:
        reconnue = trouve[2]
        appris = "appris_le" in ctx.dico.formes.get(reconnue, ({},))[0]
        if appris:
            return ("apprise", f"« {txt} » est une phrase que j'ai apprise. Oublie-la à l'écran d'abord, "
                               "ou choisis-en une autre.", None)
        return "commande", f"« {txt} » est déjà une commande. Choisis une autre phrase.", None
    for r in registre.routines:
        if r["id"] == ignorer or not peut_lancer(r, ctx):
            continue
        for f2 in _formes_routine(r):
            if f2 == f or (difflib_proche(f, f2) and mots_compatibles(f, f2)):
                return ("routine", f"Tu as déjà la routine {r['nom']} pour « {txt} ». Je la remplace ?", r["id"])
    return None


def difflib_proche(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= SEUIL_FLOU


# ------------------------------------------------------------------------------------------------ étapes
def _liste_cibles(valeur):
    """Liste de textes pour un entity_id (texte, liste séparée par des virgules ou liste), ou None si mal formé."""
    if valeur is None:
        return []
    if isinstance(valeur, str):
        return securite.cibles(valeur)
    if isinstance(valeur, (list, tuple)) and all(isinstance(v, str) for v in valeur):
        return securite.cibles(list(valeur))
    return None


def _parcourir(valeur, cibles, interdit):
    """Cherche dans les données, à toute profondeur, les entity_id (ajoutés à cibles) et les clés interdites."""
    if isinstance(valeur, dict):
        for cle, sous in valeur.items():
            c = str(cle)
            if c in INTERDITS_CIBLE or c == "target":
                interdit.append(c)
            elif c.endswith("entity_id"):
                liste = _liste_cibles(sous)
                if liste is None:
                    interdit.append(c)
                else:
                    cibles.extend(liste)
            else:
                _parcourir(sous, cibles, interdit)
    elif isinstance(valeur, list):
        for sous in valeur:
            _parcourir(sous, cibles, interdit)


def _nommer(ctx, cibles):
    return ", ".join(ctx.noms.get(c, c) for c in cibles)


def _sans_texte_declencheur(texte, ctx):
    """Une annonce ou une question qui contient le mot de réveil ou une phrase de déclenchement ferait une boucle."""
    tn = normaliser(texte)
    mots = set(tn.split())
    if ctx.mots_reserves & mots:
        return False
    cadre = f" {tn} "
    return not any(f and f" {f} " in cadre for f in ctx.declencheurs)


def valider_etape(etape, ctx):
    """(étape normalisée, None) si l'étape est permise, sinon (None, message dit à voix haute)."""
    if not isinstance(etape, dict):
        return None, "Une étape de la routine est mal formée."
    genre = etape.get("etape")
    if genre == "service":
        return _valider_service(etape, ctx)
    if genre == "musique":
        return _valider_musique(etape, ctx)
    if genre == "annonce":
        texte = str(etape.get("texte") or "").strip()
        if not texte or len(texte) > 200:
            return None, "Une annonce doit faire entre 1 et 200 caractères."
        if not _sans_texte_declencheur(texte, ctx):
            return None, "Une annonce ne peut contenir ni mon mot de réveil ni la phrase qui lance la routine."
        return {"etape": "annonce", "texte": texte}, None
    if genre == "question":
        texte = str(etape.get("texte") or "").strip()
        if not texte or len(texte) > 200:
            return None, "Une question doit faire entre 1 et 200 caractères."
        if not _sans_texte_declencheur(texte, ctx) or (ctx.dico is not None and ctx.dico.chercher(texte)):
            return None, "Je ne peux pas poser cette question dans une routine, elle déclencherait une commande."
        return {"etape": "question", "texte": texte}, None
    if genre == "pause":
        s = etape.get("secondes")
        if isinstance(s, bool) or not isinstance(s, (int, float)) or s <= 0:
            return None, "Une pause se compte en secondes."
        if s > reglage("pause_max_s"):
            return None, f"Une pause dure au plus {reglage('pause_max_s')} secondes."
        return {"etape": "pause", "secondes": s}, None
    return None, f"Je ne connais pas l'étape « {genre} » dans une routine."


def _valider_service(etape, ctx):
    domaine = str(etape.get("domaine") or "").strip()
    service = str(etape.get("service") or "").strip()
    action = f"{domaine}.{service}"
    donnees = etape.get("donnees") or {}
    inconnu = f"Je ne sais pas faire « {action} » dans une routine."
    if not domaine or not service or not isinstance(donnees, dict):
        return None, "Une étape de la routine est mal formée."
    if domaine in liste_blanche.DOMAINES_HORS_LLM:
        return None, inconnu
    cibles = _liste_cibles(etape.get("entity_id"))
    interdit = [c for c in INTERDITS_CIBLE if c in etape]
    if cibles is None:
        interdit.append("entity_id")
        cibles = []
    _parcourir(donnees, cibles, interdit)
    if interdit or not cibles or any(c.lower() in ("all", "none") or "*" in c for c in cibles):
        return None, f"Une routine doit nommer ses appareils un par un, je ne sais pas faire « {action} » ainsi."
    cibles = list(dict.fromkeys(cibles))
    if not ctx.statique:
        if ctx.entites is None:
            return None, "Je n'arrive pas à lire la liste de mes appareils."
        inconnues = [c for c in cibles if c not in ctx.entites]
        if inconnues:
            return None, f"Je ne trouve pas {_nommer(ctx, inconnues)} parmi mes appareils."
    donnees = {k: v for k, v in donnees.items() if k != "entity_id"}
    if ctx.garde_volume and service.startswith("volume"):
        args = {"service": service, "donnees": dict(donnees)}
        motif = ctx.garde_volume(ctx.phrase_creation, args)
        if motif:
            return None, f"Je retire le réglage du volume, tu ne l'as pas demandé ({_nommer(ctx, cibles)})."
        donnees = args.get("donnees") or {}
    permis = None if ctx.statique else ctx.services_permis(domaine)
    refus = None
    if not ctx.statique and not permis:
        refus = inconnu
    else:
        r = acces.controler_service(domaine, service, {**donnees, "entity_id": cibles},
                                    personne=ctx.personne or None, services_permis=permis)
        if r:
            refus = f"{str(r).rstrip('. ')}." if getattr(r, "genre", "") == "securite" else inconnu
    if refus:
        return None, refus
    return {"etape": "service", "domaine": domaine, "service": service, "entity_id": cibles, "donnees": donnees}, None


def _valider_musique(etape, ctx):
    recherche = str(etape.get("recherche") or "").strip()
    if not recherche:
        return None, "Une étape de musique doit dire quoi jouer."
    type_media = etape.get("type") or "track"
    if type_media not in TYPES_MUSIQUE:
        return None, f"Je ne sais pas jouer un « {type_media} » dans une routine."
    enceinte = str(etape.get("enceinte") or "toutes")
    if enceinte not in ctx.enceintes and not ctx.statique:
        return None, f"Je ne connais pas l'enceinte « {enceinte} » pour la musique."
    cibles = _liste_cibles(ctx.enceintes.get(enceinte)) or []
    refus = acces.controler_service("music_assistant", "play_media", {"entity_id": cibles or ["media_player.verification"]},
                                    personne=ctx.personne or None)
    if refus:
        return None, f"Je ne sais pas faire la musique sur « {enceinte} » dans une routine."
    res = {"etape": "musique", "recherche": recherche, "type": type_media, "enceinte": enceinte}
    if etape.get("artiste"):
        res["artiste"] = str(etape["artiste"]).strip()
    return res, None


def valider_etapes(etapes, ctx):
    """(étapes retenues dans l'ordre d'exécution, messages des étapes retirées). La musique passe en dernier."""
    gardees, notes = [], []
    for e in etapes:
        ok, message = valider_etape(e, ctx)
        if ok:
            gardees.append(ok)
        else:
            notes.append(message)
    gardees.sort(key=lambda e: e["etape"] == "musique")  # tri stable : l'ordre dit est l'ordre fait
    return gardees, notes


def duree_pauses(etapes):
    return sum(e["secondes"] for e in etapes if e.get("etape") == "pause")


# ------------------------------------------------------------------------------------------- reformulation
VERBES = {"turn_on": "allume", "turn_off": "éteins", "toggle": "inverse", "open_cover": "ouvre", "close_cover": "ferme",
          "media_play": "mets en lecture", "media_pause": "mets en pause", "media_stop": "arrête",
          "volume_set": "règle le volume de", "set_temperature": "règle la température de"}


def _decrire_etape(e, ctx):
    genre = e["etape"]
    if genre == "service":
        cible = _nommer(ctx, e["entity_id"])
        verbe = VERBES.get(e["service"], f"appelle {e['domaine']} {e['service']} sur")
        d = e.get("donnees") or {}
        if isinstance(d.get("brightness_pct"), (int, float)):
            return f"{verbe} {cible} à {int(d['brightness_pct'])} %"
        if isinstance(d.get("volume_level"), (int, float)):
            return f"{verbe} {cible} à {round(d['volume_level'] * 100)} %"
        return f"{verbe} {cible}"
    if genre == "musique":
        return f"lance « {e['recherche']} » sur {e['enceinte']}"
    if genre == "annonce":
        return f"dis « {e['texte']} »"
    if genre == "question":
        return f"demande « {e['texte']} » et dis la réponse"
    return f"attends {e['secondes']:g} secondes"


def decrire(routine, ctx, notes=(), remplace=None):
    """Reformulation écrite par le serveur à partir de la routine validée, pas par le LLM."""
    d = routine["declencheurs"][0]
    dites = " ou ".join(f"« {p} »" for p in d["phrases"])
    if d["variantes"]:
        n = len(d["variantes"])
        dites += f" (et {n} variante{'s' if n > 1 else ''})"
    faits = ", puis ".join(_decrire_etape(e, ctx) for e in routine["etapes"])
    debut = " ".join(notes) + " " if notes else ""
    remplace_txt = f"Je remplace la routine {remplace['nom']}. " if remplace else ""
    fin = MSG_RESTE if notes else "Je l'enregistre ?"
    return f"{debut}{remplace_txt}Routine {routine['nom']} : quand tu dis {dites}, je {faits}. {fin}".strip()


# ---------------------------------------------------------------------------------------------- registre
class Registre:
    """Les routines en mémoire, le fichier, les brouillons. Un verrou protège les écritures."""

    def __init__(self):
        self.verrou = threading.RLock()
        self.routines = []
        self.version = 0
        self.brouillons = {}
        self.absorption = {}
        self.dernier_lancement = {}
        self.charge = False

    # --------------------------------------------------------------------------------- fichier
    def charger(self):
        with self.verrou:
            self.routines, self.charge = [], True
            try:
                brut = FICHIER.read_text(encoding="utf-8")
            except FileNotFoundError:
                return self
            except OSError as e:
                journal("fichier illisible", erreur=str(e))
                return self
            try:
                donnees = json.loads(brut)
                if not isinstance(donnees, dict) or not isinstance(donnees.get("routines"), list):
                    raise ValueError("format inattendu")
                routines = [r for r in donnees["routines"] if isinstance(r, dict) and r.get("id")]
            except ValueError as e:
                mise_de_cote = FICHIER.with_name(f"{FICHIER.name}.illisible-{maison.maintenant():%Y%m%d-%H%M%S}")
                try:
                    os.replace(FICHIER, mise_de_cote)
                except OSError:
                    pass
                journal("fichier illisible", erreur=str(e), mis_de_cote=mise_de_cote.name)
                return self
            for r in routines:
                self._completer(r)
            self.routines = routines
            self._revalider_statique()
            return self

    @staticmethod
    def _completer(r):
        r.setdefault("nom", r["id"])
        r.setdefault("pour", "auteur")
        r.setdefault("actif", True)
        r.setdefault("a_revoir", None)
        r.setdefault("etapes", [])
        r.setdefault("executions", 0)
        r.setdefault("derniere_execution", None)
        for d in r.setdefault("declencheurs", []):
            d["phrases"] = [p for p in d.get("phrases", []) if isinstance(p, str)]
            d["variantes"] = [p for p in d.get("variantes", []) if isinstance(p, str)]
            d["formes"] = [forme(p) for p in d["phrases"] + d["variantes"]]

    def _revalider_statique(self):
        """5.4 : une routine devenue invalide (liste blanche, réglages) est coupée avec son motif."""
        for r in self.routines:
            if not r["actif"]:
                continue
            ctx = Contexte(personne=r.get("auteur", ""), statique=True)
            for e in r["etapes"]:
                ok, motif = valider_etape(e, ctx)
                if not ok:
                    r["actif"], r["a_revoir"] = False, motif
                    journal("revalidation échouée", id=r["id"], motif=motif)
                    break

    def sauver(self):
        with self.verrou:
            FICHIER.parent.mkdir(parents=True, exist_ok=True)
            tmp = FICHIER.with_name(FICHIER.name + ".tmp")
            tmp.write_text(json.dumps({"format": FORMAT, "routines": self.routines}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, FICHIER)
            self.version += 1

    def assurer(self):
        if not self.charge:
            self.charger()
        return self

    # ------------------------------------------------------------------------------- consultation
    def par_id(self, ident):
        self.assurer()
        return next((r for r in self.routines if r["id"] == ident), None)

    def visibles(self, ctx):
        """Routines que cette personne peut lister : tout pour le propriétaire, les siennes et celles « tous »."""
        self.assurer()
        return [r for r in self.routines if qui_est(ctx) == "proprietaire" or peut_lancer(r, ctx)]

    def resume(self, r):
        d = r["declencheurs"][0] if r["declencheurs"] else {"phrases": [], "variantes": []}
        return {"id": r["id"], "nom": r["nom"], "auteur": r.get("auteur"), "pour": r["pour"], "actif": r["actif"],
                "a_revoir": r["a_revoir"], "phrases": d["phrases"], "variantes": d["variantes"],
                "etapes": len(r["etapes"]), "derniere_execution": r["derniere_execution"],
                "executions": r["executions"]}

    def trouver(self, texte, ctx):
        """(routine, None) si la phrase en déclenche une que cette personne peut lancer, (routine, "reservee") si la
        phrase est celle d'une routine d'auteur et que personne n'est reconnu, sinon (None, None). Exact seulement."""
        self.assurer()
        f = forme(texte)
        for r in self.routines:
            if not r["actif"] or f not in _formes_routine(r):
                continue
            if peut_lancer(r, ctx):
                return r, None
            if not ctx.personne and ctx.role != "invite":
                return r, "reservee"
        return None, None

    def est_declencheur(self, texte):
        self.assurer()
        f = forme(texte)
        return any(f in _formes_routine(r) for r in self.routines)

    def formes_toutes(self):
        self.assurer()
        return {f for r in self.routines for f in _formes_routine(r)}

    # --------------------------------------------------------------------------------- brouillons
    def poser_brouillon(self, ctx, routine, remplace):
        cle = ctx.appareil
        self.brouillons[cle] = {"routine": routine, "remplace": remplace, "personne": ctx.personne,
                                "le": time.monotonic()}
        self.absorption[cle] = time.monotonic() + reglage("delai_confirmation_s") + reglage("absorption_s")

    def abandonner(self, ctx, raison):
        b = self.brouillons.pop(ctx.appareil, None)
        if b:
            journal("brouillon abandonné", raison=raison, nom=b["routine"]["nom"], personne=ctx.personne)
        return b

    def reponse_brouillon(self, texte, ctx):
        """Étape 1 de l'ordre de traitement (5.1) : le texte répond-il à un brouillon en attente ? Renvoie la parole
        à dire (le texte n'ira ni au dictionnaire ni au LLM), ou None pour continuer la chaîne ordinaire."""
        cle = ctx.appareil
        f = forme(texte)
        b = self.brouillons.get(cle)
        if b:
            if time.monotonic() - b["le"] > reglage("delai_confirmation_s"):
                self.abandonner(ctx, "expiré")
                return MSG_EXPIRE if f in CONFIRMER | ABANDONNER else None
            if b["personne"] != ctx.personne:
                self.abandonner(ctx, "personne changée")
                return None
            if f in CONFIRMER:
                return self.enregistrer(ctx)
            if f in ABANDONNER:
                self.abandonner(ctx, "refusé")
                self.absorption.pop(cle, None)
                return "D'accord, je n'enregistre rien."
            self.abandonner(ctx, "autre phrase")
            return None
        if f in CONFIRMER | ABANDONNER and time.monotonic() < self.absorption.get(cle, 0):
            self.absorption.pop(cle, None)
            return MSG_EXPIRE
        return None

    def enregistrer(self, ctx):
        with self.verrou:
            b = self.brouillons.pop(ctx.appareil, None)
            if not b:
                return MSG_EXPIRE
            r, remplace = b["routine"], b["remplace"]
            self.assurer()
            if remplace:
                ancien = self.par_id(remplace)
                if ancien:
                    r["id"], r["creee_le"], r["executions"] = ancien["id"], ancien["creee_le"], ancien["executions"]
                    r["modifiee_le"] = maison.maintenant().strftime(maison.FORMAT_HORODATAGE)
                    self.routines[self.routines.index(ancien)] = r
                    journal("remplacement", id=r["id"], nom=r["nom"], personne=ctx.personne, ancien=ancien)
                else:
                    self.routines.append(r)
            else:
                if len(self.routines) >= reglage("nombre_max"):
                    return f"Tu as déjà {reglage('nombre_max')} routines, supprimes-en une d'abord."
                self.routines.append(r)
                journal("création", id=r["id"], nom=r["nom"], personne=ctx.personne, appareil=ctx.appareil,
                        phrase=r["phrase_de_creation"], etapes=r["etapes"])
            self.sauver()
            return f"Routine {r['nom']} enregistrée."

    # ----------------------------------------------------------------------------------- gestion
    def activer(self, ident, actif, ctx):
        with self.verrou:
            r = self.par_id(ident)
            if not r or not peut_gerer(r, ctx):
                return False
            r["actif"] = bool(actif)
            if actif:
                r["a_revoir"] = None
            self.sauver()
            journal("réactivation" if actif else "coupure", id=ident, personne=ctx.personne)
            return True

    def supprimer(self, ident, ctx):
        with self.verrou:
            r = self.par_id(ident)
            if not r or not peut_gerer(r, ctx):
                return False
            self.routines.remove(r)
            self.sauver()
            journal("suppression", id=ident, personne=ctx.personne, copie=r)
            return True

    def exporter(self, ctx):
        if qui_est(ctx) != "proprietaire":
            return None
        self.assurer()
        return {"format": FORMAT, "routines": json.loads(json.dumps(self.routines))}

    def noter_execution(self, ident, resultat, echecs):
        with self.verrou:
            r = self.par_id(ident)
            if not r:
                return
            r["derniere_execution"] = {"le": maison.maintenant().strftime(maison.FORMAT_HORODATAGE),
                                       "resultat": resultat, "echecs": list(echecs)}
            r["executions"] = int(r.get("executions") or 0) + 1
            try:
                self.sauver()
            except OSError as e:
                print(f"routines : écriture impossible ({e})")


_REGISTRE = None


def registre():
    """Le registre du processus (chargé au premier appel). Les tests le remettent à zéro en changeant FICHIER."""
    global _REGISTRE
    if _REGISTRE is None:
        _REGISTRE = Registre().charger()
    return _REGISTRE


def reinitialiser():
    global _REGISTRE
    _REGISTRE = None


# ------------------------------------------------------------------------------------------- proposition
def refus(parole):
    return {"ok": False, "parole": parole, "routine": None, "remplace": None}


def valider_proposition(args, ctx, reg=None):
    """Valide ce que le LLM propose (4.3). Renvoie {ok, parole, routine, remplace}. Si ok, la parole est la
    reformulation à lire et le brouillon est à poser avec reg.poser_brouillon."""
    reg = reg or registre()
    reg.assurer()
    q = qui_est(ctx)
    if q == "inconnu":
        return refus(MSG_INCONNU)
    if q == "invite":
        return refus(MSG_INVITE)
    if not reglage("active"):
        return refus("Les routines sont désactivées.")
    if not isinstance(args, dict) or set(args) - CHAMPS_PROPOSITION:
        return refus("Je n'ai pas compris cette routine, redis-la autrement.")
    notes = []
    remplace = args.get("remplace") or None
    ancien = None
    if remplace:
        ancien = reg.par_id(remplace)
        if not ancien or not peut_gerer(ancien, ctx):
            return refus("Je ne trouve pas la routine à remplacer.")
    # phrases : une phrase refusée de la personne bloque, une variante refusée est retirée en silence
    phrases = [str(p).strip() for p in (args.get("phrases") or []) if isinstance(p, str) and p.strip()]
    if not phrases:
        return refus("Il me faut au moins une phrase pour lancer la routine.")
    vus, retenues = set(), []
    for p in phrases:
        r = refus_phrase(p, ctx, reg, ignorer=remplace)
        if r and r[0] == "routine":
            autre = reg.par_id(r[2])
            if autre["auteur"] == ctx.personne and (remplace in (None, autre["id"])) and \
                    (qui_est(ctx) == "proprietaire" or peut_gerer(autre, ctx)):
                remplace, ancien = autre["id"], autre
                notes.append(f"Tu as déjà la routine {autre['nom']} pour « {p} », je la remplace.")
                r = None
        if r:
            return refus(r[1])
        if forme(p) not in vus:
            vus.add(forme(p))
            retenues.append(p)
    variantes = []
    for v in (args.get("variantes") or [])[:reglage("variantes_max")]:
        if isinstance(v, str) and v.strip() and forme(v) not in vus and not refus_phrase(v.strip(), ctx, reg, ignorer=remplace):
            vus.add(forme(v))
            variantes.append(v.strip())
    # textes et étapes : les formes de déclenchement servent à refuser une annonce qui les contiendrait
    ctx.declencheurs = set(vus) | reg.formes_toutes()
    etapes_brutes = args.get("etapes")
    if not isinstance(etapes_brutes, list) or not etapes_brutes:
        return refus("Il me faut au moins une étape pour cette routine.")
    if len(etapes_brutes) > reglage("etapes_max"):
        return refus(f"Une routine fait au plus {reglage('etapes_max')} étapes.")
    etapes, retraits = valider_etapes(etapes_brutes, ctx)
    if not etapes:
        return refus(" ".join(retraits) or "Je ne sais rien faire de cette routine.")
    if duree_pauses(etapes) > reglage("duree_max_s"):
        return refus(f"Une routine dure au plus {reglage('duree_max_s')} secondes.")
    if not remplace and len(reg.routines) >= reglage("nombre_max"):
        return refus(f"Tu as déjà {reglage('nombre_max')} routines, supprimes-en une d'abord.")
    nom = str(args.get("nom") or "").strip()[:40] or retenues[0][:40].capitalize()
    reponse = str(args.get("reponse") or "").strip()[:120] or None
    maintenant = maison.maintenant()
    routine = {
        "id": f"r-{maintenant:%Y%m%d-%H%M}-{secrets.token_hex(1)}", "nom": nom, "auteur": ctx.personne,
        "pour": "auteur", "actif": True, "a_revoir": None,
        "declencheurs": [{"genre": "phrase", "phrases": retenues, "variantes": variantes,
                          "formes": [forme(p) for p in retenues + variantes]}],
        "etapes": etapes, "reponse": reponse, "phrase_de_creation": ctx.phrase_creation,
        "creee_le": maintenant.strftime(maison.FORMAT_HORODATAGE), "creee_par_appareil": ctx.appareil,
        "modifiee_le": None, "derniere_execution": None, "executions": 0}
    parole = decrire(routine, ctx, notes + retraits, ancien if remplace else None)
    return {"ok": True, "parole": parole, "routine": routine, "remplace": remplace}


# ----------------------------------------------------------------------------------------------- lancement
def lancer(routine, ctx, ha, question=None, reg=None, maintenant=time.monotonic):
    """Partie immédiate d'une routine (8.1). Renvoie (parole, suite) : suite est None ou une fonction sans argument
    qui fait la musique et les pauses restantes, à exécuter par l'appelant dans le contexte de la requête.

    ha : objet avec service(domaine, service, entity_id, donnees, confirmer) et musique(...). question : fonction
    texte vers réponse ou None. Une étape en échec ou refusée est sautée et dite, les suivantes continuent."""
    reg = reg or registre()
    nom = routine["nom"]
    t = maintenant()
    if not ctx.essai and t - reg.dernier_lancement.get(routine["id"], -1e9) < reglage("intervalle_min_s"):
        return "Je viens de la lancer.", None
    reg.dernier_lancement[routine["id"]] = t
    if ctx.entites is None:
        journal("refus", id=routine["id"], personne=ctx.personne, motif="inventaire indisponible")
        return "Je n'arrive pas à joindre la maison, je ne lance pas la routine.", None
    ctx.declencheurs = reg.formes_toutes()
    ctx.phrase_creation = routine.get("phrase_de_creation") or ""
    valides, echecs, dits = [], [], []
    ctx.echecs = echecs
    for e in routine["etapes"]:
        ok, motif = valider_etape(e, ctx)
        if ok:
            valides.append(ok)
        else:
            echecs.append(motif)
            if not routine.get("a_revoir"):
                routine["a_revoir"] = motif
    if routine.get("a_revoir") and len(valides) < len(routine["etapes"]):
        journal("revalidation échouée", id=routine["id"], motif=routine["a_revoir"], personne=ctx.personne)
    immediat, suite = [], []
    for i, e in enumerate(valides):
        if e["etape"] in ("musique", "pause"):
            immediat, suite = valides[:i], valides[i:]
            break
    else:
        immediat = valides
    corps = []
    for e in immediat:
        if e["etape"] == "service":
            res = ha.service(e["domaine"], e["service"], entity_id=e["entity_id"], donnees=e["donnees"] or None,
                             confirmer=False)
            if isinstance(res, dict) and res.get("erreur"):
                echecs.append(f"{_nommer(ctx, e['entity_id'])} n'a pas répondu." if "refus" not in str(res["erreur"])
                              else f"Je n'ai pas pu faire cela sur {_nommer(ctx, e['entity_id'])} : refusé.")
            else:
                corps.append(e)
        elif e["etape"] == "annonce":
            dits.append(e["texte"])
        elif e["etape"] == "question":
            rep = None
            if question is not None:
                try:
                    rep = question(e["texte"])
                except Exception as exc:  # LLM injoignable : on continue
                    print(f"routines : question sans réponse ({exc.__class__.__name__})")
            dits.append(rep.strip() if rep else "Je n'ai pas eu la réponse à la question.")
    if corps and not ctx.essai:
        for e in corps:
            if e["domaine"] in ("light", "switch", "fan") and e["service"] in ("turn_on", "turn_off"):
                manquantes = ha.confirmer(f"{e['domaine']}.{e['service']}", {"entity_id": e["entity_id"]}, delai=1.0)
                for m in manquantes or []:
                    echecs.append(f"{ctx.noms.get(m, m)} n'a pas répondu.")
    parole = " ".join([routine.get("reponse") or f"Routine {nom} lancée."] + dits + echecs).strip()

    def faire_suite():
        retards = []
        for e in suite:
            if e["etape"] == "pause":
                if not ctx.essai:
                    time.sleep(min(float(e["secondes"]), reglage("pause_max_s")))
            elif e["etape"] == "musique":
                if ctx.essai:
                    journal("étape sautée", id=routine["id"], etape="musique", essai=True)
                    continue
                res = ha.musique(e["recherche"], e["type"], e["enceinte"], e.get("artiste", ""))
                if isinstance(res, dict) and (res.get("erreur") or res.get("attention")):
                    retards.append(res.get("erreur") or res.get("attention"))
        fin = echecs + retards
        if not ctx.essai:
            reg.noter_execution(routine["id"], "ok" if not fin else "partiel", fin)
        journal("exécution", id=routine["id"], personne=ctx.personne, essai=ctx.essai, echecs=fin, suite=True)

    if suite:
        return parole, faire_suite
    if not ctx.essai:
        reg.noter_execution(routine["id"], "ok" if not echecs else "partiel", echecs)
    journal("exécution", id=routine["id"], personne=ctx.personne, essai=ctx.essai, echecs=echecs)
    return parole, None
