"""Écran Routines du client web (lot S-W6) : ce qu'un navigateur associé voit et fait des routines.

Ce module ne lance rien lui-même. Le serveur web lui passe le rôle de l'appareil associé et son identité, le moteur
(routines.py, Assistant.routines_reseau) fait le reste avec le même contexte de requête que pour une tablette. Il tient
quatre choses :
- le schéma strict des six messages (routines, routine_lancer, routine_activer, routine_supprimer, routine_texte,
  routines_export) : un champ en trop, en moins ou du mauvais type, et le message est refusé avant d'aller plus loin ;
- les droits par rôle, ceux de acces.TYPES_PAR_ROLE : lister, lancer et dicter pour tout rôle, couper et supprimer
  pour l'administrateur et l'habitant, exporter pour l'administrateur seulement ;
- la personne de la requête, tirée de la session et jamais du message : le propriétaire pour un administrateur,
  l'identité de l'appareil (« web:... ») pour un habitant, personne pour un invité ;
- la projection envoyée au navigateur : chaque routine dite en mots, avec un bloc « droits » calculé ici par le moteur.
  Le navigateur n'invente aucun droit. L'auteur brut et l'identifiant technique des étapes ne partent que vers le
  propriétaire.

Ce qu'il ne fait jamais : lire une personne, un rôle ou un essai dans le message, laisser partir le texte d'une
exception, répondre sur le port 8765 (le serveur des tablettes a ses propres messages).
"""
import re
from datetime import datetime, timedelta

import acces
import maison
import routines as R

GENRES = frozenset({"routines", "routine_lancer", "routine_activer", "routine_supprimer", "routine_texte",
                    "routines_export"})
# Un lancement ou un texte passe sous le verrou du moteur, comme une commande dite à voix haute.
SOUS_VERROU = frozenset({"routine_lancer", "routine_texte"})
CLES = {
    "routines": frozenset({"type"}),
    "routine_lancer": frozenset({"type", "id"}),
    "routine_activer": frozenset({"type", "id", "actif"}),
    "routine_supprimer": frozenset({"type", "id"}),
    "routine_texte": frozenset({"type", "texte"}),
    "routines_export": frozenset({"type"}),
}
IDENT = re.compile(r"^[a-z0-9_-]{1,80}$")
TEXTE_MAX = 500
ECHECS_MAX = 3

# Causes renvoyées au navigateur (liste fermée, jamais un texte venu d'ailleurs).
CAUSES = frozenset({"droit", "format", "indisponible", "inconnue"})
PREFIXE_WEB = "web:"


class RefusRoutines(Exception):
    """Un message de routines refusé avant d'avoir touché au moteur."""

    def __init__(self, cause):
        assert cause in CAUSES, cause
        super().__init__(cause)
        self.cause = cause


# ------------------------------------------------------------------ schéma et droits
def valider(genre, msg, role):
    """Lève RefusRoutines si le message n'a pas exactement le schéma attendu ou si le rôle n'a pas ce droit."""
    if genre not in GENRES or not isinstance(msg, dict) or set(msg) != CLES[genre]:
        raise RefusRoutines("format")
    if "id" in msg and not (isinstance(msg["id"], str) and IDENT.match(msg["id"])):
        raise RefusRoutines("format")
    if "actif" in msg and not isinstance(msg["actif"], bool):
        raise RefusRoutines("format")
    if "texte" in msg and not (isinstance(msg["texte"], str) and 0 < len(msg["texte"].strip()) <= TEXTE_MAX):
        raise RefusRoutines("format")
    if not acces.type_permis(role, genre):
        raise RefusRoutines("droit")


def personne_de(role, identite):
    """Personne de la requête, tirée de la session. Le préfixe « web: » ne peut jamais valoir la clé du propriétaire :
    un habitant associé ne gère donc que les routines dont il est l'auteur, jamais celles des autres."""
    if role == "administrateur":
        return acces.cle_habitant(maison.CLE_PROPRIETAIRE) or maison.CLE_PROPRIETAIRE
    if role == "habitant" and isinstance(identite, str) and identite.startswith(PREFIXE_WEB):
        return identite
    return ""


def contexte(role, personne):
    """Contexte léger du moteur, le même que celui de Assistant.contexte_routines(complet=False) pour les droits."""
    return R.Contexte(personne=personne, role=role)


# ------------------------------------------------------------------ mots
def _quand(horodatage, maintenant=None):
    """« aujourd'hui à 18 h 42 », « hier à 7 h 05 », « le 12/10 à 18 h 42 » ou None."""
    try:
        t = datetime.strptime(str(horodatage), maison.FORMAT_HORODATAGE)
    except ValueError:
        return None
    jour = (maintenant or maison.maintenant()).date()
    heure = f"{t.hour} h {t.minute:02d}"
    if t.date() == jour:
        return f"aujourd'hui à {heure}"
    if t.date() == jour - timedelta(days=1):
        return f"hier à {heure}"
    return f"le {t:%d/%m/%Y} à {heure}"


def _jour(horodatage):
    try:
        return f"le {datetime.strptime(str(horodatage), maison.FORMAT_HORODATAGE):%d/%m/%Y}"
    except ValueError:
        return None


def _nom_lisible(entity_id):
    """Repli quand Home Assistant ne donne pas de nom : « light.salon_plafond » devient « salon plafond »."""
    return entity_id.split(".", 1)[-1].replace("_", " ").strip() or entity_id


def _majuscule(texte):
    return texte[:1].upper() + texte[1:] if texte else texte


def _auteur(auteur, personne, proprietaire):
    """Qui a créé la routine, en mots. Seul le propriétaire voit le prénom d'un habitant déclaré."""
    if auteur and auteur == personne:
        return "toi"
    if auteur == maison.CLE_PROPRIETAIRE:
        return "le propriétaire"
    if proprietaire and auteur and not auteur.startswith(PREFIXE_WEB) and acces.cle_habitant(auteur):
        return auteur.capitalize()
    if proprietaire and auteur and auteur.startswith(PREFIXE_WEB):
        return "un appareil associé"
    return "un habitant"


def _etapes(routine, nommer, proprietaire):
    """Chaque étape en mots. L'identifiant technique (domaine.service sur entity_id) ne part que vers le propriétaire."""
    noms = {}
    for e in routine["etapes"]:
        for c in (e.get("entity_id") or []) if e.get("etape") == "service" else []:
            nom = None
            try:
                nom = nommer(c)
            except Exception:
                nom = None
            noms[c] = nom if isinstance(nom, str) and nom and nom != c else _nom_lisible(c)
    ctx = R.Contexte(noms=noms, statique=True)
    sortie = []
    for e in routine["etapes"]:
        try:
            texte = _majuscule(R._decrire_etape(e, ctx))
        except (KeyError, TypeError, ValueError):
            texte = "Étape illisible"
        technique = None
        if proprietaire and e.get("etape") == "service":
            technique = f"{e.get('domaine')}.{e.get('service')} sur {', '.join(e.get('entity_id') or [])}"
        sortie.append({"texte": texte, "technique": technique})
    return sortie


def _execution(derniere, n_etapes, proprietaire):
    if not isinstance(derniere, dict):
        return None
    echecs = [str(x) for x in (derniere.get("echecs") or []) if x][:ECHECS_MAX]
    if derniere.get("resultat") == "ok" and not echecs:
        resultat = f"Réussie, {n_etapes} étape{'s' if n_etapes > 1 else ''} sur {n_etapes}"
    else:
        n = len(derniere.get("echecs") or [])
        resultat = f"Partielle, {n} étape{'s' if n > 1 else ''} en échec" if n else "Partielle"
    return {"quand": _quand(derniere.get("le")), "resultat": resultat, "ok": derniere.get("resultat") == "ok",
            "echecs": echecs}


def projeter(routine, ctx, nommer):
    """Une routine telle que ce navigateur a le droit de la voir, avec ses droits décidés par le moteur."""
    proprietaire = R.qui_est(ctx) == "proprietaire"
    d = routine["declencheurs"][0] if routine.get("declencheurs") else {"phrases": [], "variantes": []}
    auteur = str(routine.get("auteur") or "")
    auteur_nom = _auteur(auteur, ctx.personne, proprietaire)
    peut_gerer = R.peut_gerer(routine, ctx)
    gerants = "le propriétaire" if auteur == maison.CLE_PROPRIETAIRE or not auteur else f"le propriétaire et {auteur_nom}"
    n = len(routine["etapes"])
    return {
        "id": routine["id"], "nom": routine["nom"], "actif": bool(routine["actif"]),
        "a_revoir": routine.get("a_revoir") if proprietaire or peut_gerer else None,
        "phrases": list(d["phrases"]), "variantes": list(d["variantes"]),
        "etapes": n, "etapes_mots": _etapes(routine, nommer, proprietaire),
        "pour": routine.get("pour"),
        "lanceurs": "tout le monde" if routine.get("pour") == "tous" else f"{auteur_nom} seulement",
        "auteur_nom": auteur_nom, "gerants": gerants,
        "creee": _jour(routine.get("creee_le")),
        "derniere_execution": _execution(routine.get("derniere_execution"), n, proprietaire),
        "executions": int(routine.get("executions") or 0),
        "droits": {"lancer": R.peut_lancer(routine, ctx), "couper": peut_gerer,
                   "supprimer": peut_gerer},
    }


# ------------------------------------------------------------------ réponses
def reponse_web(genre, rep, role, personne, nommer=None, ident=None):
    """Traduit la réponse du moteur (champ « etat ») en message du client web (champ « type »). Le moteur confond
    « inconnue » et « non permise » : une routine que ce navigateur voit mais ne gère pas devient un refus de droit,
    une routine qu'il ne voit pas reste inconnue (son existence ne fuit pas)."""
    nommer = nommer or (lambda x: x)
    etat = rep.get("etat") if isinstance(rep, dict) else None
    if etat == "routines":
        ctx = contexte(role, personne)
        reg = R.registre()
        liste = []
        for resume in rep.get("routines") or []:
            r = reg.par_id(resume.get("id"))
            if r is not None:
                liste.append(projeter(r, ctx, nommer))
        droits = rep.get("droits") or {}
        return {"type": "routines", "routines": liste, "version": rep.get("version"),
                "droits": {"exporter": bool(droits.get("exporter")), "tout_gerer": bool(droits.get("tout_gerer"))}}
    if etat == "routine_lancee":
        return {"type": "routine_lancee", "id": rep.get("id"), "ok": bool(rep.get("ok")),
                "parole": str(rep.get("parole") or ""), "echecs": [str(x) for x in rep.get("echecs") or []][:ECHECS_MAX]}
    if etat == "routine_ok":
        return {"type": "routine_ok", "genre": genre, "id": rep.get("id")}
    if etat == "routine_texte":
        return {"type": "routine_texte", "parole": str(rep.get("parole") or ""),
                "confirmation_attendue": rep.get("confirmation_attendue") or 0}
    if etat == "routines_export":
        return {"type": "routines_export", "contenu": rep.get("contenu")}
    if etat == "refuse":
        motif = str(rep.get("message") or "")
        cause = "droit" if "propriétaire" in motif else ("indisponible" if "désactivées" in motif else "inconnue")
        if cause == "inconnue" and ident:
            ctx = contexte(role, personne)
            r = R.registre().par_id(ident)
            if r is not None and r in R.registre().visibles(ctx) and not R.peut_gerer(r, ctx):
                cause = "droit"
        return {"type": "erreur", "cause": cause, "genre": genre}
    return {"type": "erreur", "cause": "indisponible", "genre": genre}
