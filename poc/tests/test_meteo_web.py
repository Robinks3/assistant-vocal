"""Écran Météo et mer du client web (S-W5) : schéma du message, filtrage par rôle, projection en mots, pannes partielles.

Aucune source réelle : les deux fournisseurs sont des coroutines factices posées dans Meteo(). La configuration est
celle de config-exemple/ (points prado, pharo, rade).
"""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import maison
import meteo_web as MW

RACINE = Path(__file__).resolve().parent.parent
MAINTENANT = datetime(2026, 10, 27, 10, 30, tzinfo=timezone.utc)
UTC_PLUS_1 = timezone(timedelta(hours=1))


def locale(instant):
    return instant.astimezone(UTC_PLUS_1)


def heure(t, **plus):
    base = {"t": t, "vent": 12, "rafales": 18, "dir": 225, "air": 17.4, "pluie": 0.2, "vagues": 0.8, "periode": 5,
            "dir_vagues": 200, "code": 2}
    base.update(plus)
    return base


def heures_de_test():
    """Du 27/10 10:00 au 29/10 23:00, heure locale du point (UTC+1 dans ces tests)."""
    sortie, debut = [], datetime(2026, 10, 27, 10, 0)
    for i in range(0, 62):
        sortie.append(heure((debut + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")))
    return sortie


def donnees_mer(**plus):
    base = {"lu_a": "2026-10-27T10:20:00Z", "titre": "Mer au Prado", "eau": 18.3,
            "soleil": [{"jour": "2026-10-27", "lever": "07:40", "coucher": "18:05"}],
            "points": [{"id": "prado", "vagues_source": "AROME", "heures": heures_de_test()}], "erreurs": []}
    base.update(plus)
    return base


def balise(ident="prado", age_min=10, seuil_min=30, **plus):
    t = MAINTENANT.timestamp() - age_min * 60
    base = {"id": ident, "nom": f"Balise {ident}", "genre": "bouée", "point": "prado", "seuil_min": seuil_min,
            "lat": 43.25, "lon": 5.36, "mesures": [{"t": t, "vent": 12, "rafale": 18, "dir": 225}]}
    base.update(plus)
    return base


def donnees_vent(*stations, **plus):
    base = {"lu_a": "2026-10-27T10:25:00Z", "stations": list(stations) or [balise()], "erreurs": []}
    base.update(plus)
    return base


def fournisseur(valeur):
    async def lire():
        if isinstance(valeur, Exception):
            raise valeur
        return valeur
    return lire


def meteo(mer="defaut", vent="defaut"):
    mer = donnees_mer() if mer == "defaut" else mer
    vent = donnees_vent() if vent == "defaut" else vent
    return MW.Meteo(None if mer is None else fournisseur(mer), None if vent is None else fournisseur(vent),
                    maintenant=lambda: MAINTENANT, locale=locale)


AUCUN = object()


def vue(m, role="habitant", msg=AUCUN):
    return asyncio.run(m.vue(role, {"type": "meteo"} if msg is AUCUN else msg))


def refus(m, role="habitant", msg=AUCUN):
    with pytest.raises(MW.RefusMeteo) as e:
        vue(m, role, msg)
    return e.value


# ------------------------------------------------------------------ schéma du message

def test_le_message_a_un_schema_strict_et_une_liste_fermee_de_causes():
    assert MW.CLES_MESSAGE == {"type", "point"} and MW.GENRES == ("meteo",)
    assert MW.CAUSES == {"droit", "format", "entite", "indisponible"}


@pytest.mark.parametrize("msg", [{"type": "meteo", "lat": 1}, {"type": "meteo", "role": "administrateur"},
                                 {"type": "meteo", "point": "prado", "source": "x"}, "prado", ["prado"], None])
def test_une_cle_inconnue_ou_un_message_qui_n_est_pas_un_objet_donne_format(msg):
    assert refus(meteo(), msg=msg).cause == "format"


@pytest.mark.parametrize("point", [3, 1.5, True, ["prado"], {"id": "prado"}])
def test_un_point_qui_n_est_pas_un_texte_donne_format(point):
    assert refus(meteo(), msg={"type": "meteo", "point": point}).cause == "format"


def test_un_point_inconnu_donne_entite_et_n_est_jamais_une_coordonnee():
    e = refus(meteo(), msg={"type": "meteo", "point": "43.25,5.36"})
    assert e.cause == "entite" and e.entite == "43.25,5.36"
    long = refus(meteo(), msg={"type": "meteo", "point": "x" * 200})
    assert len(long.entite) <= 40


def test_sans_point_le_point_par_defaut_puis_un_point_nomme():
    assert vue(meteo())["point"] == {"id": "prado", "nom": "Prado"}
    assert vue(meteo(), msg={"type": "meteo", "point": "pharo"})["point"] == {"id": "pharo", "nom": "Pharo"}
    assert vue(meteo(), msg={"type": "meteo", "point": None})["point"]["id"] == "prado"


def test_la_liste_des_points_ne_porte_que_id_et_nom():
    rep = vue(meteo())
    assert [p["id"] for p in rep["points"]] == ["prado", "pharo", "rade"]
    assert all(set(p) == {"id", "nom"} for p in rep["points"])


def test_sans_point_configure_la_vue_est_indisponible(monkeypatch):
    monkeypatch.setitem(maison.CONFIG, "mer", {"points": []})
    assert refus(meteo()).cause == "indisponible"


def test_le_premier_point_sert_de_defaut_si_aucun_n_est_marque(monkeypatch):
    mer = {"points": [{"id": "b", "nom": "B"}, {"id": "a", "nom": "A"}]}
    monkeypatch.setitem(maison.CONFIG, "mer", mer)
    assert vue(meteo())["point"]["id"] == "b"


def test_les_points_mal_formes_ou_en_double_sont_ignores():
    brut = {"points": [{"id": "a", "nom": "A"}, {"id": "a", "nom": "Doublon"}, {"id": "", "nom": "Vide"},
                       {"id": "c"}, "texte", {"id": "d", "nom": "  "}, {"id": "e", "nom": "E"}]}
    assert [p["id"] for p in MW.points_configures(brut)] == ["a", "e"]
    assert MW.points_configures({"points": "oups"}) == [] and MW.points_configures({}) == []


# ------------------------------------------------------------------ filtrage par rôle

def test_l_invite_est_refuse_avec_la_config_d_exemple():
    assert refus(meteo(), "invite").cause == "droit"
    assert vue(meteo(), "habitant") and vue(meteo(), "administrateur")


@pytest.mark.parametrize("role", ["", "root", None, 3, "Habitant"])
def test_un_role_inconnu_ne_voit_rien(role):
    assert MW.droits(role) is False
    assert refus(meteo(), role).cause == "droit"


def test_le_droit_suit_client_web_meteo_roles_et_a_defaut_exclut_l_invite():
    section = {"roles": {"administrateur": True, "habitant": False, "invite": True}}
    assert [MW.droits(r, section) for r in MW.ROLES] == [True, False, True]
    assert [MW.droits(r, {}) for r in MW.ROLES] == [True, True, False]
    assert MW.droits("habitant", {"roles": {"habitant": "oui"}}) is False, "seul True ouvre le droit"
    assert MW.droits("habitant", {"roles": "tous"}) is True and MW.droits("invite", {"roles": "tous"}) is False


def test_le_refus_de_droit_vient_avant_toute_lecture_de_source():
    appels = []

    async def espion():
        appels.append(1)
        return donnees_mer()
    m = MW.Meteo(espion, espion, maintenant=lambda: MAINTENANT, locale=locale)
    with pytest.raises(MW.RefusMeteo):
        asyncio.run(m.vue("invite", {"type": "meteo", "point": "prado"}))
    with pytest.raises(MW.RefusMeteo):
        asyncio.run(m.vue("habitant", {"type": "meteo", "lat": 1}))
    assert appels == []


def test_un_refus_ne_laisse_pas_connaitre_les_points():
    e = refus(meteo(), "invite", {"type": "meteo", "point": "inconnu"})
    assert e.cause == "droit" and e.entite is None


# ------------------------------------------------------------------ mots

@pytest.mark.parametrize("vent,mot", [(0, "calme"), (0.9, "calme"), (1, "très faible"), (3.9, "très faible"),
                                      (4, "faible"), (10.9, "faible"), (11, "modéré"), (16.9, "modéré"),
                                      (17, "assez fort"), (21.9, "assez fort"), (22, "fort"), (27.9, "fort"),
                                      (28, "très fort"), (33.9, "très fort"), (34, "tempête"), (80, "tempête")])
def test_la_force_du_vent_en_mots(vent, mot):
    assert MW.force(vent) == mot


@pytest.mark.parametrize("direction,mot", [(0, "du nord"), (22, "du nord"), (23, "du nord-est"), (90, "de l'est"),
                                           (135, "du sud-est"), (180, "du sud"), (225, "du sud-ouest"),
                                           (270, "de l'ouest"), (315, "du nord-ouest"), (350, "du nord"),
                                           (360, "du nord"), (-90, "de l'ouest"), (450, "de l'est")])
def test_le_secteur_du_vent(direction, mot):
    assert MW.secteur(direction) == mot


@pytest.mark.parametrize("valeur", [None, "225", True, float("nan"), float("inf"), [], {}])
def test_une_valeur_qui_n_est_pas_un_nombre_fini_reste_absente(valeur):
    assert MW.secteur(valeur) is None and MW.force(valeur) is None and MW._vers(valeur) is None
    assert MW.vent_en_mots(valeur, 90) is None and MW.ciel(valeur) is None and MW.symbole(valeur) is None


def test_le_vent_en_mots_avec_ou_sans_direction_et_calme():
    assert MW.vent_en_mots(14, 225) == "Vent modéré du sud-ouest"
    assert MW.vent_en_mots(14, None) == "Vent modéré"
    assert MW.vent_en_mots(0, 225) == "Calme"
    assert MW.vent_en_mots(None, 225) is None


def test_la_fleche_pointe_vers_ou_le_vent_souffle():
    assert MW._vers(225) == 45 and MW._vers(0) == 180 and MW._vers(180) == 0 and MW._vers(350) == 170


@pytest.mark.parametrize("code,symbole", [(0, "soleil"), (1, "soleil"), (2, "nuage"), (3, "nuage"),
                                          (45, "brouillard"), (48, "brouillard"), (51, "pluie"), (65, "pluie"),
                                          (80, "pluie"), (71, "neige"), (86, "neige"), (95, "orage"), (99, "orage")])
def test_le_symbole_du_ciel(code, symbole):
    assert MW.symbole(code) == symbole and symbole in MW.SYMBOLES


def test_un_code_inconnu_n_a_ni_symbole_ni_texte():
    for code in (4, 12, 100, -1, 2.5):
        assert MW.symbole(code) is None and MW.ciel(code) is None
    assert MW.ciel(0) == "Ciel dégagé" and MW.ciel(2.0) == "Partiellement nuageux"


def test_tous_les_codes_connus_ont_un_symbole_de_la_liste_fermee():
    assert {MW.symbole(c) for c in MW.CIEL} <= MW.SYMBOLES


def test_les_valeurs_sont_arrondies_sans_inventer_de_decimale():
    assert MW._arrondi(12.0) == 12 and isinstance(MW._arrondi(12.0), int)
    assert MW._arrondi(12.34) == 12.3 and MW._arrondi(None) is None and MW._arrondi(True) is None


# ------------------------------------------------------------------ projection

def test_la_vue_complete_porte_exactement_les_cles_attendues():
    rep = vue(meteo())
    assert set(rep) == {"type", "point", "points", "titre", "lu_a", "maintenant", "heures", "jours", "eau", "soleil",
                        "vagues_source", "balises", "sources_en_panne", "attribution"}
    assert rep["type"] == "meteo" and rep["titre"] == "Mer au Prado" and rep["eau"] == 18.3
    assert rep["soleil"] == {"lever": "07:40", "coucher": "18:05"} and rep["vagues_source"] == "AROME"
    assert rep["sources_en_panne"] == [] and rep["attribution"]


def test_l_instant_present_et_les_six_heures_partent_de_l_heure_locale_pleine():
    rep = vue(meteo())
    assert rep["maintenant"]["heure"] == "11:00"
    assert [h["heure"] for h in rep["heures"]] == ["11:00", "12:00", "13:00", "14:00", "15:00", "16:00"]
    assert len(rep["heures"]) == MW.HEURES_MAX


def test_une_heure_porte_les_mots_et_la_fleche_sans_rien_laisser_passer_d_autre():
    h = vue(meteo())["heures"][0]
    assert set(h) == {"heure", "vent", "rafales", "dir", "dir_vers", "vent_mot", "air", "pluie", "vagues", "periode",
                      "dir_vagues", "vagues_secteur", "ciel", "symbole"}
    assert h["vent_mot"] == "Vent modéré du sud-ouest" and h["dir_vers"] == 45
    assert h["ciel"] == "Partiellement nuageux" and h["symbole"] == "nuage" and h["vagues_secteur"] == "du sud"


def test_les_champs_inconnus_d_une_prevision_ne_passent_pas():
    mer = donnees_mer()
    mer["points"][0]["heures"][1].update({"cle_interne": "secret", "lat": 43.25, "url": "https://x.invalid"})
    texte = json.dumps(vue(meteo(mer=mer)))
    assert "secret" not in texte and "x.invalid" not in texte


def test_trois_jours_au_plus_avec_extremes_et_ciel_de_14h():
    rep = vue(meteo())
    assert [j["date"] for j in rep["jours"]] == ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert [j["jour"] for j in rep["jours"]][:2] == ["Aujourd'hui", "Demain"]
    assert rep["jours"][2]["jour"] == "Jeudi 29 oct."
    j = rep["jours"][0]
    assert j["vent_max"] == 12 and j["rafales_max"] == 18 and j["air_min"] == 17.4 and j["air_max"] == 17.4
    assert j["ciel"] == "Partiellement nuageux" and j["symbole"] == "nuage"
    assert j["pluie_total"] == round(0.2 * 14, 1)


def test_un_quatrieme_jour_est_ecarte():
    mer = donnees_mer()
    mer["points"][0]["heures"] = [heure(f"2026-10-{27 + i}T12:00") for i in range(4)]
    assert len(vue(meteo(mer=mer))["jours"]) == MW.JOURS_MAX


def test_une_valeur_absente_reste_absente_jamais_inventee():
    mer = donnees_mer()
    mer["points"][0]["heures"] = [{"t": "2026-10-27T11:00"}, heure("2026-10-27T12:00", vent=None, code=None,
                                                                   vagues="beaucoup", dir=float("nan"))]
    rep = vue(meteo(mer=mer))
    vide = rep["heures"][0]
    assert all(v is None for k, v in vide.items() if k != "heure")
    deuxieme = rep["heures"][1]
    assert deuxieme["vent"] is None and deuxieme["vagues"] is None and deuxieme["dir"] is None
    assert deuxieme["vent_mot"] is None and deuxieme["symbole"] is None
    j = rep["jours"][0]
    assert j["vent_max"] is None and j["air_max"] == 17.4, "seule la valeur présente compte, rien n'est inventé"
    assert j["pluie_total"] == 0.2 and j["vagues_max"] is None


def test_sans_prevision_pour_le_point_l_ecran_reste_servi_avec_les_balises():
    rep = vue(meteo(), msg={"type": "meteo", "point": "pharo"})
    assert rep["maintenant"] is None and rep["heures"] == [] and rep["jours"] == []
    assert rep["vagues_source"] is None


def test_le_soleil_est_celui_du_jour_local_ou_absent():
    mer = donnees_mer(soleil=[{"jour": "2026-10-26", "lever": "07:38", "coucher": "18:07"}])
    assert vue(meteo(mer=mer))["soleil"] is None
    assert vue(meteo(mer=donnees_mer(soleil=None)))["soleil"] is None


def test_l_heure_de_lecture_est_la_plus_ancienne_des_deux_sources_en_heure_locale():
    assert vue(meteo())["lu_a"] == "11:20"
    assert vue(meteo(vent=None))["lu_a"] == "11:20"
    assert vue(meteo(mer=donnees_mer(lu_a="n'importe quoi")))["lu_a"] == "11:25"
    assert vue(meteo(mer=donnees_mer(lu_a=None), vent=donnees_vent(lu_a=None)))["lu_a"] is None


def test_les_textes_venus_des_sources_sont_tronques():
    rep = vue(meteo(mer=donnees_mer(titre="T" * 500)))
    assert len(rep["titre"]) == MW.TEXTE_MAX
    assert vue(meteo(mer=donnees_mer(titre=["liste"])))["titre"] is None


# ------------------------------------------------------------------ balises

def test_une_balise_porte_son_age_en_minutes_et_le_drapeau_ancienne():
    recente, vieille = balise("prado", age_min=10), balise("callelongue", age_min=45)
    rep = vue(meteo(vent=donnees_vent(recente, vieille)))
    par_id = {b["id"]: b for b in rep["balises"]}
    assert par_id["prado"]["age_min"] == 10 and par_id["prado"]["ancienne"] is False
    assert par_id["callelongue"]["age_min"] == 45 and par_id["callelongue"]["ancienne"] is True
    assert par_id["prado"]["vent_mot"] == "Vent modéré du sud-ouest" and par_id["prado"]["dir_vers"] == 45


def test_le_seuil_se_lit_par_source_et_l_age_egal_au_seuil_n_est_pas_ancien():
    rep = vue(meteo(vent=donnees_vent(balise("prado", age_min=30, seuil_min=30), balise("port", age_min=31, seuil_min=30),
                                      balise("frioul", age_min=500, seuil_min=None))))
    par_id = {b["id"]: b["ancienne"] for b in rep["balises"]}
    assert par_id == {"prado": False, "port": True, "frioul": False}


def test_un_instant_dans_le_futur_donne_un_age_nul():
    assert vue(meteo(vent=donnees_vent(balise(age_min=-20))))["balises"][0]["age_min"] == 0


def test_les_balises_suivent_la_liste_du_point_dans_son_ordre():
    stations = [balise("frioul"), balise("prado"), balise("port"), balise("hors-liste")]
    rep = vue(meteo(vent=donnees_vent(*stations)))
    assert [b["id"] for b in rep["balises"]] == ["prado", "port", "frioul"]


def test_un_point_sans_station_n_a_pas_de_balise():
    assert vue(meteo(), msg={"type": "meteo", "point": "rade"})["balises"] == []


def test_sans_liste_de_stations_les_balises_sont_celles_dont_le_point_correspond(monkeypatch):
    mer = {"points": [{"id": "prado", "nom": "Prado"}, {"id": "pharo", "nom": "Pharo"}]}
    monkeypatch.setitem(maison.CONFIG, "mer", mer)
    stations = donnees_vent(balise("a", point="pharo"), balise("b", point="prado"))
    assert [b["id"] for b in vue(meteo(vent=stations))["balises"]] == ["b"]
    assert [b["id"] for b in vue(meteo(vent=stations), msg={"type": "meteo", "point": "pharo"})["balises"]] == ["a"]


def test_une_balise_sans_mesure_ou_mal_formee_est_ignoree():
    sans_mesure = balise("prado", mesures=[])
    sans_nom = balise("port", nom="  ")
    sans_instant = balise("frioul", mesures=[{"vent": 3}])
    bonne = balise("callelongue")
    rep = vue(meteo(vent=donnees_vent(sans_mesure, sans_nom, sans_instant, bonne, "texte", None)))
    assert [b["id"] for b in rep["balises"]] == ["callelongue"]


def test_une_balise_ne_laisse_partir_aucune_coordonnee():
    rep = vue(meteo())
    assert set(rep["balises"][0]) == {"id", "nom", "genre", "vent", "rafale", "dir", "dir_vers", "vent_mot",
                                     "age_min", "ancienne"}


# ------------------------------------------------------------------ pannes partielles

def test_une_source_eteinte_n_est_pas_une_panne():
    rep = vue(meteo(vent=None))
    assert rep["sources_en_panne"] == [] and rep["balises"] == [] and rep["heures"]
    rep = vue(meteo(mer=None))
    assert rep["sources_en_panne"] == [] and rep["heures"] == [] and rep["balises"]


def test_une_source_qui_leve_est_signalee_et_l_autre_est_servie(capsys):
    rep = vue(meteo(mer=RuntimeError("clé API sk-secret et http://interne.invalid/x")))
    assert rep["sources_en_panne"] == ["Prévisions en mer indisponibles"] and rep["balises"]
    rep = vue(meteo(vent=OSError("disque")))
    assert rep["sources_en_panne"] == ["Balises de vent indisponibles"] and rep["heures"]
    sortie = capsys.readouterr().out
    assert "RuntimeError" in sortie and "sk-secret" not in sortie and "interne.invalid" not in sortie


def test_une_source_qui_rend_autre_chose_qu_un_objet_est_une_panne():
    rep = vue(meteo(vent=["pas", "un", "objet"]))
    assert rep["sources_en_panne"] == ["Balises de vent indisponibles"]


def test_les_erreurs_des_sources_sont_reprises_une_fois_et_plafonnees():
    mer = donnees_mer(erreurs=["Vagues du Prado indisponibles", "Vagues du Prado indisponibles", 12, "  ", None])
    vent = donnees_vent(erreurs=["Balise du port muette"] + [f"Autre {i}" for i in range(10)])
    rep = vue(meteo(mer=mer, vent=vent))
    assert rep["sources_en_panne"][:2] == ["Vagues du Prado indisponibles", "Balise du port muette"]
    assert len(rep["sources_en_panne"]) == 6


def test_deux_sources_vides_donnent_indisponible():
    assert refus(meteo(mer=None, vent=None)).cause == "indisponible"
    assert refus(meteo(mer=RuntimeError("x"), vent=RuntimeError("y"))).cause == "indisponible"
    assert refus(meteo(mer=None, vent=RuntimeError("y"))).cause == "indisponible"


def test_une_exception_de_la_source_ne_sort_jamais_du_module():
    m = meteo(mer=ValueError("texte secret"), vent=donnees_vent())
    assert "secret" not in json.dumps(vue(m))


# ------------------------------------------------------------------ aucune coordonnée, aucune adresse réelle

def test_aucune_coordonnee_ne_sort_de_la_vue_complete():
    texte = json.dumps(vue(meteo()))
    assert "43.25" not in texte and "5.36" not in texte and '"lat"' not in texte and '"lon"' not in texte
    for point in ("prado", "pharo", "rade"):
        t = json.dumps(vue(meteo(), msg={"type": "meteo", "point": point}))
        assert "43.2" not in t and "5.3" not in t.replace('"vent": 12', "")


def test_le_module_ne_contient_ni_adresse_ni_url_ni_coordonnee_ni_identifiant_reel():
    source = (RACINE / "meteo_web.py").read_text(encoding="utf-8")
    assert not re.search(r"https?://", source)
    assert not re.search(r"\b\d{1,3}\.\d{3,}\b", source), "pas de coordonnée décimale en dur"
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", source), "pas d'adresse IP en dur"
    assert not re.search(r"\b[a-z_]+\.[a-z0-9_]+_[a-z0-9_]+\b(?=['\"])", source.replace("meteo_mer", "")), \
        "pas d'identifiant d'entité Home Assistant en dur"


def test_le_module_n_importe_que_des_modules_du_moteur_et_la_bibliotheque_standard():
    source = (RACINE / "meteo_web.py").read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:import|from)\s+([a-z_]+)", source, re.M))
    assert imports == {"math", "time", "datetime", "maison", "meteo_mer"}


def test_les_textes_du_module_n_ont_ni_tiret_cadratin_ni_emoji():
    source = (RACINE / "meteo_web.py").read_text(encoding="utf-8")
    assert "—" not in source and "–" not in source and "…" not in source
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", source)
