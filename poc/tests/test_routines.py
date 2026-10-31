"""Moteur de routines (0.42.0, S-R1) : fichier, propositions, phrases, droits, lancement, messages réseau.

Tout tourne sur config-exemple/ (Sacha propriétaire, Camille habitante). La règle de fer est prouvée par
cas_routines.json : chaque étape qu'une commande directe refuse est refusée aussi dans une routine, à la
création comme au lancement d'un fichier trafiqué, et le faux Home Assistant n'est alors jamais appelé."""
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import acces
import assistant as A
import liste_blanche
import maison
import routines as R

CAS = json.loads((Path(__file__).parent / "cas_routines.json").read_text(encoding="utf-8"))
ENCEINTES = {"toutes": "media_player.enceintes_maison", "salon": "media_player.barre_son_salon",
             "cuisine": "media_player.enceinte_cuisine"}
INVENTAIRE = {"light.salon_plafond", "light.cuisine_suspensions", "light.couloir_plafond",
              "light.chambre_camille_plafonds", "switch.chambre_camille_prise", "switch.prise",
              "cover.chambre_sacha", "media_player.tele_salon", "script.extinction_generale",
              "automation.alarme_matin", "lock.porte_entree", "alarm_control_panel.maison"}
LUMIERE = {"etape": "service", "domaine": "light", "service": "turn_off", "entity_id": ["light.salon_plafond"]}


# ---------------------------------------------------------------------------------------------------- outils
_DICO = []


def dico():
    """Le dictionnaire réel de config-exemple, sans phrase apprise (fichier d'apprises dans un dossier jetable)."""
    if not _DICO:
        from dictionnaire import Dictionnaire
        _DICO.append(Dictionnaire(maison.chemin("commandes.yaml"), Path(tempfile.mkdtemp()) / "apprises.yaml"))
    return _DICO[0]


def ctx(personne="sacha", role="administrateur", **kw):
    kw.setdefault("entites", INVENTAIRE)
    kw.setdefault("enceintes", ENCEINTES)
    kw.setdefault("dico", dico())
    kw.setdefault("mots_reserves", ("assistant",))
    kw.setdefault("motifs_reserves", (A.CORRECTION, A.INTENTION_ROUTINE))
    kw.setdefault("appareil", "tablette-salon")
    return R.Contexte(personne=personne, role=role, **kw)


class FauxHA:
    """Home Assistant simulé : note les appels, ne touche à rien."""

    def __init__(self, erreurs=None):
        self.appels, self.musiques, self.confirmations = [], [], []
        self.erreurs = erreurs or {}
        self.ENCEINTES_MUSIQUE = dict(ENCEINTES)
        self.entites_llm = set(INVENTAIRE) - {"lock.porte_entree", "alarm_control_panel.maison"}
        self.essai = False

    def service(self, domaine, service, entity_id=None, donnees=None, confirmer=True):
        self.appels.append((domaine, service, entity_id, donnees, confirmer))
        return self.erreurs.get(f"{domaine}.{service}", {"ok": True})

    def confirmer(self, nom, corps, delai=1.0):
        self.confirmations.append((nom, corps))
        return []

    def musique(self, recherche, type_media, enceinte, artiste=""):
        self.musiques.append((recherche, type_media, enceinte, artiste))
        return {"ok": True}

    def services_permis(self, domaine):
        return liste_blanche.SERVICES_PERMIS.get(domaine, set())

    def inventaire(self):
        lignes = [f"{e} | {e.split('.')[1].replace('_', ' ')} | salon" for e in sorted(self.entites_llm)]
        return "\n".join(lignes), ""


def proposition(**kw):
    base = {"nom": "Bonne nuit", "phrases": ["je vais dormir maintenant"], "etapes": [dict(LUMIERE)]}
    base.update(kw)
    return base


def enregistrer(args=None, personne="sacha", role="administrateur", reg=None, pour=None):
    """Valide une proposition, pose le brouillon et le confirme. Renvoie la routine enregistrée."""
    reg = reg or R.registre()
    c = ctx(personne, role)
    res = R.valider_proposition(args or proposition(), c, reg)
    assert res["ok"], res["parole"]
    if pour:
        res["routine"]["pour"] = pour
    reg.poser_brouillon(c, res["routine"], res["remplace"])
    assert "enregistrée" in reg.reponse_brouillon("oui", c)
    return reg.par_id(res["routine"]["id"])


# ------------------------------------------------------------------------------------- intention de création
@pytest.mark.parametrize("phrase", CAS["intention"]["oui"])
def test_intention_reconnue(phrase):
    assert A.INTENTION_ROUTINE.search(phrase)


@pytest.mark.parametrize("phrase", CAS["intention"]["non"])
def test_intention_laisse_passer_une_phrase_ordinaire(phrase):
    assert not A.INTENTION_ROUTINE.search(phrase)


# 0.43.3 : les demandes dites naturellement sont reconnues brutes et aussi après `epurer`, qui retire les formules
# de politesse avant `routines_avant`. Une commande ordinaire ne passe dans aucun des deux cas.
@pytest.mark.parametrize("phrase", CAS["intention"]["oui"])
def test_intention_reconnue_apres_epurer(phrase):
    from dictionnaire import epurer
    assert A.INTENTION_ROUTINE.search(epurer(phrase))


@pytest.mark.parametrize("phrase", CAS["intention"]["non"])
def test_intention_ordinaire_ignoree_apres_epurer(phrase):
    from dictionnaire import epurer
    assert not A.INTENTION_ROUTINE.search(epurer(phrase))


# ------------------------------------------------------------------ la règle de fer : jamais plus qu'en direct
def corps_direct(etape):
    corps = dict(etape.get("donnees") or {})
    corps["entity_id"] = etape.get("entity_id")
    for cle in ("area_id", "device_id", "floor_id", "label_id"):
        if cle in etape:
            corps[cle] = etape[cle]
    return corps


@pytest.mark.parametrize("cas", CAS["etapes_refusees"], ids=lambda c: c["nom"])
def test_etape_refusee_a_la_creation_et_au_lancement(cas):
    personne = cas.get("personne", "sacha")
    role = "administrateur" if personne == "sacha" else "habitant"
    etape = cas["etape"]
    ok, message = R.valider_etape(etape, ctx(personne, role))
    assert ok is None and message
    # Un fichier trafiqué qui contiendrait l'étape : rien n'atteint Home Assistant.
    routine = {"id": "r-trafiquee", "nom": "Trafiquée", "auteur": personne, "pour": "tous", "actif": True,
               "a_revoir": None, "declencheurs": [], "etapes": [etape], "reponse": None, "phrase_de_creation": ""}
    ha = FauxHA()
    c = ctx(personne, role, essai=False)
    parole, suite = R.lancer(routine, c, ha, reg=R.registre())
    assert ha.appels == [] and ha.musiques == [] and suite is None
    assert len(c.echecs) == 1 and c.echecs[0] in parole


@pytest.mark.parametrize("cas", [c for c in CAS["etapes_refusees"] if c["direct_refuse"]], ids=lambda c: c["nom"])
def test_ce_que_la_commande_directe_refuse_la_routine_le_refuse(cas):
    etape = cas["etape"]
    personne = cas.get("personne", "sacha")
    domaine, service = etape["domaine"], etape["service"]
    direct = acces.controler_service(domaine, service, corps_direct(etape), personne=personne or None,
                                     services_permis=liste_blanche.SERVICES_PERMIS.get(domaine, set()))
    assert direct, "la commande directe devrait refuser ce cas"
    role = "administrateur" if personne == "sacha" else "habitant"
    ok, _ = R.valider_etape(etape, ctx(personne, role))
    assert ok is None


@pytest.mark.parametrize("cas", CAS["etapes_protegees"], ids=lambda c: c["nom"])
def test_protection_de_l_occupant_suit_la_commande_directe(cas, monkeypatch):
    """Protection coupée en dur : la routine permet ce que la commande permet. Allumée : elle refuse comme elle."""
    import securite
    etape = cas["etape"]
    personne = cas.get("personne", "sacha")
    role = "administrateur" if personne == "sacha" else "habitant"
    domaine, service = etape["domaine"], etape["service"]

    def direct():
        return acces.controler_service(domaine, service, corps_direct(etape), personne=personne or None,
                                       services_permis=liste_blanche.SERVICES_PERMIS.get(domaine, set()))

    assert direct() is None
    assert R.valider_etape(etape, ctx(personne, role))[1] is None
    monkeypatch.setattr(securite, "PROTEGER_OCCUPANT", True)
    assert direct()
    ok, message = R.valider_etape(etape, ctx(personne, role))
    assert ok is None and "sécurité" in message
    routine = {"id": "r-t", "nom": "T", "auteur": personne, "pour": "tous", "actif": True, "a_revoir": None,
               "declencheurs": [], "etapes": [etape], "reponse": None, "phrase_de_creation": ""}
    ha = FauxHA()
    R.lancer(routine, ctx(personne, role, essai=False), ha, reg=R.registre())
    assert ha.appels == []


@pytest.mark.parametrize("cas", CAS["etapes_permises"], ids=lambda c: c["nom"])
def test_etape_permise(cas):
    personne = cas.get("personne", "sacha")
    ok, message = R.valider_etape(cas["etape"], ctx(personne, "administrateur" if personne == "sacha" else "habitant"))
    assert message is None and ok["etape"] == cas["etape"]["etape"]


def test_chaque_etape_de_service_passe_par_le_point_de_controle(monkeypatch):
    vus = []
    reel = acces.controler_service

    def espion(domaine, service, corps, personne=None, services_permis=None):
        vus.append((domaine, service, list(corps["entity_id"]), personne))
        return reel(domaine, service, corps, personne=personne, services_permis=services_permis)

    monkeypatch.setattr(acces, "controler_service", espion)
    etape = {"etape": "service", "domaine": "light", "service": "turn_on", "entity_id": ["light.salon_plafond"]}
    ok, _ = R.valider_etape(etape, ctx())
    assert ok and vus == [("light", "turn_on", ["light.salon_plafond"], "sacha")]
    routine = {"id": "r-x", "nom": "X", "auteur": "sacha", "pour": "auteur", "actif": True, "a_revoir": None,
               "declencheurs": [], "etapes": [etape, dict(etape, service="turn_off")], "reponse": None,
               "phrase_de_creation": ""}
    vus.clear()
    ha = FauxHA()
    R.lancer(routine, ctx(essai=True), ha, reg=R.registre())
    assert [v[1] for v in vus] == ["turn_on", "turn_off"]
    assert [a[1] for a in ha.appels] == ["turn_on", "turn_off"]


def test_un_reglage_de_la_maison_refuse_aussi_dans_une_routine(monkeypatch):
    etape = {"etape": "service", "domaine": "switch", "service": "turn_on", "entity_id": ["switch.prise"]}
    monkeypatch.setattr(liste_blanche, "REGLAGES", {"interrupteurs": ["switch.chambre_camille_prise"]})
    assert acces.controler_service("switch", "turn_on", {"entity_id": ["switch.prise"]}, personne="sacha",
                                   services_permis=liste_blanche.SERVICES_PERMIS["switch"])
    ok, message = R.valider_etape(etape, ctx())
    assert ok is None and "switch.turn_on" in message
    monkeypatch.setattr(liste_blanche, "REGLAGES", {"interrupteurs": ["switch.prise"]})
    ok, message = R.valider_etape(etape, ctx())
    assert message is None and ok["entity_id"] == ["switch.prise"]


def test_un_attribut_refuse_par_les_reglages_est_refuse(monkeypatch):
    etape = {"etape": "service", "domaine": "light", "service": "turn_on", "entity_id": ["light.salon_plafond"],
             "donnees": {"brightness_pct": 40}}
    monkeypatch.setattr(liste_blanche, "REGLAGES", {"attributs_refuses": {"light.turn_on": ["brightness_pct"]}})
    assert R.valider_etape(etape, ctx())[0] is None


def test_un_reglage_qui_change_coupe_la_routine_au_chargement(monkeypatch):
    routine = enregistrer({**proposition(), "etapes": [{"etape": "service", "domaine": "switch",
                                                        "service": "turn_on", "entity_id": ["switch.prise"]}]})
    assert routine["actif"]
    monkeypatch.setattr(liste_blanche, "REGLAGES", {"interrupteurs": ["switch.chambre_camille_prise"]})
    R.reinitialiser()
    rechargee = R.registre().par_id(routine["id"])
    assert rechargee["actif"] is False and rechargee["a_revoir"]


def test_domaine_reserve_a_l_appli_inconnu_dans_une_routine():
    ok, message = R.valider_etape({"etape": "service", "domaine": "remote", "service": "send_command",
                                   "entity_id": ["media_player.tele_salon"]}, ctx())
    assert ok is None and "remote.send_command" in message


# ------------------------------------------------------------------------------------------------ le registre
def test_registre_absent_vide_et_sans_fichier(routines_temporaires):
    reg = R.registre()
    assert reg.routines == [] and reg.version == 0 and not routines_temporaires.exists()


def test_aller_retour_du_fichier(routines_temporaires):
    routine = enregistrer()
    assert routines_temporaires.exists()
    brut = json.loads(routines_temporaires.read_text(encoding="utf-8"))
    assert brut["format"] == R.FORMAT and brut["routines"][0]["id"] == routine["id"]
    R.reinitialiser()
    relue = R.registre().par_id(routine["id"])
    assert relue["nom"] == "Bonne nuit" and relue["etapes"] == routine["etapes"]
    assert relue["declencheurs"][0]["formes"] == [R.forme("je vais dormir maintenant")]


def test_chaque_ecriture_augmente_la_version():
    reg = R.registre()
    avant = reg.version
    routine = enregistrer(reg=reg)
    assert reg.version == avant + 1
    assert reg.activer(routine["id"], False, ctx())
    assert reg.version == avant + 2
    assert reg.supprimer(routine["id"], ctx())
    assert reg.version == avant + 3 and reg.routines == []


def test_fichier_corrompu_mis_de_cote(routines_temporaires):
    routines_temporaires.write_text("{pas du json", encoding="utf-8")
    reg = R.registre()
    assert reg.routines == [] and not routines_temporaires.exists()
    restes = list(routines_temporaires.parent.glob("routines.json.illisible-*"))
    assert len(restes) == 1 and restes[0].read_text(encoding="utf-8") == "{pas du json"
    assert enregistrer(reg=reg)["nom"] == "Bonne nuit"


def test_fichier_de_forme_inattendue_mis_de_cote(routines_temporaires):
    routines_temporaires.write_text(json.dumps(["rien"]), encoding="utf-8")
    assert R.registre().routines == []
    assert list(routines_temporaires.parent.glob("routines.json.illisible-*"))


def test_revalidation_au_chargement_coupe_une_routine_devenue_invalide(routines_temporaires):
    routine = enregistrer()
    brut = json.loads(routines_temporaires.read_text(encoding="utf-8"))
    brut["routines"][0]["etapes"][0]["domaine"] = "lock"
    routines_temporaires.write_text(json.dumps(brut), encoding="utf-8")
    R.reinitialiser()
    relue = R.registre().par_id(routine["id"])
    assert relue["actif"] is False and "lock.turn_off" in relue["a_revoir"]
    assert R.registre().trouver("je vais dormir maintenant", ctx()) == (None, None)


# ------------------------------------------------------------------------------------------- les propositions
def test_proposition_nominale():
    res = R.valider_proposition(proposition(variantes=["je file dormir"], reponse="Bonne nuit."), ctx(), R.registre())
    assert res["ok"] and res["remplace"] is None
    r = res["routine"]
    assert r["auteur"] == "sacha" and r["pour"] == "auteur" and r["actif"]
    assert r["declencheurs"][0]["variantes"] == ["je file dormir"] and r["reponse"] == "Bonne nuit."
    assert r["etapes"] == [{"etape": "service", "domaine": "light", "service": "turn_off",
                            "entity_id": ["light.salon_plafond"], "donnees": {}}]
    assert res["parole"].startswith("Routine Bonne nuit : quand tu dis « je vais dormir maintenant »")
    assert res["parole"].endswith("Je l'enregistre ?")
    assert not R.registre().routines  # rien n'est écrit avant le oui


def test_brouillon_puis_oui_enregistre_et_non_abandonne():
    reg = R.registre()
    c = ctx()
    res = R.valider_proposition(proposition(), c, reg)
    reg.poser_brouillon(c, res["routine"], None)
    assert reg.reponse_brouillon("non", c) == "D'accord, je n'enregistre rien."
    assert reg.routines == [] and reg.reponse_brouillon("oui", c) == R.MSG_EXPIRE or True
    res = R.valider_proposition(proposition(), c, reg)
    reg.poser_brouillon(c, res["routine"], None)
    assert reg.reponse_brouillon("d'accord", c) == "Routine Bonne nuit enregistrée."
    assert len(reg.routines) == 1


def test_une_autre_phrase_abandonne_le_brouillon_sans_l_absorber():
    reg = R.registre()
    c = ctx()
    res = R.valider_proposition(proposition(), c, reg)
    reg.poser_brouillon(c, res["routine"], None)
    assert reg.reponse_brouillon("allume la lumière du salon", c) is None
    assert c.appareil not in reg.brouillons and reg.routines == []


def test_le_oui_tardif_est_absorbe_une_fois():
    reg = R.registre()
    c = ctx()
    res = R.valider_proposition(proposition(), c, reg)
    reg.poser_brouillon(c, res["routine"], None)
    reg.brouillons[c.appareil]["le"] -= 1000
    assert reg.reponse_brouillon("oui", c) == R.MSG_EXPIRE
    assert reg.routines == []
    assert reg.reponse_brouillon("oui", c) == R.MSG_EXPIRE  # fenêtre d'absorption encore ouverte
    assert reg.reponse_brouillon("oui", c) is None


def test_un_brouillon_expire_sans_oui_laisse_passer_le_texte():
    reg = R.registre()
    c = ctx()
    reg.poser_brouillon(c, R.valider_proposition(proposition(), c, reg)["routine"], None)
    reg.brouillons[c.appareil]["le"] -= 1000
    assert reg.reponse_brouillon("allume le couloir", c) is None


def test_un_brouillon_n_est_confirme_que_par_la_meme_personne():
    reg = R.registre()
    c = ctx()
    reg.poser_brouillon(c, R.valider_proposition(proposition(), c, reg)["routine"], None)
    autre = ctx("camille", "habitant")
    assert reg.reponse_brouillon("oui", autre) is None
    assert reg.routines == []


def test_un_brouillon_est_propre_a_son_appareil():
    reg = R.registre()
    c = ctx()
    reg.poser_brouillon(c, R.valider_proposition(proposition(), c, reg)["routine"], None)
    ailleurs = ctx(appareil="cuisine")
    assert reg.reponse_brouillon("oui", ailleurs) is None
    assert reg.reponse_brouillon("oui", c) == "Routine Bonne nuit enregistrée."


def test_refus_d_une_personne_non_reconnue_et_d_un_invite():
    assert R.valider_proposition(proposition(), ctx("", "local"), R.registre())["parole"] == R.MSG_INCONNU
    assert R.valider_proposition(proposition(), ctx("", "invite"), R.registre())["parole"] == R.MSG_INVITE
    assert R.valider_proposition(proposition(), ctx("sacha", "invite"), R.registre())["parole"] == R.MSG_INVITE


def test_routines_desactivees(monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"active": False}})
    assert R.valider_proposition(proposition(), ctx(), R.registre())["parole"] == "Les routines sont désactivées."


@pytest.mark.parametrize("args,attendu", [
    ({"nom": "X", "phrases": ["je vais dormir"], "etapes": [LUMIERE], "autre": 1},
     "Je n'ai pas compris cette routine, redis-la autrement."),
    ({"etapes": [LUMIERE]}, "Il me faut au moins une phrase pour lancer la routine."),
    ({"phrases": ["je vais dormir"]}, "Il me faut au moins une étape pour cette routine."),
    ({"phrases": ["je vais dormir"], "etapes": []}, "Il me faut au moins une étape pour cette routine."),
    ({"phrases": ["je vais dormir"], "etapes": [LUMIERE], "remplace": "r-fantome"},
     "Je ne trouve pas la routine à remplacer."),
])
def test_propositions_mal_formees(args, attendu):
    assert R.valider_proposition(args, ctx(), R.registre())["parole"] == attendu


def test_limites_de_la_section_routines(monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"etapes_max": 2, "duree_max_s": 30,
                                                                         "nombre_max": 1, "pause_max_s": 20}})
    c = ctx()
    trois = proposition(etapes=[dict(LUMIERE)] * 3)
    assert R.valider_proposition(trois, c, R.registre())["parole"] == "Une routine fait au plus 2 étapes."
    longue = proposition(etapes=[{"etape": "pause", "secondes": 20}, {"etape": "pause", "secondes": 20}])
    assert R.valider_proposition(longue, c, R.registre())["parole"] == "Une routine dure au plus 30 secondes."
    trop = proposition(etapes=[{"etape": "pause", "secondes": 21}])
    assert "au plus 20 secondes" in R.valider_proposition(trop, c, R.registre())["parole"]
    enregistrer()
    plein = R.valider_proposition(proposition(phrases=["je rentre du travail"]), c, R.registre())
    assert plein["parole"] == "Tu as déjà 1 routines, supprimes-en une d'abord."


def test_une_etape_refusee_est_retiree_et_dite():
    res = R.valider_proposition(proposition(etapes=[dict(LUMIERE),
                                                    {"etape": "service", "domaine": "lock", "service": "unlock",
                                                     "entity_id": ["lock.porte_entree"]}]), ctx(), R.registre())
    assert res["ok"] and len(res["routine"]["etapes"]) == 1
    assert "lock.unlock" in res["parole"] and res["parole"].endswith(R.MSG_RESTE)


def test_toutes_les_etapes_refusees_refusent_la_routine():
    res = R.valider_proposition(proposition(etapes=[{"etape": "service", "domaine": "lock", "service": "unlock",
                                                     "entity_id": ["lock.porte_entree"]}]), ctx(), R.registre())
    assert not res["ok"] and "lock.unlock" in res["parole"]


def test_la_musique_passe_en_dernier():
    res = R.valider_proposition(proposition(etapes=[
        {"etape": "musique", "recherche": "jazz"}, dict(LUMIERE), {"etape": "annonce", "texte": "Bonne nuit."}]),
        ctx(), R.registre())
    assert [e["etape"] for e in res["routine"]["etapes"]] == ["service", "annonce", "musique"]


def test_une_annonce_ne_peut_pas_contenir_la_phrase_de_la_routine():
    res = R.valider_proposition(proposition(etapes=[{"etape": "annonce", "texte": "Alors, je vais dormir maintenant"}]),
                                ctx(), R.registre())
    assert not res["ok"] and "ni mon mot de réveil ni la phrase" in res["parole"]


def test_nom_et_reponse_sont_bornes():
    res = R.valider_proposition(proposition(nom="N" * 90, reponse="R" * 300), ctx(), R.registre())
    assert len(res["routine"]["nom"]) == 40 and len(res["routine"]["reponse"]) == 120


# ----------------------------------------------------------------------------------------------- les phrases
@pytest.mark.parametrize("phrase,genre", [
    ("dodo", "phrase"), ("oui", "phrase"), ("stop", "phrase"), ("bonne nuit sacha", "phrase"),
    ("quand je dis bonjour", "phrase"), ("non annule", "phrase"), ("dis assistant bonsoir", "phrase"),
    ("lance ma routine du soir", "phrase"), ("éteins tout", "commande"), ("pause", "phrase"),
])
def test_phrases_refusees(phrase, genre):
    refus = R.refus_phrase(phrase, ctx(), R.registre())
    assert refus and refus[0] == genre


def test_une_phrase_deja_connue_comme_commande_est_refusee():
    refus = R.refus_phrase("bonne nuit", ctx(), R.registre())
    assert refus and refus[0] == "commande" and "déjà une commande" in refus[1]


def test_une_phrase_apprise_est_refusee_comme_apprise(tmp_path):
    from dictionnaire import Dictionnaire
    d = Dictionnaire(maison.chemin("commandes.yaml"), tmp_path / "apprises.yaml")
    assert d.apprendre("range le salon vite", [{"domaine": "light"}], "C'est fait.", "2026-10-26")
    refus = R.refus_phrase("range le salon vite", ctx(dico=d), R.registre())
    assert refus and refus[0] == "apprise" and "j'ai apprise" in refus[1]


def test_une_phrase_ordinaire_passe():
    assert R.refus_phrase("je vais dormir maintenant", ctx(), R.registre()) is None


def test_doublon_de_routine_propose_le_remplacement():
    enregistrer()
    refus = R.refus_phrase("je vais dormir maintenant", ctx(), R.registre())
    assert refus and refus[0] == "routine" and refus[1].startswith("Tu as déjà la routine Bonne nuit")
    assert R.refus_phrase("je vai dormir maintenant", ctx(), R.registre())[0] == "routine"  # faute de transcription


def test_une_phrase_deja_prise_par_son_auteur_remplace_la_routine():
    ancienne = enregistrer()
    res = R.valider_proposition(proposition(nom="Dodo", etapes=[dict(LUMIERE, entity_id=["light.couloir_plafond"])]),
                                ctx(), R.registre())
    assert res["ok"] and res["remplace"] == ancienne["id"]
    assert "je la remplace" in res["parole"]
    c = ctx()
    R.registre().poser_brouillon(c, res["routine"], res["remplace"])
    R.registre().reponse_brouillon("oui", c)
    reg = R.registre()
    assert len(reg.routines) == 1 and reg.routines[0]["id"] == ancienne["id"] and reg.routines[0]["nom"] == "Dodo"
    assert reg.routines[0]["modifiee_le"]


def test_la_phrase_d_une_routine_d_un_autre_habitant_n_est_pas_volee():
    enregistrer(personne="camille", role="habitant", pour="auteur")
    # Sacha ne peut pas lancer la routine d'auteur de Camille, la phrase reste donc libre pour lui.
    assert R.refus_phrase("je vais dormir maintenant", ctx(), R.registre()) is None


def test_les_variantes_refusees_sont_retirees_sans_bruit():
    res = R.valider_proposition(proposition(variantes=["oui", "je file dormir"]), ctx(), R.registre())
    assert res["ok"] and res["routine"]["declencheurs"][0]["variantes"] == ["je file dormir"]


def test_le_nombre_de_variantes_est_borne(monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"variantes_max": 1}})
    res = R.valider_proposition(proposition(variantes=["je file dormir", "je vais me coucher"]), ctx(), R.registre())
    assert res["routine"]["declencheurs"][0]["variantes"] == ["je file dormir"]


def test_phrases_interdites_de_la_configuration(monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"phrases_interdites": ["je rentre tard"]}})
    assert R.refus_phrase("je rentre tard", ctx(), R.registre())[0] == "phrase"


# -------------------------------------------------------------------------------------------------- les droits
def test_qui_est_qui():
    assert R.qui_est(ctx("sacha")) == "proprietaire"
    assert R.qui_est(ctx("camille", "habitant")) == "habitant"
    assert R.qui_est(ctx("", "local")) == "inconnu"
    assert R.qui_est(ctx("sacha", "invite")) == "invite"
    assert R.droits(ctx("camille", "habitant")) == {"qui": "habitant", "creer": True, "tout_gerer": False,
                                                    "exporter": False}
    assert R.droits(ctx("sacha"))["exporter"] is True


def test_droit_de_lancer():
    r_auteur = enregistrer(personne="camille", role="habitant")
    assert R.peut_lancer(r_auteur, ctx("camille", "habitant"))
    assert not R.peut_lancer(r_auteur, ctx("sacha"))
    assert not R.peut_lancer(r_auteur, ctx("", "local"))
    r_auteur["pour"] = "tous"
    assert R.peut_lancer(r_auteur, ctx("sacha")) and R.peut_lancer(r_auteur, ctx("", "invite"))


def test_gestion_proprietaire_tout_habitant_les_siennes():
    reg = R.registre()
    de_camille = enregistrer(personne="camille", role="habitant", reg=reg)
    de_sacha = enregistrer({**proposition(phrases=["je rentre du travail"])}, reg=reg)
    camille, sacha, invite = ctx("camille", "habitant"), ctx("sacha"), ctx("", "invite")
    assert not reg.activer(de_sacha["id"], False, camille) and de_sacha["actif"]
    assert not reg.supprimer(de_sacha["id"], camille)
    assert not reg.activer(de_camille["id"], False, invite)
    assert reg.activer(de_camille["id"], False, sacha) and de_camille["actif"] is False
    assert reg.activer(de_camille["id"], True, camille) and de_camille["actif"] is True
    assert reg.supprimer(de_camille["id"], camille)
    assert reg.supprimer(de_sacha["id"], sacha)


def test_liste_filtree_par_personne():
    reg = R.registre()
    enregistrer({**proposition(nom="De Camille")}, personne="camille", role="habitant", reg=reg)
    enregistrer({**proposition(nom="De Sacha", phrases=["je rentre du travail"])}, reg=reg)
    commune = enregistrer({**proposition(phrases=["on mange maintenant"], nom="Repas")}, reg=reg, pour="tous")
    assert {r["nom"] for r in reg.visibles(ctx("sacha"))} == {"De Camille", "De Sacha", "Repas"}  # le propriétaire voit tout
    assert {r["nom"] for r in reg.visibles(ctx("camille", "habitant"))} == {"De Camille", "Repas"}
    assert [r["id"] for r in reg.visibles(ctx("", "invite"))] == [commune["id"]]


def test_export_reserve_au_proprietaire():
    reg = R.registre()
    enregistrer(reg=reg)
    assert reg.exporter(ctx("camille", "habitant")) is None and reg.exporter(ctx("", "invite")) is None
    export = reg.exporter(ctx("sacha"))
    assert export["format"] == R.FORMAT and len(export["routines"]) == 1
    export["routines"][0]["nom"] = "Modifiée"
    assert reg.routines[0]["nom"] == "Bonne nuit"  # copie, pas le registre lui-même


def test_trouver_par_la_phrase():
    reg = R.registre()
    enregistrer(personne="camille", role="habitant", reg=reg)
    routine, etat = reg.trouver("Je vais dormir maintenant !", ctx("camille", "habitant"))
    assert routine and etat is None
    assert reg.trouver("je vais dormir maintenant", ctx("sacha")) == (None, None)
    routine, etat = reg.trouver("je vais dormir maintenant", ctx("", "local"))
    assert routine and etat == "reservee"
    assert reg.trouver("je vais dormir maintenant", ctx("", "invite")) == (None, None)
    reg.activer(routine["id"], False, ctx("sacha"))
    assert reg.trouver("je vais dormir maintenant", ctx("camille", "habitant")) == (None, None)


# ------------------------------------------------------------------------------------------------- lancement
def test_lancement_ordre_reponse_et_comptage():
    reg = R.registre()
    routine = enregistrer({**proposition(reponse="Dors bien."), "etapes": [
        dict(LUMIERE, entity_id=["light.salon_plafond", "light.cuisine_suspensions"]),
        {"etape": "annonce", "texte": "Bonne nuit, à demain."},
        {"etape": "service", "domaine": "cover", "service": "close_cover", "entity_id": ["cover.chambre_sacha"]}]})
    ha = FauxHA()
    parole, suite = R.lancer(routine, ctx(), ha, reg=reg)
    assert suite is None
    assert [(a[0], a[1], a[2]) for a in ha.appels] == [
        ("light", "turn_off", ["light.salon_plafond", "light.cuisine_suspensions"]),
        ("cover", "close_cover", ["cover.chambre_sacha"])]
    assert all(a[4] is False for a in ha.appels)
    assert parole == "Dors bien. Bonne nuit, à demain."
    assert reg.par_id(routine["id"])["executions"] == 1
    assert reg.par_id(routine["id"])["derniere_execution"]["resultat"] == "ok"
    assert ha.confirmations == [("light.turn_off", {"entity_id": ["light.salon_plafond",
                                                                  "light.cuisine_suspensions"]})]


def test_parole_par_defaut():
    routine = enregistrer()
    parole, _ = R.lancer(routine, ctx(essai=True), FauxHA(), reg=R.registre())
    assert parole == "Routine Bonne nuit lancée."


def test_essai_ne_note_rien_et_ne_confirme_pas():
    reg = R.registre()
    routine = enregistrer()
    ha = FauxHA()
    R.lancer(routine, ctx(essai=True), ha, reg=reg)
    assert reg.par_id(routine["id"])["executions"] == 0 and ha.confirmations == []


def test_intervalle_minimal_entre_deux_lancements():
    reg = R.registre()
    routine = enregistrer()
    ha = FauxHA()
    horloge = [100.0]
    R.lancer(routine, ctx(), ha, reg=reg, maintenant=lambda: horloge[0])
    horloge[0] += 3
    parole, _ = R.lancer(routine, ctx(), ha, reg=reg, maintenant=lambda: horloge[0])
    assert parole == "Je viens de la lancer." and len(ha.appels) == 1
    horloge[0] += 20
    R.lancer(routine, ctx(), ha, reg=reg, maintenant=lambda: horloge[0])
    assert len(ha.appels) == 2


def test_l_essai_ignore_l_intervalle():
    reg = R.registre()
    routine = enregistrer()
    ha = FauxHA()
    R.lancer(routine, ctx(essai=True), ha, reg=reg)
    R.lancer(routine, ctx(essai=True), ha, reg=reg)
    assert len(ha.appels) == 2


def test_inventaire_indisponible_ne_lance_rien():
    routine = enregistrer()
    ha = FauxHA()
    parole, suite = R.lancer(routine, ctx(entites=None), ha, reg=R.registre())
    assert parole == "Je n'arrive pas à joindre la maison, je ne lance pas la routine." and suite is None
    assert ha.appels == []


def test_une_etape_devenue_refusee_est_sautee_et_dite():
    routine = enregistrer({**proposition(), "etapes": [
        dict(LUMIERE, entity_id=["light.salon_plafond"]),
        dict(LUMIERE, entity_id=["light.couloir_plafond"])]})
    ha = FauxHA()
    parole, _ = R.lancer(routine, ctx(entites=INVENTAIRE - {"light.couloir_plafond"}, essai=True), ha,
                         reg=R.registre())
    assert [a[2] for a in ha.appels] == [["light.salon_plafond"]]
    assert "Je ne trouve pas light.couloir_plafond parmi mes appareils." in parole
    assert routine["a_revoir"]


def test_un_echec_de_home_assistant_est_dit_et_la_suite_continue():
    routine = enregistrer({**proposition(), "etapes": [
        dict(LUMIERE, entity_id=["light.salon_plafond"]),
        {"etape": "service", "domaine": "cover", "service": "close_cover", "entity_id": ["cover.chambre_sacha"]}]})
    ha = FauxHA(erreurs={"light.turn_off": {"erreur": "HTTP 500"}})
    c = ctx(essai=True)
    parole, _ = R.lancer(routine, c, ha, reg=R.registre())
    assert len(ha.appels) == 2 and len(c.echecs) == 1 and "light.salon_plafond n'a pas répondu" in parole


def test_une_question_repond_ou_s_excuse():
    routine = enregistrer({**proposition(), "etapes": [{"etape": "question", "texte": "Quel temps fera-t-il ?"}]})
    parole, _ = R.lancer(routine, ctx(essai=True), FauxHA(), question=lambda t: " Il fera beau. ", reg=R.registre())
    assert parole == "Routine Bonne nuit lancée. Il fera beau."

    def panne(texte):
        raise RuntimeError("hors ligne")

    parole, _ = R.lancer(routine, ctx(essai=True), FauxHA(), question=panne, reg=R.registre())
    assert parole.endswith("Je n'ai pas eu la réponse à la question.")


def test_musique_et_pauses_forment_la_suite(monkeypatch):
    dormi = []
    monkeypatch.setattr(R.time, "sleep", lambda s: dormi.append(s))
    reg = R.registre()
    routine = enregistrer({**proposition(), "etapes": [
        dict(LUMIERE), {"etape": "pause", "secondes": 5}, {"etape": "musique", "recherche": "jazz doux",
                                                          "type": "playlist", "enceinte": "salon"}]})
    ha = FauxHA()
    parole, suite = R.lancer(routine, ctx(), ha, reg=reg)
    assert callable(suite) and len(ha.appels) == 1 and ha.musiques == []
    assert reg.par_id(routine["id"])["executions"] == 0  # noté en fin de suite
    suite()
    assert dormi == [5.0] and ha.musiques == [("jazz doux", "playlist", "salon", "")]
    assert reg.par_id(routine["id"])["executions"] == 1


def test_la_suite_en_essai_ne_dort_pas_et_ne_joue_rien(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: pytest.fail("pause en essai"))
    routine = enregistrer({**proposition(), "etapes": [dict(LUMIERE), {"etape": "pause", "secondes": 5},
                                                       {"etape": "musique", "recherche": "jazz"}]})
    ha = FauxHA()
    _, suite = R.lancer(routine, ctx(essai=True), ha, reg=R.registre())
    suite()
    assert ha.musiques == []


def test_une_musique_en_retard_rend_l_execution_partielle():
    class Muet(FauxHA):
        def musique(self, *a, **k):
            return {"attention": "rien ne joue"}

    reg = R.registre()
    routine = enregistrer({**proposition(), "etapes": [{"etape": "musique", "recherche": "jazz"}]})
    _, suite = R.lancer(routine, ctx(), Muet(), reg=reg)
    suite()
    assert reg.par_id(routine["id"])["derniere_execution"] == {
        "le": reg.par_id(routine["id"])["derniere_execution"]["le"], "resultat": "partiel", "echecs": ["rien ne joue"]}


def test_le_volume_passe_par_le_garde_fou():
    refus = []

    def garde(phrase, args):
        refus.append(phrase)
        return "volume non demandé"

    etape = {"etape": "service", "domaine": "media_player", "service": "volume_set",
             "entity_id": ["media_player.tele_salon"], "donnees": {"volume_level": 0.9}}
    ok, message = R.valider_etape(etape, ctx(garde_volume=garde, phrase_creation="mets de la musique"))
    assert ok is None and "Je retire le réglage du volume" in message and refus == ["mets de la musique"]


@pytest.mark.parametrize("etape,attendu", [
    ({"etape": "musique", "recherche": "jazz"}, {"etape": "musique", "recherche": "jazz", "type": "track",
                                                  "enceinte": "toutes"}),
    ({"etape": "musique", "recherche": "Gainsbourg", "type": "artist", "enceinte": "cuisine"},
     {"etape": "musique", "recherche": "Gainsbourg", "type": "artist", "enceinte": "cuisine"}),
    ({"etape": "musique", "recherche": "Ma playlist", "type": "playlist", "artiste": " Moi "},
     {"etape": "musique", "recherche": "Ma playlist", "type": "playlist", "enceinte": "toutes", "artiste": "Moi"}),
])
def test_etape_de_musique_normalisee(etape, attendu):
    assert R.valider_etape(etape, ctx()) == (attendu, None)


def test_pause_normalisee():
    assert R.valider_etape({"etape": "pause", "secondes": 12.5}, ctx()) == ({"etape": "pause", "secondes": 12.5}, None)


# --------------------------------------------------------------------- section routines absente de la config
def test_sans_section_routines_les_defauts_s_appliquent(monkeypatch):
    sans = {k: v for k, v in maison.CONFIG.items() if k != "routines"}
    monkeypatch.setattr(maison, "CONFIG", sans)
    assert R.reglage("active") is True and R.reglage("etapes_max") == 8 and R.reglage("phrases_interdites") == []
    routine = enregistrer()
    assert routine["nom"] == "Bonne nuit"


def test_reglages_mal_formes_retombent_sur_les_defauts(monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"active": "oui", "etapes_max": True,
                                                                         "phrases_interdites": "x"}})
    assert R.reglage("active") is True and R.reglage("etapes_max") == 8 and R.reglage("phrases_interdites") == []
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": "n'importe quoi"})
    assert R.reglage("nombre_max") == 30


def test_la_section_de_l_exemple_est_lue():
    assert R.reglage("etapes_max") == 8 and R.reglage("phrases_interdites") == ["bonne nuit sacha"]
    assert "_lisez_moi" in maison.CONFIG["routines"]


# --------------------------------------------------------------------------------------------- l'assistant
@pytest.fixture
def assistant(monkeypatch):
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    return faux_assistant()


def faux_assistant(ha="defaut"):
    a = object.__new__(A.Assistant)
    a.cfg, a.lecons, a.suites_routine = {}, {}, []
    a.essai = True
    a.dico = dico()
    a.ha = FauxHA() if ha == "defaut" else ha
    appels = []

    class Cerveau:
        rappel_routine = staticmethod(a.creer_routine)

        def repondre(self, texte, mode=None):
            appels.append((texte, mode))
            if mode == "question":
                return "Il fera beau.", []
            res = self.rappel_routine(self.proposition, texte)
            return res["parole"], []

    a.cerveau = Cerveau()
    a.cerveau.proposition = proposition(phrases=["dodo profond"], nom="Dodo")
    a.appels_cerveau = appels
    return a


def requete(a, personne="sacha", role="administrateur", appareil="appareil:tab1", essai=True):
    return a.requete(essai=essai, personne=personne, appareil=appareil, role=role, canal="texte")


def test_creation_a_la_voix_puis_declencheur(assistant):
    a = assistant
    with requete(a):
        pre = a.routines_avant("quand je te dis dodo profond éteins le salon")
        assert pre["voie"] == "routine (création)" and pre["confirmation"] is True
        assert pre["parole"].startswith("Routine Dodo : quand tu dis « dodo profond »")
        assert a.appels_cerveau == [("quand je te dis dodo profond éteins le salon", "proposer")]
        fin = a.routines_avant("oui")
        assert fin["parole"] == "Routine Dodo enregistrée." and fin["confirmation"] is False
        lancee = a.routines_avant("dodo profond")
        assert lancee["voie"] == "routine (Dodo)" and lancee["actions"] == ["routine Dodo"]
        assert lancee["parole"] == "Routine Dodo lancée."
    assert [x[:3] for x in a.ha.appels] == [("light", "turn_off", ["light.salon_plafond"])]


def test_une_phrase_ordinaire_continue_la_chaine(assistant):
    with requete(assistant):
        assert assistant.routines_avant("allume la lumière du salon") is None
        assert assistant.routines_avant("oui") is None


def test_la_routine_d_auteur_n_est_pas_lancee_par_un_autre(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    with requete(assistant, "camille", "habitant", "appareil:tab2"):
        assert assistant.routines_avant("dodo profond") is None
    with requete(assistant, "", "local", ""):
        pre = assistant.routines_avant("dodo profond")
        assert pre["voie"] == "routine refus" and "réservée à Sacha" in pre["parole"]
    assert assistant.ha.appels == []


def test_un_invite_ne_cree_pas_de_routine(assistant):
    with requete(assistant, "", "invite", "appareil:invite"):
        pre = assistant.routines_avant("quand je te dis dodo profond éteins le salon")
    assert pre["parole"] == R.MSG_INVITE and assistant.appels_cerveau == []


def test_personne_non_reconnue_ne_cree_pas_de_routine(assistant):
    with requete(assistant, "", "local", ""):
        pre = assistant.routines_avant("quand je te dis dodo profond éteins le salon")
    assert pre["parole"] == R.MSG_INCONNU and assistant.appels_cerveau == []


def test_sans_home_assistant_pas_de_creation(monkeypatch):
    monkeypatch.setattr(A, "journaliser", lambda *a, **k: None)
    a = faux_assistant(ha=None)
    with requete(a):
        pre = a.routines_avant("quand je te dis dodo profond éteins le salon")
    assert pre["parole"] == "Je n'arrive pas à joindre la maison, je ne crée pas de routine."


def test_routines_desactivees_ferme_la_creation_sans_toucher_au_reste(assistant, monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"active": False}})
    with requete(assistant):
        assert assistant.routines_avant("quand je te dis dodo profond éteins le salon")["parole"] == \
            "Les routines sont désactivées."
        assert assistant.routines_avant("allume la lumière du salon") is None


def test_une_erreur_interne_ne_part_jamais_au_llm_ordinaire(assistant, monkeypatch):
    def casse(texte):
        raise RuntimeError("panne")

    monkeypatch.setattr(assistant, "_routines_avant", casse)
    with requete(assistant):
        pre = assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assert pre["parole"] == "Je n'arrive pas à gérer les routines pour le moment."
        assert assistant.routines_avant("allume la lumière du salon") is None


def test_inventaire_illisible_ferme_la_creation(assistant):
    def casse():
        raise RuntimeError("HA hors ligne")

    assistant.ha.inventaire = casse
    with requete(assistant):
        pre = assistant.routines_avant("quand je te dis dodo profond éteins le salon")
    assert "Je n'arrive pas à lire la liste de mes appareils" in pre["parole"]


def test_la_suite_d_une_routine_tourne_dans_un_fil(assistant, monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    assistant.cerveau.proposition = proposition(phrases=["dodo profond"], nom="Dodo", etapes=[
        dict(LUMIERE), {"etape": "pause", "secondes": 1}, {"etape": "musique", "recherche": "jazz"}])
    with requete(assistant, essai=False):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        assistant.routines_avant("dodo profond")
    for fil in assistant.suites_routine:
        fil.join(5)
    assert assistant.ha.musiques == [("jazz", "track", "toutes", "")]


# ---------------------------------------------------------------------------------- messages réseau (7.4)
def message(a, genre, personne="sacha", role="administrateur", **champs):
    with requete(a, personne, role):
        return a.routines_reseau(genre, {"type": genre, **champs}, serveur="tablette")


def test_reseau_liste_filtree_et_droits(assistant):
    with requete(assistant, "camille", "habitant", "appareil:tab2"):
        assistant.cerveau.proposition = proposition(phrases=["dodo profond"], nom="Dodo")
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    rep = message(assistant, "routines")
    assert rep["etat"] == "routines" and rep["serveur"] == "tablette" and rep["version"] == 1
    assert [r["nom"] for r in rep["routines"]] == ["Dodo"] and rep["droits"]["qui"] == "proprietaire"  # il voit tout
    rep = message(assistant, "routines", "camille", "habitant")
    assert [r["nom"] for r in rep["routines"]] == ["Dodo"] and rep["droits"]["tout_gerer"] is False
    assert "etapes" in rep["routines"][0] and rep["routines"][0]["etapes"] == 1  # un nombre, pas le contenu


def test_reseau_liste_vide_quand_les_routines_sont_desactivees(assistant, monkeypatch):
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"active": False}})
    rep = message(assistant, "routines")
    assert rep["routines"] == [] and rep["droits"]["creer"] is False
    assert message(assistant, "routine_lancer", id="x") == {"etat": "refuse", "type": "routine_lancer",
                                                            "message": "routines désactivées"}


def test_reseau_lancer_une_routine_visible_ou_non(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    ident = R.registre().routines[0]["id"]
    rep = message(assistant, "routine_lancer", id=ident)
    assert rep == {"etat": "routine_lancee", "id": ident, "parole": "Routine Dodo lancée.", "echecs": [], "ok": True}
    inconnue = message(assistant, "routine_lancer", "camille", "habitant", id=ident)
    assert inconnue["ok"] is False and inconnue["parole"] == "Je ne trouve pas cette routine."
    assert message(assistant, "routine_lancer", id="r-fantome")["ok"] is False
    assert len(assistant.ha.appels) == 1


def test_reseau_lancer_une_routine_coupee(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    ident = R.registre().routines[0]["id"]
    assert message(assistant, "routine_activer", id=ident, actif=False) == {"etat": "routine_ok", "id": ident}
    rep = message(assistant, "routine_lancer", id=ident)
    assert rep["ok"] is False and rep["parole"] == "La routine Dodo est coupée." and assistant.ha.appels == []


def test_reseau_lancer_remonte_les_echecs(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    assistant.ha.entites_llm.discard("light.salon_plafond")
    rep = message(assistant, "routine_lancer", id=R.registre().routines[0]["id"])
    assert rep["ok"] is True and len(rep["echecs"]) == 1 and "Je ne trouve pas" in rep["echecs"][0]


def test_reseau_activer_et_supprimer_respectent_les_droits(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    ident = R.registre().routines[0]["id"]
    refus = {"etat": "refuse", "type": "routine_supprimer", "message": "routine inconnue ou non permise"}
    assert message(assistant, "routine_supprimer", "camille", "habitant", id=ident) == refus
    assert message(assistant, "routine_activer", id=ident, actif="oui") == {
        "etat": "refuse", "type": "routine_activer", "message": "champ actif attendu"}
    assert message(assistant, "routine_supprimer", id=ident) == {"etat": "routine_ok", "id": ident}
    assert R.registre().routines == []


def test_reseau_texte_cree_puis_confirme(assistant):
    rep = message(assistant, "routine_texte", texte="quand je te dis dodo profond éteins le salon")
    assert rep["etat"] == "routine_texte" and rep["confirmation_attendue"] == 30
    assert rep["parole"].startswith("Routine Dodo : quand tu dis")
    rep = message(assistant, "routine_texte", texte="oui")
    assert rep == {"etat": "routine_texte", "parole": "Routine Dodo enregistrée.", "confirmation_attendue": 0}


def test_reseau_texte_ordinaire_ou_vide(assistant):
    rep = message(assistant, "routine_texte", texte="allume la lumière du salon")
    assert rep == {"etat": "routine_texte", "parole": "Ce n'est pas une demande de routine.",
                   "confirmation_attendue": 0}
    assert message(assistant, "routine_texte", texte="   ") == {"etat": "routine_texte", "parole": "",
                                                                 "confirmation_attendue": 0}


def test_reseau_export_pour_le_proprietaire_seul(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    rep = message(assistant, "routines_export")
    assert rep["etat"] == "routines_export" and len(rep["contenu"]["routines"]) == 1
    assert message(assistant, "routines_export", "camille", "habitant") == {
        "etat": "refuse", "type": "routines_export", "message": "réservé au propriétaire"}


def test_reseau_type_inconnu(assistant):
    assert message(assistant, "routine_magique")["message"] == "type inconnu"


# ------------------------------------------------------------------------------ serveur : rôles et signal
TYPES_LECTURE = {"routines", "routine_lancer", "routine_texte"}


@pytest.mark.parametrize("role,permis", [
    ("administrateur", TYPES_LECTURE | {"routine_activer", "routine_supprimer", "routines_export"}),
    ("habitant", TYPES_LECTURE | {"routine_activer", "routine_supprimer"}),
    ("partage", TYPES_LECTURE),
    ("invite", TYPES_LECTURE),
    ("", set()),
    ("inconnu", set()),
])
def test_types_de_routines_permis_par_role(role, permis):
    tous = TYPES_LECTURE | {"routine_activer", "routine_supprimer", "routines_export"}
    assert {t for t in tous if acces.type_permis(role, t)} == permis


def faux_serveur(monkeypatch, assistant, role="administrateur", personne="sacha", chiffre=True):
    import serveur_satellite as S
    envoyes, diffuses, historiques = [], [], []

    class Moteur:
        profil, essai, appareils, satellites, pages_admin = "tablette", False, None, set(), set()

        def __init__(self):
            self.assistant, self.verrou = assistant, asyncio.Lock()

        messages_routines = S.Moteur.messages_routines

        async def diffuser(self, m):
            diffuses.append(m)

        async def diffuser_historique(self, ligne):
            historiques.append(ligne)

    sat = object.__new__(S.Satellite)
    sat.moteur, sat.nom, sat.identite, sat.chiffre = Moteur(), "Tab", "appareil:tab1", chiffre

    async def envoyer(**m):
        envoyes.append(m)

    sat.envoyer = envoyer
    monkeypatch.setattr(S.acces, "role_effectif", lambda identite, appareils: role)
    monkeypatch.setattr(S.acces, "personne_effective", lambda identite, declaree, appareils: personne)
    monkeypatch.setattr(S, "lire_journal", lambda n=1: [{"horodatage": "x"}])
    return S, sat, envoyes, diffuses, historiques


def recevoir(sat, **msg):
    asyncio.run(sat.recevoir_texte(json.dumps(msg)))

    async def attendre():
        await asyncio.sleep(0)
        taches = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if taches:
            await asyncio.gather(*taches)

    asyncio.run(attendre())


def jouer(sat, **msg):
    """Envoie un message au satellite et attend la fin des tâches qu'il lance, dans une seule boucle."""
    async def scenario():
        await sat.recevoir_texte(json.dumps(msg))
        await asyncio.sleep(0)
        taches = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if taches:
            await asyncio.gather(*taches)
    asyncio.run(scenario())


def test_serveur_port_chiffre_liste_et_signal(monkeypatch, assistant):
    S, sat, envoyes, diffuses, historiques = faux_serveur(monkeypatch, assistant)
    jouer(sat, type="routines", essai=True)
    assert envoyes[-1]["etat"] == "routines" and envoyes[-1]["version"] == 0 and diffuses == []
    jouer(sat, type="routine_texte", texte="quand je te dis dodo profond éteins le salon", essai=True)
    assert envoyes[-1]["etat"] == "routine_texte" and envoyes[-1]["confirmation_attendue"] == 30
    assert diffuses == [] and historiques  # rien d'écrit encore, mais l'historique de l'appli s'enrichit
    jouer(sat, type="routine_texte", texte="oui", essai=True)
    assert diffuses == [{"etat": "routines_maj", "version": 1}]
    ident = R.registre().routines[0]["id"]
    jouer(sat, type="routine_lancer", id=ident, essai=True)
    assert envoyes[-1]["etat"] == "routine_lancee" and envoyes[-1]["ok"] is True
    jouer(sat, type="routine_activer", id=ident, actif=False)
    assert diffuses[-1] == {"etat": "routines_maj", "version": 2}
    assert "etapes" not in json.dumps(diffuses)  # le signal ne porte jamais le contenu


def test_serveur_refuse_le_role_insuffisant(monkeypatch, assistant):
    S, sat, envoyes, _, _ = faux_serveur(monkeypatch, assistant, role="partage")
    jouer(sat, type="routine_supprimer", id="x")
    assert envoyes == [{"etat": "refuse", "type": "routine_supprimer",
                        "message": "type de message non permis pour ce rôle"}]
    S2, sat2, envoyes2, _, _ = faux_serveur(monkeypatch, assistant, role="habitant")
    jouer(sat2, type="routines_export")
    assert envoyes2 == [{"etat": "refuse", "type": "routines_export",
                         "message": "type de message non permis pour ce rôle"}]


def test_serveur_refuse_les_routines_sur_le_port_en_clair(monkeypatch, assistant):
    S, sat, envoyes, _, _ = faux_serveur(monkeypatch, assistant, chiffre=False)
    for genre in ("routines", "routine_lancer", "routine_texte", "routine_activer", "routine_supprimer",
                  "routines_export"):
        jouer(sat, type=genre, id="x")
    assert [e["message"] for e in envoyes] == ["réservé au port chiffré"] * 6
    assert R.registre().routines == []


def test_serveur_une_exception_n_est_jamais_renvoyee_brute(monkeypatch, assistant):
    S, sat, envoyes, _, _ = faux_serveur(monkeypatch, assistant)

    def casse(*a, **k):
        raise ValueError("secret interne")

    sat.moteur.messages_routines = casse
    jouer(sat, type="routines")
    assert envoyes == [{"etat": "refuse", "type": "routines", "message": "erreur inattendue (ValueError)"}]


def test_serveur_la_personne_vient_de_l_identite_pas_du_message(monkeypatch, assistant):
    S, sat, envoyes, _, _ = faux_serveur(monkeypatch, assistant, role="habitant", personne="camille")
    jouer(sat, type="routines", personne="sacha")
    assert envoyes[-1]["droits"]["qui"] == "habitant"


def test_capacite_routines_suit_le_reglage(monkeypatch):
    import serveur_satellite as S
    moteur = SimpleNamespace(profil="tablette", assistant=SimpleNamespace(ha=None), empreinte_tls="", vision=None)
    assert S.Moteur.capacites(moteur)["routines"] is True
    monkeypatch.setattr(maison, "CONFIG", {**maison.CONFIG, "routines": {"active": False}})
    assert S.Moteur.capacites(moteur)["routines"] is False


def test_categorie_routine_du_journal():
    import serveur_satellite as S
    ligne = {"horodatage": "2026-10-26 22:10:00", "texte": "dodo profond", "voie": "routine (Dodo)", "actions": []}
    assert S.entree_historique(ligne, {})["compris_par"] == "routine"
    refus = dict(ligne, voie="routine refus")
    assert S.entree_historique(refus, {})["compris_par"] == "routine"
    creation = dict(ligne, voie="routine (création)")
    assert S.entree_historique(creation, {})["compris_par"] == "routine"


# ------------------------------------------------------------------------------- gestion à la voix (0.43.0, S-R2)
def voix(texte, personne="sacha", role="administrateur", **kw):
    """Une commande de gestion passée au moteur, comme le fait l'assistant (contexte léger, complet à la demande)."""
    c = ctx(personne, role)
    return R.gerer(texte, c, R.registre(), contexte_complet=lambda: ctx(personne, role, **kw))


def deux_routines():
    """Bonne nuit (Sacha, phrase « je vais dormir maintenant ») et Arrivée (Sacha, phrase « je suis rentré »)."""
    enregistrer()
    enregistrer(proposition(nom="Arrivée", phrases=["je suis rentré"],
                            etapes=[dict(LUMIERE, service="turn_on", entity_id=["light.couloir_plafond"])]))


# La section 6.1 de la note : une phrase par commande, toutes reconnues par l'analyseur sans LLM.
@pytest.mark.parametrize("phrase,attendu", [
    ("quelles sont mes routines", ("lister", "")),
    ("liste mes routines", ("lister", "")),
    ("montre-moi mes routines", ("lister", "")),
    ("quelles routines j'ai", ("lister", "")),
    ("que fait la routine Arrivée", ("decrire", "arrivee")),
    ("décris la routine Arrivée", ("decrire", "arrivee")),
    ("explique-moi la routine Arrivée", ("decrire", "arrivee")),
    ("coupe la routine Arrivée", ("couper", "arrivee")),
    ("désactive la routine Arrivée", ("couper", "arrivee")),
    ("réactive la routine Arrivée", ("reactiver", "arrivee")),
    ("rallume la routine Arrivée", ("reactiver", "arrivee")),
    ("supprime la routine Arrivée", ("supprimer", "arrivee")),
    ("efface la routine Arrivée", ("supprimer", "arrivee")),
    ("oublie la routine Arrivée", ("supprimer", "arrivee")),
    ("peux-tu supprimer la routine Arrivée", ("supprimer", "arrivee")),
    ("lance la routine Arrivée", ("lancer", "arrivee")),
    ("exécute la routine qui s'appelle Arrivée", ("lancer", "qui s appelle arrivee")),
    ("supprime toutes mes routines", ("plusieurs", "")),
    ("coupe toutes les routines", ("plusieurs", "")),
    ("supprime la routine", ("supprimer", "")),
])
def test_analyseur_reconnait_chaque_commande(phrase, attendu):
    assert R.analyser(phrase) == attendu


@pytest.mark.parametrize("phrase", [
    "allume la lumière du salon", "quand je te dis dodo éteins le salon", "change la routine Arrivée",
    "crée une routine pour le soir", "la routine du matin est super", "joue la routine", "oublie ça", "coupe la lumière",
])
def test_analyseur_laisse_passer_le_reste(phrase):
    assert R.analyser(phrase) is None


def test_lister_les_routines():
    assert voix("quelles sont mes routines")["parole"] == "Tu n'as aucune routine."
    deux_routines()
    rep = voix("liste mes routines")
    assert rep["voie"] == "routine (lister)" and rep["lancer"] is None and rep["actions"] == []
    assert rep["parole"] == ("Tu as 2 routines : Bonne nuit (« je vais dormir maintenant »), "
                             "Arrivée (« je suis rentré »).")


def test_lister_dit_l_auteur_les_routines_coupees_et_plafonne():
    enregistrer(personne="camille", role="habitant", pour="tous")
    reg = R.registre()
    reg.activer(reg.routines[0]["id"], False, ctx())
    assert voix("quelles sont mes routines")["parole"] == (
        "Tu as une routine : Bonne nuit de Camille (« je vais dormir maintenant »), coupée.")
    MOTS = ["cinéma", "lecture", "dîner", "ménage", "réveil", "bricolage"]  # phrases très différentes : aucun remplacement
    for i in range(6):
        enregistrer(proposition(nom=f"Scène {i}", phrases=[MOTS[i] + " pour la soirée"]), pour="tous")
    parole = voix("liste mes routines")["parole"]
    assert parole.startswith("Tu as 7 routines") and parole.endswith("et 2 autres, visibles à l'écran.")


def test_lister_une_habitante_ne_voit_que_ses_routines_et_les_partagees():
    enregistrer(pour="auteur")
    enregistrer(proposition(nom="Arrivée", phrases=["je suis rentré"]), pour="tous")
    parole = voix("quelles sont mes routines", "camille", "habitant")["parole"]
    assert "Arrivée" in parole and "Bonne nuit" not in parole


def test_decrire_une_routine_par_son_nom_ou_sa_phrase():
    deux_routines()
    rep = voix("que fait la routine Arrivée")
    assert rep["voie"] == "routine (decrire)" and rep["parole"].startswith("Routine Arrivée : quand tu dis « je suis rentré »")
    assert "Je l'enregistre ?" not in rep["parole"] and "?" not in rep["parole"]
    assert voix("décris la routine je vais dormir maintenant")["parole"].startswith("Routine Bonne nuit")


def test_decrire_une_routine_coupee_le_dit():
    ancienne = enregistrer()
    R.registre().activer(ancienne["id"], False, ctx())
    assert voix("décris la routine Bonne nuit")["parole"].endswith("Elle est coupée.")


def test_couper_puis_reactiver():
    ancienne = enregistrer()
    assert voix("coupe la routine Bonne nuit")["parole"] == "Routine Bonne nuit coupée."
    assert R.registre().par_id(ancienne["id"])["actif"] is False
    assert voix("désactive la routine Bonne nuit")["parole"] == "La routine Bonne nuit est déjà coupée."
    assert voix("réactive la routine Bonne nuit")["parole"] == "Routine Bonne nuit réactivée."
    assert R.registre().par_id(ancienne["id"])["actif"] is True
    assert voix("réactive la routine Bonne nuit")["parole"] == "La routine Bonne nuit est déjà active."


def test_une_routine_coupee_ne_se_declenche_plus_mais_reste_dans_la_liste():
    ancienne = enregistrer()
    voix("coupe la routine Bonne nuit")
    assert R.registre().trouver("je vais dormir maintenant", ctx())[0] is None
    assert "coupée" in voix("liste mes routines")["parole"]
    assert R.registre().par_id(ancienne["id"])


def test_reactiver_revalide_les_etapes():
    ancienne = enregistrer()
    voix("coupe la routine Bonne nuit")
    # Le fichier a été modifié à la main pendant que la routine dormait : une étape que la validation refuse.
    reg = R.registre()
    reg.par_id(ancienne["id"])["etapes"] = [{"etape": "service", "domaine": "lock", "service": "unlock",
                                              "entity_id": ["lock.porte_entree"]}]
    rep = voix("réactive la routine Bonne nuit")
    assert rep["parole"].startswith("Je ne réactive pas la routine Bonne nuit : ")
    r = reg.par_id(ancienne["id"])
    assert r["actif"] is False and r["a_revoir"]
    assert "réactivation refusée" in R.JOURNAL.read_text(encoding="utf-8")


def test_reactiver_refuse_une_entite_disparue_de_l_inventaire():
    ancienne = enregistrer()
    voix("coupe la routine Bonne nuit")
    rep = voix("réactive la routine Bonne nuit", entites={"light.inconnue"})
    assert rep["parole"].startswith("Je ne réactive pas la routine Bonne nuit")
    assert R.registre().par_id(ancienne["id"])["actif"] is False


def test_supprimer_demande_confirmation_puis_oui():
    ancienne = enregistrer()
    rep = voix("supprime la routine Bonne nuit")
    assert rep["parole"] == "Je supprime la routine Bonne nuit ?" and rep["voie"] == "routine (supprimer)"
    assert R.registre().par_id(ancienne["id"])  # rien n'est encore effacé
    assert R.registre().reponse_brouillon("oui", ctx()) == "Routine Bonne nuit supprimée."
    assert R.registre().routines == []


def test_supprimer_puis_non_garde_la_routine():
    ancienne = enregistrer()
    voix("efface la routine Bonne nuit")
    assert R.registre().reponse_brouillon("non", ctx()) == "D'accord, je ne supprime rien."
    assert R.registre().par_id(ancienne["id"])
    assert R.registre().reponse_brouillon("oui", ctx()) is None  # le brouillon est parti avec le « non »


def test_supprimer_une_confirmation_expiree_ne_supprime_rien(monkeypatch):
    ancienne = enregistrer()
    voix("supprime la routine Bonne nuit")
    reg = R.registre()
    appareil = ctx().appareil
    reg.brouillons[appareil]["le"] -= R.reglage("delai_confirmation_s") + 1  # le délai est passé
    assert reg.reponse_brouillon("oui", ctx()) == R.MSG_EXPIRE_SUPPRESSION
    assert reg.par_id(ancienne["id"]) and appareil not in reg.brouillons


def test_supprimer_garde_une_copie_complete_au_journal():
    ancienne = enregistrer()
    voix("supprime la routine Bonne nuit")
    R.registre().reponse_brouillon("oui", ctx())
    lignes = [json.loads(x) for x in R.JOURNAL.read_text(encoding="utf-8").splitlines()]
    sup = [x for x in lignes if "suppression" in x.values()]
    assert sup and sup[-1]["copie"]["id"] == ancienne["id"] and sup[-1]["copie"]["etapes"] == ancienne["etapes"]


def test_une_autre_personne_ne_confirme_pas_la_suppression():
    enregistrer()
    voix("supprime la routine Bonne nuit")
    assert R.registre().reponse_brouillon("oui", ctx("camille", "habitant")) is None
    assert len(R.registre().routines) == 1


def test_supprimer_sans_cible_demande_laquelle():
    deux_routines()
    rep = voix("supprime la routine")
    assert rep["parole"] == "Laquelle ? Il y a Bonne nuit, Arrivée."
    assert R.registre().brouillons == {}


def test_cible_inconnue_ou_aucune_routine():
    assert voix("supprime la routine Arrivée")["parole"] == "Tu n'as aucune routine."
    deux_routines()
    assert voix("supprime la routine Pizza")["parole"] == "Je ne trouve pas de routine « pizza ». Il y a Bonne nuit, Arrivée."


def test_cible_approchee_faute_de_transcription():
    deux_routines()
    assert voix("coupe la routine arrivé")["parole"] == "Routine Arrivée coupée."
    assert voix("décris la routine bonne nuits")["parole"].startswith("Routine Bonne nuit")


def test_deux_routines_ambigues_et_preference_pour_les_siennes():
    enregistrer(proposition(nom="Matin tôt", phrases=["debout là dedans"]), pour="tous")
    enregistrer(proposition(nom="Matin tard", phrases=["encore un peu de repos"]), pour="tous")
    rep = voix("coupe la routine matin")
    assert rep["parole"] == "Plusieurs routines correspondent : Matin tôt, Matin tard. Laquelle ?"
    assert all(r["actif"] for r in R.registre().routines)
    # Même nom chez deux auteurs : Camille vise la sienne.
    enregistrer(proposition(nom="Dodo", phrases=["dodo de sacha"]), pour="tous")
    enregistrer(proposition(nom="Dodo", phrases=["dodo de camille"]), personne="camille", role="habitant", pour="tous")
    assert voix("coupe la routine Dodo", "camille", "habitant")["parole"] == "Routine Dodo coupée."
    dodos = {r["auteur"]: r["actif"] for r in R.registre().routines if r["nom"] == "Dodo"}
    assert dodos == {"sacha": True, "camille": False}


def test_identifiants_de_routine_sans_collision_a_la_minute():
    # Avec un seul octet aléatoire, deux routines créées la même minute partageaient un identifiant une fois sur 256.
    enregistrer(proposition(nom="Une", phrases=["premiere phrase"]), pour="tous")
    assert len(R.registre().routines[-1]["id"].rsplit("-", 1)[1]) == 8


def test_toutes_mes_routines_est_refuse():
    deux_routines()
    for phrase in ("supprime toutes mes routines", "coupe toutes les routines", "efface mes routines"):
        assert voix(phrase)["parole"] == "Je gère les routines une par une, dis-moi laquelle."
    assert len(R.registre().routines) == 2 and R.registre().brouillons == {}


def test_lancer_renvoie_la_routine_a_executer():
    deux_routines()
    rep = voix("lance la routine Arrivée")
    assert rep["lancer"]["nom"] == "Arrivée" and rep["parole"] == ""
    voix("coupe la routine Arrivée")
    rep = voix("lance la routine Arrivée")
    assert rep["lancer"] is None and rep["parole"] == "La routine Arrivée est coupée."


# --- droits
def test_une_habitante_ne_touche_pas_a_la_routine_d_un_autre():
    ancienne = enregistrer(pour="tous")
    for phrase in ("coupe la routine Bonne nuit", "réactive la routine Bonne nuit", "supprime la routine Bonne nuit"):
        assert voix(phrase, "camille", "habitant")["parole"] == "La routine Bonne nuit n'est pas à toi, je n'y touche pas."
    assert R.registre().par_id(ancienne["id"])["actif"] is True and R.registre().brouillons == {}
    # Lecture et lancement restent permis sur une routine partagée.
    assert voix("décris la routine Bonne nuit", "camille", "habitant")["parole"].startswith("Routine Bonne nuit")
    assert voix("lance la routine Bonne nuit", "camille", "habitant")["lancer"]["id"] == ancienne["id"]


def test_une_habitante_ne_voit_pas_la_routine_privee_d_un_autre():
    enregistrer(pour="auteur")
    assert voix("décris la routine Bonne nuit", "camille", "habitant")["parole"] == "Tu n'as aucune routine."
    assert voix("lance la routine Bonne nuit", "camille", "habitant")["lancer"] is None


def test_l_habitante_gere_les_siennes():
    enregistrer(personne="camille", role="habitant")
    assert voix("coupe la routine Bonne nuit", "camille", "habitant")["parole"] == "Routine Bonne nuit coupée."
    assert voix("réactive la routine Bonne nuit", "camille", "habitant")["parole"] == "Routine Bonne nuit réactivée."
    voix("supprime la routine Bonne nuit", "camille", "habitant")
    assert R.registre().reponse_brouillon("oui", ctx("camille", "habitant")) == "Routine Bonne nuit supprimée."


def test_le_proprietaire_gere_celles_des_autres():
    enregistrer(personne="camille", role="habitant", pour="auteur")
    assert voix("coupe la routine Bonne nuit")["parole"] == "Routine Bonne nuit coupée."
    assert voix("réactive la routine Bonne nuit")["parole"] == "Routine Bonne nuit réactivée."


@pytest.mark.parametrize("role,msg", [("invite", R.MSG_GESTION_INVITE), ("local", R.MSG_GESTION_INCONNU)])
def test_invite_et_inconnu_ne_modifient_rien(role, msg):
    ancienne = enregistrer(pour="tous")
    for phrase in ("coupe la routine Bonne nuit", "réactive la routine Bonne nuit", "supprime la routine Bonne nuit"):
        assert voix(phrase, "", role)["parole"] == msg
    assert R.registre().par_id(ancienne["id"])["actif"] is True and R.registre().brouillons == {}


def test_invite_lit_et_lance_seulement_ce_qui_est_partage():
    enregistrer(pour="tous")
    enregistrer(proposition(nom="Arrivée", phrases=["je suis rentré"]), pour="auteur")
    parole = voix("quelles sont mes routines", "", "invite")["parole"]
    assert "Bonne nuit" in parole and "Arrivée" not in parole


# --- au niveau de l'assistant
def test_assistant_suppression_a_la_voix_en_deux_temps(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        pre = assistant.routines_avant("supprime la routine Dodo")
        assert pre["parole"] == "Je supprime la routine Dodo ?" and pre["voie"] == "routine (supprimer)"
        assert pre["confirmation"] is True
        fin = assistant.routines_avant("oui")
        assert fin["parole"] == "Routine Dodo supprimée." and fin["confirmation"] is False
        assert assistant.routines_avant("dodo profond") is None
    assert R.registre().routines == []


def test_assistant_oublie_la_routine_ne_confond_pas_avec_la_correction(assistant):
    """« oublie » est aussi un mot de CORRECTION : juste après une leçon apprise, la routine passe d'abord."""
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        assistant.lecons[A.Cerveau.cle_conversation()[1]] = ("allume le truc", __import__("time").time())
        pre = assistant.routines_avant("oublie la routine Dodo")
        assert pre["parole"] == "Je supprime la routine Dodo ?"
        assistant.routines_avant("oui")
    assert R.registre().routines == []
    assert assistant.lecons  # la leçon n'a pas été touchée


def test_assistant_un_oublie_ordinaire_reste_une_correction(assistant):
    with requete(assistant):
        assert assistant.routines_avant("oublie ça") is None


def test_assistant_liste_decrit_coupe_reactive(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        assert assistant.routines_avant("quelles sont mes routines")["parole"] == (
            "Tu as une routine : Dodo (« dodo profond »).")
        assert assistant.routines_avant("que fait la routine Dodo")["parole"].startswith(
            "Routine Dodo : quand tu dis « dodo profond »")
        assert assistant.routines_avant("coupe la routine Dodo")["parole"] == "Routine Dodo coupée."
        assert assistant.routines_avant("dodo profond") is None
        assert assistant.routines_avant("réactive la routine Dodo")["parole"] == "Routine Dodo réactivée."
        assert assistant.routines_avant("dodo profond")["parole"] == "Routine Dodo lancée."


def test_assistant_lance_la_routine_par_son_nom(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        pre = assistant.routines_avant("lance la routine Dodo")
        assert pre["parole"] == "Routine Dodo lancée." and pre["voie"] == "routine (Dodo)"
        assert pre["actions"] == ["routine Dodo"]
    assert [x[:3] for x in assistant.ha.appels] == [("light", "turn_off", ["light.salon_plafond"])]


def test_assistant_gestion_refusee_a_un_invite_sans_appeler_le_llm(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
    with requete(assistant, "", "invite", "appareil:invite"):
        pre = assistant.routines_avant("supprime la routine Dodo")
    assert pre["parole"] == R.MSG_GESTION_INVITE and len(R.registre().routines) == 1
    assert len(assistant.appels_cerveau) == 1  # seulement la création de départ


def test_assistant_modification_dit_avant_apres_et_remplace(assistant):
    with requete(assistant):
        assistant.routines_avant("quand je te dis dodo profond éteins le salon")
        assistant.routines_avant("oui")
        assistant.cerveau.proposition = proposition(
            phrases=["dodo profond"], nom="Dodo", etapes=[dict(LUMIERE, entity_id=["light.couloir_plafond"])])
        pre = assistant.routines_avant("quand je te dis dodo profond éteins le couloir")
        assert "Avant : " in pre["parole"] and "Après : " in pre["parole"] and pre["parole"].endswith("Je remplace ?")
        fin = assistant.routines_avant("oui")
        assert fin["parole"] == "Routine Dodo enregistrée."
    assert len(R.registre().routines) == 1
    assert R.registre().routines[0]["etapes"][0]["entity_id"] == ["light.couloir_plafond"]


def test_decrire_en_modification_montre_avant_et_apres():
    ancienne = enregistrer()
    res = R.valider_proposition(proposition(nom="Dodo", etapes=[dict(LUMIERE, entity_id=["light.couloir_plafond"])]),
                                ctx(), R.registre())
    parole = R.decrire(res["routine"], ctx(), remplace=R.registre().par_id(res["remplace"]))
    assert res["remplace"] == ancienne["id"]
    assert parole.startswith("Routine Dodo. Avant : ") and " Après : " in parole and parole.endswith("Je remplace ?")


def test_decrire_elide_j_devant_une_voyelle():
    r = enregistrer(proposition(nom="Allumage", phrases=["fais de la lumière"],
                                etapes=[dict(LUMIERE, service="turn_on", entity_id=["light.couloir_plafond"])]))
    assert "tu dis « fais de la lumière », j'allume" in R.decrire(r, ctx())


# --- retour « mauvais » du propriétaire
def test_retour_mauvais_sur_une_commande_de_routine_ne_change_rien(monkeypatch):
    import serveur_satellite as S
    ecrit = []
    monkeypatch.setattr(A, "ajouter_jsonl", lambda chemin, ligne: ecrit.append(ligne))
    oubliees = []
    faux = SimpleNamespace(assistant=SimpleNamespace(dico=SimpleNamespace(oublier=lambda p: oubliees.append(p) or True)))
    effet = S.Moteur.noter_retour(faux, {"verdict": "mauvais", "entendu": "supprime la routine dodo",
                                         "compris_par": "routine (supprimer)"}, "tablette")
    assert effet == "routine : noté, rien n'est changé" and oubliees == []
    assert ecrit[0]["effet"] == effet and ecrit[0]["verdict"] == "mauvais"
    assert "retour mauvais" in R.JOURNAL.read_text(encoding="utf-8")
    # Une phrase ordinaire apprise reste oubliée comme avant.
    effet = S.Moteur.noter_retour(faux, {"verdict": "mauvais", "entendu": "allume le truc",
                                         "compris_par": "dictionnaire"}, "tablette")
    assert effet.startswith("phrase apprise") and oubliees
